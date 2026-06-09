---
tags: [project, taxonomy]
status: planned
updated: 2026-06-07
---

# Target Class Taxonomy

The class set the tool should predict, anchored on [[Taxonomies (IFC, Uniclass)|IFC]] (see [[ADR-004 IFC-anchored taxonomy]]). Two levels: a trainable Level-1 set, and optional Level-2 subtypes added later.

## Level 1 — the trainable target (~10 classes)

Chosen as the **intersection of what's geometrically separable in TLS** and **what public training data covers** (S3DIS for structure; CLOI/ResPointNet++/MEP for plant).

| # | Class | IFC class | First feasible via | Research basis |
|---|---|---|---|---|
| 1 | Floor / slab | IfcSlab (FLOOR/BASESLAB) | rules (horizontal planar, low Z) | S3DIS |
| 2 | Wall | IfcWall | rules (vertical planar) | S3DIS |
| 3 | Ceiling / roof | IfcSlab (ROOF) | rules (horizontal planar, high Z) | S3DIS |
| 4 | Beam | IfcBeam | RF / planes | S3DIS, CLOI |
| 5 | Column | IfcColumn | RF / planes + verticality | S3DIS |
| 6 | Pipe | IfcPipeSegment (+Fitting) | cylinder RANSAC | CLOI, MEP, ResPointNet++ |
| 7 | Duct | IfcDuctSegment | RF / planar box | MEP |
| 8 | Cable tray / conduit | IfcCableCarrierSegment | RF / planar box | MEP |
| 9 | Equipment (pump/valve/tank) | IfcPump / IfcValve / IfcTank | RF; tank via large cylinder | CLOI, ResPointNet++ |
| 10 | Clutter / other | — | residual | S3DIS clutter |

> [!note] Coverage of the user's requested classes
> Requested: pipes ✅(6) · pumps ✅(9) · beams ✅(4) · columns ✅(5) · walls ✅(2) · floors ✅(1) · vessels/tanks ✅(9, large cylinder) · valves ✅(9 / L2) · flanges (L2) · ducts ✅(7) · cable trays ✅(8). Floors+ceilings split 1/3.

## Level 2 — optional subtypes (attributes, added later)

Predict these only once Level-1 is solid, or derive geometrically:
- **Pipe** → {straight, elbow, tee, flange} (CLOI shape taxonomy)
- **Equipment** → {pump, valve(ball/gate/globe/…), tank/vessel}
- **Beam** → {I-shape, rectangular, channel, angle}

Fine subtypes generally need the [[Deep Learning Methods|DL track]] or rule-based pipe-graph heuristics — see [[Plant and Piping Methods]].

## Export

Primary label = IFC class. Optionally attach **Uniclass Ss/Pr** codes as metadata on export for UK clients ([[Taxonomies (IFC, Uniclass)]]).

## Colour LUT

Each class gets a fixed colour in the class→colour LUT used by [[Classification Colouring]]. A stable, perceptually-distinct palette (e.g. one tab10/tab20 entry per class) keeps recoloured scans legible.

## Related

- [[Recommended Approach]] · [[Taxonomies (IFC, Uniclass)]] · [[Classification Colouring]] · [[ADR-004 IFC-anchored taxonomy]]
