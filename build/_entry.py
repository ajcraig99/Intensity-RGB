"""Frozen-bundle entrypoint for the ``intensity-recolor`` binary.

This stub is the PyInstaller entry script. It intentionally lives in
``build/`` (not inside the ``intensity_rgb`` package) so the package's
own ``__main__.py`` (GUI launcher) and the ``cli.py`` console-script
entry both remain untouched.

Dispatch rules:

* No args, or first arg is ``gui`` -> launch the PySide6 desktop UI
  (``intensity_rgb.app.main``). This matches the ``python -m intensity_rgb``
  semantics from Wave 4.
* Anything else -> forward to ``intensity_rgb.cli.main``, which is the
  same entry point the ``[project.scripts]`` ``intensity-recolor`` shim
  uses for ``pip install``-based deployments.

The bundle smoke test in ``tests/test_bundle_linux.sh`` exercises the
CLI path (``--help``, ``clone --help``, ``bake --help``, and a tiny
``clone`` of the ``single_scan_rgb.e57`` fixture).
"""
from __future__ import annotations

import sys


def _looks_like_gui_invocation(argv: list[str]) -> bool:
    # ``argv[0]`` is the program name; subsequent entries are user args.
    rest = argv[1:]
    if not rest:
        return True
    if rest[0] == "gui":
        # Consume the ``gui`` marker so the GUI never sees it.
        del argv[1]
        return True
    return False


def main() -> int:
    if _looks_like_gui_invocation(sys.argv):
        from intensity_rgb.app import main as gui_main

        return int(gui_main())
    from intensity_rgb.cli import main as cli_main

    return int(cli_main())


if __name__ == "__main__":
    sys.exit(main())
