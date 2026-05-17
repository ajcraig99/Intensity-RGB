"""QThread worker wrapping the Intensity-RGB V2.0 streaming pipeline.

Plans:
    /home/arron/.claude/plans/quizzical-humming-metcalfe.md  (Wave 4 / D2)
    /home/arron/.claude/plans/stateful-hatching-kitten.md    ("UI" section)

This module is the GUI-side bridge between the Qt-free pipeline functions
in :mod:`intensity_rgb.pipeline` and the PySide6 main window built in
:mod:`intensity_rgb.gui` (Wave 4 / D1).

Design notes
------------

* Cancellation uses a :class:`threading.Event`. The pipeline checks the
  flag between blocks (one ``block_size`` worth of work, typically
  100k-1M points, i.e. a fraction of a second). The :meth:`cancel` slot
  simply sets the event; the worker thread sees it on the next inter-
  block check and raises :class:`PipelineCancelled`, which we translate
  into a ``finished(False, "cancelled")`` signal.

* Throughput is computed from a deque of ``(timestamp, points_done)``
  samples covering the trailing :data:`_THROUGHPUT_WINDOW_SEC` seconds.
  This is smoother than the per-block window the pipeline's own
  ``_ProgressEmitter`` reports, and matches what the GUI's status bar
  wants (a stable pts/s number, not an oscillating per-block one).

* Signal rate: pipeline progress events fire every ``progress_every``
  blocks (default 5), so roughly once per 5 * block_size points. On
  ~1 MB/block files at ~5 M pts/s that's ~1 Hz — already gentle enough
  for the UI. The throughput / ETA signals are additionally throttled
  to :data:`_EMIT_MIN_INTERVAL_SEC` so very fast pipelines don't spam.

* All exceptions inside :meth:`run_job` are caught and translated to
  ``finished(False, <message>)``. We never let an exception escape the
  worker thread — that would crash the Qt event loop. ``UnsupportedFile
  Error`` is surfaced verbatim (the GUI shows it as a non-fatal
  dialog); everything else gets a short ``traceback.format_exc`` tail
  so the user has something to paste into a bug report.
"""

from __future__ import annotations

import threading
import time
import traceback
from collections import deque
from typing import Optional, Tuple

from PySide6.QtCore import QObject, QThread, Signal, Slot

from intensity_rgb.io.e57_clone import UnsupportedFileError
from intensity_rgb.pipeline import (
    PipelineCancelled,
    PipelineResult,
    ProgressEvent,
    pipeline_bake_intensity,
    pipeline_bake_normals,
    pipeline_clone,
)


__all__ = ["PipelineWorker", "create_worker_thread"]


# Window over which throughput is averaged (seconds). Three seconds gives
# the GUI a number that survives a one-block stall without lurching.
_THROUGHPUT_WINDOW_SEC: float = 3.0

# Minimum gap between throughput/ETA emissions (seconds). Progress events
# still fire at the pipeline's rate; this just keeps the derived metrics
# from going faster than the eye.
_EMIT_MIN_INTERVAL_SEC: float = 0.5

# Per-component invert chips show the K largest components. K matches
# design §"Normal orientation" — 8 keeps the chip row readable even on a
# narrow window.
TOP_K_COMPONENTS: int = 8


def _format_count(n: int) -> str:
    """Format point counts with thousands separators."""
    return f"{int(n):,}"


def _format_pts_per_sec(pps: float) -> str:
    """Render a pts/s value with k/M/G suffix."""
    if pps >= 1e9:
        return f"{pps / 1e9:.2f}G pts/s"
    if pps >= 1e6:
        return f"{pps / 1e6:.2f}M pts/s"
    if pps >= 1e3:
        return f"{pps / 1e3:.1f}k pts/s"
    return f"{pps:.0f} pts/s"


def _format_rss(b: Optional[int]) -> str:
    if b is None:
        return "RSS n/a"
    mb = b / (1024.0 * 1024.0)
    if mb >= 1024.0:
        return f"peak RSS {mb / 1024.0:.2f} GB"
    return f"peak RSS {mb:.0f} MB"


def _build_summary(result: PipelineResult) -> str:
    """Compose the human-readable summary that lands on ``finished``."""
    elapsed = max(result.elapsed_seconds, 1e-6)
    pps = float(result.total_points) / elapsed if result.total_points else 0.0
    parts = [
        f"{_format_count(result.total_points)} pts in {elapsed:.1f}s",
        f"({_format_pts_per_sec(pps)})",
        _format_rss(result.peak_rss_bytes),
    ]
    if result.voxel_quality_fraction is not None:
        parts.append(f"voxel quality {result.voxel_quality_fraction * 100:.1f}%")
    if result.n_components is not None:
        parts.append(f"{result.n_components} components")
    return "; ".join(parts)


class PipelineWorker(QObject):
    """QObject worker that runs a pipeline on its owning thread.

    Move an instance to a :class:`QThread`, connect the thread's
    ``started`` signal to :meth:`run_job` (or invoke it via
    ``QMetaObject.invokeMethod``), and listen on the signals below.
    """

    # ``(points_done, points_total)`` from the pipeline's ProgressEvent.
    progress = Signal(int, int)
    # Sliding-window throughput in points per second.
    throughput = Signal(float)
    # Process peak RSS in bytes.
    peak_rss = Signal(int)
    # Fraction of Pass-2 query points landing in a quality voxel (0..1).
    voxel_quality = Signal(float)
    # Remaining time estimate in seconds.
    eta_seconds = Signal(float)
    # Human-readable log line (informational, not the final summary).
    log = Signal(str)
    # ``(success, message_or_error)`` — terminal signal.
    finished = Signal(bool, str)
    # Stage name: "clone" | "pass1" | "pass2" | "finalize".
    stage = Signal(str)
    # Connected-component count from orient_normals (bake_normals only).
    n_components = Signal(int)
    # Top-K components (per design): list of dicts with keys
    # {"id": int, "voxel_count": int, "mean_normal": [x, y, z]}.
    # Emitted once after Pass 1's orient_normals completes (bake_normals
    # only). Sorted by voxel_count desc; clipped to TOP_K_COMPONENTS.
    components_info = Signal(list)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._cancel_flag: threading.Event = threading.Event()
        # Throughput samples — list of (timestamp, points_done) tuples
        # within the trailing _THROUGHPUT_WINDOW_SEC seconds.
        self._tput_samples: "deque[Tuple[float, int]]" = deque()
        self._last_emit_time: float = 0.0
        self._last_stage: Optional[str] = None

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot()
    def cancel(self) -> None:
        """Sets the internal cancellation flag.

        The running pipeline will exit at the next inter-block check
        (typically within one ``block_size`` of work — a fraction of a
        second on the carpark_stairs fixture).
        """
        self._cancel_flag.set()

    @Slot(dict)
    def run_job(self, spec: dict) -> None:
        """Execute the pipeline described by ``spec``.

        See module docstring for the keys this slot reads. Emits the
        terminal :attr:`finished` signal exactly once before returning,
        whether the run succeeded, raised ``UnsupportedFileError``,
        was cancelled, or hit an unexpected exception.
        """
        # Reset cancel flag and throughput samples for re-use.
        self._cancel_flag.clear()
        self._tput_samples.clear()
        self._last_emit_time = 0.0
        self._last_stage = None

        mode = spec.get("mode")
        if mode not in ("clone", "bake_intensity", "bake_normals"):
            self.finished.emit(False, f"unknown mode {mode!r}")
            return

        input_path = spec.get("input")
        output_path = spec.get("output")
        if not input_path or not output_path:
            self.finished.emit(
                False, "spec missing required 'input' and/or 'output' path"
            )
            return

        block_size = int(spec.get("block_size", 1_000_000))

        try:
            self.log.emit(f"Starting {mode}: {input_path} -> {output_path}")
            if mode == "clone":
                result = pipeline_clone(
                    input_path,
                    output_path,
                    block_size=block_size,
                    on_progress=self._on_progress,
                    cancel_flag=self._cancel_flag,
                )
            elif mode == "bake_intensity":
                intensity_range = spec.get("intensity_range")
                if intensity_range is None:
                    self.finished.emit(
                        False, "bake_intensity requires 'intensity_range'"
                    )
                    return
                brightness = float(spec.get("brightness", 70.0))
                result = pipeline_bake_intensity(
                    input_path,
                    output_path,
                    intensity_range=tuple(intensity_range),
                    brightness=brightness,
                    block_size=block_size,
                    on_progress=self._on_progress,
                    cancel_flag=self._cancel_flag,
                )
            else:  # bake_normals
                intensity_range = spec.get("intensity_range")
                if intensity_range is None:
                    self.finished.emit(
                        False, "bake_normals requires 'intensity_range'"
                    )
                    return
                kwargs = dict(
                    intensity_range=tuple(intensity_range),
                    brightness=float(spec.get("brightness", 70.0)),
                    voxel_size=float(spec.get("voxel_size", 0.5)),
                    shading_mode=str(spec.get("shading_mode", "lambertian")),
                    light_dir=tuple(spec.get("light_dir", (0.0, 0.0, -1.0))),
                    ambient=float(spec.get("ambient", 0.2)),
                    ground_color=tuple(spec.get("ground_color", (60, 40, 30))),
                    sky_color=tuple(spec.get("sky_color", (180, 210, 255))),
                    up_vector=tuple(spec.get("up_vector", (0.0, 0.0, 1.0))),
                    invert_globally=bool(spec.get("invert_globally", False)),
                    block_size=block_size,
                    on_progress=self._on_progress,
                    cancel_flag=self._cancel_flag,
                    on_orientation_result=self._on_orientation_result,
                )
                result = pipeline_bake_normals(input_path, output_path, **kwargs)

        except PipelineCancelled:
            self.log.emit("Pipeline cancelled by user.")
            self.finished.emit(False, "cancelled")
            return
        except UnsupportedFileError as e:
            # Non-fatal user-facing error: surface the message verbatim so
            # the GUI can show a friendly dialog without a traceback.
            self.log.emit(f"Unsupported file: {e}")
            self.finished.emit(False, str(e))
            return
        except Exception as e:  # pragma: no cover - defensive catch-all
            tb = traceback.format_exc(limit=8)
            self.log.emit(f"Pipeline failed: {e!r}")
            self.finished.emit(False, f"{type(e).__name__}: {e}\n{tb}")
            return

        # Emit terminal-stage stats on success.
        if result.voxel_quality_fraction is not None:
            self.voxel_quality.emit(float(result.voxel_quality_fraction))
        if result.n_components is not None:
            self.n_components.emit(int(result.n_components))
        if result.peak_rss_bytes is not None:
            self.peak_rss.emit(int(result.peak_rss_bytes))

        summary = _build_summary(result)
        self.log.emit(summary)
        self.finished.emit(True, summary)

    # ------------------------------------------------------------------
    # Internal: orientation-pass callback (bake_normals only)
    # ------------------------------------------------------------------

    def _on_orientation_result(self, orient_result: object) -> None:
        """Convert the pipeline's ``OrientationResult`` into a UI-friendly
        payload and emit ``components_info``.

        Called on the worker thread by ``pipeline_bake_normals`` once
        Pass 1 finishes orienting normals. We slice to ``TOP_K_COMPONENTS``
        (components are already sorted by voxel_count desc per
        ``OrientationResult`` docstring) and serialize each entry as a
        plain dict so the receiver doesn't need to import the
        orientation module.
        """
        try:
            components = list(getattr(orient_result, "components", []) or [])
        except Exception:
            return
        payload = []
        for idx, comp in enumerate(components[:TOP_K_COMPONENTS]):
            try:
                mn = comp.mean_normal
                mean = [float(mn[0]), float(mn[1]), float(mn[2])]
            except Exception:
                mean = [0.0, 0.0, 0.0]
            payload.append({
                "id": idx,
                "voxel_count": int(getattr(comp, "voxel_count", 0)),
                "mean_normal": mean,
            })
        try:
            self.components_info.emit(payload)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal: pipeline progress callback
    # ------------------------------------------------------------------

    def _on_progress(self, ev: ProgressEvent) -> None:
        """Translate a pipeline ProgressEvent into Qt signals.

        Called from the worker thread (i.e. *this* QObject's thread once
        moved by :func:`create_worker_thread`). Signals are emitted
        directly; Qt's default Auto connection routes them to the UI
        thread as queued events when the receiver lives there.
        """
        now = time.perf_counter()

        # Stage transitions: emit once when the pipeline crosses into a
        # new stage so the GUI can update its progress label.
        if ev.stage != self._last_stage:
            self._last_stage = ev.stage
            try:
                self.stage.emit(ev.stage)
            except Exception:
                pass

        # Always emit raw progress so the bar moves smoothly.
        try:
            self.progress.emit(int(ev.points_done), int(ev.points_total))
        except Exception:
            pass

        # Throttle the derived metrics — throughput/ETA/RSS — so a hot
        # pipeline can't drown the UI in updates.
        if now - self._last_emit_time < _EMIT_MIN_INTERVAL_SEC:
            return
        self._last_emit_time = now

        # Sliding-window throughput.
        self._tput_samples.append((now, int(ev.points_done)))
        cutoff = now - _THROUGHPUT_WINDOW_SEC
        while len(self._tput_samples) > 1 and self._tput_samples[0][0] < cutoff:
            self._tput_samples.popleft()

        tput: float = 0.0
        if len(self._tput_samples) >= 2:
            t0, p0 = self._tput_samples[0]
            t1, p1 = self._tput_samples[-1]
            dt = t1 - t0
            dp = p1 - p0
            if dt > 0 and dp > 0:
                tput = float(dp) / dt
        elif ev.throughput_pts_per_sec is not None:
            # Bootstrap: pipeline's own per-block measure for the first
            # emission, before our window has two samples.
            tput = float(ev.throughput_pts_per_sec)

        try:
            self.throughput.emit(tput)
        except Exception:
            pass

        # ETA based on the smoothed throughput.
        if ev.points_total > 0 and tput > 0:
            remaining = max(ev.points_total - ev.points_done, 0)
            eta = float(remaining) / max(tput, 1.0)
        else:
            eta = 0.0
        try:
            self.eta_seconds.emit(float(eta))
        except Exception:
            pass

        if ev.peak_rss_bytes is not None:
            try:
                self.peak_rss.emit(int(ev.peak_rss_bytes))
            except Exception:
                pass


def create_worker_thread(spec: dict) -> Tuple[QThread, PipelineWorker]:
    """Build a QThread + PipelineWorker pair pre-wired to run ``spec``.

    The caller still owns lifetime — connect signals, then call
    ``thread.start()``. The worker's :meth:`run_job` is hooked to the
    thread's ``started`` signal and the thread is set to quit cleanly
    when ``finished`` fires, so a typical usage looks like::

        thread, worker = create_worker_thread(spec)
        worker.progress.connect(self.on_progress)
        worker.finished.connect(self.on_finished)
        thread.start()

    The QThread is parentless and not owned by any Qt object — the
    caller must keep a reference (typically as ``self._thread``) until
    ``thread.wait()`` returns.
    """
    thread = QThread()
    worker = PipelineWorker()
    worker.moveToThread(thread)
    # Bind ``spec`` into the started slot via a default argument so the
    # closure captures by value, not by reference.
    thread.started.connect(lambda spec=spec: worker.run_job(spec))
    # Have the thread quit itself once the job is done so the caller
    # only needs to wait() — they don't have to remember to call quit().
    worker.finished.connect(thread.quit)
    return thread, worker
