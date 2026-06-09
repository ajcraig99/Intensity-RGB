---
tags: [project]
status: current
updated: 2026-06-07
---

# Constraints and Scale

These constraints are non-negotiable and **filter every classification option** in [[Classification MOC|the research]]. Any method that violates them is off-spec for the core tool.

## Hard constraints

| Constraint | Detail |
|---|---|
| **CPU-only** | No GPU is assumed at runtime. Rules out in-loop deep-learning inference (see [[Deep Learning Methods]]). |
| **Memory-flat** | RAM bounded by `block_size` + the voxel grid, **not** total point count. |
| **Streaming** | The cloud is read/written block-at-a-time; it is **never** fully resident. |
| **No global kNN** | At 500M–7B points there is no in-RAM KDTree over the whole cloud. Any per-point neighbourhood that must be *consistent across block boundaries* needs a halo strategy or a voxel-grid reformulation. |

## Data scale

Typical scans are **500 million to 7 billion points**, unstructured `.e57`. This is the assumption behind block-streaming I/O and the [[Voxel Normals and PCA|voxel accumulator]].

> [!tip] The voxel grid is the escape hatch
> Because the tool already aggregates points into a voxel grid in [[Streaming IO Model|Pass 1]], "no global kNN" stops being a blocker: per-voxel neighbourhoods (6/26-connected) give a consistent, bounded-memory substitute for point-level kNN. This is why the [[Recommended Approach|recommended path]] computes features **per voxel**, not per point.

## What these constraints imply for classification

1. **Feature extraction must be per-voxel or per-block-with-halo**, never global. ✅ The voxel PCA already satisfies this.
2. **Classifier inference must be per-block and stateless** (e.g. a pickled scikit-learn model called on each block's feature matrix). ✅
3. **Training is offline and out-of-band** — it does not happen in the streaming tool.
4. **Deep-learning inference, if ever added, is an optional offline GPU pass**, separate from the streaming core. See [[ADR-002 Defer deep learning to GPU track]].

## Related

- [[Voxel Normals and PCA]] · [[Recommended Approach]] · [[Method Comparison]] · [[Architecture]]
