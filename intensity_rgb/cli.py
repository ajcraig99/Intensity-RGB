"""Command-line interface for Intensity-RGB V2.0.

This is a Wave 1 skeleton — every subcommand is a stub that exits 2 with a
"not yet implemented" message. Wave 3 (C2) fully implements ``clone``,
``recolor-test``, and ``bake``.
"""
from __future__ import annotations

import argparse
import sys
from typing import Sequence


_NOT_IMPLEMENTED_EXIT = 2


def _stub(command: str) -> int:
    print(f"{command} not yet implemented (Wave 3 — C2)", file=sys.stderr)
    return _NOT_IMPLEMENTED_EXIT


def _cmd_clone(args: argparse.Namespace) -> int:
    return _stub("clone")


def _cmd_recolor_test(args: argparse.Namespace) -> int:
    return _stub("recolor-test")


def _cmd_bake(args: argparse.Namespace) -> int:
    return _stub("bake")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="intensity-recolor",
        description=(
            "Intensity-RGB V2.0 — recolor .e57 point clouds from intensity, "
            "with optional Eye-Dome Lighting shading."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="{clone,recolor-test,bake}")
    subparsers.required = False  # so --help works without a subcommand

    # clone: byte-faithful copy of an .e57 (used to validate the writer path)
    p_clone = subparsers.add_parser(
        "clone",
        help="Clone an .e57 file (read all scans, write them back unchanged).",
        description="Clone an .e57 file end-to-end. Used as a writer smoke test.",
    )
    p_clone.add_argument("--input", required=True, help="Source .e57 file path.")
    p_clone.add_argument("--output", required=True, help="Destination .e57 file path.")
    p_clone.set_defaults(func=_cmd_clone)

    # recolor-test: render a preview PNG of intensity->RGB mapping on a sample.
    p_recolor = subparsers.add_parser(
        "recolor-test",
        help="Render a preview PNG of the intensity->RGB mapping on a sample scan.",
        description=(
            "Sample points from an input .e57 and render a preview PNG showing "
            "the proposed intensity->RGB recolor (no .e57 written)."
        ),
    )
    p_recolor.add_argument("--input", required=True, help="Source .e57 file path.")
    p_recolor.add_argument("--output", required=True, help="Destination PNG path.")
    p_recolor.add_argument(
        "--samples",
        type=int,
        default=100_000,
        help="Number of points to sample for the preview (default: 100000).",
    )
    p_recolor.set_defaults(func=_cmd_recolor_test)

    # bake: full intensity->RGB recolor of an .e57 (the main pipeline).
    p_bake = subparsers.add_parser(
        "bake",
        help="Bake intensity->RGB recolor into a new .e57.",
        description=(
            "Stream-process an input .e57, replacing the RGB columns with values "
            "derived from each point's intensity (and optional EDL shading)."
        ),
    )
    p_bake.add_argument("--input", required=True, help="Source .e57 file path.")
    p_bake.add_argument("--output", required=True, help="Destination .e57 file path.")
    p_bake.add_argument(
        "--shading",
        choices=["none", "edl"],
        default="none",
        help="Optional shading mode applied on top of the intensity ramp.",
    )
    p_bake.set_defaults(func=_cmd_bake)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
