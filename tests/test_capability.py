"""Wave 3 / C3 tests for ``intensity_rgb.capability``.

Targets:
- Header-only inspection completes in << 1 s on every fixture.
- Carpark fixture yields the canonical 4,138,438 point total and GREEN
  verdicts for the modes that don't need an extreme RAM footprint.
- The intensity-only synthetic fixture gets RED across all RGB-requiring
  modes, with a reason that names RGB / color.
- The chunked-RAM math matches the canonical formula in the design
  (``stateful-hatching-kitten.md`` §"Capability panel (header-only)").
"""

from __future__ import annotations

import os
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# Make the vendored pye57 importable when tests are invoked from a fresh
# environment (matches the smoke-script pattern used elsewhere).
sys.path.insert(0, os.path.join(REPO_ROOT, "vendor", "pye57", "src"))
sys.path.insert(0, REPO_ROOT)

from intensity_rgb.capability import (  # noqa: E402
    CapabilityReport,
    inspect_file,
)


CARPARK = os.path.join(REPO_ROOT, "carpark_stairs.e57")
INTENSITY_ONLY = os.path.join(REPO_ROOT, "tests", "artifacts", "intensity_only.e57")
SINGLE_RGB = os.path.join(REPO_ROOT, "tests", "artifacts", "single_scan_rgb.e57")
MULTI_SCAN = os.path.join(REPO_ROOT, "tests", "artifacts", "multi_scan.e57")


# ---------------------------------------------------------------------------
# Carpark — the only real-world fixture in the repo
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not os.path.exists(CARPARK), reason="carpark_stairs.e57 missing")
def test_inspect_carpark_basic_shape():
    """One scan, 4.13M points, RGB present, completes well under 1 s."""
    report = inspect_file(CARPARK)
    assert isinstance(report, CapabilityReport)
    assert report.scan_count == 1
    assert report.total_points == 4_138_438
    assert report.per_scan_point_counts == [4_138_438]
    assert report.rgb_present_in_all_scans is True
    # The carpark fixture is unstructured.
    assert report.organized_in_any_scan is False
    assert report.elapsed_seconds < 1.0, (
        f"inspect_file took {report.elapsed_seconds:.3f}s — header walk should "
        "be << 1 s on any file"
    )


@pytest.mark.skipif(not os.path.exists(CARPARK), reason="carpark_stairs.e57 missing")
def test_carpark_aabb_within_expected_envelope():
    """Carpark sits in roughly a 3m × 9m × 14m bounding box. The exact
    numbers are in the data, but we sanity-check the extents are small
    enough that the chunked accumulator's chunk count is single-digit at
    voxel_size=0.5, chunk=32 (16m per chunk per axis).
    """
    report = inspect_file(CARPARK, voxel_size=0.5, chunk=32)
    assert report.file_aabb_min is not None
    assert report.file_aabb_max is not None
    ext_x = report.file_aabb_max[0] - report.file_aabb_min[0]
    ext_y = report.file_aabb_max[1] - report.file_aabb_min[1]
    ext_z = report.file_aabb_max[2] - report.file_aabb_min[2]
    # Loose envelope so this doesn't fail if the file is re-captured.
    assert 1.0 < ext_x < 30.0
    assert 1.0 < ext_y < 30.0
    assert 1.0 < ext_z < 60.0

    # At voxel_size=0.5 × chunk=32 = 16 m per chunk per axis, a 3×9×14 m
    # AABB occupies a *handful* of chunks (single-digit). The math:
    #   ceil(3/16) * ceil(9/16) * ceil(14/16) = 1*1*1 = 1.
    # Allow a bit of slack for fixture re-captures.
    assert 1 <= report.max_possible_chunk_count <= 8


@pytest.mark.skipif(not os.path.exists(CARPARK), reason="carpark_stairs.e57 missing")
def test_carpark_ram_math_small():
    """At voxel_size=0.5, chunk=32, carpark's tiny AABB means pass 1 RAM
    upper bound is at most a few tens of MB plus the constant overhead.
    """
    report = inspect_file(CARPARK, voxel_size=0.5, chunk=32, block_size=1_000_000)
    # max_chunks * 32^3 * 10 * 8 = max_chunks * ~2.6 MB. At ≤ 8 chunks,
    # that's ≤ 21 MB; plus the 64 MiB overhead constant and ~80 MB block
    # buffer ceiling, we expect well under 300 MB.
    assert report.pass1_peak_ram_upper_bound_bytes < 300 * 1024 * 1024
    assert report.pass2_peak_ram_upper_bound_bytes < 300 * 1024 * 1024


@pytest.mark.skipif(not os.path.exists(CARPARK), reason="carpark_stairs.e57 missing")
def test_carpark_verdicts():
    """RGB present + tiny AABB → at minimum GREEN for intensity_only,
    GREEN or YELLOW for the shading modes.
    """
    report = inspect_file(CARPARK)
    assert report.verdicts["intensity_only"] == "GREEN"
    assert report.verdicts["intensity_lambertian"] in ("GREEN", "YELLOW")
    assert report.verdicts["normal_as_color"] in ("GREEN", "YELLOW")
    # Reasons exist and are non-empty.
    for mode in ("intensity_only", "intensity_lambertian", "normal_as_color"):
        assert mode in report.verdict_reasons
        assert isinstance(report.verdict_reasons[mode], str)
        assert len(report.verdict_reasons[mode]) > 0


# ---------------------------------------------------------------------------
# Synthetic intensity-only fixture — RED verdict per design precondition
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.path.exists(INTENSITY_ONLY),
    reason="tests/artifacts/intensity_only.e57 missing",
)
def test_intensity_only_red_verdict():
    report = inspect_file(INTENSITY_ONLY)
    assert report.rgb_present_in_all_scans is False
    assert report.verdicts["intensity_only"] == "RED"
    assert report.verdicts["intensity_lambertian"] == "RED"
    assert report.verdicts["normal_as_color"] == "RED"
    reason = report.verdict_reasons["intensity_only"].lower()
    assert ("rgb" in reason) or ("color" in reason)
    assert report.elapsed_seconds < 1.0


# ---------------------------------------------------------------------------
# Synthetic single-scan-rgb fixture — all GREEN
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.path.exists(SINGLE_RGB),
    reason="tests/artifacts/single_scan_rgb.e57 missing",
)
def test_single_scan_rgb_all_green():
    report = inspect_file(SINGLE_RGB)
    assert report.scan_count == 1
    assert report.rgb_present_in_all_scans is True
    # 10m cube fixture sits well inside one chunk at voxel_size=0.5.
    assert report.verdicts["intensity_only"] == "GREEN"
    assert report.verdicts["intensity_lambertian"] == "GREEN"
    assert report.verdicts["normal_as_color"] == "GREEN"
    assert report.elapsed_seconds < 1.0


# ---------------------------------------------------------------------------
# Synthetic multi-scan fixture — 3 scans, all GREEN
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.path.exists(MULTI_SCAN),
    reason="tests/artifacts/multi_scan.e57 missing",
)
def test_multi_scan_three_scans_all_green():
    report = inspect_file(MULTI_SCAN)
    assert report.scan_count == 3
    assert len(report.per_scan_point_counts) == 3
    # multi_scan fixture is built from `make_multi_scan` which always
    # writes RGB for every scan.
    assert report.rgb_present_in_all_scans is True
    assert report.verdicts["intensity_only"] == "GREEN"
    assert report.verdicts["intensity_lambertian"] == "GREEN"
    assert report.verdicts["normal_as_color"] == "GREEN"
    assert report.elapsed_seconds < 1.0


# ---------------------------------------------------------------------------
# Elapsed-time assertion across every fixture present in the repo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(
            CARPARK,
            marks=pytest.mark.skipif(
                not os.path.exists(CARPARK), reason="carpark missing"
            ),
        ),
        pytest.param(
            INTENSITY_ONLY,
            marks=pytest.mark.skipif(
                not os.path.exists(INTENSITY_ONLY), reason="intensity_only missing"
            ),
        ),
        pytest.param(
            SINGLE_RGB,
            marks=pytest.mark.skipif(
                not os.path.exists(SINGLE_RGB), reason="single_scan_rgb missing"
            ),
        ),
        pytest.param(
            MULTI_SCAN,
            marks=pytest.mark.skipif(
                not os.path.exists(MULTI_SCAN), reason="multi_scan missing"
            ),
        ),
    ],
)
def test_inspect_file_under_two_seconds(path):
    report = inspect_file(path)
    assert report.elapsed_seconds < 2.0, (
        f"inspect_file({path}) took {report.elapsed_seconds:.3f}s"
    )


# ---------------------------------------------------------------------------
# RAM math — explicit canonical check at a degenerate AABB
# ---------------------------------------------------------------------------


def test_ram_math_single_chunk_canonical():
    """Force a system with infinite RAM and a tiny AABB; verify the
    upper bound matches the formula in the design plan.

    Pass 1: max_chunks * 32^3 * 10 * 8 = 1 * 32768 * 80 = 2_621_440 bytes
            + block_size * 80 + overhead
    Pass 2: max_chunks * 32^3 * 13      = 1 * 32768 * 13 = 425_984 bytes
            + block_size * 80 + overhead
    """
    if not os.path.exists(CARPARK):
        pytest.skip("carpark required for canonical math check")
    report = inspect_file(
        CARPARK,
        voxel_size=0.5,
        chunk=32,
        block_size=1_000_000,
        system_ram_bytes=1024 ** 4,  # 1 TiB — guarantees GREEN
    )
    n = report.max_possible_chunk_count
    expected_pass1_chunk_bytes = n * (32 ** 3) * 10 * 8
    expected_pass2_chunk_bytes = n * (32 ** 3) * 13
    # Both peak-ram numbers must be at least the chunk-grid cost.
    assert report.pass1_peak_ram_upper_bound_bytes >= expected_pass1_chunk_bytes
    assert report.pass2_peak_ram_upper_bound_bytes >= expected_pass2_chunk_bytes
    # And bounded above by chunk-grid cost + block buffer + 128 MiB slack.
    assert report.pass1_peak_ram_upper_bound_bytes <= (
        expected_pass1_chunk_bytes + 1_000_000 * 80 + 128 * 1024 * 1024
    )
