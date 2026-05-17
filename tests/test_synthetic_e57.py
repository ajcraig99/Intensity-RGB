"""Tests for `tests/synthetic_e57.py`.

In-memory cloud tests must always pass green. The `.e57`-producing fixture
tests are skipped (not failed) when `pye57` is not importable, so that this
file goes green even before A1 finishes vendoring/building pye57.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from tests.synthetic_e57 import (
    make_intensity_only,
    make_multi_scan,
    make_plane_cloud,
    make_single_scan_rgb,
    make_sphere_cloud,
    make_two_plane_disconnected,
)

ARTIFACTS_DIR = os.path.join(os.path.dirname(__file__), "artifacts")

try:
    import pye57  # noqa: F401

    PYE57_AVAILABLE = True
    PYE57_SKIP_REASON = ""
except Exception as exc:  # pragma: no cover - exercised when A1 hasn't landed
    PYE57_AVAILABLE = False
    PYE57_SKIP_REASON = f"pye57 not importable yet ({exc!r}); waiting on A1"


pye57_required = pytest.mark.skipif(not PYE57_AVAILABLE, reason=PYE57_SKIP_REASON)


# ---------------------------------------------------------------------------
# In-memory cloud generators
# ---------------------------------------------------------------------------


class TestPlaneCloud:
    def test_shape_and_dtype(self):
        pts = make_plane_cloud(n=10_000, seed=42)
        assert pts.shape == (10_000, 3)
        assert pts.dtype == np.float64

    def test_z_std_small_for_xy_plane(self):
        # Default normal = (0, 0, 1), noise = 0.01 -> Z std should be ~0.01.
        pts = make_plane_cloud(n=20_000, noise=0.01, seed=1)
        assert pts[:, 2].std() < 0.02
        # XY spread should dwarf Z spread.
        assert pts[:, 0].std() > 10 * pts[:, 2].std()
        assert pts[:, 1].std() > 10 * pts[:, 2].std()

    def test_custom_normal_is_low_variance_axis(self):
        # With normal = +X, the X axis should be the thin axis.
        pts = make_plane_cloud(n=20_000, normal=(1.0, 0.0, 0.0), noise=0.005, seed=2)
        assert pts[:, 0].std() < 0.02
        assert pts[:, 1].std() > 10 * pts[:, 0].std()
        assert pts[:, 2].std() > 10 * pts[:, 0].std()

    def test_seed_is_deterministic(self):
        a = make_plane_cloud(n=500, seed=7)
        b = make_plane_cloud(n=500, seed=7)
        np.testing.assert_array_equal(a, b)


class TestSphereCloud:
    def test_shape_and_dtype(self):
        pts = make_sphere_cloud(n=10_000, seed=0)
        assert pts.shape == (10_000, 3)
        assert pts.dtype == np.float64

    def test_radius_no_noise(self):
        pts = make_sphere_cloud(n=20_000, radius=2.5, center=(0, 0, 0), noise=0.0, seed=3)
        r = np.linalg.norm(pts, axis=1)
        # No noise -> all radii should equal the target to within fp tolerance.
        np.testing.assert_allclose(r, 2.5, rtol=1e-10, atol=1e-10)

    def test_radius_with_noise(self):
        pts = make_sphere_cloud(n=20_000, radius=1.0, noise=0.02, seed=4)
        r = np.linalg.norm(pts, axis=1)
        # Mean radius ~ 1.0, std ~ 0.02 (the noise param).
        assert abs(r.mean() - 1.0) < 0.005
        assert r.std() < 0.05

    def test_center_offset(self):
        pts = make_sphere_cloud(n=5_000, radius=1.0, center=(10.0, -3.0, 4.0), seed=5)
        # Distance from the offset centre should be the radius.
        d = np.linalg.norm(pts - np.array([10.0, -3.0, 4.0]), axis=1)
        np.testing.assert_allclose(d, 1.0, rtol=1e-10, atol=1e-10)


class TestTwoPlaneDisconnected:
    def test_shape_and_dtype(self):
        pts = make_two_plane_disconnected(n=10_000, gap=5.0, seed=0)
        assert pts.shape == (10_000, 3)
        assert pts.dtype == np.float64

    def test_two_distinct_z_clusters(self):
        gap = 5.0
        pts = make_two_plane_disconnected(n=20_000, gap=gap, noise=0.01, seed=6)
        z = pts[:, 2]
        # Histogram into two bins on either side of zero — both must be non-empty.
        lower = z[z < 0]
        upper = z[z >= 0]
        assert lower.size > 0 and upper.size > 0
        # Cluster means should be very close to -gap/2 and +gap/2.
        assert abs(lower.mean() - (-gap / 2.0)) < 0.05
        assert abs(upper.mean() - (+gap / 2.0)) < 0.05
        # No points should sit anywhere near the midline (i.e. there is a true gap).
        # With noise=0.01 and gap=5.0, |z| should always be at least ~2.4.
        assert np.abs(z).min() > (gap / 2.0 - 0.2)

    def test_odd_n_total_preserved(self):
        pts = make_two_plane_disconnected(n=10_001, gap=2.0, seed=8)
        assert pts.shape == (10_001, 3)


# ---------------------------------------------------------------------------
# .e57 fixture writers (require pye57)
# ---------------------------------------------------------------------------


def _expected_field_set(with_color: bool) -> set:
    fields = {"cartesianX", "cartesianY", "cartesianZ", "intensity"}
    if with_color:
        fields |= {"colorRed", "colorGreen", "colorBlue"}
    return fields


@pye57_required
def test_make_single_scan_rgb(tmp_path):
    path = str(tmp_path / "single_scan_rgb.e57")
    make_single_scan_rgb(path, n_points=2_000, seed=0)
    # Also write into the shared artifacts dir so later waves can use it.
    persistent = os.path.join(ARTIFACTS_DIR, "single_scan_rgb.e57")
    make_single_scan_rgb(persistent, n_points=2_000, seed=0)

    import pye57

    e57 = pye57.E57(path)
    try:
        assert e57.scan_count == 1
        data = e57.read_scan_raw(0)
        assert _expected_field_set(with_color=True).issubset(data.keys())
        # Each field should have the right length.
        for name in _expected_field_set(with_color=True):
            assert len(data[name]) == 2_000
    finally:
        del e57


@pye57_required
def test_make_multi_scan(tmp_path):
    path = str(tmp_path / "multi_scan.e57")
    make_multi_scan(path, n_scans=3, n_points_per_scan=1_000, seed=0)
    persistent = os.path.join(ARTIFACTS_DIR, "multi_scan.e57")
    make_multi_scan(persistent, n_scans=3, n_points_per_scan=1_000, seed=0)

    import pye57

    e57 = pye57.E57(path)
    try:
        assert e57.scan_count == 3
        for k in range(3):
            data = e57.read_scan_raw(k)
            assert _expected_field_set(with_color=True).issubset(data.keys())
            assert len(data["cartesianX"]) == 1_000
    finally:
        del e57


@pye57_required
def test_make_intensity_only(tmp_path):
    path = str(tmp_path / "intensity_only.e57")
    make_intensity_only(path, n_points=1_500, seed=0)
    persistent = os.path.join(ARTIFACTS_DIR, "intensity_only.e57")
    make_intensity_only(persistent, n_points=1_500, seed=0)

    import pye57

    e57 = pye57.E57(path)
    try:
        assert e57.scan_count == 1
        data = e57.read_scan_raw(0)
        # Must have X/Y/Z + intensity ...
        assert _expected_field_set(with_color=False).issubset(data.keys())
        # ... and must NOT have RGB.
        for missing in ("colorRed", "colorGreen", "colorBlue"):
            assert missing not in data, f"intensity-only fixture leaked {missing}"
        assert len(data["intensity"]) == 1_500
    finally:
        del e57
