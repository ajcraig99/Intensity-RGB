"""B2 smoke test — exercises E57CloneReader / E57CloneWriter / clone_file
end-to-end against the four fixtures called out in the Wave 2 / B2 brief:

    1. carpark_stairs.e57          + identity_transform                -> ok
    2. tests/artifacts/multi_scan.e57 + identity_transform              -> 3 scans
    3. tests/artifacts/single_scan_rgb.e57 + constant_rgb_transform     -> RGB == (255,0,0)
    4. tests/artifacts/intensity_only.e57 + update_color_limits=True    -> UnsupportedFileError

Each case prints the returned dict (or the exception). Exit status is
non-zero on the first unexpected failure.
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback

import numpy as np

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "vendor", "pye57", "src"))
sys.path.insert(0, REPO_ROOT)

from intensity_rgb.io.e57_clone import (  # noqa: E402
    E57CloneReader,
    UnsupportedFileError,
    clone_file,
    constant_rgb_transform,
    identity_transform,
)
from pye57 import E57, libe57  # noqa: E402


CARPARK = os.path.join(REPO_ROOT, "carpark_stairs.e57")
MULTI = os.path.join(REPO_ROOT, "tests", "artifacts", "multi_scan.e57")
SINGLE_RGB = os.path.join(REPO_ROOT, "tests", "artifacts", "single_scan_rgb.e57")
INT_ONLY = os.path.join(REPO_ROOT, "tests", "artifacts", "intensity_only.e57")


def _read_scan_rgb(path: str, scan_idx: int = 0):
    """Return RGB arrays + colorLimits range for a scan."""
    e = E57(path, mode="r")
    try:
        scan = libe57.StructureNode(e.data3d.get(scan_idx))
        cv_raw = scan["points"]
        cv = cv_raw if isinstance(cv_raw, libe57.CompressedVectorNode) else libe57.CompressedVectorNode(cv_raw)
        n = cv.childCount()
        r = np.empty(n, dtype=np.uint8)
        g = np.empty(n, dtype=np.uint8)
        b = np.empty(n, dtype=np.uint8)
        dbufs = libe57.VectorSourceDestBuffer()
        for name, arr in (("colorRed", r), ("colorGreen", g), ("colorBlue", b)):
            dbufs.append(libe57.SourceDestBuffer(e.image_file, name, arr, n, True, False))
        reader = cv.reader(dbufs)
        reader.read()
        reader.close()
        cl_raw = scan["colorLimits"]
        cl = cl_raw if isinstance(cl_raw, libe57.StructureNode) else libe57.StructureNode(cl_raw)
        limits = {}
        for k in (
            "colorRedMinimum", "colorRedMaximum",
            "colorGreenMinimum", "colorGreenMaximum",
            "colorBlueMinimum", "colorBlueMaximum",
        ):
            limits[k] = libe57.IntegerNode(cl.get(k)).value()
        return r, g, b, limits
    finally:
        e.close()


def main() -> int:
    failures = []
    tmpdir = tempfile.mkdtemp(prefix="b2_smoke_")

    # --- 1. carpark_stairs identity round-trip --------------------------
    out1 = os.path.join(tmpdir, "carpark_clone.e57")
    print("=" * 60)
    print(f"[1/4] carpark_stairs.e57 + identity_transform")
    try:
        result = clone_file(CARPARK, out1, transform=identity_transform, block_size=500_000)
        print("  returned:", result)
        with E57CloneReader(out1) as chk:
            assert chk.scan_count == result["scan_count"], chk.scan_count
            chk_total = sum(s.total_points for s in chk.iter_scans())
        assert chk_total == result["total_points"], (chk_total, result["total_points"])
        print(f"  verified scan_count={result['scan_count']} total_points={result['total_points']}")
    except Exception:
        traceback.print_exc()
        failures.append("carpark identity")

    # --- 2. multi_scan identity ----------------------------------------
    out2 = os.path.join(tmpdir, "multi_scan_clone.e57")
    print("=" * 60)
    print(f"[2/4] multi_scan.e57 (3 scans) + identity_transform")
    try:
        result = clone_file(MULTI, out2, transform=identity_transform)
        print("  returned:", result)
        assert result["scan_count"] == 3, result["scan_count"]
        with E57CloneReader(out2) as chk:
            scan_counts = [s.total_points for s in chk.iter_scans()]
            assert chk.scan_count == 3, chk.scan_count
        print(f"  verified per-scan point counts: {scan_counts}")
    except Exception:
        traceback.print_exc()
        failures.append("multi_scan identity")

    # --- 3. single_scan_rgb constant red + colorLimits ------------------
    out3 = os.path.join(tmpdir, "constant_red.e57")
    print("=" * 60)
    print(f"[3/4] single_scan_rgb.e57 + constant_rgb_transform((255,0,0)) + update_color_limits=True")
    try:
        result = clone_file(
            SINGLE_RGB, out3,
            transform=constant_rgb_transform((255, 0, 0)),
            update_color_limits=True,
        )
        print("  returned:", result)
        r, g, b, limits = _read_scan_rgb(out3, 0)
        assert (r == 255).all(), f"colorRed mismatch: unique={np.unique(r)}"
        assert (g == 0).all(), f"colorGreen mismatch: unique={np.unique(g)}"
        assert (b == 0).all(), f"colorBlue mismatch: unique={np.unique(b)}"
        assert limits == {
            "colorRedMinimum": 0, "colorRedMaximum": 255,
            "colorGreenMinimum": 0, "colorGreenMaximum": 255,
            "colorBlueMinimum": 0, "colorBlueMaximum": 255,
        }, f"colorLimits mismatch: {limits}"
        print(f"  verified RGB constant=(255,0,0) over {r.size} points; colorLimits={limits}")
    except Exception:
        traceback.print_exc()
        failures.append("constant RGB")

    # --- 4. intensity_only refuses update_color_limits ------------------
    out4 = os.path.join(tmpdir, "intensity_only_should_not_exist.e57")
    print("=" * 60)
    print(f"[4/4] intensity_only.e57 + update_color_limits=True  -> expect UnsupportedFileError")
    raised = None
    try:
        clone_file(INT_ONLY, out4, update_color_limits=True)
    except UnsupportedFileError as e:
        raised = e
    except Exception:
        traceback.print_exc()
        failures.append("intensity_only (wrong exception)")
    if raised is None:
        print("  ERROR: no exception raised")
        failures.append("intensity_only (no exception)")
    else:
        print(f"  raised UnsupportedFileError as expected: {raised}")

    print("=" * 60)
    if failures:
        print(f"FAIL: {len(failures)} smoke case(s) failed: {failures}")
        return 1
    print("OK: all 4 smoke cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
