"""C1 smoke test — exercises the three pipeline entry points against
``carpark_stairs.e57``.

1. pipeline_clone -> identity round-trip.
2. pipeline_bake_intensity -> verify RGB differs from source.
3. pipeline_bake_normals (lambertian) -> assert voxel_quality_fraction
   above the 0.3 floor we expect for an outdoor carpark scan.

Output is human-readable; non-zero exit status on the first failure.
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback

import numpy as np

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "vendor", "pye57", "src"))
sys.path.insert(0, REPO_ROOT)

from intensity_rgb.io.e57_clone import E57CloneReader  # noqa: E402
from intensity_rgb.pipeline import (  # noqa: E402
    get_aabb_and_intensity_range,
    pipeline_bake_intensity,
    pipeline_bake_normals,
    pipeline_clone,
)
from pye57 import E57, libe57  # noqa: E402


CARPARK = os.path.join(REPO_ROOT, "carpark_stairs.e57")


def _read_first_block_rgb(path: str, n: int = 50_000):
    e = E57(path, mode="r")
    try:
        scan = libe57.StructureNode(e.data3d.get(0))
        cv_raw = scan["points"]
        cv = (
            cv_raw
            if isinstance(cv_raw, libe57.CompressedVectorNode)
            else libe57.CompressedVectorNode(cv_raw)
        )
        total = cv.childCount()
        n = min(n, total)
        r = np.empty(n, dtype=np.uint8)
        g = np.empty(n, dtype=np.uint8)
        b = np.empty(n, dtype=np.uint8)
        dbufs = libe57.VectorSourceDestBuffer()
        for name, arr in (("colorRed", r), ("colorGreen", g), ("colorBlue", b)):
            dbufs.append(
                libe57.SourceDestBuffer(e.image_file, name, arr, n, True, False)
            )
        reader = cv.reader(dbufs)
        reader.read()
        reader.close()
        return r, g, b
    finally:
        e.close()


def _progress(stage_name):
    def cb(ev):
        pct = 0.0 if ev.points_total == 0 else 100.0 * ev.points_done / ev.points_total
        tput = (
            "?" if ev.throughput_pts_per_sec is None
            else f"{ev.throughput_pts_per_sec / 1e6:.2f} Mpts/s"
        )
        rss = (
            "?"
            if ev.peak_rss_bytes is None
            else f"{ev.peak_rss_bytes / (1024 ** 2):.0f} MiB"
        )
        print(
            f"    [{stage_name}/{ev.stage}] {ev.points_done:,}/{ev.points_total:,} "
            f"({pct:5.1f}%)  {tput}  rss={rss}"
        )
    return cb


def main() -> int:
    failures = []
    tmpdir = tempfile.mkdtemp(prefix="c1_smoke_")
    print("Using tmpdir:", tmpdir)
    print("Source:", CARPARK)

    # -- AABB probe ----------------------------------------------------------
    print("=" * 70)
    print("[probe] get_aabb_and_intensity_range(carpark_stairs.e57)")
    try:
        with E57CloneReader(CARPARK) as r:
            probe = get_aabb_and_intensity_range(r)
        print(f"  aabb_min={probe['aabb_min']}")
        print(f"  aabb_max={probe['aabb_max']}")
        print(f"  intensity in [{probe['intensity_min']:.4f}, {probe['intensity_max']:.4f}]")
        print(f"  points_seen={probe['points_seen']:,}")
    except Exception:
        traceback.print_exc()
        failures.append("aabb probe")

    # -- 1. pipeline_clone ---------------------------------------------------
    out1 = os.path.join(tmpdir, "c1_clone.e57")
    print("=" * 70)
    print("[1/3] pipeline_clone(carpark_stairs.e57 -> c1_clone.e57)")
    try:
        result = pipeline_clone(
            CARPARK, out1, block_size=500_000, on_progress=_progress("1"),
        )
        print(f"  -> output_path={result.output_path}")
        print(f"     output_size_bytes={result.output_size_bytes:,}")
        print(f"     scan_count={result.scan_count}")
        print(f"     total_points={result.total_points:,}")
        print(f"     blocks_written={result.blocks_written}")
        print(f"     elapsed_seconds={result.elapsed_seconds:.2f}")
        print(
            "     peak_rss_bytes="
            f"{result.peak_rss_bytes:,}" if result.peak_rss_bytes else "     peak_rss_bytes=None"
        )
        assert result.scan_count == 1
        assert result.total_points > 0
    except Exception:
        traceback.print_exc()
        failures.append("pipeline_clone")

    # -- 2. pipeline_bake_intensity ------------------------------------------
    out2 = os.path.join(tmpdir, "c1_bake_i.e57")
    print("=" * 70)
    print("[2/3] pipeline_bake_intensity(intensity_range=(0,4096), brightness=70)")
    try:
        # Capture a small sample of the source RGB for the diff check.
        src_r, src_g, src_b = _read_first_block_rgb(CARPARK, n=50_000)

        result = pipeline_bake_intensity(
            CARPARK,
            out2,
            intensity_range=(0.0, 4096.0),
            brightness=70.0,
            block_size=500_000,
            on_progress=_progress("2"),
        )
        print(f"  -> output_path={result.output_path}")
        print(f"     output_size_bytes={result.output_size_bytes:,}")
        print(f"     total_points={result.total_points:,}")
        print(f"     elapsed_seconds={result.elapsed_seconds:.2f}")
        print(
            "     peak_rss_bytes="
            f"{result.peak_rss_bytes:,}" if result.peak_rss_bytes else "     peak_rss_bytes=None"
        )

        # The bake should produce RGB that differs from the source.
        dst_r, dst_g, dst_b = _read_first_block_rgb(out2, n=50_000)
        same_r = np.array_equal(src_r, dst_r)
        same_g = np.array_equal(src_g, dst_g)
        same_b = np.array_equal(src_b, dst_b)
        if same_r and same_g and same_b:
            raise AssertionError(
                "bake_intensity output RGB is bit-identical to source — "
                "transform did not run"
            )
        # Sanity: count how many of the first 50 k rows changed in any channel.
        diff_any = (src_r != dst_r) | (src_g != dst_g) | (src_b != dst_b)
        frac_changed = float(diff_any.mean())
        print(f"     RGB-diff fraction (first 50k pts): {frac_changed:.3f}")
    except Exception:
        traceback.print_exc()
        failures.append("pipeline_bake_intensity")

    # -- 3. pipeline_bake_normals (lambertian) -------------------------------
    out3 = os.path.join(tmpdir, "c1_bake_n.e57")
    print("=" * 70)
    print("[3/3] pipeline_bake_normals(lambertian, voxel_size=0.5)")
    try:
        result = pipeline_bake_normals(
            CARPARK,
            out3,
            intensity_range=(0.0, 4096.0),
            brightness=70.0,
            voxel_size=0.5,
            shading_mode="lambertian",
            light_dir=(0.3, 0.4, -1.0),
            ambient=0.3,
            block_size=500_000,
            on_progress=_progress("3"),
        )
        print(f"  -> output_path={result.output_path}")
        print(f"     output_size_bytes={result.output_size_bytes:,}")
        print(f"     scan_count={result.scan_count}")
        print(f"     total_points={result.total_points:,}")
        print(f"     blocks_written={result.blocks_written}")
        print(f"     elapsed_seconds={result.elapsed_seconds:.2f}")
        print(
            "     peak_rss_bytes="
            f"{result.peak_rss_bytes:,}" if result.peak_rss_bytes else "     peak_rss_bytes=None"
        )
        print(f"     voxel_quality_fraction={result.voxel_quality_fraction:.3f}")
        print(f"     n_components={result.n_components}")
        if result.voxel_quality_fraction is None or result.voxel_quality_fraction <= 0.3:
            raise AssertionError(
                f"voxel_quality_fraction={result.voxel_quality_fraction!r} "
                "below 0.3 floor — carpark is mostly planar surfaces, "
                "expected better"
            )
    except Exception:
        traceback.print_exc()
        failures.append("pipeline_bake_normals")

    print("=" * 70)
    if failures:
        print(f"FAIL: {len(failures)} smoke case(s) failed: {failures}")
        return 1
    print("OK: all 3 C1 smoke cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
