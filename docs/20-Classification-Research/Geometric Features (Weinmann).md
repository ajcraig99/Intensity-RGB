---
tags: [research/classical]
status: research
updated: 2026-06-07
---

# Geometric Features (Weinmann)

The canonical CPU-only feature set for point-cloud classification, derived from the eigenvalues of a local covariance matrix (Weinmann et al. 2013/2015). **These are exactly the quantities [[Voxel Normals and PCA|the tool already computes per voxel and then discards]].**

## The features

Given covariance eigenvalues `λ1 ≥ λ2 ≥ λ3 ≥ 0` (note: descending convention here; the code produces ascending `λ0 ≤ λ1 ≤ λ2`, so `λ1_here = λ2_code` etc.):

| Feature | Formula | High value means |
|---|---|---|
| Linearity | `(λ1 − λ2) / λ1` | edge / wire / **pipe rim**, 1-D structure |
| Planarity | `(λ2 − λ3) / λ1` | **wall / floor / beam face**, 2-D structure |
| Sphericity | `λ3 / λ1` | clutter / vegetation, 3-D scatter |
| Omnivariance | `(λ1 λ2 λ3)^⅓` | volumetric spread |
| Anisotropy | `(λ1 − λ3) / λ1` | directional structure |
| Eigenentropy | `−Σ λi·ln λi` | disorder of the local shape |
| Change of curvature | `λ3 / (λ1+λ2+λ3)` | surface variation |
| Sum | `λ1 + λ2 + λ3` | local scale |

Plus two non-eigenvalue features that the tool can also produce cheaply:

| Feature | Source | High value means |
|---|---|---|
| **Verticality** | `1 − |n·ẑ|` from the oriented normal | **wall**; low → **floor/ceiling** |
| **Height** | `means.z` + a global Z-histogram | floor vs. ceiling vs. elevated runs |

## Why this is the on-ramp

- These features are **the formula set behind** CloudCompare's "Compute geometric features", the [[Classical Geometric Methods|jakteristics]] library, and the Semantic3D Random-Forest baseline.
- They need **no labels** to compute and **no global neighbourhood** — a local covariance suffices, and the tool already builds one per voxel.
- Adding them is "read off the eigenvalues you already have" — see [[ADR-003 Retain voxel eigenvalues]].

## Discriminative power for plant classes

| Class | Signature |
|---|---|
| Wall | high planarity + high verticality |
| Floor / ceiling | high planarity + low verticality + Z near histogram mode |
| Pipe / cylinder | curved: moderate planarity locally, distinctive across scales; linear along axis |
| Beam / column | planar facets + linear extent + verticality (column) / horizontality (beam) |
| Clutter / equipment | high sphericity / eigenentropy |

## Sources

- Weinmann et al., "Geometric Features and Their Relevance for 3D Point Cloud Classification", KIT — https://publikationen.bibliothek.kit.edu/1000081641/7655183
- Semantic3D RF baseline — https://ar5iv.labs.arxiv.org/html/1704.03847

## Related

- [[Voxel Normals and PCA]] · [[Classical Geometric Methods]] · [[Recommended Approach]] · [[ADR-003 Retain voxel eigenvalues]]
