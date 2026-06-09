---
tags: [research]
status: research
updated: 2026-06-07
---

# Method Comparison (master scorecard)

One table to filter every method against the [[Constraints and Scale|hard constraints]]. ✅ = satisfies, ⚠️ = with caveats, ❌ = violates.

| Method / family | Classifies | Licence | CPU-only | Streaming | Needs labels | Integration | Verdict |
|---|---|---|---|---|---|---|---|
| **Eigenvalue features** ([[Geometric Features (Weinmann)]]) | feature vectors | public math | ✅ | ✅ native per-voxel | ❌ | **trivial** (read off existing eigvals) | ★ foundation |
| **Elevation/verticality rules** | floor/ceiling/wall | public math | ✅ | ✅ (+1 global Z-hist) | ❌ | trivial–low | ★ ship first |
| **scikit-learn RF / HistGBM** | semantic classes | BSD-3 | ✅ | ✅ inference per-block | ✅ (small) | low | ★ core classifier |
| **jakteristics** | feature vectors | BSD | ✅ | ⚠️ block halo | ❌ | low | optional (point-density features) |
| **Open3D `segment_plane`/DBSCAN** | planes/clusters | MIT | ✅ | ⚠️ large planes fragment | ❌ | low | optional refinement |
| **PCL `sample_consensus`** | plane/cyl/sphere | BSD-3 | ✅ | ⚠️ shape must fit block | ❌ | med-high | cylinder fitting (pipes) |
| **PCL RegionGrowing** | smooth segments | BSD-3 | ✅ | ❌ cross-block kNN | ❌ | med-high | reimplement as voxel-graph |
| **CGAL Shape_detection** | 5 primitives | **GPL** | ✅ | ❌ global octree | ❌ | high | avoid (licence + global) |
| **Efficient RANSAC** (orig) | 5 primitives | research/MIT ports | ✅ | ❌ global | ❌ | high | concept only |
| **CANUPO / 3DMASC** | multi-class +RF | LGPL / GPL | ✅ | ⚠️ multi-scale global | ✅ | high | **offline** labelling aid |
| **PointNet++ / CLOI-NET / ResPointNet++** | all incl. valve/pump | MIT | ❌ GPU | ❌ >10⁶/pass | ✅ | high | future GPU track |
| **KPConv / KP-FCNN (Noichl)** | 14 plant classes | MIT | ❌ GPU | ❌ tiled GPU | ✅ (synthetic) | high | future GPU track |
| **RandLA-Net** | generic + plant | ⚠️ NC official / MIT reimpl | ❌ GPU | ⚠️ ~10⁶ tiles | ✅ | high | future GPU track |
| **SuperPoint Transformer** | generic | MIT | ❌ (GPU-first) | ⚠️ best tiling | ✅ | high | future GPU track (best scale) |

## Reading the table

- The ★ rows are the [[Recommended Approach]]: features → rules → RF, all CPU-only / streaming / mostly label-free, all building on the [[Voxel Normals and PCA|voxel PCA]].
- Everything GPU lands in [[ADR-002 Defer deep learning to GPU track|the deferred DL track]].
- The only thing primitive fitting + RF **cannot** do is the fine classes (valve/pump/flange) — those wait for the DL track or rule-based pipe-graph heuristics ([[Plant and Piping Methods]]).

## Related

- [[Classification MOC]] · [[Classical Geometric Methods]] · [[Deep Learning Methods]] · [[Recommended Approach]]
