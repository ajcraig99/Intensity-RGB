"""Module entrypoint for ``python -m intensity_rgb``.

Launches the Wave 4 PySide6 desktop UI defined in
:mod:`intensity_rgb.app`. For headless smoke tests, set
``QT_QPA_PLATFORM=offscreen`` before invoking.
"""
from __future__ import annotations

import sys

from intensity_rgb.app import main


if __name__ == "__main__":
    sys.exit(main())
