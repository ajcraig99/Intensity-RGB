"""Vectorized intensity -> HSV -> RGB baking.

V2 replacement for V1's per-point ``colorsys.hsv_to_rgb`` loop. The contract
is bit-for-bit (or +/-1 LSB) parity with V1's ``process()`` in
``Intensity-RGB_V1.0.py``.
"""

from __future__ import annotations

import numpy as np

# V1 hard-codes three sentinel max-intensity values with these normalization
# rules; any other ``max_inten`` falls through with no normalization (the raw
# intensity is passed straight into ``colorsys.hsv_to_rgb`` as the hue).
_NORMALIZE_DIVIDE = (255.0, 4096.0)
_NORMALIZE_OFFSET = 2048.0


def _hsv_to_rgb_vec(h: np.ndarray, v: float) -> np.ndarray:
    """Vectorized HSV->RGB, S=1, returning float (N,3) in [0,1].

    Mirrors ``colorsys.hsv_to_rgb`` exactly when ``s == 1``:

        i = int(h*6)              # floor toward zero
        f = h*6 - i
        p = v*(1-s) = 0           (since s==1)
        q = v*(1 - s*f) = v*(1-f)
        t = v*(1 - s*(1-f)) = v*f
        sector = i % 6 -> picks one of six (r,g,b) tuples
    """
    h = np.asarray(h, dtype=np.float64)

    # colorsys uses ``int(h*6.0)`` which truncates toward zero. With our
    # inputs h is always >= 0 (V1's normalization paths produce non-negative
    # hues; the 2048 branch produces h >= 1 which is fine -- the sector lookup
    # uses ``i % 6``).
    h6 = h * 6.0
    i = h6.astype(np.int64)  # truncation toward zero, matches int(x) for x>=0
    f = h6 - i
    sector = np.mod(i, 6)

    q = v * (1.0 - f)
    t = v * f
    vv = np.full_like(h, v, dtype=np.float64)
    zz = np.zeros_like(h, dtype=np.float64)

    # sector -> (r, g, b) per colorsys:
    # 0: (v, t, 0)   (p=0 with s=1)
    # 1: (q, v, 0)
    # 2: (0, v, t)
    # 3: (0, q, v)
    # 4: (t, 0, v)
    # 5: (v, 0, q)
    r = np.choose(sector, [vv, q,  zz, zz, t,  vv])
    g = np.choose(sector, [t,  vv, vv, q,  zz, zz])
    b = np.choose(sector, [zz, zz, t,  vv, vv, q])
    return np.stack([r, g, b], axis=-1)


def bake_rgb_from_intensity(
    intensity: np.ndarray,
    *,
    max_inten: float,
    brightness: float,
) -> np.ndarray:
    """Vectorized intensity -> RGB; V1 parity is the contract.

    Parameters
    ----------
    intensity:
        ``(N,)`` array of per-point intensities, int or float.
    max_inten:
        Scanner-specific max intensity. V1 special-cases 255, 2048, 4096.
    brightness:
        0..100, mapped to V (the brightness/value channel of HSV).

    Returns
    -------
    ``(N, 3)`` ``uint8`` RGB array.
    """
    inten = np.asarray(intensity, dtype=np.float64).reshape(-1)
    v = float(brightness) / 100.0
    m = float(max_inten)

    if m == 255.0 or m == 4096.0:
        h = inten / m
    elif m == 2048.0:
        h = (inten + m) / m
    else:
        # V1 fallthrough: no normalization, hue is the raw intensity.
        h = inten

    rgb_float = _hsv_to_rgb_vec(h, v)
    # V1 uses ``int(channel * 255)`` which truncates toward zero. For
    # non-negative channels in [0,1] this is equivalent to floor.
    rgb_u8 = (rgb_float * 255.0).astype(np.uint8)
    return rgb_u8
