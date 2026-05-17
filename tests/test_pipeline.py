"""End-to-end pipeline tests (Wave 3 / C4).

These tests exercise the C1 pipeline functions (``pipeline_clone``,
``pipeline_bake_intensity``, ``pipeline_bake_normals``,
``get_aabb_and_intensity_range``, ``PipelineResult``) against the real
``carpark_stairs.e57`` fixture plus the synthetic builders in
``tests/synthetic_e57.py``.

If C1 hasn't landed yet, this module will fail at import — that's the TDD
signal, not a problem to paper over with stubs.
"""

from __future__ import annotations

import os

import numpy as np
import pye57
import pytest

from intensity_rgb.io.e57_clone import E57CloneReader, UnsupportedFileError
from intensity_rgb.pipeline import (
    PipelineResult,
    get_aabb_and_intensity_range,
    pipeline_bake_intensity,
    pipeline_bake_normals,
    pipeline_clone,
)

from tests.render_preview import render_preview
from tests.synthetic_e57 import (
    make_intensity_only,
    make_multi_scan,
    make_single_scan_rgb,
)

CARPARK = "carpark_stairs.e57"
FIX = "tests/artifacts"


@pytest.fixture(scope="module", autouse=True)
def ensure_fixtures():
    os.makedirs(FIX, exist_ok=True)
    make_single_scan_rgb(f"{FIX}/single_scan_rgb.e57", n_points=5000, seed=0)
    make_multi_scan(
        f"{FIX}/multi_scan.e57", n_scans=3, n_points_per_scan=2000, seed=0
    )
    make_intensity_only(f"{FIX}/intensity_only.e57", n_points=2000, seed=0)
    yield


def _read_scan_xyz_rgb(path, scan_idx=0):
    e = pye57.E57(path, mode="r")
    try:
        data = e.read_scan_raw(scan_idx)
        xyz = np.stack(
            [
                np.asarray(data["cartesianX"]),
                np.asarray(data["cartesianY"]),
                np.asarray(data["cartesianZ"]),
            ],
            axis=-1,
        )
        rgb = None
        if all(k in data for k in ("colorRed", "colorGreen", "colorBlue")):
            rgb = np.stack(
                [
                    np.asarray(data["colorRed"]),
                    np.asarray(data["colorGreen"]),
                    np.asarray(data["colorBlue"]),
                ],
                axis=-1,
            ).astype(np.uint8)
    finally:
        e.close()
    return xyz, rgb


# ---- pipeline_clone -------------------------------------------------------


def test_pipeline_clone_bit_identical_carpark(tmp_path):
    out = str(tmp_path / "clone.e57")
    result = pipeline_clone(CARPARK, out)
    assert isinstance(result, PipelineResult)
    assert result.scan_count == 1
    assert result.total_points == 4_138_438
    src_xyz, src_rgb = _read_scan_xyz_rgb(CARPARK)
    dst_xyz, dst_rgb = _read_scan_xyz_rgb(out)
    assert np.allclose(src_xyz, dst_xyz, rtol=1e-12, atol=1e-12)
    assert np.array_equal(src_rgb, dst_rgb)


# ---- pipeline_bake_intensity ---------------------------------------------


def test_pipeline_bake_intensity_changes_rgb_only(tmp_path):
    out = str(tmp_path / "bake_i.e57")
    result = pipeline_bake_intensity(
        CARPARK, out, intensity_range=(0, 4096), brightness=70.0
    )
    assert result.scan_count == 1
    assert result.total_points == 4_138_438
    src_xyz, src_rgb = _read_scan_xyz_rgb(CARPARK)
    dst_xyz, dst_rgb = _read_scan_xyz_rgb(out)
    # XYZ unchanged
    assert np.allclose(src_xyz, dst_xyz, rtol=1e-12, atol=1e-12)
    # RGB different
    assert not np.array_equal(
        src_rgb, dst_rgb
    ), "intensity bake should change RGB columns"
    # Output dtype + range sanity
    assert dst_rgb.dtype == np.uint8
    assert 0 <= dst_rgb.min() <= dst_rgb.max() <= 255
    # Render preview for self-verification (write to tests/artifacts/, not asserted)
    render_preview(
        dst_xyz,
        dst_rgb,
        "tests/artifacts/pipeline_bake_intensity_carpark.png",
        title="bake_intensity (range=0..4096, brightness=70)",
    )


def test_pipeline_bake_intensity_on_synthetic(tmp_path):
    src = f"{FIX}/single_scan_rgb.e57"
    out = str(tmp_path / "bake_i_synth.e57")
    result = pipeline_bake_intensity(
        src, out, intensity_range=(0, 4096), brightness=70
    )
    assert result.total_points == 5000


def test_pipeline_bake_intensity_unsupported(tmp_path):
    src = f"{FIX}/intensity_only.e57"
    out = str(tmp_path / "should_not_exist.e57")
    with pytest.raises(UnsupportedFileError):
        pipeline_bake_intensity(
            src, out, intensity_range=(0, 4096), brightness=70
        )
    assert not os.path.exists(out)


# ---- pipeline_bake_normals -----------------------------------------------


def test_pipeline_bake_normals_lambertian_carpark(tmp_path):
    out = str(tmp_path / "bake_n.e57")
    result = pipeline_bake_normals(
        CARPARK,
        out,
        intensity_range=(0, 4096),
        shading_mode="lambertian",
        voxel_size=0.5,
    )
    assert result.scan_count == 1
    # Voxel quality should be at least some fraction; carpark is mostly planar.
    assert result.voxel_quality_fraction is not None
    assert result.voxel_quality_fraction > 0.20, (
        f"voxel quality {result.voxel_quality_fraction} unexpectedly low"
    )
    # Output validates as .e57
    chk = pye57.E57(out, mode="r")
    chk.close()
    # Render
    dst_xyz, dst_rgb = _read_scan_xyz_rgb(out)
    render_preview(
        dst_xyz,
        dst_rgb,
        "tests/artifacts/pipeline_bake_normals_carpark.png",
        title=(
            f"bake_normals lambertian @ vsize=0.5, "
            f"qual={result.voxel_quality_fraction:.2%}"
        ),
    )


def test_pipeline_bake_normals_normal_as_color_synthetic(tmp_path):
    src = f"{FIX}/single_scan_rgb.e57"
    out = str(tmp_path / "bake_nac.e57")
    result = pipeline_bake_normals(
        src,
        out,
        intensity_range=(0, 4096),
        shading_mode="normal_as_color",
        voxel_size=0.5,
    )
    assert result.total_points == 5000


def test_pipeline_bake_normals_orientation_callback_fires(tmp_path):
    """The optional ``on_orientation_result`` hook fires once after Pass 1.

    Added in Wave 4 / D3 so the worker can surface the connected-component
    list to the UI as per-component chips. The callback receives the
    pipeline's :class:`OrientationResult` directly; we only assert it
    was invoked exactly once and the payload has a non-empty
    ``components`` list.
    """
    src = f"{FIX}/single_scan_rgb.e57"
    out = str(tmp_path / "bake_orient_cb.e57")
    seen: list = []

    def cb(orient_result):
        seen.append(orient_result)

    result = pipeline_bake_normals(
        src,
        out,
        intensity_range=(0, 4096),
        shading_mode="lambertian",
        voxel_size=0.5,
        on_orientation_result=cb,
    )
    assert result.total_points == 5000
    assert len(seen) == 1, "on_orientation_result must fire exactly once"
    assert hasattr(seen[0], "components"), "callback received an OrientationResult"


# ---- get_aabb_and_intensity_range helper ---------------------------------


def test_get_aabb_and_intensity_range_carpark():
    with E57CloneReader(CARPARK) as r:
        result = get_aabb_and_intensity_range(
            r, sample_blocks=2, block_size=200_000
        )
    assert "aabb_min" in result and "aabb_max" in result
    assert "intensity_min" in result and "intensity_max" in result
    assert "points_seen" in result and result["points_seen"] > 0
    extent = np.asarray(result["aabb_max"]) - np.asarray(result["aabb_min"])
    assert (extent > 0).all(), "AABB extent should be positive on each axis"


# ---- cancellation / progress smoke ---------------------------------------


def test_pipeline_bake_intensity_cancellation_smoke(tmp_path):
    """Smoke: ensure on_progress callback receives >= 1 event for carpark.

    A more complete cancellation test belongs in Wave 4 (worker.py tests).
    """
    events = []

    def cb(ev):
        events.append(ev)

    out = str(tmp_path / "bake_cancel.e57")
    pipeline_bake_intensity(
        CARPARK, out, intensity_range=(0, 4096), on_progress=cb
    )
    assert len(events) >= 1
    assert hasattr(events[0], "points_done") or hasattr(events[0], "stage")
