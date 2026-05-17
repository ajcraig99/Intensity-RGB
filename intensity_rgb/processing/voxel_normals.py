"""Chunked dense voxel accumulator + compact-then-eigh PCA normals.

Streaming-friendly normal estimation for unstructured point clouds.

Design reference: stateful-hatching-kitten.md, section "Voxel accumulator
design". The accumulator stores 10 float64 moments per voxel
``(count, sum_x, sum_y, sum_z, sum_xx, sum_xy, sum_xz, sum_yy, sum_yz, sum_zz)``
inside lazily allocated ``(C, C, C, 10)`` chunks keyed by ``(cx, cy, cz)``.

Pass 1: caller streams point blocks into :meth:`VoxelAccumulator.add_block`.
Pass 2: caller invokes :meth:`VoxelAccumulator.finalize`, which dilates
under-supported voxels from their 26-connected neighbours, runs
:func:`finalize_chunk` per chunk (compact-then-eigh: ``np.linalg.eigh`` only
sees the ``(M, 3, 3)`` stack of valid voxels), and returns a dict of
:class:`FrozenChunk` (float32 normals + bool quality + float32 means).

A subsequent Pass 2 over the cloud can look up the per-point normal +
quality flag through :func:`lookup_normals`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Defaults (also settable per-instance via VoxelAccumulator's ctor).
CHUNK = 32
MIN_SUPPORT = 8
PLANARITY_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FrozenChunk:
    """Per-chunk Pass-2 lookup table.

    Attributes
    ----------
    normals
        ``(C, C, C, 3)`` float32. Smallest-eigenvalue eigenvector of the
        per-voxel covariance. Zeros for voxels that didn't pass the
        min-support / planarity gate.
    quality
        ``(C, C, C)`` bool. True iff the voxel had >= ``min_support``
        points (post-dilation) AND its planarity score met the threshold.
    means
        ``(C, C, C, 3)`` float32. Centroid of points falling in the
        voxel. Zeros where ``quality`` is False.
    """

    normals: np.ndarray
    quality: np.ndarray
    means: np.ndarray


# ---------------------------------------------------------------------------
# Pass-1 accumulator
# ---------------------------------------------------------------------------


class VoxelAccumulator:
    """Chunked dense moments accumulator.

    Parameters
    ----------
    origin
        ``(3,)`` float64 anchor (the AABB-min). Caller is responsible for
        choosing it — typically the file-level cartesianBounds min.
    voxel_size
        Edge length of a single voxel, in scene units (metres).
    chunk
        Voxels per chunk axis. Default 32, so each chunk is a
        ``(32, 32, 32, 10)`` float64 = 2.62 MB block.
    min_support
        Minimum point count per voxel for normal estimation.
    planarity_threshold
        Minimum planarity score ``1 - lambda0 / lambda1`` for the voxel
        to be marked ``quality=True``.
    """

    def __init__(
        self,
        origin: np.ndarray,
        voxel_size: float,
        chunk: int = CHUNK,
        min_support: int = MIN_SUPPORT,
        planarity_threshold: float = PLANARITY_THRESHOLD,
    ) -> None:
        origin = np.asarray(origin, dtype=np.float64).reshape(3)
        if voxel_size <= 0:
            raise ValueError("voxel_size must be positive")
        if chunk <= 0:
            raise ValueError("chunk must be positive")
        self.origin = origin
        self.voxel_size = float(voxel_size)
        self.chunk = int(chunk)
        self.min_support = int(min_support)
        self.planarity_threshold = float(planarity_threshold)
        # Lazily allocated chunk dict.
        self.moments: dict[tuple[int, int, int], np.ndarray] = {}

    # ------------------------------------------------------------------
    # Pass 1
    # ------------------------------------------------------------------

    def add_block(self, xyz: np.ndarray) -> None:
        """Accumulate moments from a streaming block of points.

        Parameters
        ----------
        xyz
            ``(B, 3)`` array of XYZ coordinates. Will be coerced to
            float64. Empty arrays are a no-op.
        """
        xyz = np.asarray(xyz, dtype=np.float64)
        if xyz.size == 0:
            return
        if xyz.ndim != 2 or xyz.shape[1] != 3:
            raise ValueError(f"xyz must be (B, 3); got {xyz.shape}")

        C = self.chunk
        # (B, 3) int32 voxel index (can be negative if points are below
        # the origin — np.divmod handles negatives consistently).
        voxel_xyz = np.floor((xyz - self.origin) / self.voxel_size).astype(np.int64)
        chunk_xyz, local_xyz = np.divmod(voxel_xyz, C)
        # local_xyz is in [0, C) regardless of sign.

        # Group by chunk via a packed int64 key. Offset by a large value
        # so negative chunk coords still encode uniquely under shift.
        SHIFT = 1 << 20  # supports |chunk| up to ~1M -> AABB ~16 Mvox/axis
        packed = (
            (chunk_xyz[:, 0] + SHIFT) * (1 << 42)
            + (chunk_xyz[:, 1] + SHIFT) * (1 << 21)
            + (chunk_xyz[:, 2] + SHIFT)
        )

        # Per-point contributions to the 10 moments. Built once per
        # block, then scattered per-chunk.
        B = xyz.shape[0]
        contrib = np.empty((B, 10), dtype=np.float64)
        contrib[:, 0] = 1.0
        contrib[:, 1:4] = xyz
        contrib[:, 4] = xyz[:, 0] * xyz[:, 0]  # xx
        contrib[:, 5] = xyz[:, 0] * xyz[:, 1]  # xy
        contrib[:, 6] = xyz[:, 0] * xyz[:, 2]  # xz
        contrib[:, 7] = xyz[:, 1] * xyz[:, 1]  # yy
        contrib[:, 8] = xyz[:, 1] * xyz[:, 2]  # yz
        contrib[:, 9] = xyz[:, 2] * xyz[:, 2]  # zz

        # Flat-local index inside a chunk: 0 .. C^3 - 1.
        flat_local = (
            local_xyz[:, 0] * (C * C) + local_xyz[:, 1] * C + local_xyz[:, 2]
        ).astype(np.intp)

        # Unique chunk keys + inverse for vectorised grouping.
        uniq_keys, inverse = np.unique(packed, return_inverse=True)
        # Sort points by their chunk-group so we can slice each group
        # by a single contiguous range.
        order = np.argsort(inverse, kind="stable")
        sorted_inv = inverse[order]
        # Boundaries of each unique chunk group inside the sorted order.
        boundaries = np.searchsorted(
            sorted_inv, np.arange(uniq_keys.size + 1)
        )
        # Per-group lookup table for the chunk_xyz that owns it.
        group_chunk_xyz = chunk_xyz[order[boundaries[:-1]]]

        sorted_flat_local = flat_local[order]
        sorted_contrib = contrib[order]

        for gi in range(uniq_keys.size):
            start = boundaries[gi]
            end = boundaries[gi + 1]
            if start == end:
                continue
            cx, cy, cz = (int(v) for v in group_chunk_xyz[gi])
            key = (cx, cy, cz)
            chunk_arr = self.moments.get(key)
            if chunk_arr is None:
                chunk_arr = np.zeros((C, C, C, 10), dtype=np.float64)
                self.moments[key] = chunk_arr
            chunk_flat = chunk_arr.reshape(-1, 10)
            np.add.at(
                chunk_flat,
                sorted_flat_local[start:end],
                sorted_contrib[start:end],
            )

    # ------------------------------------------------------------------
    # Pass 2 (compact-then-eigh)
    # ------------------------------------------------------------------

    def finalize(self) -> dict[tuple[int, int, int], FrozenChunk]:
        """Run dilation + eigh per chunk and return frozen lookup tables.

        Frees ``self.moments`` after producing the frozen dict, so peak
        RAM at the Pass-1 → Pass-2 boundary is bounded by the frozen
        chunks (~ 1/8 the float64 moments).
        """
        if not self.moments:
            return {}

        self._dilate_under_supported()

        frozen: dict[tuple[int, int, int], FrozenChunk] = {}
        for key, chunk_arr in self.moments.items():
            fc = finalize_chunk(
                chunk_arr,
                min_support=self.min_support,
                planarity_threshold=self.planarity_threshold,
            )
            if fc is not None:
                frozen[key] = fc
        # Drop the moments dict to recover memory.
        self.moments = {}
        return frozen

    # ------------------------------------------------------------------
    # 26-connected neighbour dilation (operates on the live moments dict)
    # ------------------------------------------------------------------

    def _dilate_under_supported(self) -> None:
        """Pull moments from 26-connected neighbours into under-supported voxels.

        Iterates each chunk's under-supported voxels (n < min_support but
        n > 0 — purely-empty voxels are left alone), sums in the moments
        of their 26 neighbours (which may live in adjacent chunks), and
        writes the result back. Implemented as a single-shot fallback
        (no iteration) per the design.
        """
        if not self.moments:
            return

        C = self.chunk
        min_support = self.min_support

        # Build a snapshot of chunk arrays at start — we never want to
        # pull dilated values from neighbours mid-pass (would compound).
        # The snapshot is a shallow copy of the dict + ndarray views.
        snapshot = {k: v.copy() for k, v in self.moments.items()}

        # Pre-build the 26 offsets.
        offsets = np.array(
            [
                (dx, dy, dz)
                for dx in (-1, 0, 1)
                for dy in (-1, 0, 1)
                for dz in (-1, 0, 1)
                if not (dx == 0 and dy == 0 and dz == 0)
            ],
            dtype=np.int64,
        )

        for key, chunk_arr in self.moments.items():
            flat = chunk_arr.reshape(-1, 10)
            n = flat[:, 0]
            need = np.flatnonzero((n > 0) & (n < min_support))
            if need.size == 0:
                continue

            # Decompose flat indices back to (lx, ly, lz).
            lx = need // (C * C)
            rem = need % (C * C)
            ly = rem // C
            lz = rem % C
            local_xyz = np.stack([lx, ly, lz], axis=1).astype(np.int64)

            cx, cy, cz = key
            chunk_origin = np.array([cx, cy, cz], dtype=np.int64) * C
            world_voxel = chunk_origin + local_xyz  # (N, 3)

            accum = np.zeros((need.size, 10), dtype=np.float64)
            # Keep the under-supported voxel's own moments in the sum,
            # so a borderline voxel that's already n=5 gets to combine
            # with neighbours rather than be replaced by them.
            accum += flat[need]

            for ox, oy, oz in offsets:
                neighbour_world = world_voxel + np.array(
                    [ox, oy, oz], dtype=np.int64
                )
                n_chunk = neighbour_world // C
                n_local = neighbour_world - n_chunk * C  # always in [0, C)
                # Group by neighbour chunk key.
                # np.unique on packed int64 keys.
                SHIFT = 1 << 20
                packed = (
                    (n_chunk[:, 0] + SHIFT) * (1 << 42)
                    + (n_chunk[:, 1] + SHIFT) * (1 << 21)
                    + (n_chunk[:, 2] + SHIFT)
                )
                uniq, inverse = np.unique(packed, return_inverse=True)
                # Build a small map: which rows in `need` map to which
                # neighbour chunk.
                for gi in range(uniq.size):
                    rows = np.flatnonzero(inverse == gi)
                    if rows.size == 0:
                        continue
                    n_key = (
                        int(n_chunk[rows[0], 0]),
                        int(n_chunk[rows[0], 1]),
                        int(n_chunk[rows[0], 2]),
                    )
                    n_arr = snapshot.get(n_key)
                    if n_arr is None:
                        continue
                    n_flat_view = n_arr.reshape(-1, 10)
                    nl = n_local[rows]
                    flat_local_idx = (
                        nl[:, 0] * (C * C) + nl[:, 1] * C + nl[:, 2]
                    ).astype(np.intp)
                    accum[rows] += n_flat_view[flat_local_idx]

            # Write back. After this, `need` voxels carry their original
            # moments + 26-neighbour moments; finalize_chunk will then
            # decide if they meet min_support.
            flat[need] = accum


# ---------------------------------------------------------------------------
# Per-chunk finalisation (pure function — easy to unit-test)
# ---------------------------------------------------------------------------


def finalize_chunk(
    chunk: np.ndarray,
    min_support: int = MIN_SUPPORT,
    planarity_threshold: float = PLANARITY_THRESHOLD,
) -> FrozenChunk | None:
    """Compact-then-eigh finaliser for one ``(C, C, C, 10)`` chunk.

    Returns ``None`` if no voxel in the chunk passes ``min_support``.
    Otherwise returns a :class:`FrozenChunk` with float32 normals + bool
    quality + float32 means.

    NaN-safe by construction: ``np.linalg.eigh`` only sees the
    ``(M, 3, 3)`` stack of valid voxels, never empty cells.
    """
    if chunk.ndim != 4 or chunk.shape[3] != 10:
        raise ValueError(f"chunk must be (C, C, C, 10); got {chunk.shape}")
    if chunk.shape[0] != chunk.shape[1] or chunk.shape[0] != chunk.shape[2]:
        raise ValueError("chunk must be cubic")

    C = chunk.shape[0]
    flat = chunk.reshape(-1, 10)
    n = flat[:, 0]
    valid_idx = np.flatnonzero(n >= min_support)

    if valid_idx.size == 0:
        return None

    valid = flat[valid_idx]
    inv_n = 1.0 / valid[:, 0]
    means = valid[:, 1:4] * inv_n[:, None]  # (M, 3)

    # Build (M, 3, 3) symmetric second-moment matrix divided by n.
    sxx = valid[:, 4] * inv_n
    sxy = valid[:, 5] * inv_n
    sxz = valid[:, 6] * inv_n
    syy = valid[:, 7] * inv_n
    syz = valid[:, 8] * inv_n
    szz = valid[:, 9] * inv_n
    M = valid_idx.size
    second = np.empty((M, 3, 3), dtype=np.float64)
    second[:, 0, 0] = sxx
    second[:, 0, 1] = sxy
    second[:, 0, 2] = sxz
    second[:, 1, 0] = sxy
    second[:, 1, 1] = syy
    second[:, 1, 2] = syz
    second[:, 2, 0] = sxz
    second[:, 2, 1] = syz
    second[:, 2, 2] = szz

    # cov = second - outer(means, means)
    cov = second - np.einsum("mi,mj->mij", means, means)

    # Symmetrise to defend against tiny float drift before eigh.
    cov = 0.5 * (cov + cov.transpose(0, 2, 1))

    eigvals, eigvecs = np.linalg.eigh(cov)  # ascending eigenvalues
    # Smallest eigenvalue -> normal direction.
    normals_valid = eigvecs[..., 0]  # (M, 3)

    # Planarity = 1 - lambda0 / lambda1; large eigvec1 => more planar.
    lam0 = eigvals[..., 0]
    lam1 = eigvals[..., 1]
    planarity = 1.0 - lam0 / np.maximum(lam1, 1e-12)
    quality_valid = planarity >= planarity_threshold

    total = C * C * C
    out_normals = np.zeros((total, 3), dtype=np.float32)
    out_quality = np.zeros(total, dtype=bool)
    out_means = np.zeros((total, 3), dtype=np.float32)

    # Only scatter normals where quality is True. This keeps zeroed-out
    # cells distinguishable from real-but-noisy normals in downstream
    # lookups.
    quality_idx = valid_idx[quality_valid]
    out_normals[quality_idx] = normals_valid[quality_valid].astype(np.float32)
    out_quality[quality_idx] = True
    out_means[valid_idx] = means.astype(np.float32)

    return FrozenChunk(
        normals=out_normals.reshape(C, C, C, 3),
        quality=out_quality.reshape(C, C, C),
        means=out_means.reshape(C, C, C, 3),
    )


# ---------------------------------------------------------------------------
# Pass-2 lookup helper
# ---------------------------------------------------------------------------


def lookup_normals(
    frozen: dict[tuple[int, int, int], FrozenChunk],
    origin: np.ndarray,
    voxel_size: float,
    chunk_size: int,
    xyz: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return per-point normal + quality flag from a frozen chunk dict.

    Vectorised on the chunk-key dimension via :func:`np.unique`.

    Parameters
    ----------
    frozen
        Output of :meth:`VoxelAccumulator.finalize`.
    origin
        ``(3,)`` AABB-min anchor (must match the accumulator's).
    voxel_size
        Voxel edge length (must match the accumulator's).
    chunk_size
        Voxels per chunk axis (must match the accumulator's).
    xyz
        ``(N, 3)`` query points.

    Returns
    -------
    normals
        ``(N, 3)`` float32. Zeros where the chunk isn't frozen or the
        voxel's quality flag is False.
    quality
        ``(N,)`` bool. True iff the point lies in a frozen chunk and the
        voxel's quality flag is True.
    """
    xyz = np.asarray(xyz, dtype=np.float64)
    if xyz.size == 0:
        return (
            np.zeros((0, 3), dtype=np.float32),
            np.zeros((0,), dtype=bool),
        )
    if xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError(f"xyz must be (N, 3); got {xyz.shape}")

    origin = np.asarray(origin, dtype=np.float64).reshape(3)
    C = int(chunk_size)
    N = xyz.shape[0]

    voxel_xyz = np.floor((xyz - origin) / float(voxel_size)).astype(np.int64)
    chunk_xyz, local_xyz = np.divmod(voxel_xyz, C)

    normals = np.zeros((N, 3), dtype=np.float32)
    quality = np.zeros(N, dtype=bool)

    if not frozen:
        return normals, quality

    SHIFT = 1 << 20
    packed = (
        (chunk_xyz[:, 0] + SHIFT) * (1 << 42)
        + (chunk_xyz[:, 1] + SHIFT) * (1 << 21)
        + (chunk_xyz[:, 2] + SHIFT)
    )
    uniq, inverse = np.unique(packed, return_inverse=True)
    order = np.argsort(inverse, kind="stable")
    sorted_inv = inverse[order]
    boundaries = np.searchsorted(sorted_inv, np.arange(uniq.size + 1))
    group_chunk_xyz = chunk_xyz[order[boundaries[:-1]]]

    sorted_local = local_xyz[order]

    for gi in range(uniq.size):
        start = boundaries[gi]
        end = boundaries[gi + 1]
        if start == end:
            continue
        cx, cy, cz = (int(v) for v in group_chunk_xyz[gi])
        fc = frozen.get((cx, cy, cz))
        rows = order[start:end]
        if fc is None:
            continue
        nl = sorted_local[start:end]
        nflat = fc.normals.reshape(-1, 3)
        qflat = fc.quality.reshape(-1)
        flat_idx = (
            nl[:, 0] * (C * C) + nl[:, 1] * C + nl[:, 2]
        ).astype(np.intp)
        normals[rows] = nflat[flat_idx]
        quality[rows] = qflat[flat_idx]

    return normals, quality
