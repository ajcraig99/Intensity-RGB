"""Qt-free orchestration layer for the Intensity-RGB V2.0 streaming pipeline.

Plans:
    /home/arron/.claude/plans/quizzical-humming-metcalfe.md   (Wave 3 / C1)
    /home/arron/.claude/plans/stateful-hatching-kitten.md     (Shading models,
                                                               Voxel accumulator,
                                                               Normal orientation)

This module is the single integration surface the CLI (C2) and the
PySide6 GUI (D-wave) both call into. It combines:

* Wave 1 numpy modules: :mod:`intensity_rgb.processing.intensity`,
  :mod:`intensity_rgb.processing.voxel_normals`,
  :mod:`intensity_rgb.processing.shading`,
  :mod:`intensity_rgb.processing.orientation`.

* Wave 2 I/O substrate: :mod:`intensity_rgb.io.e57_clone`
  (E57CloneReader / E57CloneWriter / clone_file).

Three public entry points are exposed:

* :func:`pipeline_clone`             – pure identity clone (uses :func:`clone_file`).
* :func:`pipeline_bake_intensity`    – single-pass intensity → RGB bake.
* :func:`pipeline_bake_normals`      – two-pass voxel-normal bake with a
  Lambertian / three_point / normal_as_color shading model.

A helper :func:`get_aabb_and_intensity_range` covers the capability /
auto-range need on the CLI side and seeds the AABB origin for the
voxel grid in :func:`pipeline_bake_normals`.

Conventions
-----------

* All ops are vectorised; the per-block work is pure numpy.
* Progress is reported through an optional callback that takes a
  :class:`ProgressEvent` dataclass. The callback is invoked at most
  every ``progress_every`` blocks (default 5) per stage.
* Cancellation is via an optional ``threading.Event``; checked between
  blocks. A cancelled pipeline raises :class:`PipelineCancelled`.
* Peak RSS is read from ``resource.getrusage`` on Linux (kibibytes on
  Linux per kernel docs). ``None`` on platforms where the module isn't
  available.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

import numpy as np

from intensity_rgb.io.e57_clone import (
    E57CloneReader,
    E57CloneWriter,
    FieldBuffer,
    UnsupportedFileError,
    clone_file,
    identity_transform,
)
from intensity_rgb.processing.intensity import bake_rgb_from_intensity
from intensity_rgb.processing.orientation import orient_normals
from intensity_rgb.processing.shading import (
    DEFAULT_AMBIENT,
    DEFAULT_GROUND,
    DEFAULT_SKY,
    lambertian,
    normal_as_color,
    three_point,
)
from intensity_rgb.processing.voxel_normals import (
    CHUNK,
    MIN_SUPPORT,
    PLANARITY_THRESHOLD,
    VoxelAccumulator,
    lookup_normals,
)

try:
    import resource  # Linux / macOS — Windows lacks this module.
except ImportError:  # pragma: no cover - Windows fallback
    resource = None  # type: ignore[assignment]


__all__ = [
    "PipelineCancelled",
    "ProgressEvent",
    "PipelineResult",
    "get_aabb_and_intensity_range",
    "pipeline_clone",
    "pipeline_bake_intensity",
    "pipeline_bake_normals",
]


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


class PipelineCancelled(RuntimeError):
    """Raised when the caller's ``cancel_flag`` event is set mid-pipeline."""


@dataclass
class ProgressEvent:
    """Snapshot pushed to ``on_progress`` from inside the streaming loop.

    Attributes
    ----------
    points_done:
        Cumulative point count for the current stage.
    points_total:
        Best-known total for the current stage; 0 if unknown (e.g. before
        the reader has been opened).
    stage:
        ``"pass1"`` | ``"pass2"`` | ``"clone"`` | ``"finalize"``.
    throughput_pts_per_sec:
        Sliding-window throughput estimate over the last ``progress_every``
        blocks; ``None`` until the first window completes.
    peak_rss_bytes:
        Process peak RSS in bytes, or ``None`` on platforms without
        ``resource``.
    """

    points_done: int
    points_total: int
    stage: str
    throughput_pts_per_sec: Optional[float]
    peak_rss_bytes: Optional[int]


@dataclass
class PipelineResult:
    """Returned by every pipeline entry point.

    Attributes
    ----------
    output_path:
        Absolute or caller-supplied destination path.
    output_size_bytes:
        ``os.path.getsize(output_path)`` after the pipeline closes.
    scan_count:
        Number of scans in the source (== written count).
    total_points:
        Sum of points actually streamed through the writer (i.e. the
        Pass-2 sum on bake_normals; the only pass on the others).
    blocks_written:
        Total number of write_block calls across all scans.
    elapsed_seconds:
        Wall-clock time from pipeline entry to return.
    peak_rss_bytes:
        Final peak RSS reading, or ``None`` if unavailable.
    voxel_quality_fraction:
        Fraction of Pass-2 query points that landed in a quality-True
        voxel (``None`` on clone / bake_intensity, where no voxel grid
        is built).
    n_components:
        Number of connected components produced by :func:`orient_normals`
        (``None`` outside bake_normals).
    """

    output_path: str
    output_size_bytes: int
    scan_count: int
    total_points: int
    blocks_written: int
    elapsed_seconds: float
    peak_rss_bytes: Optional[int]
    voxel_quality_fraction: Optional[float] = None
    n_components: Optional[int] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _peak_rss_bytes() -> Optional[int]:
    """Return process peak RSS in **bytes**.

    On Linux ``ru_maxrss`` is in kibibytes; on macOS it's in bytes.
    We assume Linux (the project's target dev platform) and multiply by
    1024. If ``resource`` is missing, return ``None``.
    """
    if resource is None:
        return None
    try:
        kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(kib) * 1024
    except Exception:  # pragma: no cover - defensive
        return None


def _maybe_cancel(flag: Optional[threading.Event]) -> None:
    if flag is not None and flag.is_set():
        raise PipelineCancelled("pipeline cancelled by caller")


class _ProgressEmitter:
    """Throttled ProgressEvent emitter with a sliding-window throughput.

    The window covers the last ``every`` blocks (or the last call,
    whichever is more recent). ``maybe_emit`` is called once per block;
    actual emission happens every ``every`` calls plus on ``flush``.
    """

    def __init__(
        self,
        callback: Optional[Callable[[ProgressEvent], None]],
        stage: str,
        every: int,
        points_total: int,
    ):
        self._cb = callback
        self._stage = stage
        self._every = max(1, int(every))
        self._points_total = int(points_total)
        self._counter = 0
        self._window_start_time = time.perf_counter()
        self._window_start_points = 0
        self._points_done = 0

    def add(self, points: int) -> None:
        self._points_done += int(points)
        self._counter += 1
        if self._counter >= self._every:
            self._emit()
            self._counter = 0

    def flush(self) -> None:
        # Emit any partial window (e.g. final block of a stage).
        if self._counter > 0 or self._points_done == 0:
            self._emit()
            self._counter = 0

    def _emit(self) -> None:
        if self._cb is None:
            return
        now = time.perf_counter()
        dt = now - self._window_start_time
        d_pts = self._points_done - self._window_start_points
        tput: Optional[float]
        if dt > 0 and d_pts > 0:
            tput = float(d_pts) / dt
        else:
            tput = None
        try:
            self._cb(
                ProgressEvent(
                    points_done=self._points_done,
                    points_total=self._points_total,
                    stage=self._stage,
                    throughput_pts_per_sec=tput,
                    peak_rss_bytes=_peak_rss_bytes(),
                )
            )
        except Exception:
            # Never let a misbehaving callback take down the pipeline.
            pass
        self._window_start_time = now
        self._window_start_points = self._points_done


def _xyz_block(block: Dict[str, FieldBuffer]) -> np.ndarray:
    """Stack cartesianX/Y/Z FieldBuffer arrays into an ``(N, 3)`` float64."""
    cx = block["cartesianX"].numpy_array
    cy = block["cartesianY"].numpy_array
    cz = block["cartesianZ"].numpy_array
    n = cx.shape[0]
    out = np.empty((n, 3), dtype=np.float64)
    out[:, 0] = cx
    out[:, 1] = cy
    out[:, 2] = cz
    return out


def _intensity_to_raw(
    block: Dict[str, FieldBuffer], intensity_range: Tuple[float, float]
) -> np.ndarray:
    """Recover *raw* intensity from a (potentially normalized) FieldBuffer.

    pye57 / libE57 descales ScaledIntegerNode-based intensity into
    natural-unit floats. For ``carpark_stairs.e57`` the source uses
    ScaledIntegerNode and the field arrives as float32 in ``[0, 1]``.
    V1's intensity → RGB normalization branches key on *raw* maxima
    (255 / 2048 / 4096) so we have to invert the descaling here.

    Recovery rule: assume the descaled values cover the caller-supplied
    ``intensity_range`` linearly:

        raw = normalized * (max - min) + min

    If the file already stored intensity as a raw integer / non-scaled
    float (rare in the wild — but we handle it), the FieldBuffer values
    are already raw and we pass them through. We detect this by checking
    whether the array fits inside ``[min - eps, max + eps]`` already:
    descaled floats sit in ``[0, 1]`` and almost certainly fall outside
    a raw range like ``[0, 4096]``.
    """
    inten_fb = block.get("intensity")
    if inten_fb is None or inten_fb.numpy_array is None:
        # Field missing — caller should have validated; return zeros so
        # bake_rgb_from_intensity yields a constant colour rather than
        # crashing.
        n = block["cartesianX"].numpy_array.shape[0]
        return np.zeros(n, dtype=np.float64)

    raw_or_norm = inten_fb.numpy_array
    lo, hi = float(intensity_range[0]), float(intensity_range[1])
    # If the values already fit inside the declared raw range with some
    # slack, treat as raw and pass through unchanged.
    if raw_or_norm.size > 0:
        amin = float(raw_or_norm.min())
        amax = float(raw_or_norm.max())
        if amin >= lo - 1e-6 and amax <= hi + 1e-6 and hi > 1.5:
            return np.asarray(raw_or_norm, dtype=np.float64)
    # Otherwise: assume descaled to [0, 1] (or whatever the proto's
    # min/max maps to) and re-scale to raw.
    return np.asarray(raw_or_norm, dtype=np.float64) * (hi - lo) + lo


def _rgb_dtype_from_block(block: Dict[str, FieldBuffer]) -> np.dtype:
    """Pick a dtype for RGB writes that matches the prototype.

    The streaming writer respects the FieldBuffer's array dtype when
    writing back. The source RGB prototype is typically a uint8
    IntegerNode; we mirror its dtype so the writer doesn't have to
    convert.
    """
    cr = block.get("colorRed")
    if cr is not None and cr.numpy_array is not None:
        return cr.numpy_array.dtype
    return np.dtype(np.uint8)


def _apply_rgb_to_block(
    block: Dict[str, FieldBuffer], rgb: np.ndarray
) -> Dict[str, FieldBuffer]:
    """Write the ``(N, 3) uint8`` ``rgb`` into the block's RGB FieldBuffers.

    Preserves the prototype_node / descaled flag of each channel — the
    writer needs those to reconstruct the destination prototype.
    """
    dst_dtype = _rgb_dtype_from_block(block)
    for ch_idx, ch in enumerate(("colorRed", "colorGreen", "colorBlue")):
        existing = block.get(ch)
        if existing is None:
            # Source has no RGB; we cannot inject one here (V2.0 scope
            # explicitly excludes adding fields, see UnsupportedFileError).
            # Callers that need RGB must pre-validate via has_rgb.
            continue
        new_arr = np.asarray(rgb[:, ch_idx], dtype=dst_dtype)
        block[ch] = FieldBuffer(
            name=ch,
            numpy_array=new_arr,
            prototype_node=existing.prototype_node,
            raw_bytes=None,
            descaled=existing.descaled,
        )
    return block


# ---------------------------------------------------------------------------
# Capability / auto-range helper
# ---------------------------------------------------------------------------


def get_aabb_and_intensity_range(
    reader: E57CloneReader,
    sample_blocks: int = 10,
    block_size: int = 200_000,
) -> dict:
    """Stream the first ``sample_blocks`` blocks of scan 0 and return
    a dict with the observed AABB + intensity min/max.

    Used by:

    * :func:`pipeline_bake_normals` — to seed the voxel grid origin so
      the grid is bounded by where points actually live (sparse files
      with off-origin scenes would otherwise allocate empty chunks
      between the world origin and the scan).
    * The CLI's ``--auto-range`` feature — same scan sampler the V1 GUI
      used, vectorised.

    Parameters
    ----------
    reader:
        An *already-opened* :class:`E57CloneReader`. Caller owns
        lifetime; this function does not enter / exit the context.
    sample_blocks:
        Max number of blocks to sample from scan 0. Default 10 — at
        ``block_size=200_000`` that's 2 M points, plenty for
        AABB / intensity-range estimation on the largest scanners.
    block_size:
        Per-block read size handed to ``iter_blocks``.

    Returns
    -------
    dict
        ``{"aabb_min": (3,) np.float64, "aabb_max": (3,) np.float64,
        "intensity_min": float, "intensity_max": float,
        "points_seen": int}``. If the source has no scans, all numeric
        values are 0.0 and ``points_seen == 0``.
    """
    aabb_min = np.array([np.inf, np.inf, np.inf], dtype=np.float64)
    aabb_max = np.array([-np.inf, -np.inf, -np.inf], dtype=np.float64)
    i_min = np.inf
    i_max = -np.inf
    points_seen = 0

    if reader.scan_count == 0:
        return {
            "aabb_min": np.zeros(3, dtype=np.float64),
            "aabb_max": np.zeros(3, dtype=np.float64),
            "intensity_min": 0.0,
            "intensity_max": 0.0,
            "points_seen": 0,
        }

    scan = next(iter(reader.iter_scans()))
    for i, block in enumerate(scan.iter_blocks(block_size=block_size)):
        if i >= sample_blocks:
            break
        xyz = _xyz_block(block)
        if xyz.size:
            aabb_min = np.minimum(aabb_min, xyz.min(axis=0))
            aabb_max = np.maximum(aabb_max, xyz.max(axis=0))
        inten_fb = block.get("intensity")
        if inten_fb is not None and inten_fb.numpy_array is not None and inten_fb.numpy_array.size:
            i_min = min(i_min, float(inten_fb.numpy_array.min()))
            i_max = max(i_max, float(inten_fb.numpy_array.max()))
        points_seen += xyz.shape[0]

    if points_seen == 0:
        # No data — return zeros rather than infinities.
        return {
            "aabb_min": np.zeros(3, dtype=np.float64),
            "aabb_max": np.zeros(3, dtype=np.float64),
            "intensity_min": 0.0,
            "intensity_max": 0.0,
            "points_seen": 0,
        }

    return {
        "aabb_min": aabb_min,
        "aabb_max": aabb_max,
        "intensity_min": float(i_min) if np.isfinite(i_min) else 0.0,
        "intensity_max": float(i_max) if np.isfinite(i_max) else 0.0,
        "points_seen": points_seen,
    }


# ---------------------------------------------------------------------------
# Pipeline 1: pure clone
# ---------------------------------------------------------------------------


def pipeline_clone(
    input_path: str,
    output_path: str,
    *,
    block_size: int = 1_000_000,
    on_progress: Optional[Callable[[ProgressEvent], None]] = None,
    cancel_flag: Optional[threading.Event] = None,
    progress_every: int = 5,
) -> PipelineResult:
    """Identity-transform clone of ``input_path`` to ``output_path``.

    Used by:

    * The CLI's ``clone`` subcommand (no transform).
    * Wave 2 / G1a Mode A fidelity tests.

    Implementation: thin wrapper over :func:`clone_file` with
    :func:`identity_transform`. Progress is reported every
    ``progress_every`` blocks via ``on_progress`` (best-effort: we drive
    the inner reader/writer directly so we can hook progress per block,
    instead of calling ``clone_file`` end-to-end).
    """
    t0 = time.perf_counter()

    with E57CloneReader(input_path) as reader:
        total_points_estimate = sum(s.total_points for s in reader.iter_scans())
        emitter = _ProgressEmitter(
            on_progress, "clone", progress_every, total_points_estimate
        )

        scan_count = reader.scan_count
        total_points = 0
        blocks_written = 0

        with E57CloneWriter(output_path, source=reader) as writer:
            writer.copy_file_header()
            for img in reader.images2D:
                writer.copy_image2D(img)
            for extra in reader.extra_nodes:
                writer.clone_node(extra)
            writer.copy_pointGroupingSchemes_if_present()
            for scan_reader in reader.iter_scans():
                with writer.begin_scan(
                    scan_reader, block_size=block_size, own_color_limits=False
                ) as scan_writer:
                    for block in scan_reader.iter_blocks(block_size=block_size):
                        _maybe_cancel(cancel_flag)
                        # identity_transform is a no-op; call for parity.
                        out_block = identity_transform(block)
                        n = scan_writer.write_block(out_block)
                        total_points += n
                        blocks_written += 1
                        emitter.add(n)
        emitter.flush()

    elapsed = time.perf_counter() - t0
    return PipelineResult(
        output_path=output_path,
        output_size_bytes=os.path.getsize(output_path),
        scan_count=scan_count,
        total_points=total_points,
        blocks_written=blocks_written,
        elapsed_seconds=elapsed,
        peak_rss_bytes=_peak_rss_bytes(),
    )


# ---------------------------------------------------------------------------
# Pipeline 2: single-pass intensity → RGB bake
# ---------------------------------------------------------------------------


def pipeline_bake_intensity(
    input_path: str,
    output_path: str,
    *,
    intensity_range: Tuple[float, float],
    brightness: float = 70.0,
    block_size: int = 1_000_000,
    on_progress: Optional[Callable[[ProgressEvent], None]] = None,
    cancel_flag: Optional[threading.Event] = None,
    progress_every: int = 5,
) -> PipelineResult:
    """Single-pass streaming intensity → RGB bake.

    Mirrors V1's ``process()`` function, but vectorised and streaming.
    Each block:

    1. Recover *raw* intensity from the (possibly descaled) FieldBuffer
       via :func:`_intensity_to_raw`.
    2. Call :func:`bake_rgb_from_intensity` with ``max_inten`` set to the
       upper end of ``intensity_range``.
    3. Stamp the resulting ``(N, 3) uint8`` RGB array into the block's
       ``colorRed/Green/Blue`` FieldBuffers (preserving prototype_node
       so the writer reconstructs the destination prototype faithfully).
    4. ``ScanWriter.write_block`` streams the block out.

    The destination scan gets ``colorLimits = [0, 255]`` via
    ``own_color_limits=True``.

    Raises
    ------
    UnsupportedFileError
        If any scan in the source lacks ``colorRed/Green/Blue`` in its
        prototype — V2.0 will not synthesise RGB nodes into intensity-
        only scans (the writer can't append fields to a cloned prototype
        without breaking the codec).
    """
    if intensity_range[1] <= intensity_range[0]:
        raise ValueError(
            f"intensity_range must be (lo, hi) with hi > lo; got {intensity_range!r}"
        )

    t0 = time.perf_counter()

    with E57CloneReader(input_path) as reader:
        for s in reader.iter_scans():
            if not s.has_rgb():
                raise UnsupportedFileError(
                    f"scan {s.index!r} has no colorRed/Green/Blue prototype; "
                    "V2.0 cannot bake RGB into an intensity-only scan"
                )

        total_points_estimate = sum(s.total_points for s in reader.iter_scans())
        emitter = _ProgressEmitter(
            on_progress, "clone", progress_every, total_points_estimate
        )
        scan_count = reader.scan_count
        total_points = 0
        blocks_written = 0

        with E57CloneWriter(output_path, source=reader) as writer:
            writer.copy_file_header()
            for img in reader.images2D:
                writer.copy_image2D(img)
            for extra in reader.extra_nodes:
                writer.clone_node(extra)
            writer.copy_pointGroupingSchemes_if_present()

            for scan_reader in reader.iter_scans():
                with writer.begin_scan(
                    scan_reader,
                    block_size=block_size,
                    own_color_limits=True,
                ) as scan_writer:
                    for block in scan_reader.iter_blocks(block_size=block_size):
                        _maybe_cancel(cancel_flag)
                        raw_inten = _intensity_to_raw(block, intensity_range)
                        rgb_u8 = bake_rgb_from_intensity(
                            raw_inten,
                            max_inten=float(intensity_range[1]),
                            brightness=brightness,
                        )
                        _apply_rgb_to_block(block, rgb_u8)
                        n = scan_writer.write_block(block)
                        total_points += n
                        blocks_written += 1
                        emitter.add(n)
                    scan_writer.update_color_limits()
        emitter.flush()

    elapsed = time.perf_counter() - t0
    return PipelineResult(
        output_path=output_path,
        output_size_bytes=os.path.getsize(output_path),
        scan_count=scan_count,
        total_points=total_points,
        blocks_written=blocks_written,
        elapsed_seconds=elapsed,
        peak_rss_bytes=_peak_rss_bytes(),
    )


# ---------------------------------------------------------------------------
# Pipeline 3: two-pass voxel-normal bake
# ---------------------------------------------------------------------------


def _validate_shading_mode(mode: str) -> str:
    if mode not in ("lambertian", "three_point", "normal_as_color"):
        raise ValueError(
            f"shading_mode must be one of "
            "{{'lambertian', 'three_point', 'normal_as_color'}}; "
            f"got {mode!r}"
        )
    return mode


def _shade_block(
    base_rgb: np.ndarray,
    normals: np.ndarray,
    quality: np.ndarray,
    *,
    shading_mode: str,
    light_dir: Tuple[float, float, float],
    ambient: float,
    ground_color: Tuple[int, int, int],
    sky_color: Tuple[int, int, int],
) -> np.ndarray:
    """Dispatch onto one of the three Wave-1 shading kernels.

    ``three_point`` uses ``light_dir`` as the key direction and synthesises
    a fill (right-side, half-intensity) + back (behind, quarter-intensity)
    based on the key. This gives the GUI a reasonable default until a
    full 3-light UI is wired up.
    """
    if shading_mode == "lambertian":
        return lambertian(
            base_rgb,
            normals,
            quality,
            light_dir=np.asarray(light_dir, dtype=np.float32),
            ambient=ambient,
            ground_color=np.asarray(ground_color, dtype=np.uint8),
            sky_color=np.asarray(sky_color, dtype=np.uint8),
        )
    if shading_mode == "three_point":
        key = np.asarray(light_dir, dtype=np.float32)
        # Build orthogonal fill + back from the key. We don't need
        # numerically-exact orthogonality — the shading kernel normalises.
        # Choose a stable basis: fill ~ key rotated 90deg about world-up;
        # back ~ -key (rim light from behind).
        up = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        # If key is parallel to up, swap basis to avoid a zero cross.
        if abs(float(np.dot(key / max(np.linalg.norm(key), 1e-8), up))) > 0.98:
            up = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        fill = np.cross(up, key)
        if float(np.linalg.norm(fill)) < 1e-6:
            fill = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        back = -key
        return three_point(
            base_rgb,
            normals,
            quality,
            key_dir=key,
            key_intensity=0.7,
            fill_dir=fill,
            fill_intensity=0.3,
            back_dir=back,
            back_intensity=0.2,
            ambient=ambient,
        )
    # normal_as_color: fallback colour is the base RGB row-wise — but
    # the Wave-1 kernel takes a single 3-tuple. Use the supplied
    # ``ground_color`` as the fallback for non-quality voxels.
    return normal_as_color(
        normals,
        quality,
        fallback_color=np.asarray(ground_color, dtype=np.uint8),
    )


def pipeline_bake_normals(
    input_path: str,
    output_path: str,
    *,
    intensity_range: Tuple[float, float],
    brightness: float = 70.0,
    voxel_size: float = 0.5,
    shading_mode: str = "lambertian",
    light_dir: Tuple[float, float, float] = (0.0, 0.0, -1.0),
    ambient: float = DEFAULT_AMBIENT,
    ground_color: Tuple[int, int, int] = (60, 40, 30),
    sky_color: Tuple[int, int, int] = (180, 210, 255),
    chunk: int = CHUNK,
    min_support: int = MIN_SUPPORT,
    planarity_threshold: float = PLANARITY_THRESHOLD,
    up_vector: Tuple[float, float, float] = (0.0, 0.0, 1.0),
    invert_globally: bool = False,
    block_size: int = 1_000_000,
    on_progress: Optional[Callable[[ProgressEvent], None]] = None,
    cancel_flag: Optional[threading.Event] = None,
    progress_every: int = 5,
    on_orientation_result: Optional[Callable[[object], None]] = None,
) -> PipelineResult:
    """Two-pass voxel-normal bake + shading.

    Pass 0 (cheap): stream the first 10 blocks of scan 0 to find the
    file-wide AABB minimum (used as the voxel grid origin so the chunk
    keys are bounded).

    Pass 1: stream **all** blocks of **all** scans into a single shared
    :class:`VoxelAccumulator`. After every scan, finalize() runs once
    to produce a frozen chunk dict; :func:`orient_normals` then runs
    against ``up_vector``. If ``invert_globally`` is True, every frozen
    normal is flipped once (used to fix scans where the global
    orientation came out backwards).

    Pass 2: re-open the source, look up per-block normals via
    :func:`lookup_normals`, compute a base intensity-RGB, apply the
    chosen shading kernel, and write the shaded block out.

    The source file is opened **twice** — pye57 doesn't support rewinding
    a CompressedVectorReader, so two-pass means two physical reads. On
    the carpark_stairs fixture (~4 M points / ~120 MB) that's negligible.

    Returns
    -------
    PipelineResult
        ``voxel_quality_fraction`` is the share of Pass-2 query points
        that landed in a quality-True voxel; ``n_components`` is the
        number of connected components produced by orient_normals.
    """
    _validate_shading_mode(shading_mode)
    if intensity_range[1] <= intensity_range[0]:
        raise ValueError(
            f"intensity_range must be (lo, hi) with hi > lo; got {intensity_range!r}"
        )
    if voxel_size <= 0:
        raise ValueError(f"voxel_size must be positive; got {voxel_size}")

    t0 = time.perf_counter()

    # --- Pass 0: AABB origin -------------------------------------------------
    with E57CloneReader(input_path) as reader_p0:
        aabb_summary = get_aabb_and_intensity_range(
            reader_p0, sample_blocks=10, block_size=200_000
        )
    origin = np.asarray(aabb_summary["aabb_min"], dtype=np.float64)
    # Defensive: if the AABB sampler saw no points, fall back to (0,0,0).
    if not np.isfinite(origin).all():
        origin = np.zeros(3, dtype=np.float64)

    # --- Pass 1: voxel accumulation across every scan ------------------------
    accumulator = VoxelAccumulator(
        origin=origin,
        voxel_size=voxel_size,
        chunk=chunk,
        min_support=min_support,
        planarity_threshold=planarity_threshold,
    )

    with E57CloneReader(input_path) as reader_p1:
        scan_count = reader_p1.scan_count
        # Precondition for the writer side; check now to fail fast.
        for s in reader_p1.iter_scans():
            if not s.has_rgb():
                raise UnsupportedFileError(
                    f"scan {s.index!r} has no colorRed/Green/Blue prototype; "
                    "V2.0 cannot bake RGB into an intensity-only scan"
                )

        total_points_estimate = sum(s.total_points for s in reader_p1.iter_scans())
        p1 = _ProgressEmitter(
            on_progress, "pass1", progress_every, total_points_estimate
        )
        for scan_reader in reader_p1.iter_scans():
            for block in scan_reader.iter_blocks(block_size=block_size):
                _maybe_cancel(cancel_flag)
                xyz = _xyz_block(block)
                accumulator.add_block(xyz)
                p1.add(xyz.shape[0])
        p1.flush()

    # --- Finalize: dilate + eigh + orient ------------------------------------
    fin_emitter = _ProgressEmitter(on_progress, "finalize", 1, 0)
    frozen = accumulator.finalize()
    fin_emitter.flush()
    orient_result = orient_normals(
        frozen,
        up_vector=np.asarray(up_vector, dtype=np.float32),
        voxel_size=voxel_size,
    )
    if on_orientation_result is not None:
        try:
            on_orientation_result(orient_result)
        except Exception:  # pragma: no cover - never let UI callbacks crash the pipeline
            pass
    if invert_globally:
        # Flip every frozen normal in place. We don't touch quality
        # flags or means — only the unit-vector directions.
        for fc in frozen.values():
            fc.normals *= -1.0

    n_components = len(orient_result.components)

    # --- Pass 2: re-stream + shade + write -----------------------------------
    total_points = 0
    blocks_written = 0
    quality_points = 0

    with E57CloneReader(input_path) as reader_p2:
        total_points_estimate = sum(s.total_points for s in reader_p2.iter_scans())
        p2 = _ProgressEmitter(
            on_progress, "pass2", progress_every, total_points_estimate
        )
        with E57CloneWriter(output_path, source=reader_p2) as writer:
            writer.copy_file_header()
            for img in reader_p2.images2D:
                writer.copy_image2D(img)
            for extra in reader_p2.extra_nodes:
                writer.clone_node(extra)
            writer.copy_pointGroupingSchemes_if_present()

            for scan_reader in reader_p2.iter_scans():
                with writer.begin_scan(
                    scan_reader,
                    block_size=block_size,
                    own_color_limits=True,
                ) as scan_writer:
                    for block in scan_reader.iter_blocks(block_size=block_size):
                        _maybe_cancel(cancel_flag)
                        xyz = _xyz_block(block)
                        normals, quality = lookup_normals(
                            frozen, origin, voxel_size, chunk, xyz
                        )
                        raw_inten = _intensity_to_raw(block, intensity_range)
                        base_rgb = bake_rgb_from_intensity(
                            raw_inten,
                            max_inten=float(intensity_range[1]),
                            brightness=brightness,
                        )
                        shaded = _shade_block(
                            base_rgb,
                            normals,
                            quality,
                            shading_mode=shading_mode,
                            light_dir=light_dir,
                            ambient=ambient,
                            ground_color=ground_color,
                            sky_color=sky_color,
                        )
                        _apply_rgb_to_block(block, shaded)
                        n = scan_writer.write_block(block)
                        total_points += n
                        blocks_written += 1
                        quality_points += int(quality.sum())
                        p2.add(n)
                    scan_writer.update_color_limits()
        p2.flush()

    quality_fraction = (
        float(quality_points) / float(total_points) if total_points > 0 else 0.0
    )
    elapsed = time.perf_counter() - t0
    return PipelineResult(
        output_path=output_path,
        output_size_bytes=os.path.getsize(output_path),
        scan_count=scan_count,
        total_points=total_points,
        blocks_written=blocks_written,
        elapsed_seconds=elapsed,
        peak_rss_bytes=_peak_rss_bytes(),
        voxel_quality_fraction=quality_fraction,
        n_components=n_components,
    )
