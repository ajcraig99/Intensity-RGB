"""Command-line interface for Intensity-RGB V2.0 (Wave 3 / C2).

Subcommands:

* ``clone`` — byte-faithful streaming clone of an ``.e57`` (exercises the
  writer path end-to-end; G1a Mode A).
* ``recolor-test`` — production code path with a trivial constant-RGB
  transform (G1a Mode B). Used to diff the rewrite path against ``clone``.
* ``bake`` — the real intensity-->RGB pipeline, with optional voxel-normal
  shading.

The CLI is a thin wrapper around the Qt-free orchestration in
``intensity_rgb.pipeline`` (Wave 3 / C1). All ranges/tuples are parsed
``--flag X,Y,Z`` style with comma-separated values. Exit codes:

* 0 — success
* 1 — user/operational error (missing file, auto-range declined, etc.)
* 2 — unsupported file (``UnsupportedFileError`` from the pipeline)
* 3 — unexpected exception
"""
from __future__ import annotations

import argparse
import math
import os
import resource
import sys
import time
import traceback
from typing import Callable, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Argument parsers for compound flags
# ---------------------------------------------------------------------------


def _parse_csv_floats(s: str, n: int, name: str) -> Tuple[float, ...]:
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != n:
        raise argparse.ArgumentTypeError(
            f"{name}: expected {n} comma-separated numbers (e.g. "
            f"{','.join(['0'] * n)}), got {s!r}"
        )
    try:
        return tuple(float(p) for p in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{name}: could not parse {s!r} as {n} numbers ({exc})"
        ) from None


def _parse_csv_ints(s: str, n: int, name: str) -> Tuple[int, ...]:
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != n:
        raise argparse.ArgumentTypeError(
            f"{name}: expected {n} comma-separated integers (e.g. "
            f"{','.join(['0'] * n)}), got {s!r}"
        )
    try:
        return tuple(int(p) for p in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{name}: could not parse {s!r} as {n} integers ({exc})"
        ) from None


def _intensity_range(s: str) -> Tuple[float, float]:
    lo, hi = _parse_csv_floats(s, 2, "--intensity-range")
    if not hi > lo:
        raise argparse.ArgumentTypeError(
            f"--intensity-range: max ({hi}) must be > min ({lo})"
        )
    return (lo, hi)


def _rgb_triplet(s: str) -> Tuple[int, int, int]:
    r, g, b = _parse_csv_ints(s, 3, "--rgb")
    for v in (r, g, b):
        if not 0 <= v <= 255:
            raise argparse.ArgumentTypeError(
                f"--rgb: components must be 0..255, got {(r, g, b)}"
            )
    return (r, g, b)


def _color_triplet(s: str, name: str) -> Tuple[int, int, int]:
    r, g, b = _parse_csv_ints(s, 3, name)
    for v in (r, g, b):
        if not 0 <= v <= 255:
            raise argparse.ArgumentTypeError(
                f"{name}: components must be 0..255, got {(r, g, b)}"
            )
    return (r, g, b)


def _ground_color(s: str) -> Tuple[int, int, int]:
    return _color_triplet(s, "--ground-color")


def _sky_color(s: str) -> Tuple[int, int, int]:
    return _color_triplet(s, "--sky-color")


def _xyz_triplet(s: str, name: str) -> Tuple[float, float, float]:
    return _parse_csv_floats(s, 3, name)  # type: ignore[return-value]


def _up_vector(s: str) -> Tuple[float, float, float]:
    return _xyz_triplet(s, "--up-vector")


def _light_dir_az_el(s: str) -> Tuple[float, float, float]:
    """Parse ``--light-dir AZ,EL`` (degrees) into a unit xyz vector
    *toward* the light.

    Convention (consistent with ``processing.shading.lambertian``):
    ``light_dir`` is the direction **from the surface toward the light
    source**, so ``dot(N, L) > 0`` means the surface is facing the
    light and is lit.

    Spherical mapping:
        x = cos(el) * cos(az)
        y = cos(el) * sin(az)
        z = sin(el)
    With ``el=90`` -> straight up (+Z), ``el=-90`` -> straight down.
    Default for backwards compatibility with the design doc is
    ``--light-dir 0,-90`` (light directly below, i.e. unusual) — most
    surveys want ``--light-dir 0,90`` (light above) for "sun overhead".
    """
    az, el = _parse_csv_floats(s, 2, "--light-dir")
    az_r = math.radians(az)
    el_r = math.radians(el)
    x = math.cos(el_r) * math.cos(az_r)
    y = math.cos(el_r) * math.sin(az_r)
    z = math.sin(el_r)
    return (x, y, z)


# ---------------------------------------------------------------------------
# Progress reporter
# ---------------------------------------------------------------------------


def _fmt_secs(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        return "?:??"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _fmt_pts(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1e9:.1f}G"
    if n >= 1_000_000:
        return f"{n / 1e6:.0f}M"
    if n >= 1_000:
        return f"{n / 1e3:.0f}K"
    return str(n)


def _peak_rss_bytes() -> int:
    """Peak resident-set size of this process in bytes (Linux)."""
    ru = resource.getrusage(resource.RUSAGE_SELF)
    # On Linux ``ru_maxrss`` is in kilobytes.
    return int(ru.ru_maxrss) * 1024


class _PrintProgress:
    """Throttled progress printer.

    Adapter from the pipeline's ``on_progress(ProgressEvent)`` callback
    to a human-readable status line. We print at most one update per
    ``min_interval_s`` seconds (default 2s) or after every ``min_blocks``
    callback invocations (default 10), whichever fires first.

    The pipeline already throttles to every N blocks internally
    (``progress_every`` default 5), so our own throttle layers on top.

    Output is written to ``stderr`` and overwritten with ``\r``. The
    final ``finalize`` call emits a trailing newline.
    """

    def __init__(
        self,
        label: str,
        total: Optional[int] = None,
        *,
        min_interval_s: float = 2.0,
        min_blocks: int = 10,
        stream=None,
    ):
        self.label = label
        self.total = total
        self.min_interval_s = min_interval_s
        self.min_blocks = min_blocks
        self.stream = stream if stream is not None else sys.stderr
        self.t0 = time.monotonic()
        self.last_print = 0.0
        self.last_line_len = 0
        self.calls = 0
        self.points = 0
        self.last_print_calls = 0
        self.finished = False
        self.last_throughput: Optional[float] = None
        self.last_rss: Optional[int] = None
        self.last_stage: Optional[str] = None

    def on_progress(self, *args, **kwargs) -> None:
        """Pipeline progress callback.

        Accepts either the C1 ``ProgressEvent`` calling convention
        (``on_progress(event)``) or the legacy ``(points, total)`` tuple,
        so the CLI keeps working if C1's signature changes upstream.
        """
        event = args[0] if args else None
        if event is not None and hasattr(event, "points_done"):
            self.points = int(event.points_done)
            if getattr(event, "points_total", 0):
                self.total = int(event.points_total)
            tput = getattr(event, "throughput_pts_per_sec", None)
            if tput is not None:
                self.last_throughput = float(tput)
            rss = getattr(event, "peak_rss_bytes", None)
            if rss is not None:
                self.last_rss = int(rss)
            stage = getattr(event, "stage", None)
            if stage:
                self.last_stage = str(stage)
        elif args:
            # Fallback: (points_done, total) tuple.
            self.points = int(args[0])
            if len(args) > 1 and args[1] is not None:
                self.total = int(args[1])
        self.calls += 1
        now = time.monotonic()
        if (
            now - self.last_print >= self.min_interval_s
            or self.calls - self.last_print_calls >= self.min_blocks
        ):
            self._emit(now)
            self.last_print = now
            self.last_print_calls = self.calls

    def _emit(self, now: float) -> None:
        elapsed = max(now - self.t0, 1e-6)
        # Prefer pipeline-reported sliding-window throughput; fall back
        # to cumulative average.
        if self.last_throughput is not None and self.last_throughput > 0:
            rate = self.last_throughput
        else:
            rate = self.points / elapsed if elapsed > 0 else 0.0
        if self.last_rss is not None:
            rss = self.last_rss
        else:
            rss = _peak_rss_bytes()
        rss_mb = rss / (1024 * 1024)
        stage = f"[{self.last_stage}] " if self.last_stage else ""
        if self.total and self.total > 0:
            pct = 100.0 * self.points / self.total
            eta = (self.total - self.points) / rate if rate > 0 else float("inf")
            line = (
                f"{stage}{self.label}: {_fmt_pts(self.points)} / {self.total} "
                f"({pct:.1f}%) @ {rate / 1e6:.1f}M pts/s, RSS {rss_mb:.0f}MB, "
                f"ETA {_fmt_secs(eta)}"
            )
        else:
            line = (
                f"{stage}{self.label}: {_fmt_pts(self.points)} pts @ "
                f"{rate / 1e6:.1f}M pts/s, RSS {rss_mb:.0f}MB, "
                f"elapsed {_fmt_secs(elapsed)}"
            )
        pad = max(0, self.last_line_len - len(line))
        self.stream.write("\r" + line + " " * pad)
        self.stream.flush()
        self.last_line_len = len(line)

    def finalize(self) -> None:
        if self.finished:
            return
        self.finished = True
        if self.last_line_len:
            self.stream.write("\n")
            self.stream.flush()

    def elapsed(self) -> float:
        return time.monotonic() - self.t0


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------


def _result_get(result, key, default=None):
    """Read a field from either a dict or a dataclass-style object."""
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)


def _print_summary(
    output: str,
    result,
    elapsed: float,
    *,
    voxel_quality: Optional[float] = None,
    components: Optional[int] = None,
    stream=None,
) -> None:
    stream = stream if stream is not None else sys.stdout
    try:
        size_bytes = os.path.getsize(output)
        size_mb = size_bytes / (1024 * 1024)
    except OSError:
        size_mb = float("nan")
    scan_count = _result_get(result, "scan_count", "?")
    total_points = _result_get(result, "total_points", 0)
    rss_bytes = _result_get(result, "peak_rss_bytes", None)
    if rss_bytes is None:
        rss_bytes = _peak_rss_bytes()
    rss_mb = rss_bytes / (1024 * 1024)

    stream.write(f"Done. Output: {output} ({size_mb:.1f} MB)\n")
    stream.write(f"  Scan count:       {scan_count}\n")
    if isinstance(total_points, int):
        stream.write(f"  Total points:     {total_points:,}\n")
    else:
        stream.write(f"  Total points:     {total_points}\n")
    stream.write(f"  Elapsed:          {_fmt_secs(elapsed)}\n")
    stream.write(f"  Peak RSS:         {rss_mb:.0f} MB\n")
    if voxel_quality is not None:
        stream.write(f"  Voxel quality:    {100.0 * voxel_quality:.1f}%\n")
    if components is not None:
        stream.write(f"  Components:       {components}\n")
    stream.flush()


# ---------------------------------------------------------------------------
# Auto-range
# ---------------------------------------------------------------------------


def _maybe_auto_range(
    input_path: str,
    *,
    block_size: int,
    sample_blocks: int = 10,
    skip_prompt: bool = False,
) -> Tuple[float, float]:
    """Stream a sample of the file and return (min, max) intensity.

    Prompts the user unless ``skip_prompt`` (i.e. ``--yes``) is set.
    Raises ``SystemExit(1)`` on decline.
    """
    from intensity_rgb.pipeline import get_aabb_and_intensity_range
    from intensity_rgb.io.e57_clone import E57CloneReader

    print(
        f"Auto-detecting intensity range from first {sample_blocks} block(s) "
        f"of {input_path} ...",
        file=sys.stderr,
    )
    with E57CloneReader(input_path) as reader:
        info = get_aabb_and_intensity_range(
            reader, sample_blocks=sample_blocks, block_size=min(block_size, 200_000)
        )
    if info.get("points_seen", 0) == 0:
        print(
            "error: file has no readable points; --auto-range cannot run",
            file=sys.stderr,
        )
        raise SystemExit(1)
    lo = float(info["intensity_min"])
    hi = float(info["intensity_max"])
    if not hi > lo:
        print(
            f"error: --auto-range sample produced degenerate range [{lo}, {hi}]; "
            "pass --intensity-range MIN,MAX explicitly",
            file=sys.stderr,
        )
        raise SystemExit(1)
    print(f"  Estimated intensity range: [{lo}, {hi}]", file=sys.stderr)
    if not skip_prompt:
        try:
            ans = input("Use this intensity range? [Y/n] ").strip().lower()
        except EOFError:
            ans = ""
        if ans and ans not in ("y", "yes"):
            print("user declined auto-range", file=sys.stderr)
            raise SystemExit(1)
    return (lo, hi)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def _cmd_clone(args: argparse.Namespace) -> int:
    from intensity_rgb.pipeline import pipeline_clone

    progress = _PrintProgress("clone")
    result = pipeline_clone(
        args.input,
        args.output,
        block_size=args.block_size,
        on_progress=progress.on_progress,
    )
    progress.finalize()
    _print_summary(args.output, result, progress.elapsed())
    return 0


def _cmd_recolor_test(args: argparse.Namespace) -> int:
    """Production-path smoke: write a fixed RGB triplet into every point.

    Uses the same clone+rewrite codepath as ``bake``, but with a trivial
    constant-RGB transform. Useful for diff-testing the streaming write
    path against a pure ``clone`` of the same source.
    """
    from intensity_rgb.io.e57_clone import (
        clone_file,
        constant_rgb_transform,
    )

    progress = _PrintProgress("recolor-test")
    transform = constant_rgb_transform(rgb=args.rgb)
    result = clone_file(
        args.input,
        args.output,
        transform=transform,
        update_color_limits=True,
        block_size=args.block_size,
    )
    progress.points = int(result.get("total_points", 0))
    progress._emit(time.monotonic())
    progress.finalize()
    _print_summary(args.output, result, progress.elapsed())
    return 0


def _cmd_bake(args: argparse.Namespace) -> int:
    from intensity_rgb.pipeline import (
        pipeline_bake_intensity,
        pipeline_bake_normals,
    )

    # Resolve intensity range: --auto-range vs --intensity-range.
    if args.auto_range and args.intensity_range is not None:
        print(
            "error: --auto-range and --intensity-range are mutually exclusive",
            file=sys.stderr,
        )
        return 1
    if args.auto_range:
        intensity_range = _maybe_auto_range(
            args.input, block_size=args.block_size, skip_prompt=args.yes
        )
    elif args.intensity_range is not None:
        intensity_range = args.intensity_range
    else:
        print(
            "error: --intensity-range is required (or pass --auto-range)",
            file=sys.stderr,
        )
        return 1

    progress = _PrintProgress("bake")

    if args.shading == "none":
        result = pipeline_bake_intensity(
            args.input,
            args.output,
            intensity_range=intensity_range,
            brightness=args.brightness,
            block_size=args.block_size,
            on_progress=progress.on_progress,
        )
        progress.finalize()
        _print_summary(args.output, result, progress.elapsed())
    else:
        result = pipeline_bake_normals(
            args.input,
            args.output,
            intensity_range=intensity_range,
            brightness=args.brightness,
            voxel_size=args.voxel_size,
            shading_mode=args.shading,
            light_dir=args.light_dir,
            ambient=args.ambient,
            ground_color=args.ground_color,
            sky_color=args.sky_color,
            chunk=args.chunk,
            min_support=args.min_support,
            planarity_threshold=args.planarity_threshold,
            up_vector=args.up_vector,
            invert_globally=args.invert_globally,
            block_size=args.block_size,
            on_progress=progress.on_progress,
        )
        progress.finalize()
        _print_summary(
            args.output,
            result,
            progress.elapsed(),
            voxel_quality=_result_get(result, "voxel_quality_fraction"),
            components=_result_get(result, "n_components"),
        )
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="intensity-recolor",
        description=(
            "Intensity-RGB V2.0 — streaming .e57 recolor with optional "
            "voxel-normal shading."
        ),
    )
    sub = parser.add_subparsers(
        dest="command", metavar="{clone,recolor-test,bake}"
    )
    sub.required = False  # so --help without a subcommand works

    # -- clone -------------------------------------------------------------
    p_clone = sub.add_parser(
        "clone",
        help="Stream-clone an .e57 file (identity transform).",
        description=(
            "Byte-faithful streaming clone of an .e57. Used as an end-to-"
            "end smoke test of the writer path (G1a Mode A)."
        ),
    )
    p_clone.add_argument("--input", required=True, help="Source .e57 path.")
    p_clone.add_argument("--output", required=True, help="Destination .e57 path.")
    p_clone.add_argument(
        "--block-size",
        type=int,
        default=1_000_000,
        help="Points per streaming block (default: 1000000).",
    )
    p_clone.set_defaults(func=_cmd_clone)

    # -- recolor-test ------------------------------------------------------
    p_test = sub.add_parser(
        "recolor-test",
        help="Production-path smoke: write a constant RGB into every point.",
        description=(
            "Stream-write the destination file using the production "
            "clone+rewrite path with a trivial constant-RGB transform. "
            "Diff against ``clone`` output to validate the rewrite path."
        ),
    )
    p_test.add_argument("--input", required=True, help="Source .e57 path.")
    p_test.add_argument("--output", required=True, help="Destination .e57 path.")
    p_test.add_argument(
        "--rgb",
        type=_rgb_triplet,
        default=(255, 0, 0),
        metavar="R,G,B",
        help="Constant RGB triplet (default: 255,0,0).",
    )
    p_test.add_argument(
        "--block-size",
        type=int,
        default=1_000_000,
        help="Points per streaming block (default: 1000000).",
    )
    p_test.set_defaults(func=_cmd_recolor_test)

    # -- bake --------------------------------------------------------------
    p_bake = sub.add_parser(
        "bake",
        help="Bake intensity-->RGB (and optional voxel-normal shading) into a new .e57.",
        description=(
            "Stream-process an input .e57, replacing the RGB columns with "
            "values derived from each point's intensity. Optional shading "
            "modes run a two-pass pipeline: voxel-PCA normals on pass 1, "
            "shaded recolor on pass 2.\n\n"
            "Light-direction convention: --light-dir AZ,EL gives degrees "
            "(azimuth around +Z, elevation off the XY plane). Internally "
            "this is the direction *from the surface toward the light* "
            "so that dot(N, L) > 0 means the surface is lit."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_bake.add_argument("--input", required=True, help="Source .e57 path.")
    p_bake.add_argument("--output", required=True, help="Destination .e57 path.")
    p_bake.add_argument(
        "--intensity-range",
        type=_intensity_range,
        default=None,
        metavar="MIN,MAX",
        help="Intensity normalization range. Required unless --auto-range.",
    )
    p_bake.add_argument(
        "--auto-range",
        action="store_true",
        help="Estimate intensity range from a sample of the file.",
    )
    p_bake.add_argument(
        "--yes",
        action="store_true",
        help="Skip the auto-range confirmation prompt.",
    )
    p_bake.add_argument(
        "--brightness",
        type=float,
        default=70.0,
        help="HSV brightness/value channel, 0..100 (default: 70).",
    )
    p_bake.add_argument(
        "--shading",
        choices=["none", "lambertian", "three_point", "normal_as_color"],
        default="none",
        help="Shading mode (default: none -> intensity only).",
    )
    p_bake.add_argument(
        "--voxel-size",
        type=float,
        default=0.5,
        help="Voxel edge length for the normals accumulator (default: 0.5).",
    )
    p_bake.add_argument(
        "--light-dir",
        type=_light_dir_az_el,
        default=_light_dir_az_el("0,90"),
        metavar="AZ,EL",
        help=(
            "Light direction as azimuth,elevation in degrees. Default "
            "0,90 = straight up (light from above)."
        ),
    )
    p_bake.add_argument(
        "--ambient",
        type=float,
        default=0.3,
        help="Ambient fraction in [0,1] (default: 0.3).",
    )
    p_bake.add_argument(
        "--ground-color",
        type=_ground_color,
        default=(60, 40, 30),
        metavar="R,G,B",
        help="Hemisphere ambient ground colour (default: 60,40,30).",
    )
    p_bake.add_argument(
        "--sky-color",
        type=_sky_color,
        default=(180, 210, 255),
        metavar="R,G,B",
        help="Hemisphere ambient sky colour (default: 180,210,255).",
    )
    p_bake.add_argument(
        "--up-vector",
        type=_up_vector,
        default=(0.0, 0.0, 1.0),
        metavar="X,Y,Z",
        help="Up-vector prior for normal orientation (default: 0,0,1).",
    )
    p_bake.add_argument(
        "--invert-globally",
        action="store_true",
        help="Invert all normals globally after orientation.",
    )
    p_bake.add_argument(
        "--chunk",
        type=int,
        default=32,
        help="Voxel-accumulator chunk size C (default: 32; chunk = C^3 voxels).",
    )
    p_bake.add_argument(
        "--min-support",
        type=int,
        default=8,
        help="Minimum points per voxel to estimate a normal (default: 8).",
    )
    p_bake.add_argument(
        "--planarity-threshold",
        type=float,
        default=0.5,
        help="Planarity threshold for accepting a voxel normal (default: 0.5).",
    )
    p_bake.add_argument(
        "--block-size",
        type=int,
        default=1_000_000,
        help="Points per streaming block (default: 1000000).",
    )
    p_bake.set_defaults(func=_cmd_bake)

    return parser


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _dispatch(args: argparse.Namespace) -> int:
    # Import inside dispatch so the parser still works even if a
    # dependency module fails to import (e.g. C1 not yet landed).
    try:
        from intensity_rgb.io.e57_clone import UnsupportedFileError
    except Exception:
        UnsupportedFileError = None  # type: ignore[assignment]

    # Pre-flight: input must exist (cheap UX win — pye57's error is opaque).
    input_path = getattr(args, "input", None)
    if input_path and not os.path.exists(input_path):
        print(f"error: input file not found: {input_path}", file=sys.stderr)
        return 1

    try:
        return int(args.func(args))
    except SystemExit as exc:
        # _maybe_auto_range raises SystemExit(1) on user decline.
        return int(exc.code) if exc.code is not None else 0
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        if UnsupportedFileError is not None and isinstance(exc, UnsupportedFileError):
            print(f"error: {exc}", file=sys.stderr)
            return 2
        # Unknown exception class? Check by name to survive late imports.
        if type(exc).__name__ == "UnsupportedFileError":
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print("unexpected error:", file=sys.stderr)
        traceback.print_exc(limit=8)
        return 3


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return _dispatch(args)


if __name__ == "__main__":
    sys.exit(main())
