"""Tests for the vectorized shading models."""

from __future__ import annotations

import numpy as np
import pytest

from intensity_rgb.processing.shading import (
    DEFAULT_AMBIENT,
    DEFAULT_GROUND,
    DEFAULT_SKY,
    lambertian,
    normal_as_color,
    three_point,
)


# ---------------------------------------------------------------------------
# 1. Analytic Lambertian
# ---------------------------------------------------------------------------
def test_lambertian_matches_analytic():
    n = 1000
    base = np.full((n, 3), 200, dtype=np.uint8)
    normals = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (n, 1))
    quality = np.ones(n, dtype=bool)
    light_dir = np.array([0.0, 0.0, -1.0], dtype=np.float32)

    out = lambertian(
        base,
        normals,
        quality,
        light_dir=light_dir,
        ambient=DEFAULT_AMBIENT,
        ground_color=DEFAULT_GROUND,
        sky_color=DEFAULT_SKY,
    )

    # Hand calc for one point: N=(0,0,1), L_norm = (0,0,-1).
    # t = 0.5*(1+1) = 1 -> hemi = sky = (180, 210, 255).
    # N.L_norm = -1 -> clipped to 0 -> diffuse term = 0.
    # final = 200 * (0.3 * sky/255 + 0) = 200 * 0.3 * sky/255
    expected = 200.0 * (DEFAULT_AMBIENT * (DEFAULT_SKY.astype(np.float32) / 255.0))
    expected_u8 = np.clip(expected, 0, 255).astype(np.uint8)

    # Every row should equal the expected value within 1 LSB (rounding).
    diff = np.abs(out.astype(np.int16) - expected_u8.astype(np.int16))
    assert diff.max() <= 1, f"max LSB diff {diff.max()} exceeds 1"

    # Sanity: all rows identical.
    assert np.all(out == out[0])


def test_lambertian_lit_face():
    """Light pointing into the surface should give full diffuse."""
    n = 500
    base = np.full((n, 3), 100, dtype=np.uint8)
    normals = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (n, 1))
    quality = np.ones(n, dtype=bool)
    # Light coming from above shining down -> light_dir points up so that
    # N.L is positive (convention: light_dir is the direction toward the light).
    light_dir = np.array([0.0, 0.0, 1.0], dtype=np.float32)

    out = lambertian(
        base, normals, quality, light_dir=light_dir, ambient=0.3,
        ground_color=DEFAULT_GROUND, sky_color=DEFAULT_SKY,
    )
    # ambient*sky/255 + 0.7*1 = 0.3*sky/255 + 0.7
    expected = 100.0 * (0.3 * (DEFAULT_SKY.astype(np.float32) / 255.0) + 0.7)
    expected_u8 = np.clip(expected, 0, 255).astype(np.uint8)
    diff = np.abs(out.astype(np.int16) - expected_u8.astype(np.int16))
    assert diff.max() <= 1


# ---------------------------------------------------------------------------
# 2. Quality-false passthrough
# ---------------------------------------------------------------------------
def test_quality_false_passthrough_lambertian():
    n = 200
    rng = np.random.default_rng(0)
    base = rng.integers(0, 256, size=(n, 3), dtype=np.uint8)
    normals = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (n, 1))
    quality = np.zeros(n, dtype=bool)
    quality[: n // 2] = True  # first half good, second half bad

    out = lambertian(
        base, normals, quality,
        light_dir=np.array([0.0, 0.0, 1.0], dtype=np.float32),
    )
    # Bad rows must equal base exactly.
    assert np.array_equal(out[n // 2 :], base[n // 2 :])
    # Good rows must not all equal base (shading actually happened).
    assert not np.array_equal(out[: n // 2], base[: n // 2])


def test_quality_false_passthrough_three_point():
    n = 50
    rng = np.random.default_rng(1)
    base = rng.integers(0, 256, size=(n, 3), dtype=np.uint8)
    normals = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (n, 1))
    quality = np.zeros(n, dtype=bool)

    out = three_point(
        base, normals, quality,
        key_dir=np.array([0, 0, 1], dtype=np.float32), key_intensity=1.0,
        fill_dir=np.array([1, 0, 0], dtype=np.float32), fill_intensity=0.5,
        back_dir=np.array([0, 1, 0], dtype=np.float32), back_intensity=0.3,
        ambient=0.2,
    )
    assert np.array_equal(out, base)


# ---------------------------------------------------------------------------
# 3. Three-point sums + monotonic saturation
# ---------------------------------------------------------------------------
def test_three_point_in_range_and_saturates():
    rng = np.random.default_rng(2)
    n = 5000
    # Random unit normals.
    raw = rng.standard_normal((n, 3)).astype(np.float32)
    normals = raw / np.linalg.norm(raw, axis=1, keepdims=True)
    base = np.full((n, 3), 180, dtype=np.uint8)
    quality = np.ones(n, dtype=bool)

    kd = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    fd = np.array([1.0, 0.0, 0.5], dtype=np.float32)
    bd = np.array([-1.0, -1.0, -0.2], dtype=np.float32)

    low = three_point(
        base, normals, quality,
        key_dir=kd, key_intensity=0.5,
        fill_dir=fd, fill_intensity=0.3,
        back_dir=bd, back_intensity=0.2,
        ambient=0.2,
    )
    high = three_point(
        base, normals, quality,
        key_dir=kd, key_intensity=1.0,
        fill_dir=fd, fill_intensity=0.6,
        back_dir=bd, back_intensity=0.4,
        ambient=0.2,
    )

    assert low.dtype == np.uint8 and high.dtype == np.uint8
    assert low.min() >= 0 and low.max() <= 255
    assert high.min() >= 0 and high.max() <= 255

    sat_low = np.sum(np.all(low == 255, axis=1))
    sat_high = np.sum(np.all(high == 255, axis=1))
    # Doubling all intensities must produce at least as many saturated
    # pixels, and strictly more for this random distribution.
    assert sat_high >= sat_low
    assert sat_high > sat_low


# ---------------------------------------------------------------------------
# 4. Normal-as-color round-trip
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "normal, expected",
    [
        ([1.0, 0.0, 0.0], (255, 127, 127)),
        ([-1.0, 0.0, 0.0], (0, 127, 127)),
        ([0.0, 0.0, 1.0], (127, 127, 255)),
        ([0.0, 1.0, 0.0], (127, 255, 127)),
        ([0.0, -1.0, 0.0], (127, 0, 127)),
    ],
)
def test_normal_as_color_round_trip(normal, expected):
    n = 16
    normals = np.tile(np.array(normal, dtype=np.float32), (n, 1))
    quality = np.ones(n, dtype=bool)
    fallback = np.array([0, 0, 0], dtype=np.uint8)

    out = normal_as_color(normals, quality, fallback_color=fallback)
    assert out.dtype == np.uint8
    exp = np.array(expected, dtype=np.int16)
    diff = np.abs(out.astype(np.int16) - exp[None, :])
    assert diff.max() <= 1, f"got {out[0]}, expected {expected}"


def test_normal_as_color_quality_false_uses_fallback():
    n = 10
    normals = np.tile(np.array([1.0, 0.0, 0.0], dtype=np.float32), (n, 1))
    quality = np.zeros(n, dtype=bool)
    fallback = np.array([42, 84, 168], dtype=np.uint8)

    out = normal_as_color(normals, quality, fallback_color=fallback)
    assert np.all(out == fallback[None, :])


# ---------------------------------------------------------------------------
# 5. Edge cases
# ---------------------------------------------------------------------------
def test_zero_light_dir_raises():
    base = np.full((4, 3), 100, dtype=np.uint8)
    normals = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (4, 1))
    quality = np.ones(4, dtype=bool)
    with pytest.raises(ValueError):
        lambertian(
            base, normals, quality,
            light_dir=np.array([0.0, 0.0, 0.0], dtype=np.float32),
        )
    with pytest.raises(ValueError):
        three_point(
            base, normals, quality,
            key_dir=np.array([0.0, 0.0, 0.0], dtype=np.float32),
            key_intensity=1.0,
            fill_dir=np.array([1.0, 0.0, 0.0], dtype=np.float32),
            fill_intensity=0.5,
            back_dir=np.array([0.0, 1.0, 0.0], dtype=np.float32),
            back_intensity=0.3,
            ambient=0.2,
        )


def test_empty_input_lambertian():
    base = np.zeros((0, 3), dtype=np.uint8)
    normals = np.zeros((0, 3), dtype=np.float32)
    quality = np.zeros((0,), dtype=bool)
    out = lambertian(
        base, normals, quality,
        light_dir=np.array([0.0, 0.0, 1.0], dtype=np.float32),
    )
    assert out.shape == (0, 3)
    assert out.dtype == np.uint8


def test_empty_input_three_point():
    base = np.zeros((0, 3), dtype=np.uint8)
    normals = np.zeros((0, 3), dtype=np.float32)
    quality = np.zeros((0,), dtype=bool)
    out = three_point(
        base, normals, quality,
        key_dir=np.array([0, 0, 1], dtype=np.float32), key_intensity=1.0,
        fill_dir=np.array([1, 0, 0], dtype=np.float32), fill_intensity=0.5,
        back_dir=np.array([0, 1, 0], dtype=np.float32), back_intensity=0.3,
        ambient=0.2,
    )
    assert out.shape == (0, 3)
    assert out.dtype == np.uint8


def test_empty_input_normal_as_color():
    normals = np.zeros((0, 3), dtype=np.float32)
    quality = np.zeros((0,), dtype=bool)
    out = normal_as_color(
        normals, quality,
        fallback_color=np.array([0, 0, 0], dtype=np.uint8),
    )
    assert out.shape == (0, 3)
    assert out.dtype == np.uint8


def test_output_dtype_is_uint8():
    n = 32
    base = np.full((n, 3), 128, dtype=np.uint8)
    normals = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (n, 1))
    quality = np.ones(n, dtype=bool)
    a = lambertian(base, normals, quality,
                   light_dir=np.array([0, 0, 1], dtype=np.float32))
    b = three_point(base, normals, quality,
                    key_dir=np.array([0, 0, 1], dtype=np.float32), key_intensity=1.0,
                    fill_dir=np.array([1, 0, 0], dtype=np.float32), fill_intensity=0.5,
                    back_dir=np.array([0, 1, 0], dtype=np.float32), back_intensity=0.3,
                    ambient=0.2)
    c = normal_as_color(normals, quality,
                        fallback_color=np.array([0, 0, 0], dtype=np.uint8))
    assert a.dtype == np.uint8
    assert b.dtype == np.uint8
    assert c.dtype == np.uint8
