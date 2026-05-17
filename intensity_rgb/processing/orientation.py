"""Per-component normal-orientation pass for the streaming voxel pipeline.

This module consumes the `FrozenChunk` map produced by
`VoxelAccumulator.finalize()` (see plan §"Voxel accumulator design"). Each
FrozenChunk is expected to expose:

    normals : (C, C, C, 3) float32   -- unit normals (or zeros for empty cells)
    quality : (C, C, C)    bool      -- True where the voxel has a usable normal
    means   : (C, C, C, 3) float32   -- accumulated point centroid per voxel

The orientation pass does three things, in line with the canonical algorithm
in `plans/stateful-hatching-kitten.md` §"Normal orientation":

1.  Build a voxel quality-graph over the union of FrozenChunks (26-connected
    neighbours, both endpoints must be `quality=True`). Voxels span chunks,
    so neighbour lookups have to bridge chunk boundaries.
2.  Find connected components via union-find.
3.  For each component, pick a seed (voxel-count proxy, since point counts
    aren't carried through FrozenChunk), establish its sign against an
    up-vector prior (with an outward-from-centroid fallback when the seed
    normal is near-horizontal), then BFS the component flipping any
    neighbour with `dot(N_neighbour, N_current) < 0`.

The flips happen in place on each FrozenChunk's `normals` array.

`OrientationResult` carries enough information for the Wave-4 UI to flip a
single component on/off via `invert_component`.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Iterable, Mapping, MutableMapping, Sequence, Tuple

import numpy as np


VoxelKey = Tuple[int, int, int, int, int, int]  # (cx, cy, cz, lx, ly, lz)
ChunkKey = Tuple[int, int, int]


@dataclass
class ComponentInfo:
    """One connected component in the voxel quality graph.

    Attributes:
        voxel_count: number of quality voxels in the component.
        mean_normal: float32 (3,) — mean of the (post-orientation) normals
            across the component. Useful for UI preview chips.
        voxel_keys: list of (cx, cy, cz, lx, ly, lz) tuples — the addresses
            of every quality voxel in this component. Used by
            `invert_component` to flip a single island.
    """

    voxel_count: int
    mean_normal: np.ndarray  # (3,) float32
    voxel_keys: list  # list[VoxelKey]


@dataclass
class OrientationResult:
    """Result of the orientation pass.

    `components` is sorted by `voxel_count` descending so the UI can take
    `result.components[:top_k]` directly for the per-component invert chips.
    """

    components: list  # list[ComponentInfo]
    fallback_components: int = 0  # how many components used the centroid fallback


# ----- helpers --------------------------------------------------------------


def _infer_chunk_size(frozen_chunks: Mapping[ChunkKey, object]) -> int:
    """Return C from the first FrozenChunk's normals shape (C, C, C, 3)."""
    for chunk in frozen_chunks.values():
        shape = chunk.normals.shape
        if len(shape) != 4 or shape[3] != 3 or not (shape[0] == shape[1] == shape[2]):
            raise ValueError(f"unexpected FrozenChunk normals shape {shape!r}")
        return int(shape[0])
    raise ValueError("frozen_chunks is empty")


def _global_to_chunk_local(gx: int, gy: int, gz: int, C: int) -> Tuple[ChunkKey, Tuple[int, int, int]]:
    """Translate a global voxel coordinate to (chunk_key, local_index)."""
    cx, lx = divmod(gx, C)
    cy, ly = divmod(gy, C)
    cz, lz = divmod(gz, C)
    return (cx, cy, cz), (lx, ly, lz)


class _UnionFind:
    """Path-compressed union-find over integer node ids."""

    __slots__ = ("parent", "rank", "size")

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n
        self.size = [1] * n

    def find(self, x: int) -> int:
        # iterative path compression
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            nxt = self.parent[x]
            self.parent[x] = root
            x = nxt
        return root

    def union(self, a: int, b: int) -> None:
        ra = self.find(a)
        rb = self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.size[ra] += self.size[rb]
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


# 26-connected neighbour offsets (excludes (0,0,0))
_NEIGHBOUR_OFFSETS = tuple(
    (dx, dy, dz)
    for dx in (-1, 0, 1)
    for dy in (-1, 0, 1)
    for dz in (-1, 0, 1)
    if not (dx == 0 and dy == 0 and dz == 0)
)


def _collect_quality_voxels(
    frozen_chunks: Mapping[ChunkKey, object], C: int
) -> Tuple[list, dict]:
    """Enumerate all quality=True voxels.

    Returns:
        voxel_list: list of VoxelKey, ordered by chunk then by raveled local
            index. Index in this list is the node id used by union-find.
        global_index: dict mapping (gx, gy, gz) -> node id, for neighbour
            lookups across chunk boundaries.
    """
    voxel_list: list = []
    global_index: dict = {}
    for chunk_key, chunk in frozen_chunks.items():
        quality = np.asarray(chunk.quality)
        if quality.shape != (C, C, C):
            raise ValueError(f"chunk {chunk_key} quality shape {quality.shape} != ({C},{C},{C})")
        if not quality.any():
            continue
        # np.nonzero in C-order: lx outermost, lz innermost
        ls = np.nonzero(quality)
        cx, cy, cz = chunk_key
        for lx, ly, lz in zip(ls[0].tolist(), ls[1].tolist(), ls[2].tolist()):
            node_id = len(voxel_list)
            voxel_list.append((cx, cy, cz, lx, ly, lz))
            gx = cx * C + lx
            gy = cy * C + ly
            gz = cz * C + lz
            global_index[(gx, gy, gz)] = node_id
    return voxel_list, global_index


def _build_components(
    voxel_list: Sequence[VoxelKey], global_index: Mapping[Tuple[int, int, int], int], C: int
) -> Tuple[list, list]:
    """Union-find over 26-connected quality neighbours.

    Returns:
        component_ids: list[int] same length as voxel_list, root id per node.
        component_members: list of lists — voxel-node-ids grouped by root.
    """
    n = len(voxel_list)
    uf = _UnionFind(n)
    for node_id, (cx, cy, cz, lx, ly, lz) in enumerate(voxel_list):
        gx = cx * C + lx
        gy = cy * C + ly
        gz = cz * C + lz
        for dx, dy, dz in _NEIGHBOUR_OFFSETS:
            # Only union to neighbour with strictly larger node id to avoid
            # duplicating work — neighbours seen later in the iteration will
            # union to this one when they arrive.
            other = global_index.get((gx + dx, gy + dy, gz + dz))
            if other is not None and other > node_id:
                uf.union(node_id, other)

    component_ids = [uf.find(i) for i in range(n)]
    members: dict = {}
    for i, root in enumerate(component_ids):
        members.setdefault(root, []).append(i)
    component_members = list(members.values())
    return component_ids, component_members


def _flip_voxel(frozen_chunks: Mapping[ChunkKey, object], key: VoxelKey) -> None:
    cx, cy, cz, lx, ly, lz = key
    frozen_chunks[(cx, cy, cz)].normals[lx, ly, lz] *= -1.0


def _orient_component(
    member_node_ids: Sequence[int],
    voxel_list: Sequence[VoxelKey],
    global_index: Mapping[Tuple[int, int, int], int],
    frozen_chunks: Mapping[ChunkKey, object],
    C: int,
    voxel_size: float,
    up_vector: np.ndarray,
) -> Tuple[bool, np.ndarray]:
    """Orient one connected component in place.

    Returns:
        used_fallback: True if the seed used the outward-from-centroid path.
        mean_normal: (3,) float32 mean of normals after orientation.
    """
    # --- pick seed: voxel-count proxy means "any voxel"; tie-break by node id ---
    # All voxels in this component contribute equally to the count proxy, so
    # we just pick the first one. To make the seed deterministic and a touch
    # more meaningful we pick the voxel whose normal has the largest |N.z|
    # (most "stable" under the up-vector heuristic). When all normals are
    # near-horizontal the fallback path kicks in below anyway.
    best_idx = member_node_ids[0]
    best_absz = -1.0
    for node_id in member_node_ids:
        cx, cy, cz, lx, ly, lz = voxel_list[node_id]
        nz = float(frozen_chunks[(cx, cy, cz)].normals[lx, ly, lz, 2])
        if abs(nz) > best_absz:
            best_absz = abs(nz)
            best_idx = node_id

    seed_key = voxel_list[best_idx]
    cx, cy, cz, lx, ly, lz = seed_key
    seed_chunk = frozen_chunks[(cx, cy, cz)]
    seed_normal = np.asarray(seed_chunk.normals[lx, ly, lz], dtype=np.float32).copy()

    used_fallback = False
    if abs(float(seed_normal[2])) < 0.2:
        # outward-from-centroid fallback
        used_fallback = True
        # Component AABB centroid in world coords, using FrozenChunk.means.
        sum_centroid = np.zeros(3, dtype=np.float64)
        count = 0
        for node_id in member_node_ids:
            cx2, cy2, cz2, lx2, ly2, lz2 = voxel_list[node_id]
            sum_centroid += frozen_chunks[(cx2, cy2, cz2)].means[lx2, ly2, lz2]
            count += 1
        comp_centroid = sum_centroid / max(count, 1)
        seed_center = np.asarray(seed_chunk.means[lx, ly, lz], dtype=np.float64)
        outward = seed_center - comp_centroid  # outward from centroid
        if float(np.dot(seed_normal.astype(np.float64), outward)) < 0.0:
            _flip_voxel(frozen_chunks, seed_key)
            seed_normal = -seed_normal
    else:
        if float(np.dot(seed_normal, up_vector)) < 0.0:
            _flip_voxel(frozen_chunks, seed_key)
            seed_normal = -seed_normal

    # --- BFS, flipping neighbours that disagree with current ---
    visited = {best_idx}
    queue = deque([best_idx])
    member_set = set(member_node_ids)
    while queue:
        node_id = queue.popleft()
        cx, cy, cz, lx, ly, lz = voxel_list[node_id]
        current_normal = np.asarray(
            frozen_chunks[(cx, cy, cz)].normals[lx, ly, lz], dtype=np.float32
        )
        gx = cx * C + lx
        gy = cy * C + ly
        gz = cz * C + lz
        for dx, dy, dz in _NEIGHBOUR_OFFSETS:
            other = global_index.get((gx + dx, gy + dy, gz + dz))
            if other is None or other in visited or other not in member_set:
                continue
            visited.add(other)
            ocx, ocy, ocz, olx, oly, olz = voxel_list[other]
            neigh_normal = frozen_chunks[(ocx, ocy, ocz)].normals[olx, oly, olz]
            if float(np.dot(neigh_normal, current_normal)) < 0.0:
                frozen_chunks[(ocx, ocy, ocz)].normals[olx, oly, olz] *= -1.0
            queue.append(other)

    # mean normal after orientation
    acc = np.zeros(3, dtype=np.float64)
    for node_id in member_node_ids:
        cx, cy, cz, lx, ly, lz = voxel_list[node_id]
        acc += frozen_chunks[(cx, cy, cz)].normals[lx, ly, lz]
    mean_normal = (acc / max(len(member_node_ids), 1)).astype(np.float32)
    return used_fallback, mean_normal


# ----- public API -----------------------------------------------------------


def orient_normals(
    frozen_chunks: MutableMapping[ChunkKey, object],
    *,
    up_vector: np.ndarray = None,
    top_k: int = 8,
    voxel_size: float = 1.0,
) -> OrientationResult:
    """Orient normals in `frozen_chunks` in place.

    See module docstring + plans/stateful-hatching-kitten.md §"Normal
    orientation" for the canonical algorithm.

    Args:
        frozen_chunks: dict[(cx, cy, cz), FrozenChunk-like]. Each value must
            have `.normals (C,C,C,3) f32`, `.quality (C,C,C) bool`,
            `.means (C,C,C,3) f32`.
        up_vector: (3,) float32 prior direction. Defaults to +Z.
        top_k: not used by the algorithm itself, retained as a hint for the
            UI; this function returns *all* components sorted by size, the
            caller can slice the first `top_k`.
        voxel_size: world-space voxel edge length; only used for the fallback
            heuristic's "outward-from-centroid" geometry. Default 1.0 is fine
            for unit-scale tests.

    Returns:
        OrientationResult with components sorted by voxel_count desc.
    """
    if up_vector is None:
        up_vector = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    else:
        up_vector = np.asarray(up_vector, dtype=np.float32).reshape(3)

    if not frozen_chunks:
        return OrientationResult(components=[], fallback_components=0)

    C = _infer_chunk_size(frozen_chunks)

    voxel_list, global_index = _collect_quality_voxels(frozen_chunks, C)
    if not voxel_list:
        return OrientationResult(components=[], fallback_components=0)

    _, component_members = _build_components(voxel_list, global_index, C)

    components: list = []
    fallback_count = 0
    for members in component_members:
        used_fallback, mean_normal = _orient_component(
            members,
            voxel_list,
            global_index,
            frozen_chunks,
            C,
            voxel_size,
            up_vector,
        )
        if used_fallback:
            fallback_count += 1
        keys = [voxel_list[node_id] for node_id in members]
        components.append(
            ComponentInfo(
                voxel_count=len(members),
                mean_normal=mean_normal,
                voxel_keys=keys,
            )
        )

    components.sort(key=lambda c: c.voxel_count, reverse=True)
    return OrientationResult(components=components, fallback_components=fallback_count)


def invert_component(
    frozen_chunks: MutableMapping[ChunkKey, object], component: ComponentInfo
) -> None:
    """Flip every normal in `component` in place.

    Used by the Wave-4 UI's per-component invert chips. Does not mutate
    `component` itself — `mean_normal` will become stale; the caller is
    expected to re-derive UI state after toggling.
    """
    for key in component.voxel_keys:
        _flip_voxel(frozen_chunks, key)
