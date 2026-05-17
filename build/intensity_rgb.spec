# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Linux x86_64 onedir bundle of Intensity-RGB V2.0
# (Wave 5 / E1). The resulting binary is named ``intensity-recolor`` and
# routes to the same CLI as the ``[project.scripts]`` entry in
# ``pyproject.toml`` (``intensity_rgb.cli:main``).
#
# The GUI (``intensity_rgb.app:main``) is also bundled and importable via
# ``python -m intensity_rgb`` semantics inside the frozen tree; it is not
# the primary console entry because the bundle is a console-mode binary
# that supports both CLI subcommands and (when invoked with no args /
# ``gui``) launching the Qt window.
#
# Run from the repo root via ``build/build.sh``.

import os
import sys
from pathlib import Path

# ``SPECPATH`` is set by PyInstaller when the spec is loaded; fall back to
# ``__file__`` so the file is still readable as a regular Python module.
# ``SPECPATH`` is the directory containing this spec file when invoked
# via ``pyinstaller``. We don't use ``__file__`` because PyInstaller
# ``exec``s the spec without binding it.
SPEC_DIR = Path(globals().get("SPECPATH", os.getcwd()) or os.getcwd())
REPO_ROOT = SPEC_DIR.parent
VENDOR_PYE57 = REPO_ROOT / "vendor" / "pye57" / "src" / "pye57"

# Make sure both the package and the vendored pye57 are on the analysis path.
PATHS = [str(REPO_ROOT), str(VENDOR_PYE57.parent)]

# ---------------------------------------------------------------------------
# Hidden imports
# ---------------------------------------------------------------------------
# PyInstaller's hooks usually find PySide6/numpy/scipy/matplotlib, but we
# pin the submodules the app actually imports so a partial hook upstream
# does not silently break the bundle.

hiddenimports = [
    # First-party — keep both the GUI and CLI entry points discoverable.
    "intensity_rgb",
    "intensity_rgb.__main__",
    "intensity_rgb.app",
    "intensity_rgb.cli",
    "intensity_rgb.pipeline",
    "intensity_rgb.worker",
    "intensity_rgb.capability",
    "intensity_rgb.io",
    "intensity_rgb.io.e57_clone",
    "intensity_rgb.processing",
    # PySide6 surface used by ``app.py``.
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    # pye57 vendored bindings.
    "pye57",
    "pye57.e57",
    "pye57.libe57",
    "pye57.scan_header",
    "pye57.cloning",
    "pye57.streaming",
    "pye57.utils",
    # scipy submodules that scipy.spatial pulls in lazily.
    "scipy",
    "scipy.spatial",
    "scipy.sparse.csgraph",
    "scipy.sparse.csgraph._validation",
    # matplotlib backends we touch via the preview harness.
    "matplotlib",
    "matplotlib.pyplot",
    "matplotlib.backends.backend_agg",
]

# ---------------------------------------------------------------------------
# Data files
# ---------------------------------------------------------------------------
# The libe57 C-extension lives inside the vendored pye57 source tree. It
# is already a Python extension module so PyInstaller should pick it up
# via the ``pye57.libe57`` hidden import, but we also ship it explicitly
# as data into ``pye57/`` so any data-file lookups (none expected) work.

EXT_SUFFIX = f"cpython-{sys.version_info.major}{sys.version_info.minor}-x86_64-linux-gnu.so"
LIBE57_SO = VENDOR_PYE57 / f"libe57.{EXT_SUFFIX}"

datas = []
if LIBE57_SO.exists():
    datas.append((str(LIBE57_SO), "pye57"))

# Ship the pye57 ``__version__.py`` alongside so ``pye57.__version__``
# resolves under the frozen package layout.
version_py = VENDOR_PYE57 / "__version__.py"
if version_py.exists():
    datas.append((str(version_py), "pye57"))

# Collect PySide6 Qt plugins automatically — required for QApplication
# bootstrap. The PySide6 hook normally does this; we keep it explicit
# so the bundle works even if upstream hook coverage changes.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules  # noqa: E402

datas += collect_data_files("PySide6", includes=["plugins/*", "Qt/plugins/*"])
# Pull in any submodules of pye57 that pyinstaller might miss (small package).
hiddenimports += collect_submodules("pye57")

# ---------------------------------------------------------------------------
# Excludes — keep the bundle reasonable
# ---------------------------------------------------------------------------
# We never use Tkinter at runtime; the V1 script did but V2.0 is Qt-only.
# Drop unittest only if we are not running the smoke suite from inside
# the bundle (we aren't).
excludes = [
    # ---- V1 holdovers --------------------------------------------------
    "tkinter",
    "_tkinter",
    # ---- Qt modules we don't use --------------------------------------
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth",
    "PySide6.QtNetworkAuth",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtSerialPort",
    "PySide6.QtSerialBus",
    "PySide6.QtRemoteObjects",
    "PySide6.QtNfc",
    "PySide6.QtSensors",
    "PySide6.QtTextToSpeech",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSpatialAudio",
    # ---- Huge transitive deps from the system Python ------------------
    # These get pulled in by matplotlib/sympy/pandas hooks but the app
    # itself never touches them. Excluding shrinks the bundle from
    # ~4.7 GB to ~150-200 MB.
    "torch",
    "torchvision",
    "torchaudio",
    "triton",
    "nvidia",  # nvidia-cudnn, nvidia-nccl, etc.
    "tensorflow",
    "tensorboard",
    "sympy",
    "pandas",
    "lxml",
    "cryptography",
    "bcrypt",
    "nacl",
    "gi",
    "cairo",
    "GTK",
    "fsspec",
    "jinja2",
    "win32com",
    "pycparser",
    "certifi",
    "urllib3",
    "IPython",
    "ipykernel",
    "jedi",
    "parso",
    "pytest",
    "_pytest",
    "pygments",
    "PIL",  # matplotlib only needs Image for raster; agg backend doesn't need PIL
    "PyQt5",
    "PyQt6",
    "wx",
    "notebook",
    "jupyter",
    "jupyter_client",
    "jupyter_core",
    # Matplotlib non-Agg backends; we only use Agg + the preview render.
    "matplotlib.backends.backend_qtagg",
    "matplotlib.backends.backend_qt5agg",
    "matplotlib.backends.backend_qt6agg",
    "matplotlib.backends.backend_gtk3agg",
    "matplotlib.backends.backend_gtk4agg",
    "matplotlib.backends.backend_wxagg",
    "matplotlib.backends.backend_tkagg",
    "matplotlib.backends.backend_webagg",
    "matplotlib.backends.backend_nbagg",
]

# ---------------------------------------------------------------------------
# Analysis / build
# ---------------------------------------------------------------------------

# Use the bundle's own entry stub so the GUI launcher in
# ``intensity_rgb/__main__.py`` stays untouched. The stub dispatches
# CLI vs GUI based on argv (see ``build/_entry.py``).
ENTRY = str(SPEC_DIR / "_entry.py")

a = Analysis(
    [ENTRY],
    pathex=PATHS,
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="intensity-recolor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="intensity-recolor",
)
