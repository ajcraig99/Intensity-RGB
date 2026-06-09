---
tags: [reference, research/classical]
status: reference
updated: 2026-06-07
---

# Research — Classical Methods (verbatim)

> Verbatim research-agent output. Synthesized version: [[Classical Geometric Methods]]. See [[90-Reference/README|README]].

---

# Classical / Geometric Point Cloud Classification & Segmentation — CPU-Only, Streaming-Friendly Methods

Research scoped to your Intensity-RGB pipeline: CPU-only, memory-flat, block-at-a-time `.e57` processing on 500M–7B-point unstructured scans, where you *already* compute chunked voxel-resolution PCA normals. Deep-learning methods are deliberately excluded.

The single most important constraint up front: **at billions of points there is no global kNN and no in-RAM KDTree over the whole cloud.** Any method whose accuracy depends on a *consistent* per-point spherical/k-neighborhood that spans your block boundaries either needs a halo/overlap strategy or must be reformulated to run on the voxel grid you already accumulate. This is the axis that separates "easy to integrate" from "research project" below.

---

## 1. Primitive fitting (RANSAC family)

### Efficient RANSAC (Schnabel, Wahl, Klein 2007)
- **What it does:** Detects planes, spheres, cylinders, cones, tori in unorganized clouds via localized random sampling + a lazy score/cost-function with octree-driven local sampling. Robust to heavy noise/outliers; decomposes millions of points in under a minute on a single CPU. Foundational reference.
- **URL:** https://cg.cs.uni-bonn.de/publication/schnabel-2007-efficient ; paper https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1467-8659.2007.01016.x
- **License / availability:** Original reference impl is research-licensed; production implementations live in CGAL (GPL) and an MIT-ish community port (https://github.com/alessandro-gentilini/Efficient-RANSAC-for-Point-Cloud-Shape-Detection).
- **CPU/streaming:** CPU-only by design. *Global by construction* — it builds an octree over the whole input and samples globally to grow shapes that may span the cloud. Per-block use loses large primitives that cross block boundaries.
- **Classifies:** Geometric primitives (and by extension: walls=planes, pipes=cylinders), not semantic classes.

### CGAL Shape Detection (`Shape_detection`)
- **What it does:** Production implementation of *both* Efficient RANSAC *and* a deterministic Region Growing variant. Five primitives: plane, sphere, cylinder, cone, torus. Region growing is slower but deterministic and higher quality.
- **URL:** https://doc.cgal.org/latest/Shape_detection/index.html
- **License:** **GPL** (commercial license available from GeometryFactory). This is a real constraint for a shipped tool.
- **CPU/streaming:** CPU-only, header-only C++ template. Needs all points (and normals) in memory; not block-streaming. C++ binding work required.
- **Integration difficulty into numpy/Python:** High — C++ template instantiation, Eigen/Boost deps, no first-class Python binding, GPL.

### PCL `sample_consensus` + `sac_segmentation`
- **What it does:** SAC framework (RANSAC, MSAC, MLESAC, etc.) over models `SACMODEL_PLANE`, `SACMODEL_SPHERE`, `SACMODEL_CYLINDER`, `SACMODEL_LINE`, normal-constrained variants, etc. Plane is `[nx ny nz d]`; cylinder is axis-point + axis-dir + radius.
- **URL:** https://pointclouds.org/documentation/group__sample__consensus.html
- **License:** **BSD-3** (permissive — friendly for a shipped product).
- **CPU/streaming:** CPU-only. Operates on a `PointCloud<T>` in memory; per-block feasible if you fit within a block, but cross-block primitives are lost. Cylinder fitting needs per-point normals (you have voxel normals).
- **Integration difficulty:** Medium-high — heavy C++ dependency tree (Boost, Eigen, FLANN, VTK). Python bindings (`python-pcl`, `pclpy`) are perennially fragile/stale. You'd likely shell out or vendor a thin binding.

### Open3D `segment_plane` + `cluster_dbscan`
- **What it does:** `segment_plane()` (RANSAC plane: `distance_threshold`, `ransac_n`, `num_iterations` → plane coeffs + inlier indices); iterative plane removal + `cluster_dbscan(eps, min_points)` for Euclidean clustering of the residual. No native cylinder/sphere RANSAC.
- **URL:** https://www.open3d.org/docs/release/python_api/open3d.geometry.PointCloud.html
- **License:** **MIT** (best-in-class for shipping).
- **CPU/streaming:** CPU-only, first-class **NumPy-native Python API** (this is the big advantage). Plane RANSAC is cheap per-block. DBSCAN builds a KDTree over the points handed to it → fine per-block, but cluster IDs won't be consistent across blocks without a stitching pass.
- **Integration difficulty:** **Low** — `pip install open3d`, hand it `np.ndarray`, get indices back. Easiest primitive-fitting on-ramp by far.

**Verdict for your pipeline:** Open3D `segment_plane` (MIT, pure-pip, numpy-native) is the pragmatic RANSAC choice. Run it *per voxel-block* to tag locally-dominant planes; accept that very large planes (a long wall) get fragmented and reconcile by plane-normal/offset clustering in a cheap second pass over per-block plane parameters.

---

## 2. Region growing & curvature/normal segmentation

### PCL `RegionGrowing<PointT, NormalT>`
- **What it does:** Merges neighboring points whose normals agree within a smoothness angle threshold and whose curvature difference is small. Seeds from lowest-curvature (flattest) points. Output = smooth-surface clusters (segmentation, not labeled classes).
- **URL:** https://pointclouds.org/documentation/tutorials/region_growing_segmentation.html
- **License:** BSD-3.
- **CPU/streaming:** CPU-only. Needs per-point normals + curvature + a neighbor graph (kNN). The graph crosses block boundaries — **not natively streaming.** Per-block gives boundary seams.
- **Integration difficulty:** Medium-high (same PCL C++/bindings issue as above).
- **Relevance:** You already compute PCA normals + can derive curvature (`λ3 / (λ1+λ2+λ3)`) per voxel. A *voxel-graph* region-grow (6/26-connected voxels, same smoothness/curvature test) is a clean numpy reimplementation that needs no point-level kNN — this is the streaming-native adaptation.

---

## 3. Feature-based classification (the recommended core)

### Eigenvalue-based geometric features (Weinmann et al. 2013/2015)
- **What it does:** From the 3 covariance eigenvalues (λ1≥λ2≥λ3) of a local neighborhood, derive **linearity** `(λ1−λ2)/λ1`, **planarity** `(λ2−λ3)/λ1`, **sphericity** `λ3/λ1`, **omnivariance** `(λ1λ2λ3)^⅓`, **anisotropy** `(λ1−λ3)/λ1`, **eigenentropy**, **sum of eigenvalues**, **change of curvature** `λ3/Σλ`, plus **verticality** (from the normal/smallest-eigenvector vs. up) and **height** features. These are the canonical discriminators: walls→high planarity+verticality, vegetation→high sphericity, wires/edges→high linearity, ground→high planarity+low verticality.
- **URL:** https://publikationen.bibliothek.kit.edu/1000081641/7655183 (KIT, "Geometric Features and Their Relevance for 3D Point Cloud Classification")
- **License/availability:** The math is public-domain; it's the formula set behind CloudCompare's "Compute geometric features," jakteristics, and the Semantic3D baseline.
- **CPU/streaming:** CPU-only and cheap. **This is exactly what your voxel PCA already produces** — you have the eigen-decomposition per voxel; the features are arithmetic on the eigenvalues plus the normal you already orient. Fully per-voxel, no global neighborhood, memory-flat. This is the highest-leverage finding for you.
- **Integration difficulty:** **Trivial** — add ~15 lines of numpy to `processing/voxel_normals.py` consuming the eigenvalues you already compute.

### jakteristics (Python)
- **What it does:** Computes the 13 Weinmann-style features (eigenvalue sum, omnivariance, eigenentropy, anisotropy, planarity, linearity, PCA1, PCA2, surface variation, sphericity, verticality, normal Nx/Ny/Nz) directly from a NumPy `xyz` array, radius- or k-neighborhood search, multi-threaded.
- **URL:** https://github.com/jakarto3d/jakteristics ; https://jakteristics.readthedocs.io
- **License:** **BSD** (permissive).
- **Dependencies:** Cython + numpy + scipy (BLAS/LAPACK). No heavy C++ stack. Reported ~2× faster than CloudCompare.
- **CPU/streaming:** CPU-only, multi-CPU. Uses per-point radius/KDTree neighborhoods → crosses block boundaries; per-block needs halo overlap to avoid edge artifacts. But it ingests/returns numpy, so it slots cleanly into your I/O.
- **Integration difficulty:** **Low** if used per-point with block halos; **moot** if you instead compute features from your existing voxel PCA (you'd only reach for jakteristics if you want true per-point features at point-density rather than voxel resolution).

### CANUPO (CloudCompare plugin / standalone, Brodu & Lague 2012)
- **What it does:** Multi-scale dimensionality classifier. At each point computes the 1D/2D/3D dimensionality signature across *several radii*, trains binary SVM classifiers from user-painted samples, separates e.g. vegetation vs. rock vs. ground/water in complex natural scenes.
- **URL:** https://nicolas.brodu.net/en/recherche/canupo/ ; wiki https://www.cloudcompare.org/doc/wiki/index.php/CANUPO_(plugin) ; code https://github.com/candrsn/canupo
- **License:** **LGPL v2.1+**.
- **CPU/streaming:** CPU-only. **Multi-scale = needs neighborhoods at multiple radii**, the largest of which (often several meters) far exceeds a sensible block; genuinely multi-scale-global. Hard to stream without large halos.
- **Integration difficulty:** High (C++ plugin; standalone CLI exists but multi-scale neighborhood requirement fights your streaming model). Best used as an *offline labeller* to generate training data, not in-loop.

### 3DMASC (CloudCompare plugin, Letard/Lague et al. 2024)
- **What it does:** **M**ultiple **A**ttributes, **S**cales, **C**louds → computes a rich feature set at multiple scales over one or more clouds, trains a **random forest**, outputs labeled points *with per-point class confidence*. Explainable, GUI + CLI.
- **URL:** https://lidar.univ-rennes.fr/en/3dmasc ; paper https://arxiv.org/abs/2401.09481
- **License:** Ships within CloudCompare (GPL ecosystem).
- **CPU/streaming:** CPU-only; multi-scale → same global-neighborhood caveat as CANUPO. RF inference itself is per-point and trivially streamable once features exist.
- **Integration difficulty:** High as a plugin; but its *design pattern* (multi-scale geometric features → RF + confidence) is the blueprint for what you'd build natively.

---

## 4. Classifier stage — Random Forest / Gradient Boosting (Semantic3D baseline pattern)
- **What it does:** Feed the per-point/per-voxel geometric features (Sec. 3) into a Random Forest (or gradient boosting). The Semantic3D RF baseline uses multi-scale Weinmann features + vertical/cylindrical *height* features (deliberately **no** color/intensity — they found those didn't help and aren't always present). 8 urban classes.
- **URL:** https://ar5iv.labs.arxiv.org/html/1704.03847 (semantic3D.net benchmark paper)
- **Library:** **scikit-learn** `RandomForestClassifier` / `HistGradientBoostingClassifier` (BSD, pure-pip, numpy-native).
- **CPU/streaming:** Training is offline on a labeled subset. **Inference is embarrassingly per-point/per-voxel and perfectly streaming** — load a pickled model once, call `.predict()` on each block's feature matrix. Memory-flat, CPU-only, no neighborhoods needed at inference (the neighborhood info is already baked into the features).
- **Integration difficulty:** **Low.** ~30 lines: features → `model.predict()` → write a per-point class scalar back into your `.e57` block.

---

## 5. Elevation / verticality floor & wall extraction (cheapest semantic win)
- **What it does:** Pure heuristics, no learning. **Verticality** (from your normal vs. up vector) + **height** separate structure: near-vertical planar voxels → **walls**; near-horizontal planar voxels at the low/high modes of a **Z-histogram** → **floor/ceiling**. RANSAC plane fitting refines each; vertical point-distribution histograms locate horizontal structures, line/plane fitting handles walls.
- **URL:** https://files.core.ac.uk/download/pdf/35279765.pdf ("Detection of Walls, Floors and Ceilings in Point Cloud Data")
- **License:** Algorithmic — implement yourself in numpy.
- **CPU/streaming:** **Ideal for streaming.** Verticality + planarity are per-voxel (you already have them). A global Z-histogram is a tiny accumulator updated per block (one pass), then floor/ceiling thresholds applied per block in a second pass — fits your existing two-pass shading architecture exactly.
- **Integration difficulty:** **Trivial to low.** No new dependencies.

---

## Comparison table

| Method / Tool | Classifies | License | Deps (C++ vs Python) | CPU-only | Streaming / per-block feasibility | Integration difficulty |
|---|---|---|---|---|---|---|
| **Eigenvalue geometric features** (Weinmann) | feature vectors (planarity/linearity/sphericity/verticality…) | public (math) | pure numpy | ✓ | **Native per-voxel — you already have the eigenvalues** | **Trivial** |
| **Elevation/verticality floor-wall** | floor / ceiling / wall | public (math) | pure numpy | ✓ | **Native** (per-voxel + 1 global Z-histogram accumulator) | **Trivial–Low** |
| **scikit-learn RF / HistGBM** (Semantic3D pattern) | semantic classes (inference) | BSD-3 | pure python | ✓ | **Inference fully per-block**; training offline | **Low** |
| **jakteristics** | feature vectors | BSD | Cython+scipy | ✓ | per-point, needs block **halo** for radius search | **Low** |
| **Open3D `segment_plane`/DBSCAN** | planes / Euclidean clusters | MIT | C++ w/ numpy Python API | ✓ | per-block plane fits OK; large planes fragment; cluster IDs need stitching | **Low** |
| **PCL `sample_consensus`** | plane/cylinder/sphere/line | BSD-3 | heavy C++ (Boost/Eigen/FLANN/VTK) | ✓ | per-block if shape fits in block | **Med-High** (binding pain) |
| **PCL RegionGrowing** | smooth-surface segments | BSD-3 | heavy C++ | ✓ | needs cross-block kNN graph — **not native** | **Med-High** |
| **CGAL Shape Detection** | plane/sphere/cyl/cone/torus | **GPL** | C++ templates (Eigen/Boost) | ✓ | global octree — **not streaming** | **High** |
| **Efficient RANSAC (orig)** | 5 primitives | research / ports MIT | C++ | ✓ | global by construction | **High** |
| **CANUPO** | binary natural classes (veg/rock/ground…) | **LGPL-2.1+** | C++ plugin/CLI | ✓ | multi-scale → **global-ish**, large halos | **High** (use offline) |
| **3DMASC** | multi-class + confidence (RF) | GPL (CloudCompare) | C++ plugin | ✓ | multi-scale features global; RF inference streamable | **High** (blueprint, not in-loop) |

---

## Recommended classical pipeline (streaming, CPU-only, numpy-native)

Build **on top of the voxel-PCA you already have** rather than introducing a heavy C++ neighborhood library. Everything below is pip-installable and permissively licensed (numpy/scipy/scikit-learn, optionally Open3D-MIT, jakteristics-BSD).

**Pass A — voxel feature accumulation (extends your existing `voxel_normals.py`):**
For each voxel you already get covariance eigenvalues λ1≥λ2≥λ3 and an oriented normal. Emit per voxel:
- planarity `(λ2−λ3)/λ1`, linearity `(λ1−λ2)/λ1`, sphericity `λ3/λ1`, omnivariance, anisotropy, change-of-curvature `λ3/Σλ`
- verticality `1 − |n·ẑ|` (or `|n·ẑ|`), and the voxel's mean/centroid Z
- Simultaneously update **one global accumulator**: a coarse Z-histogram (cheap, bounded memory) for floor/ceiling mode detection.

**Pass B — labeling (per block, second streaming pass — mirrors your two-pass shading):**

1. **Rule-based structural layer (no training, ship immediately):**
   - planar + vertical → **wall**
   - planar + horizontal + Z near histogram low mode → **floor**; near high mode → **ceiling**
   - high linearity → **edge/wire/pole**; high sphericity → **vegetation/clutter**
   This alone gives floor/wall/ceiling/clutter on billion-point scans with zero new dependencies.

2. **Optional ML layer (when rules aren't enough):** train a **scikit-learn RandomForest** (or `HistGradientBoostingClassifier`) offline on a labeled sample using the Pass-A feature vectors (the Semantic3D recipe — geometry only, no color/intensity needed). At runtime, `model.predict()` per block — fully streaming, memory-flat. Write the class as a new per-point scalar into the output `.e57`.

**Optional refinement (per block, only if needed):**
- **Open3D `segment_plane`** per block to get clean plane instances (wall/floor IDs) and crisp inlier sets; reconcile plane parameters across blocks in a light post-pass.
- A **voxel-graph region-grow** (26-connected, your existing normals + curvature, numpy) to turn per-voxel labels into connected surface instances without any point-level kNN.

**What to deliberately avoid in-loop:** CGAL (GPL + global octree), PCL bindings (dependency/maintenance tax), and multi-scale CANUPO/3DMASC (their large-radius neighborhoods fight your block model). Use CANUPO/3DMASC, if at all, *offline* to help label training data for your scikit-learn stage.

The key insight: your chunked voxel PCA is already 90% of a Weinmann/Semantic3D feature extractor. The classification capability is mostly a matter of *reading off* features you're already computing and bolting on a pickled scikit-learn model — staying entirely within CPU, numpy, and your existing two-pass streaming architecture.

### Sources
- Efficient RANSAC: https://cg.cs.uni-bonn.de/publication/schnabel-2007-efficient
- CGAL Shape Detection: https://doc.cgal.org/latest/Shape_detection/index.html
- PCL sample_consensus: https://pointclouds.org/documentation/group__sample__consensus.html
- PCL RegionGrowing: https://pointclouds.org/documentation/tutorials/region_growing_segmentation.html
- Open3D PointCloud (segment_plane / DBSCAN): https://www.open3d.org/docs/release/python_api/open3d.geometry.PointCloud.html
- Weinmann geometric features (KIT): https://publikationen.bibliothek.kit.edu/1000081641/7655183
- jakteristics: https://github.com/jakarto3d/jakteristics
- CANUPO (Brodu & Lague): https://nicolas.brodu.net/en/recherche/canupo/ and https://www.cloudcompare.org/doc/wiki/index.php/CANUPO_(plugin)
- 3DMASC: https://lidar.univ-rennes.fr/en/3dmasc and https://arxiv.org/abs/2401.09481
- Semantic3D RF baseline: https://ar5iv.labs.arxiv.org/html/1704.03847
- Floor/wall/ceiling detection: https://files.core.ac.uk/download/pdf/35279765.pdf
