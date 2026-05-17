"""Vectorized shading models for point clouds.

All functions operate on (N, 3) arrays and return uint8 RGB.
The ``quality`` mask selects which rows are shaded; False rows pass
through unchanged (Lambertian / three_point) or use ``fallback_color``
(normal_as_color).
"""

from __future__ import annotations

import numpy as np

# Module-level defaults (also referenced by the tests).
DEFAULT_AMBIENT = 0.3
DEFAULT_GROUND = np.array([60, 40, 30], dtype=np.uint8)
DEFAULT_SKY = np.array([180, 210, 255], dtype=np.uint8)


def _normalize(v: np.ndarray, *, eps: float = 1e-8) -> np.ndarray:
    """Return ``v`` normalized to unit length.

    Raises ``ValueError`` if the input vector has zero norm — a zero
    light direction is ambiguous and the caller almost certainly made
    a mistake.
    """
    v = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(v))
    if n <= eps:
        raise ValueError("light direction has zero norm")
    return v / n


def _as_uint8_color(c: np.ndarray) -> np.ndarray:
    return np.asarray(c, dtype=np.uint8).reshape(3)


def lambertian(
    base: np.ndarray,
    normals: np.ndarray,
    quality: np.ndarray,
    *,
    light_dir: np.ndarray,
    ambient: float = DEFAULT_AMBIENT,
    ground_color: np.ndarray = DEFAULT_GROUND,
    sky_color: np.ndarray = DEFAULT_SKY,
) -> np.ndarray:
    """Lambertian shading with a hemispherical ambient term.

    ``final = base * (ambient * lerp(ground, sky, 0.5*(N.z+1))
                      + (1 - ambient) * max(0, N.L))``

    Quality-False rows return ``base`` unmodified.
    """
    base = np.asarray(base, dtype=np.uint8)
    normals = np.asarray(normals, dtype=np.float32)
    quality = np.asarray(quality, dtype=bool)
    n_points = base.shape[0]

    if n_points == 0:
        return base.copy().reshape(0, 3)

    L = _normalize(light_dir)
    ground = _as_uint8_color(ground_color).astype(np.float32)
    sky = _as_uint8_color(sky_color).astype(np.float32)

    # Hemisphere term: t = 0.5 * (N.z + 1) in [0, 1] (after clamp).
    t = np.clip(0.5 * (normals[:, 2] + 1.0), 0.0, 1.0)[:, None]  # (N, 1)
    hemi = ground * (1.0 - t) + sky * t                          # (N, 3) in 0..255

    # N dot L, clamped at 0.
    ndl = np.clip(normals @ L, 0.0, None)[:, None]               # (N, 1)

    # base * (ambient * hemi/255 + (1-ambient) * ndl)
    base_f = base.astype(np.float32)
    shaded = base_f * (ambient * (hemi / 255.0) + (1.0 - ambient) * ndl)
    shaded = np.clip(shaded, 0, 255).astype(np.uint8)

    # Quality mask: False -> passthrough base.
    out = np.where(quality[:, None], shaded, base)
    return out.astype(np.uint8)


def three_point(
    base: np.ndarray,
    normals: np.ndarray,
    quality: np.ndarray,
    *,
    key_dir: np.ndarray,
    key_intensity: float,
    fill_dir: np.ndarray,
    fill_intensity: float,
    back_dir: np.ndarray,
    back_intensity: float,
    ambient: float = DEFAULT_AMBIENT,
) -> np.ndarray:
    """Classic three-point lighting (key + fill + back).

    Each light contributes ``intensity * max(0, N.dir)``. Plus an
    ambient base term. Final is clamped to 0..255.
    """
    base = np.asarray(base, dtype=np.uint8)
    normals = np.asarray(normals, dtype=np.float32)
    quality = np.asarray(quality, dtype=bool)
    n_points = base.shape[0]

    if n_points == 0:
        return base.copy().reshape(0, 3)

    K = _normalize(key_dir)
    F = _normalize(fill_dir)
    B = _normalize(back_dir)

    contrib = (
        key_intensity * np.clip(normals @ K, 0.0, None)
        + fill_intensity * np.clip(normals @ F, 0.0, None)
        + back_intensity * np.clip(normals @ B, 0.0, None)
    )[:, None]  # (N, 1)

    base_f = base.astype(np.float32)
    shaded = base_f * (ambient + contrib)
    shaded = np.clip(shaded, 0, 255).astype(np.uint8)

    out = np.where(quality[:, None], shaded, base)
    return out.astype(np.uint8)


def normal_as_color(
    normals: np.ndarray,
    quality: np.ndarray,
    *,
    fallback_color: np.ndarray,
) -> np.ndarray:
    """Encode the unit normal as RGB: ``(n + 1) * 127.5``.

    Quality-False rows are replaced with ``fallback_color``.
    """
    normals = np.asarray(normals, dtype=np.float32)
    quality = np.asarray(quality, dtype=bool)
    n_points = normals.shape[0]

    if n_points == 0:
        return np.zeros((0, 3), dtype=np.uint8)

    fb = _as_uint8_color(fallback_color)

    encoded = np.clip((normals + 1.0) * 127.5, 0, 255).astype(np.uint8)
    out = np.where(quality[:, None], encoded, fb[None, :])
    return out.astype(np.uint8)
