---
tags: [research/taxonomy]
status: research
updated: 2026-06-07
---

# Taxonomies (IFC, Uniclass)

How plant elements map to standard scan-to-BIM ontologies. This drives the [[Target Class Taxonomy|class set the tool should predict]]. Full source report: [[Research — Datasets and Taxonomies]].

Two ontologies dominate: **IFC** (international, buildingSMART, ISO 16739 — the geometry-bearing schema) and **Uniclass 2015** (UK NBS — a coding overlay).

## IFC element classes (IFC 4.3) for plant

IFC's "flow" supertypes give a clean coarse grouping:

| Plant element | IFC class | Flow supertype |
|---|---|---|
| Pipe run | **IfcPipeSegment** | FlowSegment |
| Pipe bend / tee / reducer | **IfcPipeFitting** | FlowFitting |
| Duct (HVAC) | **IfcDuctSegment** | FlowSegment |
| Cable tray / ladder | **IfcCableCarrierSegment** | FlowSegment |
| Valve | **IfcValve** | FlowController |
| Pump | **IfcPump** | FlowMovingDevice |
| Tank / vessel | **IfcTank** | FlowStorageDevice |
| Beam | **IfcBeam** | (built element) |
| Column | **IfcColumn** | (built element) |
| Wall | **IfcWall** | (built element) |
| Floor / ceiling | **IfcSlab** (PredefinedType FLOOR / ROOF / BASESLAB) | (built element) |

> [!note] No `IfcVessel`
> Process vessels are modelled as **IfcTank** / IfcFlowStorageDevice. Full process-plant semantics (P&ID-grade) historically come from **ISO 15926 / CFIHOS / DEXPI**; IFC 4.3 adds more infrastructure coverage. For a recolour/classification tool, IFC's building + MEP classes are sufficient granularity.

## Uniclass 2015 (UK)

A hierarchical coding overlay (`Tt_nn_nn_nn`). Relevant tables: **EF** (Elements/Functions), **Ss** (Systems), **Pr** (Products). Best used as a **secondary code attached to an IFC class** on export — IFC carries geometry + primary type, Uniclass carries the project-coding reference. Do **not** train against Uniclass directly (thousands of codes).

## Recommended ontology stance

Anchor the trainable taxonomy on **IFC** (ISO-standardised, maps directly to deliverable BIM elements / Revit-IFC export); attach **Uniclass Ss/Pr** codes as optional export metadata for UK clients. See [[Target Class Taxonomy]] and [[ADR-004 IFC-anchored taxonomy]].

## Sources

IfcPipeSegment https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcPipeSegment.htm · IfcValve · IfcPump · IfcTank · IfcBeam · IfcColumn (same lexical root) · Uniclass https://uniclass.thenbs.com/

## Related

- [[Target Class Taxonomy]] · [[ADR-004 IFC-anchored taxonomy]] · [[Datasets and Benchmarks]] · [[Research — Datasets and Taxonomies]]
