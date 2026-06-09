---
tags: [decision]
status: decision
updated: 2026-06-07
---

# ADR-003 — Retain voxel eigenvalues in FrozenChunk

## Status
**Accepted** (2026-06-07) — proposed change, the keystone of [[Classification Roadmap|P0]].

## Context
`processing/voxel_normals.py:finalize_chunk` runs `np.linalg.eigh` on each voxel's covariance, uses `λ0` and `λ1` to derive `planarity`, takes `eigvecs[:,0]` as the normal — then returns a [[Voxel Normals and PCA|FrozenChunk]] holding only `normals`, `quality`, `means`. **All three eigenvalues are discarded** (`λ2` isn't even read). Those eigenvalues are the exact input to the [[Geometric Features (Weinmann)|Weinmann feature set]] that the [[Recommended Approach|classical classifier]] needs.

## Decision
Persist `FrozenChunk.eigvals (C,C,C,3) float32` alongside `normals`/`quality`/`means`. Compute the geometric feature vector from these retained eigenvalues (plus the oriented normal for verticality and `means.z` for height) — **no extra pass, no extra eigendecomposition**.

## Consequences
- **Positive:** unlocks the whole feature-based classifier for ~15 lines + one array; computed in the pass that already exists; memory cost is `+3 float32 per voxel` (modest vs. the existing `3+1+3` floats/bools).
- **Negative / cost:** small RAM increase in the frozen grid — must be reflected in the [[Constraints and Scale|capability RAM upper-bound formula]] in `capability.py`.
- **Revisit when:** never expected to reverse; if memory becomes tight, eigenvalues could be quantised or features computed-then-discarded in Pass 1.

## Related
[[Voxel Normals and PCA]] · [[Geometric Features (Weinmann)]] · [[Recommended Approach]] · [[Classification Roadmap]]
