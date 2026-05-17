"""Tests for the chunked voxel accumulator and compact-then-eigh finaliser.

Covers the five required correctness gates:

1. Plane test       — 100k noisy points on z=5; mean |N · z_hat| > 0.95.
2. Sphere test      — 100k points on a unit sphere; mean |N · radial| > 0.9.
3. Sparse chunk     — 100 points across a 50³-voxel region; no NaNs;
                      under-supported voxels are quality=False.
4. Empty-cell safety — one valid cell in an otherwise-zero chunk; eigh
                      never sees NaN; the valid cell produces a sensible
                      normal.
5. Neighbour dilation — an under-supported voxel surrounded by good
                      neighbours gets a normal; an isolated low-count
                      voxel stays quality=False.
"""

from __future__ import annotations

import numpy as np
import pytest

from intensity_rgb.processing.voxel_normals import (
    CHUNK,
    MIN_SUPPORT,
    FrozenChunk,
    VoxelAccumulator,
    finalize_chunk,
    lookup_normals,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gather_all_normals(frozen: dict[tuple[int, int, int], FrozenChunk]):
    """Concatenate normals + quality from a frozen-chunk dict."""
    nlists, qlists = [], []
    for fc in frozen.values():
        nlists.append(fc.normals.reshape(-1, 3))
        qlists.append(fc.quality.reshape(-1))
    if not nlists:
        return (
            np.zeros((0, 3), dtype=np.float32),
            np.zeros((0,), dtype=bool),
        )
    return np.concatenate(nlists, axis=0), np.concatenate(qlists, axis=0)


# ---------------------------------------------------------------------------
# 1. Plane test
# ---------------------------------------------------------------------------


def test_plane_normals_align_with_z_axis():
    rng = np.random.default_rng(0xC0FFEE)
    N = 100_000
    xy = rng.uniform(-10, 10, size=(N, 2))
    z = 5.0 + rng.normal(0.0, 0.01, size=N)  # ~1 cm noise
    xyz = np.column_stack([xy, z])

    origin = np.array([-10.0, -10.0, 4.5], dtype=np.float64)
    acc = VoxelAccumulator(origin=origin, voxel_size=0.5)
    # Feed in two blocks to exercise the streaming path.
    acc.add_block(xyz[: N // 2])
    acc.add_block(xyz[N // 2 :])
    frozen = acc.finalize()
    assert len(frozen) > 0, "plane should occupy at least one chunk"

    normals, quality = _gather_all_normals(frozen)
    n = normals[quality]
    assert n.shape[0] > 0, "at least some voxels must be quality=True"
    dot = np.abs(n @ np.array([0.0, 0.0, 1.0]))
    assert dot.mean() > 0.95, f"mean |N·z_hat| was {dot.mean():.3f}"


# ---------------------------------------------------------------------------
# 2. Sphere test
# ---------------------------------------------------------------------------


def test_sphere_normals_are_radial():
    rng = np.random.default_rng(0xDADA)
    N = 100_000
    # Uniform on the unit sphere.
    vec = rng.normal(size=(N, 3))
    vec /= np.linalg.norm(vec, axis=1, keepdims=True)

    origin = np.array([-1.5, -1.5, -1.5], dtype=np.float64)
    # Small voxels so each voxel sees a near-planar patch of the sphere.
    acc = VoxelAccumulator(
        origin=origin,
        voxel_size=0.1,
        min_support=8,
        planarity_threshold=0.3,
    )
    acc.add_block(vec)
    frozen = acc.finalize()
    assert len(frozen) > 0

    # Probe at each voxel's centroid — read normals & means back.
    pts, normals = [], []
    for fc in frozen.values():
        q = fc.quality
        if not q.any():
            continue
        mean_xyz = fc.means[q]
        n = fc.normals[q]
        pts.append(mean_xyz)
        normals.append(n)
    pts = np.concatenate(pts, axis=0).astype(np.float64)
    normals = np.concatenate(normals, axis=0).astype(np.float64)
    radial = pts / np.maximum(np.linalg.norm(pts, axis=1, keepdims=True), 1e-12)
    dot = np.abs(np.sum(normals * radial, axis=1))
    assert dot.mean() > 0.9, f"mean |N·r_hat| was {dot.mean():.3f}"


# ---------------------------------------------------------------------------
# 3. Sparse chunk test
# ---------------------------------------------------------------------------


def test_sparse_chunk_no_nans_low_count_voxels_quality_false():
    rng = np.random.default_rng(42)
    # 100 points scattered uniformly across a 50^3 voxel cube.
    voxel_size = 1.0
    origin = np.zeros(3)
    coords = rng.uniform(0.0, 50.0, size=(100, 3))
    acc = VoxelAccumulator(origin=origin, voxel_size=voxel_size, min_support=8)
    acc.add_block(coords)
    frozen = acc.finalize()

    # No matter how many chunks survive, every produced normal must be
    # finite and no quality-True voxel may exist (no voxel has 8 pts).
    for fc in frozen.values():
        assert np.isfinite(fc.normals).all(), "frozen normals contain NaN/inf"
        assert np.isfinite(fc.means).all(), "frozen means contain NaN/inf"
        # With ~100 random points across 125k voxels, no voxel reaches
        # min_support=8 even after 26-neighbour dilation.
        assert not fc.quality.any(), "no voxel should pass min_support here"


# ---------------------------------------------------------------------------
# 4. Empty-cell safety
# ---------------------------------------------------------------------------


def test_finalize_chunk_with_single_valid_cell():
    """One valid cell in an otherwise-zero chunk must not feed NaN to eigh."""
    C = 32
    chunk = np.zeros((C, C, C, 10), dtype=np.float64)
    # Synthesize 12 points landing in voxel (5, 5, 5), forming a near-planar
    # patch in the xy-plane around (10, 10, 0).
    pts = np.array(
        [
            [10.00, 10.00, 0.0],
            [10.05, 10.02, 0.0],
            [10.02, 10.05, 0.0],
            [10.07, 10.03, 0.0],
            [10.03, 10.07, 0.0],
            [10.08, 10.05, 0.0],
            [10.05, 10.08, 0.0],
            [10.01, 10.01, 0.0],
            [10.06, 10.06, 0.0],
            [10.04, 10.04, 0.0],
            [10.09, 10.09, 0.0],
            [10.02, 10.08, 0.0],
        ],
        dtype=np.float64,
    )
    vox = (5, 5, 5)
    n = pts.shape[0]
    chunk[vox][0] = n
    chunk[vox][1:4] = pts.sum(axis=0)
    chunk[vox][4] = (pts[:, 0] * pts[:, 0]).sum()
    chunk[vox][5] = (pts[:, 0] * pts[:, 1]).sum()
    chunk[vox][6] = (pts[:, 0] * pts[:, 2]).sum()
    chunk[vox][7] = (pts[:, 1] * pts[:, 1]).sum()
    chunk[vox][8] = (pts[:, 1] * pts[:, 2]).sum()
    chunk[vox][9] = (pts[:, 2] * pts[:, 2]).sum()

    fc = finalize_chunk(chunk, min_support=8, planarity_threshold=0.5)
    assert fc is not None
    assert np.isfinite(fc.normals).all()
    # The one valid cell must be quality True.
    assert fc.quality[vox]
    nvec = fc.normals[vox]
    # Cell is flat in z — normal should be ±z_hat.
    assert abs(nvec[2]) > 0.95
    # All other voxels must be untouched (zeros, quality False).
    qcopy = fc.quality.copy()
    qcopy[vox] = False
    assert not qcopy.any()


def test_finalize_chunk_all_empty_returns_none():
    chunk = np.zeros((CHUNK, CHUNK, CHUNK, 10), dtype=np.float64)
    assert finalize_chunk(chunk) is None


# ---------------------------------------------------------------------------
# 5. Neighbour-dilation fallback
# ---------------------------------------------------------------------------


def test_neighbour_dilation_promotes_borderline_voxel():
    """A low-count voxel surrounded by good neighbours becomes quality True.

    Builds an accumulator where:
      - Voxel A has 4 points (< MIN_SUPPORT=8).
      - All 8 in-plane neighbours of A have 8 points each (well-supported),
        all lying on the same xy plane at z = A_z + 0.5.
      - The out-of-plane neighbours (z±1) are empty — so dilation pulls
        only from coherent neighbours, the result is still planar.
      - Voxel B (isolated, far away) has 4 points, no good neighbours.

    Quality fraction visibly changes pre→post-dilation: without dilation
    A is quality=False, with dilation it's quality=True. We verify the
    post-finalize state directly here.
    """
    rng = np.random.default_rng(7)
    voxel_size = 1.0
    origin = np.array([0.0, 0.0, 0.0])

    def planar_points(vox_idx, count, z_plane):
        cx, cy, cz = vox_idx
        xs = cx + rng.uniform(0.1, 0.9, size=count)
        ys = cy + rng.uniform(0.1, 0.9, size=count)
        # z lies tightly on a single plane shared by A and its 8 in-plane
        # neighbours — clipped into the voxel.
        zs = np.full(count, z_plane, dtype=np.float64)
        zs += rng.normal(0.0, 0.005, size=count)
        zs = np.clip(zs, cz + 0.01, cz + 0.99)
        return np.column_stack([xs, ys, zs])

    A = (10, 10, 10)
    z_plane = A[2] + 0.5

    pts_blocks = [planar_points(A, 4, z_plane)]  # under-supported
    # Only 8 in-plane (dz=0) neighbours so the dilated patch stays planar.
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            pts_blocks.append(
                planar_points((A[0] + dx, A[1] + dy, A[2]), 8, z_plane)
            )

    # Isolated under-supported voxel B far away — no neighbours.
    B = (60, 60, 60)
    pts_blocks.append(planar_points(B, 4, B[2] + 0.5))

    xyz = np.concatenate(pts_blocks, axis=0)
    acc = VoxelAccumulator(
        origin=origin,
        voxel_size=voxel_size,
        min_support=8,
        planarity_threshold=0.5,
    )
    acc.add_block(xyz)

    # Snapshot the quality A would have *without* dilation by running
    # finalize_chunk on a copy of the moments before VoxelAccumulator
    # mutates them. (The test wants to assert dilation changed things.)
    from intensity_rgb.processing.voxel_normals import finalize_chunk

    moments_snapshot = {k: v.copy() for k, v in acc.moments.items()}
    # Find which chunk holds A.
    a_chunk_key = (A[0] // CHUNK, A[1] // CHUNK, A[2] // CHUNK)
    a_local = (A[0] % CHUNK, A[1] % CHUNK, A[2] % CHUNK)
    pre_frozen = finalize_chunk(
        moments_snapshot[a_chunk_key], min_support=8, planarity_threshold=0.5
    )
    pre_quality_at_A = bool(pre_frozen.quality[a_local]) if pre_frozen else False

    frozen = acc.finalize()

    # Post-dilation: lookup A and B via the helper.
    query = np.array(
        [
            [A[0] + 0.5, A[1] + 0.5, z_plane],
            [B[0] + 0.5, B[1] + 0.5, B[2] + 0.5],
        ]
    )
    normals, qualities = lookup_normals(
        frozen,
        origin=origin,
        voxel_size=voxel_size,
        chunk_size=CHUNK,
        xyz=query,
    )
    assert not pre_quality_at_A, "A should be quality=False before dilation"
    assert qualities[0], "voxel A should be promoted by neighbour dilation"
    # Its normal should be near ±z_hat (planar patch).
    assert abs(normals[0, 2]) > 0.9, f"A normal: {normals[0]}"
    assert not qualities[1], "isolated low-count voxel B must remain quality=False"


# ---------------------------------------------------------------------------
# Extra: lookup_normals contract sanity (no NaN, unfrozen-chunk safety).
# ---------------------------------------------------------------------------


def test_lookup_unfrozen_chunk_returns_zero_and_quality_false():
    # Single well-supported voxel near origin.
    rng = np.random.default_rng(1)
    pts = np.column_stack(
        [
            rng.uniform(0.05, 0.45, size=20),
            rng.uniform(0.05, 0.45, size=20),
            rng.normal(0.25, 0.001, size=20),
        ]
    )
    origin = np.zeros(3)
    acc = VoxelAccumulator(origin=origin, voxel_size=0.5)
    acc.add_block(pts)
    frozen = acc.finalize()

    # Query far from any frozen chunk.
    far_query = np.array([[1e4, 1e4, 1e4]])
    n, q = lookup_normals(
        frozen,
        origin=origin,
        voxel_size=0.5,
        chunk_size=CHUNK,
        xyz=far_query,
    )
    assert n.shape == (1, 3)
    assert not q[0]
    assert (n == 0).all()


def test_origin_validation():
    with pytest.raises(ValueError):
        VoxelAccumulator(origin=np.zeros(3), voxel_size=0.0)
    with pytest.raises(ValueError):
        VoxelAccumulator(origin=np.zeros(3), voxel_size=0.5, chunk=0)
