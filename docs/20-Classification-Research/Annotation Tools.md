---
tags: [research/datasets]
status: research
updated: 2026-06-07
---

# Annotation Tools

For labelling your own `.e57` scans to train the [[Classical Geometric Methods|Random-Forest]] (or a future [[Deep Learning Methods|DL]]) classifier. Full source report: [[Research — Datasets and Taxonomies]].

| Tool | Type | Strengths | Plant fit |
|---|---|---|---|
| **CloudCompare** | OSS desktop | **reads `.e57` natively**, handles huge clouds, scalar fields, scissor/segment tools, manual class assignment | **best free starting point** for in-house labelling |
| **labelCloud** (ch-sa) | OSS (Python) | 3D bounding boxes + box-based semantic labels, rotated boxes | quick instance boxing (pumps, valves, vessels) |
| **Point Labeler** (jbehley) | OSS (C++) | polygon + brush per-point labelling, multi-scan | dense per-point labelling (SemanticKITTI tool) |
| **Segments.ai** | commercial SaaS | unlimited cloud size, tiling, batch, QA pipelines | best for scaling a real labelled set |
| **Supervisely** | commercial/freemium | AI auto-segment, tracking | watch ~1M pts/scene viewport cap |

> [!tip] Scale workflow
> At [[Constraints and Scale|500M–7B points]] the practical loop is: **voxel-downsample a representative subset → label in CloudCompare/Segments.ai → train → infer on full-resolution streamed blocks.** Labelling happens on a thinned subset; inference runs at full density via the streaming pipeline.

## Recommended

Start with **CloudCompare** — it's free, reads `.e57` directly, and CANUPO/3DMASC plugins ([[Classical Geometric Methods]]) can pre-segment to speed up manual labelling.

## Sources

CloudCompare https://www.cloudcompare.org/ · labelCloud https://github.com/ch-sa/labelCloud · Point Labeler https://github.com/jbehley/point_labeler · Segments.ai https://segments.ai/

## Related

- [[Datasets and Benchmarks]] · [[Recommended Approach]] · [[Research — Datasets and Taxonomies]]
