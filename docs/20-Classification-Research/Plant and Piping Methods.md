---
tags: [research/plant]
status: research
updated: 2026-06-07
---

# Plant and Piping Methods

Methods purpose-built for **industrial plant / piping** scan-to-BIM. Full source report: [[Research — Plant and Piping]].

## Deep-learning methods (domain-specific)

| Method | Year | Backbone | Classes | Accuracy | GPU |
|---|---|---|---|---|---|
| **CLOI-NET** (Agapaki & Brilakis) | 2020 | enhanced PointNet++ + geometric post | pipe, elbow, channel, I-beam, angle, CHS, flange, valve, conduit, solid bar (10) | ~82% mean class acc | yes |
| **ResPointNet++** (Yin et al.) | 2021 | residual PointNet++ | pipes, pumps, tanks, I-beams, rect beams (5) | OA 94%, mIoU 87% | yes |
| **SE-PseudoGrid** (Yin et al.) | 2022 | squeeze-excite local aggregation | tee/elbow/flange/reducer/pipe/valve | **OA 96.3%** | yes; code OSS |
| **Scan2BIM-NET** (Perez-Perez et al.) | — | CNN+RNN ensemble | beam, ceiling, column, floor, pipe, wall (6) | — | yes |
| **Noichl & Borrmann** (TUM) | 2024 | KP-FCNN (KPConv) | 14 plant classes incl. pipe fitting, duct, cable routing, tank, bracing | synthetic raised mean F1 ~27% | yes |

**Takeaway:** the best plant accuracy comes from GPU deep learning trained on labelled (often **synthetic-from-IFC**) data. None of it satisfies [[Constraints and Scale|CPU-only streaming]] — they belong to the [[Deep Learning Methods|future GPU track]].

## Geometric pipe / cylinder extraction (CPU-friendly)

| Technique | Idea | Notes |
|---|---|---|
| **Efficient RANSAC cylinder** (Schnabel) | minimal-sample cylinder fit; axis = cross of two sampled normals | label-free, octree-local → streaming-friendly per tile |
| **Region growing on normals/curvature** | grow smooth/curved segments → pipe candidates | chunkable; RANSAC pre-segmenter |
| **Hough / Gaussian-sphere axis clustering** | cluster axis directions, then circle-Hough | keep accumulator **per-tile** (global is memory-heavy) |
| **Skeleton / centerline (Laplacian contraction)** | contract → longest path → circle fit → spline | run **per isolated pipe instance** only |
| **DeepPipes** (Yu 2020) | CNN part detection + model fitting + graph | F1 0.92; GPU |

**Recurring pattern:** normals → region-grow (planar vs cylindrical) → RANSAC/Hough cylinder per region → join into runs. The fitting steps are CPU-only and label-free; only connectivity/skeleton stages need a connected component resident.

## What's realistically separable without labels

✅ **pipes** (cylinders), **walls/floors** (planes), **beams/columns** (plane sets/profiles), **vessels/tanks** (large cylinders+caps), **ducts/cable trays** (planar boxes).
❌ **valves, flanges, pumps** are **not** separable by primitive fitting alone — they need a learned classifier (GPU track) or rule-based heuristics on the extracted pipe graph (flange = annular thickening / paired circles on axis; valve = bulge between two flanges). Treat as a downstream layer; out of geometric scope initially.

## Commercial context (what mature tools actually do)

EdgeWise/ClearEdge3D and Leica Cyclone 3DR "Region Grow" use **classical geometric extraction** (region grow + cylinder fitting) for pipes/steel — validating the [[Recommended Approach|classical-first]] direction. Newer aurivus uses GPU deep learning as a cloud service.

## Sources

CLOI-NET https://www.sciencedirect.com/science/article/abs/pii/S1474034620300902 · ResPointNet++ https://www.sciencedirect.com/science/article/abs/pii/S0926580521003253 · Noichl & Borrmann https://onlinelibrary.wiley.com/doi/10.1111/mice.13153

## Related

- [[Classical Geometric Methods]] · [[Deep Learning Methods]] · [[Datasets and Benchmarks]] · [[Target Class Taxonomy]] · [[Research — Plant and Piping]]
