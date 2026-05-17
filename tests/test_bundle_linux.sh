#!/usr/bin/env bash
# Wave 5 / E1: bundle smoke test for the Linux x86_64 onedir build.
#
# Unpacks dist/Intensity-RGB-linux-x86_64.zip into a temporary directory,
# exercises the CLI surface, and runs a real ``clone`` over the
# Wave-1 / A7 synthetic fixture ``tests/artifacts/single_scan_rgb.e57``.
#
# Requires: ``unzip`` (or stdlib ``python3 -m zipfile``).
set -euo pipefail

cd "$(dirname "$0")/.."

ZIP=dist/Intensity-RGB-linux-x86_64.zip
if [ ! -f "$ZIP" ]; then
    echo "Bundle zip not found at $ZIP -- run build/build.sh first" >&2
    exit 1
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Use ``unzip`` if present; otherwise fall back to Python stdlib (Arch
# base may not ship ``unzip``).
if command -v unzip >/dev/null 2>&1; then
    unzip -q "$ZIP" -d "$TMP"
else
    python3 -m zipfile -e "$ZIP" "$TMP"
fi

BIN="$TMP/Intensity-RGB-linux-x86_64/intensity-recolor"
if [ ! -x "$BIN" ]; then
    echo "Entry binary not found or not executable at $BIN" >&2
    exit 1
fi

# CLI help surface
"$BIN" --help > /dev/null
"$BIN" clone --help > /dev/null
"$BIN" bake --help > /dev/null

# Functional smoke: clone a tiny .e57 from the Wave-1 fixture set.
FIXTURE=tests/artifacts/single_scan_rgb.e57
if [ ! -f "$FIXTURE" ]; then
    echo "Fixture $FIXTURE missing -- regenerate via tests/synthetic_e57.py" >&2
    exit 1
fi
OUT="$TMP/clone_check.e57"
"$BIN" clone --input "$FIXTURE" --output "$OUT" > "$TMP/clone.log" 2>&1 || {
    echo "Clone smoke failed; log follows:" >&2
    cat "$TMP/clone.log" >&2
    exit 1
}
if [ ! -s "$OUT" ]; then
    echo "Clone smoke produced no output at $OUT" >&2
    cat "$TMP/clone.log" >&2
    exit 1
fi

# Optional: the clone log should have printed a summary with point count.
if ! grep -qE "Total points" "$TMP/clone.log"; then
    echo "Warning: clone summary did not mention total points" >&2
    cat "$TMP/clone.log" >&2
fi

echo "Linux bundle smoke OK"
echo "  binary:        $BIN"
echo "  cloned output: $OUT ($(du -h "$OUT" | cut -f1))"
