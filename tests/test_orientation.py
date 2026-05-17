"""Tests for `intensity_rgb.processing.orientation`.

The orientation pass runs after `VoxelAccumulator.finalize()` (Wave 1 / A3),
which we don't actually need here — we synthesize FrozenChunk objects
directly using the same field contract documented in the plan:

    normals : (C, C, C, 3) float32
    quality : (C, C, C)    bool
    means   : (C, C, C, 3) float32

A3 has not yet landed `FrozenChunk` as a public dataclass, so we define a
local equivalent here. If A3 ships with a divergent shape, the orientation
module's contract is satisfied as long as the same three attributes exist
with the same shapes/dtypes — the integration story can adapt either side.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from intensity_rgb.processing.orientation import (
    ComponentInfo,
    OrientationResult,
    invert_component,
    orient_normals,
)


# ---- local FrozenChunk stand-in (matches A3's contract) --------------------


@dataclass
class FrozenChunk:
    normals: np.ndarray  # (C, C, C, 3) float32
    quality: np.ndarray  # (C, C, C)    bool
    means: np.ndarray  # (C, C, C, 3) float32

    @classmethod
    def empty(cls, C: int, chunk_key, voxel_size: float = 1.0) -> "FrozenChunk":
        normals = np.zeros((C, C, C, 3), dtype=np.float32)
        quality = np.zeros((C, C, C), dtype=bool)
        # Default means: voxel centre in world coords (so they read like
        # something the accumulator might produce).
        cx, cy, cz = chunk_key
        means = np.zeros((C, C, C, 3), dtype=np.float32)
        for lx in range(C):
            for ly in range(C):
                for lz in range(C):
                    means[lx, ly, lz] = (
                        (cx * C + lx + 0.5) * voxel_size,
                        (cy * C + ly + 0.5) * voxel_size,
                        (cz * C + lz + 0.5) * voxel_size,
                    )
        return cls(normals=normals, quality=quality, means=means)


# ---- builders --------------------------------------------------------------


def _set_voxel(
    frozen_chunks: dict,
    C: int,
    gx: int,
    gy: int,
    gz: int,
    normal: np.ndarray,
    voxel_size: float = 1.0,
) -> None:
    """Mark a global voxel as quality and assign it a normal."""
    cx, lx = divmod(gx, C)
    cy, ly = divmod(gy, C)
    cz, lz = divmod(gz, C)
    chunk_key = (cx, cy, cz)
    if chunk_key not in frozen_chunks:
        frozen_chunks[chunk_key] = FrozenChunk.empty(C, chunk_key, voxel_size)
    chunk = frozen_chunks[chunk_key]
    chunk.normals[lx, ly, lz] = normal.astype(np.float32)
    chunk.quality[lx, ly, lz] = True


def _build_plane_xy(
    z: int,
    x_range: range,
    y_range: range,
    *,
    normal: np.ndarray,
    C: int = 8,
    frozen_chunks=None,
    voxel_size: float = 1.0,
) -> dict:
    """Build a flat horizontal sheet of quality voxels at a fixed global z."""
    if frozen_chunks is None:
        frozen_chunks = {}
    for gx in x_range:
        for gy in y_range:
            _set_voxel(frozen_chunks, C, gx, gy, z, normal, voxel_size)
    return frozen_chunks


def _build_wall_yz(
    x: int,
    y_range: range,
    z_range: range,
    *,
    normal: np.ndarray,
    C: int = 8,
    frozen_chunks=None,
    voxel_size: float = 1.0,
) -> dict:
    """Build a flat vertical wall at a fixed global x (normals along ±X)."""
    if frozen_chunks is None:
        frozen_chunks = {}
    for gy in y_range:
        for gz in z_range:
            _set_voxel(frozen_chunks, C, x, gy, gz, normal, voxel_size)
    return frozen_chunks


def _collect_normals(frozen_chunks: dict, component: ComponentInfo) -> np.ndarray:
    out = np.zeros((len(component.voxel_keys), 3), dtype=np.float32)
    for i, (cx, cy, cz, lx, ly, lz) in enumerate(component.voxel_keys):
        out[i] = frozen_chunks[(cx, cy, cz)].normals[lx, ly, lz]
    return out


# ---- tests ----------------------------------------------------------------


def test_two_plane_disconnected_both_align_up():
    """Two horizontal sheets separated by an occlusion gap.

    Plane A at z=2 has normals (+Z), plane B at z=20 has normals (-Z).
    The gap (>= 2 voxels) breaks 26-connectivity, so they form two
    components. With up_vector=+Z, both components should end up pointing
    +Z, including the one that started flipped.
    """
    C = 8
    chunks: dict = {}
    # Plane A: 4x4 patch at z=2, normals already +Z
    _build_plane_xy(2, range(0, 4), range(0, 4), normal=np.array([0, 0, 1.0]), C=C, frozen_chunks=chunks)
    # Plane B: 4x4 patch at z=20 (far enough away to be disconnected), normals -Z
    _build_plane_xy(20, range(0, 4), range(0, 4), normal=np.array([0, 0, -1.0]), C=C, frozen_chunks=chunks)

    result = orient_normals(chunks, up_vector=np.array([0, 0, 1.0], dtype=np.float32))

    assert len(result.components) == 2, f"expected 2 components, got {len(result.components)}"
    # Both components should be roughly equal in size (16 voxels each).
    assert result.components[0].voxel_count == 16
    assert result.components[1].voxel_count == 16

    for comp in result.components:
        assert comp.mean_normal[2] > 0.9, (
            f"component mean_normal {comp.mean_normal} not pointing up"
        )

    # And per-voxel: every normal should have z > 0.
    for comp in result.components:
        normals = _collect_normals(chunks, comp)
        assert np.all(normals[:, 2] > 0.0), f"component has down-facing voxels: {normals}"


def test_single_plane_already_correct_noop():
    """One connected plane already pointing +Z. Orient should leave it alone."""
    C = 8
    chunks: dict = {}
    _build_plane_xy(3, range(0, 5), range(0, 5), normal=np.array([0, 0, 1.0]), C=C, frozen_chunks=chunks)

    # snapshot
    pre = {k: v.normals.copy() for k, v in chunks.items()}

    result = orient_normals(chunks, up_vector=np.array([0, 0, 1.0], dtype=np.float32))

    assert len(result.components) == 1
    assert result.components[0].voxel_count == 25
    for k, v in chunks.items():
        np.testing.assert_array_equal(v.normals, pre[k], err_msg=f"chunk {k} mutated unexpectedly")
    assert result.components[0].mean_normal[2] > 0.99


def test_single_plane_flipped_gets_corrected():
    """One plane starting at -Z normals; after orient, all should be +Z."""
    C = 8
    chunks: dict = {}
    _build_plane_xy(3, range(0, 5), range(0, 5), normal=np.array([0, 0, -1.0]), C=C, frozen_chunks=chunks)

    result = orient_normals(chunks, up_vector=np.array([0, 0, 1.0], dtype=np.float32))

    assert len(result.components) == 1
    normals = _collect_normals(chunks, result.components[0])
    # Every voxel should now point +Z.
    assert np.all(normals[:, 2] > 0.9), f"some voxels still negative: {normals}"
    assert result.components[0].mean_normal[2] > 0.9


def test_invert_component_only_flips_one_island():
    """Two-plane scene; invert one component and assert only its normals flipped."""
    C = 8
    chunks: dict = {}
    _build_plane_xy(2, range(0, 4), range(0, 4), normal=np.array([0, 0, 1.0]), C=C, frozen_chunks=chunks)
    _build_plane_xy(20, range(0, 4), range(0, 4), normal=np.array([0, 0, -1.0]), C=C, frozen_chunks=chunks)

    result = orient_normals(chunks, up_vector=np.array([0, 0, 1.0], dtype=np.float32))
    assert len(result.components) == 2

    # Pre-invert: both pointing +Z.
    before_0 = _collect_normals(chunks, result.components[0]).copy()
    before_1 = _collect_normals(chunks, result.components[1]).copy()
    assert np.all(before_0[:, 2] > 0.9)
    assert np.all(before_1[:, 2] > 0.9)

    invert_component(chunks, result.components[0])

    after_0 = _collect_normals(chunks, result.components[0])
    after_1 = _collect_normals(chunks, result.components[1])

    np.testing.assert_allclose(after_0, -before_0, atol=1e-6)
    np.testing.assert_allclose(after_1, before_1, atol=1e-6)


def test_horizontal_seed_falls_back_to_centroid():
    """Vertical wall: every normal has |z| = 0 → fallback kicks in.

    We assert two properties:
    1. The orientation pass marked a fallback (so the centroid branch ran).
    2. All wall normals end up on the same side of the wall after orient
       (i.e., globally consistent, even if we can't say whether that side
       is +X or -X without extra knowledge).
    """
    C = 8
    chunks: dict = {}
    # Wall at gx=4 with normals pointing +X. We give half of them a starting
    # sign of -X so BFS has work to do, then assert globally-consistent.
    wall_x = 4
    for i, gy in enumerate(range(0, 6)):
        for j, gz in enumerate(range(0, 6)):
            # Alternate initial sign so seed orientation has something to fix.
            sign = 1.0 if ((i + j) % 2 == 0) else -1.0
            _set_voxel(
                chunks,
                C,
                wall_x,
                gy,
                gz,
                np.array([sign, 0.0, 0.0]),
                voxel_size=1.0,
            )

    result = orient_normals(chunks, up_vector=np.array([0, 0, 1.0], dtype=np.float32))

    assert len(result.components) == 1
    assert result.fallback_components == 1, (
        "horizontal-seed fallback did not run on a vertical wall"
    )

    normals = _collect_normals(chunks, result.components[0])
    # |N.z| is 0 everywhere; check X-axis consistency.
    signs = np.sign(normals[:, 0])
    # Either all +1 or all -1 — fallback is heuristic, we don't pin which side.
    assert np.all(signs == signs[0]), (
        f"wall normals not globally consistent: {signs}"
    )
    # And |N.x| ~ 1, no degenerate vectors.
    assert np.all(np.abs(normals[:, 0]) > 0.99)


def test_empty_input_returns_empty_result():
    """Edge case: no chunks. Should not raise, returns empty result."""
    result = orient_normals({})
    assert result.components == []
    assert result.fallback_components == 0


def test_all_low_quality_returns_empty():
    """All voxels quality=False → no components."""
    C = 8
    chunks = {(0, 0, 0): FrozenChunk.empty(C, (0, 0, 0))}
    # quality stays False everywhere
    result = orient_normals(chunks)
    assert result.components == []


def test_chunk_boundary_voxels_connect():
    """Two adjacent voxels straddling a chunk boundary should form ONE component.

    With C=4, voxels at global x=3 and x=4 live in chunks (0,0,0) and (1,0,0)
    respectively. They are 26-connected so the orientation pass must treat
    them as one island.
    """
    C = 4
    chunks: dict = {}
    _set_voxel(chunks, C, 3, 0, 0, np.array([0, 0, 1.0]))
    _set_voxel(chunks, C, 4, 0, 0, np.array([0, 0, -1.0]))  # flipped on purpose

    result = orient_normals(chunks, up_vector=np.array([0, 0, 1.0], dtype=np.float32))
    assert len(result.components) == 1, (
        f"chunk boundary not bridged: {len(result.components)} components"
    )
    assert result.components[0].voxel_count == 2
    # Both should end up +Z after BFS.
    normals = _collect_normals(chunks, result.components[0])
    assert np.all(normals[:, 2] > 0.9)
