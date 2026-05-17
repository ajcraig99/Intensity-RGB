"""Programmatic builders for small synthetic point-cloud fixtures.

Two flavours:

1. `.e57` fixtures written via pye57's `E57.write_scan_raw` API
   (`make_single_scan_rgb`, `make_multi_scan`, `make_intensity_only`).
   These power the G1a clone-fidelity tests in Wave 2 and the pipeline
   tests in Wave 3.

2. In-memory `numpy` point clouds (`make_plane_cloud`, `make_sphere_cloud`,
   `make_two_plane_disconnected`) used by voxel/normal/orientation unit
   tests that don't need to round-trip through libE57.

All builders take a `seed` argument and use `numpy.random.default_rng(seed)`
so the fixtures are bit-for-bit deterministic.

The .e57 builders import `pye57` lazily inside each function so that this
module can be imported (and the in-memory helpers used) even before A1
has finished vendoring/building pye57.

Reference: https://github.com/davidcaron/pye57
"""

from __future__ import annotations

import math
import os
from typing import Tuple

import numpy as np


# ---------------------------------------------------------------------------
# In-memory cloud generators (no pye57 dependency)
# ---------------------------------------------------------------------------


def make_plane_cloud(
    n: int = 100_000,
    *,
    normal: Tuple[float, float, float] = (0.0, 0.0, 1.0),
    noise: float = 0.01,
    extent: float = 1.0,
    seed: int = 0,
) -> np.ndarray:
    """Return `(n, 3)` float64 points on a plane through the origin.

    The plane is centred at the origin with the given unit `normal`; points are
    uniformly distributed inside a square of half-width `extent` on that
    plane, with isotropic Gaussian noise of standard deviation `noise` added
    along the normal axis.
    """
    rng = np.random.default_rng(seed)
    normal_vec = np.asarray(normal, dtype=np.float64)
    norm = np.linalg.norm(normal_vec)
    if norm == 0.0:
        raise ValueError("normal must be non-zero")
    n_hat = normal_vec / norm

    # Build an orthonormal basis (u, v) spanning the plane.
    # Pick a helper axis not parallel to n_hat.
    helper = np.array([1.0, 0.0, 0.0]) if abs(n_hat[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(n_hat, helper)
    u /= np.linalg.norm(u)
    v = np.cross(n_hat, u)

    uv = rng.uniform(-extent, extent, size=(n, 2))
    offsets = rng.normal(0.0, noise, size=n)
    pts = uv[:, 0:1] * u + uv[:, 1:2] * v + offsets[:, None] * n_hat
    return pts.astype(np.float64, copy=False)


def make_sphere_cloud(
    n: int = 100_000,
    *,
    radius: float = 1.0,
    center: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    noise: float = 0.0,
    seed: int = 0,
) -> np.ndarray:
    """Return `(n, 3)` float64 points on a sphere of radius `radius`.

    Points are uniformly distributed on the sphere surface using the standard
    "normalize a 3D Gaussian" trick; optional `noise` adds Gaussian thickness
    along the radial direction.
    """
    rng = np.random.default_rng(seed)
    raw = rng.standard_normal(size=(n, 3))
    raw /= np.linalg.norm(raw, axis=1, keepdims=True)
    if noise > 0.0:
        r = radius + rng.normal(0.0, noise, size=(n, 1))
    else:
        r = radius
    pts = raw * r + np.asarray(center, dtype=np.float64)
    return pts.astype(np.float64, copy=False)


def make_two_plane_disconnected(
    n: int = 100_000,
    *,
    gap: float = 5.0,
    noise: float = 0.01,
    extent: float = 1.0,
    seed: int = 0,
) -> np.ndarray:
    """Return `(n, 3)` float64 points on two parallel planes separated by `gap`.

    The planes are both perpendicular to +Z; one sits at `z = -gap/2` and one
    at `z = +gap/2`. Points are split evenly between the two planes (the
    second plane gets the remainder when `n` is odd). No points are placed
    between the planes — this simulates an occlusion gap that voxel
    connected-component code should split into two clusters.
    """
    rng = np.random.default_rng(seed)
    n_lower = n // 2
    n_upper = n - n_lower

    half_gap = gap / 2.0

    lower_xy = rng.uniform(-extent, extent, size=(n_lower, 2))
    lower_z = -half_gap + rng.normal(0.0, noise, size=(n_lower, 1))
    lower = np.hstack([lower_xy, lower_z])

    upper_xy = rng.uniform(-extent, extent, size=(n_upper, 2))
    upper_z = half_gap + rng.normal(0.0, noise, size=(n_upper, 1))
    upper = np.hstack([upper_xy, upper_z])

    pts = np.vstack([lower, upper]).astype(np.float64, copy=False)
    return pts


# ---------------------------------------------------------------------------
# .e57 fixture writers (require pye57 at runtime)
# ---------------------------------------------------------------------------


def _random_cube_points(rng: np.random.Generator, n: int, side: float) -> dict:
    """Build a dict of float64 X/Y/Z arrays uniformly inside a cube of side `side`."""
    half = side / 2.0
    xyz = rng.uniform(-half, half, size=(n, 3)).astype(np.float64)
    return {
        "cartesianX": np.ascontiguousarray(xyz[:, 0]),
        "cartesianY": np.ascontiguousarray(xyz[:, 1]),
        "cartesianZ": np.ascontiguousarray(xyz[:, 2]),
    }


def make_single_scan_rgb(
    path: str,
    *,
    n_points: int = 10_000,
    seed: int = 0,
) -> None:
    """Write a `.e57` with one scan containing X/Y/Z + intensity + RGB.

    Coordinates are uniformly random inside a 10 m cube centred on the origin.
    Intensity is uniformly distributed in [0, 4096] (float). RGB are uint8
    drawn uniformly from [0, 255].
    """
    import pye57  # lazy import so module is usable pre-A1

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    rng = np.random.default_rng(seed)
    data = _random_cube_points(rng, n_points, side=10.0)
    data["intensity"] = rng.uniform(0.0, 4096.0, size=n_points).astype(np.float64)
    data["colorRed"] = rng.integers(0, 256, size=n_points, dtype=np.uint8)
    data["colorGreen"] = rng.integers(0, 256, size=n_points, dtype=np.uint8)
    data["colorBlue"] = rng.integers(0, 256, size=n_points, dtype=np.uint8)

    # `mode="w"` truncates / creates the file. We don't pass `scan_header`;
    # pye57 will synthesise prototype + limits from the data and kwargs.
    e57 = pye57.E57(path, mode="w")
    try:
        e57.write_scan_raw(
            data,
            name="synthetic_single_rgb",
            rotation=np.array([1.0, 0.0, 0.0, 0.0]),       # identity quaternion (w, x, y, z)
            translation=np.array([0.0, 0.0, 0.0]),
        )
    finally:
        # pye57.E57 closes the underlying libe57 ImageFile when the python
        # object is garbage-collected; explicit del keeps tests deterministic.
        del e57


def make_multi_scan(
    path: str,
    *,
    n_scans: int = 3,
    n_points_per_scan: int = 5_000,
    seed: int = 0,
) -> None:
    """Write a `.e57` with `n_scans` scans, distinct names + poses, same prototype as
    `make_single_scan_rgb` (X/Y/Z + intensity + RGB).

    Pose for scan `k`:
      - translation = (k * 5.0, 0, 0)  (5 m apart along +X)
      - rotation    = identity quaternion (w=1, x=y=z=0)
    """
    import pye57

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    rng = np.random.default_rng(seed)
    e57 = pye57.E57(path, mode="w")
    try:
        for k in range(n_scans):
            data = _random_cube_points(rng, n_points_per_scan, side=10.0)
            data["intensity"] = rng.uniform(0.0, 4096.0, size=n_points_per_scan).astype(np.float64)
            data["colorRed"] = rng.integers(0, 256, size=n_points_per_scan, dtype=np.uint8)
            data["colorGreen"] = rng.integers(0, 256, size=n_points_per_scan, dtype=np.uint8)
            data["colorBlue"] = rng.integers(0, 256, size=n_points_per_scan, dtype=np.uint8)

            e57.write_scan_raw(
                data,
                name=f"synthetic_scan_{k:02d}",
                rotation=np.array([1.0, 0.0, 0.0, 0.0]),
                translation=np.array([float(k) * 5.0, 0.0, 0.0]),
            )
    finally:
        del e57


def make_intensity_only(
    path: str,
    *,
    n_points: int = 5_000,
    seed: int = 0,
) -> None:
    """Write a `.e57` with one scan whose prototype has X/Y/Z + intensity but NO color.

    Used by G1a Mode C to test the "fail-fast on no-RGB" path of the pipeline.

    pye57 API note (verified against `vendor/pye57/src/pye57/e57.py`,
    `write_scan_raw`): the prototype is built from the *keys present in the
    `data` dict*. `colorRed/Green/Blue` are only added to the prototype if all
    three are present in `data`. Therefore omitting them from `data` is
    sufficient to produce an intensity-only prototype — no special flag or
    scan_header tweak is required.
    """
    import pye57

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    rng = np.random.default_rng(seed)
    data = _random_cube_points(rng, n_points, side=10.0)
    data["intensity"] = rng.uniform(0.0, 4096.0, size=n_points).astype(np.float64)

    e57 = pye57.E57(path, mode="w")
    try:
        e57.write_scan_raw(
            data,
            name="synthetic_intensity_only",
            rotation=np.array([1.0, 0.0, 0.0, 0.0]),
            translation=np.array([0.0, 0.0, 0.0]),
        )
    finally:
        del e57
