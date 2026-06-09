---
tags: [recolour-mode]
status: current
updated: 2026-06-07
---

# Normal-based Colouring

Shades the [[Intensity Colouring|intensity base RGB]] using per-voxel PCA normals. Implemented in `processing/shading.py`; normals come from [[Voxel Normals and PCA]] and are sign-corrected by `processing/orientation.py`.

## Shaders

| Mode | Formula (sketch) | Use |
|---|---|---|
| `lambertian` | hemispherical ambient (lerp ground/sky by `0.5·(N.z+1)`) + `max(0, N·L)` directional | default structural shading |
| `three_point` | `ambient + key·max(0,N·K) + fill·max(0,N·F) + back·max(0,N·B)` | studio-style lighting |
| `normal_as_color` | `(N+1)·127.5` | debug visualisation of normal directions |

Where `quality == False` (under-supported or non-planar voxel), the shaders pass the base RGB through unchanged.

## Viewpoint-free orientation (the hard part)

PCA gives an *unsigned* normal (a line, not a ray). `orient_normals` recovers a consistent sign **without** a sensor viewpoint:

1. Build a graph of quality voxels; union-find 26-connected **components**.
2. Per component, pick the most-vertical seed; orient it via the `up_vector` prior (or outward-from-centroid if near-horizontal).
3. BFS-propagate the sign, flipping neighbours whose dot product disagrees.

This is **fundamentally heuristic** — multi-component scenes with conflicting orientations may need `--invert-globally` or the GUI per-component toggles (`invert_component`).

## Reuse for classification

The same per-voxel normal + the **verticality** it implies are direct inputs to [[Geometric Features (Weinmann)|geometric features]] — vertical planar voxels → walls, horizontal planar voxels → floors/ceilings. See [[Recommended Approach]].

## Related

- [[Voxel Normals and PCA]] · [[Classification Colouring]] · [[Recolour Roadmap]]
