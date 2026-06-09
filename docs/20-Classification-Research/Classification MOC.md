---
tags: [research, moc]
status: research
updated: 2026-06-07
---

# Classification — Map of Content

Navigation hub for the point-cloud classification research. All notes here are **synthesized** from four research sweeps; the verbatim source reports live in `90-Reference/` (see [[90-Reference/README|README]]).

## The question

How can [[Project Overview|Intensity-RGB]] classify points into [[Target Class Taxonomy|plant element classes]] given its [[Constraints and Scale|CPU-only / streaming / no-global-kNN]] constraints?

## Method families

| Note | Family | CPU-only? | Streaming? | Needs labels? |
|---|---|---|---|---|
| [[Classical Geometric Methods]] | RANSAC, region growing, feature+RF | ✅ | ✅ | mostly ❌ |
| [[Geometric Features (Weinmann)]] | per-point/voxel feature math | ✅ | ✅ | ❌ |
| [[Deep Learning Methods]] | PointNet++, KPConv, transformers | ❌ GPU | ⚠️ tile only | ✅ |
| [[Plant and Piping Methods]] | domain-specific (CLOI, ResPointNet++…) | ❌ GPU | ⚠️ | ✅ |

See the master scorecard in [[Method Comparison]].

## Supporting research

- [[Datasets and Benchmarks]] — what labelled data exists (spoiler: no open commercial plant set).
- [[Taxonomies (IFC, Uniclass)]] — how plant elements map to industry ontologies.
- [[Annotation Tools]] — labelling your own `.e57` scans.

## The headline conclusion

Every CPU-only, streaming-feasible, label-free approach in the literature is **geometric**, and it maps directly onto the [[Voxel Normals and PCA|voxel PCA the tool already runs]]. All deep-learning methods are GPU + labelled data + tiling that conflicts with the memory-flat 500M–7B constraint — and there is **no freely downloadable, commercially-licensed, labelled industrial-plant dataset** (CLOI is the nearest, gated). This is why the [[Recommended Approach]] is classical-geometric-first. The reasoning is recorded in [[ADR-001 Classical-geometric-first]] and [[ADR-002 Defer deep learning to GPU track]].

## Related

- [[Recommended Approach]] · [[Classification Colouring]] · [[Home]]
