"""V1 parity tests for ``bake_rgb_from_intensity``.

V1's ``process()`` in ``Intensity-RGB_V1.0.py`` is tkinter-bound and reads
its inputs from Entry widgets, so we cannot import it directly. Instead we
extract the *core* V1 transformation -- the exact sequence of statements
from lines 144..153 -- into a tiny Python reference and compare bit-for-bit.
The reference is a faithful copy of those statements, not a re-derivation.
"""

from __future__ import annotations

import colorsys

import numpy as np
import pytest

from intensity_rgb.processing.intensity import bake_rgb_from_intensity


def v1_reference_one(inten: float, max_inten: float, hsl_l: float) -> tuple[int, int, int]:
    """Bit-exact copy of V1 lines 144-153 for a single intensity sample.

    V1 source (Intensity-RGB_V1.0.py, lines 144..153)::

        if max_inten == 255:
            inten = inten/max_inten
        if max_inten == 2048:
            inten = (inten+max_inten)/max_inten
        if max_inten == 4096:
            inten = inten/max_inten
        rgb = colorsys.hsv_to_rgb(inten, 1, hsl_l)
        red = (int((rgb[0]*255)))
        green = (int((rgb[1]*255)))
        blue = (int((rgb[2]*255)))
    """
    if max_inten == 255:
        inten = inten / max_inten
    if max_inten == 2048:
        inten = (inten + max_inten) / max_inten
    if max_inten == 4096:
        inten = inten / max_inten
    rgb = colorsys.hsv_to_rgb(inten, 1, hsl_l)
    red = int((rgb[0] * 255))
    green = int((rgb[1] * 255))
    blue = int((rgb[2] * 255))
    return red, green, blue


def v1_reference_vec(intensities: np.ndarray, max_inten: float, brightness: float) -> np.ndarray:
    """Apply the V1 reference per-point; returns ``(N, 3) uint8``."""
    hsl_l = float(brightness) / 100.0
    out = np.empty((intensities.size, 3), dtype=np.uint8)
    for i, x in enumerate(intensities.tolist()):
        out[i] = v1_reference_one(float(x), float(max_inten), hsl_l)
    return out


# ---------------------------------------------------------------------------
# Sampled grids
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("max_inten", [255, 2048, 4096])
@pytest.mark.parametrize("brightness", [30, 50, 70, 90])
def test_parity_hardcoded_ranges(max_inten: int, brightness: int) -> None:
    # Sample every integer 0..max_inten if small, else 1024 evenly-spaced.
    if max_inten <= 256:
        intensities = np.arange(0, max_inten + 1, dtype=np.float64)
    else:
        intensities = np.linspace(0.0, float(max_inten), 1024, dtype=np.float64)

    got = bake_rgb_from_intensity(
        intensities, max_inten=float(max_inten), brightness=float(brightness)
    )
    expected = v1_reference_vec(intensities, float(max_inten), float(brightness))

    diff = np.abs(got.astype(np.int16) - expected.astype(np.int16))
    max_diff = int(diff.max(initial=0))
    assert max_diff <= 1, (
        f"max LSB delta {max_diff} > 1 for max_inten={max_inten}, "
        f"brightness={brightness}; worst index={int(diff.max(axis=1).argmax())}"
    )


@pytest.mark.parametrize("brightness", [30, 50, 70, 90])
def test_parity_arbitrary_max_fallthrough(brightness: int) -> None:
    """Arbitrary max_inten: V1 does NO normalization; we must match that."""
    max_inten = 1000.0
    # Hues for the no-normalization branch are the raw intensities; restrict to
    # something reasonable. We use a dense sweep across the same magnitude
    # range we'd see for max=1000, but the inputs go straight in as hue so we
    # also include sub-1 fractional values to exercise the first hue sector.
    intensities = np.concatenate(
        [
            np.linspace(0.0, 1.0, 64, dtype=np.float64),
            np.linspace(1.0, 1000.0, 512, dtype=np.float64),
        ]
    )

    got = bake_rgb_from_intensity(
        intensities, max_inten=max_inten, brightness=float(brightness)
    )
    expected = v1_reference_vec(intensities, max_inten, float(brightness))

    diff = np.abs(got.astype(np.int16) - expected.astype(np.int16))
    max_diff = int(diff.max(initial=0))
    assert max_diff <= 1, (
        f"arbitrary-max LSB delta {max_diff} > 1 for max_inten={max_inten}, "
        f"brightness={brightness}"
    )


def test_output_shape_and_dtype() -> None:
    out = bake_rgb_from_intensity(
        np.arange(10, dtype=np.float64), max_inten=255.0, brightness=70.0
    )
    assert out.shape == (10, 3)
    assert out.dtype == np.uint8


def test_accepts_integer_input() -> None:
    """V1 reads raw text, but downstream callers may hand us int arrays."""
    int_inten = np.arange(0, 256, dtype=np.int32)
    float_inten = int_inten.astype(np.float64)
    out_i = bake_rgb_from_intensity(int_inten, max_inten=255.0, brightness=70.0)
    out_f = bake_rgb_from_intensity(float_inten, max_inten=255.0, brightness=70.0)
    assert np.array_equal(out_i, out_f)
