---
tags: [research/classical]
status: research
updated: 2026-06-07
---

# Classical Geometric Methods

Non-deep-learning methods that run **CPU-only** and can work block-at-a-time. This is the family the [[Recommended Approach]] is built from. Full source report: [[Research — Classical Methods]].

## 1. Primitive fitting (RANSAC family)

| Tool | Primitives | Licence | CPU/streaming | Integration |
|---|---|---|---|---|
| **Efficient RANSAC** (Schnabel 2007) | plane, sphere, cylinder, cone, torus | research; MIT-ish ports | CPU; **global octree** by construction | high |
| **CGAL Shape_detection** | 5 primitives (+ region-growing variant) | **GPL** / commercial | CPU; needs all points in RAM | high (C++ templates) |
| **PCL `sample_consensus`** | plane/cylinder/sphere/line | **BSD-3** | CPU; per-block if shape fits in block | med-high (heavy C++, fragile py bindings) |
| **Open3D `segment_plane` + `cluster_dbscan`** | plane RANSAC + Euclidean clusters | **MIT** | CPU; **numpy-native python API** | **low** (`pip install open3d`) |

> [!note] Best pragmatic primitive tool
> **Open3D** (`segment_plane`, MIT, numpy-native) is the easiest on-ramp for plane RANSAC. It has no native cylinder RANSAC — for pipes you'd add cylinder fitting (PCL model, or fit on region-grown curved segments). Large planes fragment per-block and need a cheap reconciliation pass on plane parameters.

## 2. Region growing & curvature segmentation

- **PCL `RegionGrowing`** (BSD-3) merges neighbours by normal-angle + curvature. Needs a cross-block kNN graph → **not natively streaming**.
- **Streaming-native adaptation:** a **voxel-graph** region grow (6/26-connected voxels, same smoothness/curvature test) on the tool's existing voxel normals — pure numpy, no point-level kNN. This is the recommended form.

## 3. Feature-based classification (the recommended core)

- **Eigenvalue geometric features** (Weinmann) — see [[Geometric Features (Weinmann)]]. Trivial to add; the tool already computes the eigenvalues.
- **jakteristics** (BSD, Cython) — computes the 13 Weinmann features from a numpy `xyz` array. Per-point radius search → needs block **halos**; or skip it and read features off the voxel PCA.
- **CANUPO** (LGPL) & **3DMASC** (GPL, CloudCompare) — multi-scale dimensionality + Random Forest. Their large multi-scale neighbourhoods fight the streaming model → use **offline** to help label training data, not in-loop.

## 4. Classifier stage — Random Forest / Gradient Boosting

- **scikit-learn** `RandomForestClassifier` / `HistGradientBoostingClassifier` (BSD, pure-pip). Training is offline; **inference is embarrassingly per-block and perfectly streaming** — load a pickled model once, call `.predict()` on each block's feature matrix. This is the Semantic3D baseline recipe (geometry only; colour/intensity optional).

## 5. Elevation / verticality floor & wall extraction (cheapest win)

Pure heuristics, no learning: verticality + a global Z-histogram separate **walls** (vertical planar), **floors/ceilings** (horizontal planar at Z modes). Fits the existing two-pass architecture exactly (the Z-histogram is a tiny Pass-1 accumulator).

## What to avoid in-loop

CGAL (GPL + global octree), PCL python bindings (dependency/maintenance tax), multi-scale CANUPO/3DMASC (global neighbourhoods).

## Sources

PCL `sample_consensus` https://pointclouds.org/documentation/group__sample__consensus.html · Open3D https://www.open3d.org/docs/release/python_api/open3d.geometry.PointCloud.html · jakteristics https://github.com/jakarto3d/jakteristics · CANUPO https://nicolas.brodu.net/en/recherche/canupo/ · 3DMASC https://arxiv.org/abs/2401.09481 · Efficient RANSAC https://cg.cs.uni-bonn.de/publication/schnabel-2007-efficient

## Related

- [[Geometric Features (Weinmann)]] · [[Method Comparison]] · [[Recommended Approach]] · [[Research — Classical Methods]]
