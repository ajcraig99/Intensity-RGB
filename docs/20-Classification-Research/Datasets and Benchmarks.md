---
tags: [research/datasets]
status: research
updated: 2026-06-07
---

# Datasets and Benchmarks

What labelled data exists for training/fine-tuning a classifier. Full source report: [[Research — Datasets and Taxonomies]].

> [!important] The headline
> There is **no large, open, commercially-licensed, labelled industrial-plant point-cloud dataset.** CLOI is the nearest in domain but gated. The proven workaround is **synthetic-from-CAD/IFC** generation (Noichl-Borrmann), which dovetails with the tool's existing synthetic-fixture pipeline.

## General-purpose benchmarks

| Dataset | Scene | Points | Classes | Licence | Plant fit |
|---|---|---|---|---|---|
| **S3DIS** | indoor offices | ~273–696M | 13 incl. **floor, ceiling, wall, beam, column** | academic/registration | **best mainstream transfer** (structural classes) |
| **Semantic3D** | outdoor TLS | ~4B labelled | 8 (urban) | CC BY-NC-SA | TLS-density pre-train; no plant classes |
| **ScanNet v2** | indoor RGB-D | 2.5M views | 20 | ToU | domestic furniture; wall/floor transfer |
| **SemanticKITTI** | automotive LiDAR | billions | 19/25 | CC BY-NC-SA | domain mismatch; intensity-trained |
| **Paris-Lille-3D / NPM3D** | urban MLS | ~143M | ~9–50 | CC BY-NC-ND | urban; ND blocks derivatives |
| **DALES** | aerial ALS | >0.5B | 8 | **CC BY 4.0** | only truly open licence; aerial |
| **Toronto-3D** | urban MLS | ~78M | 8 | CC BY-NC | has intensity+RGB attributes |

## Industrial / plant / MEP datasets

| Dataset | Source | Classes | Public? |
|---|---|---|---|
| **CLOI** | 4 real plants, TLS, ~140M | 7–10 shape classes (pipe, elbow, I-beam, flange, valve…) | **gated** (request) |
| **ResPointNet++ benchmark** | process plant TLS | pipes, pumps, tanks, beams | not released |
| **CIOL** | 4 industrial sites | I-beams, elbows, pipes, valves, handrails (10) | **not public** |
| **MEP multi-class** (LGVT) | 4 buildings, 92M | cable tray, conduit, duct, water pipe, hanger… (9) | "first public MEP set" — check paper |
| **Noichl synthetic** | synthetic-from-IFC + 2 real TLS | 14 plant classes | method published, assets gated |
| libE57 / FARO / Leica samples | vendor TLS | **unlabelled** | free | use as `.e57` **format test fixtures**, not training |

## Data strategy for this tool

1. **Pre-train** on S3DIS (structural classes) — if/when a [[Deep Learning Methods|DL track]] exists.
2. **Fine-tune** on **synthetic plant data generated from BIM/CAD** (Noichl-Borrmann) — overcomes the open-data scarcity.
3. **Validate/correct** on a small **hand-labelled set of your own `.e57` scans**, labelled in CloudCompare ([[Annotation Tools]]).

For the [[Recommended Approach|classical Random-Forest stage]], training needs only a **small** labelled sample (RF on geometric features is data-efficient), so even a few hand-labelled scans suffice to start.

## Sources

S3DIS http://buildingparser.stanford.edu/dataset.html · Semantic3D http://www.semantic3d.net/ · DALES https://go.udayton.edu/dales3d · CLOI https://www.repository.cam.ac.uk/items/409268a8-5214-429f-b338-afde4f35a43e

## Related

- [[Taxonomies (IFC, Uniclass)]] · [[Annotation Tools]] · [[Plant and Piping Methods]] · [[Research — Datasets and Taxonomies]]
