---
tags: [decision]
status: decision
updated: 2026-06-07
---

# ADR-004 — IFC-anchored class taxonomy

## Status
**Accepted** (2026-06-07)

## Context
The classifier needs a defined class set. The research ([[Taxonomies (IFC, Uniclass)]]) surfaced two industry ontologies: **IFC** (ISO 16739, geometry-bearing, buildingSMART) and **Uniclass 2015** (UK coding overlay, thousands of codes). The class set must map to deliverable BIM elements, align with available training data ([[Datasets and Benchmarks]]: S3DIS structure + CLOI/MEP plant), and stay coarse enough to be geometrically separable.

## Decision
Adopt an **IFC-anchored two-level [[Target Class Taxonomy|taxonomy]]**: a trainable **Level-1** set of ~10 classes (floor, wall, ceiling, beam, column, pipe, duct, cable-tray, equipment, clutter) mapping 1:1 to IFC classes; optional **Level-2** subtypes (pipe→elbow/tee/flange, equipment→pump/valve/tank) added later as attributes. **Uniclass** is attached as optional export metadata, never a training target.

## Consequences
- **Positive:** labels map directly to IFC/Revit deliverables; Level-1 is the intersection of separable + data-available; flow-supertype grouping is principled and extensible.
- **Negative / cost:** process-plant fine semantics (P&ID-grade, ISO 15926/DEXPI) are out of scope; some equipment collapses into one Level-1 class until [[Deep Learning Methods|DL]] enables subtypes.
- **Revisit when:** a client needs P&ID-grade classes, or DL makes Level-2 subtypes trainable.

## Related
[[Target Class Taxonomy]] · [[Taxonomies (IFC, Uniclass)]] · [[Recommended Approach]]
