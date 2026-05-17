#!/usr/bin/env bash
# Wave 5 / E1: build the Linux x86_64 onedir PyInstaller bundle.
#
# Outputs:
#   dist/Intensity-RGB-linux-x86_64/      (unpacked bundle)
#   dist/Intensity-RGB-linux-x86_64.zip   (zipped, <= 250 MB target)
set -euo pipefail

cd "$(dirname "$0")/.."

# Use the user-installed pyinstaller (matches A1's --user --break-system-packages pattern).
PYINSTALLER="${PYINSTALLER:-pyinstaller}"
if ! command -v "$PYINSTALLER" >/dev/null 2>&1; then
    if [ -x "$HOME/.local/bin/pyinstaller" ]; then
        PYINSTALLER="$HOME/.local/bin/pyinstaller"
    else
        echo "ERROR: pyinstaller not found on PATH (and ~/.local/bin/pyinstaller missing)" >&2
        exit 1
    fi
fi

# Vendored pye57 must be importable when PyInstaller runs analysis.
export PYTHONPATH="${PYTHONPATH:-}${PYTHONPATH:+:}$PWD/vendor/pye57/src"

# Clean previous build outputs (but leave other dist/ artifacts alone).
rm -rf build/work dist/intensity-recolor dist/Intensity-RGB-linux-x86_64 dist/Intensity-RGB-linux-x86_64.zip

"$PYINSTALLER" --clean --noconfirm \
    --workpath build/work \
    --distpath dist \
    build/intensity_rgb.spec

# Rename the onedir output to a versioned directory for distribution.
mv dist/intensity-recolor dist/Intensity-RGB-linux-x86_64

unpacked_mb=$(du -sm dist/Intensity-RGB-linux-x86_64 | cut -f1)
echo "Unpacked bundle: ${unpacked_mb} MB"

# Zip (quietly) from inside dist/ so paths inside the zip are relative.
# Prefer the system ``zip`` if available; otherwise fall back to
# Python's stdlib ``zipfile`` (Arch base doesn't ship ``zip``).
if command -v zip >/dev/null 2>&1; then
    (cd dist && zip -qr Intensity-RGB-linux-x86_64.zip Intensity-RGB-linux-x86_64)
else
    (cd dist && python3 -m zipfile -c Intensity-RGB-linux-x86_64.zip Intensity-RGB-linux-x86_64)
fi

zipped_mb=$(du -m dist/Intensity-RGB-linux-x86_64.zip | cut -f1)
echo "Zipped bundle:   ${zipped_mb} MB"

if [ "$zipped_mb" -gt 250 ]; then
    echo "ERROR: bundle exceeds 250MB target (${zipped_mb} MB)" >&2
    exit 1
fi
echo "OK: bundle within 250 MB target."
