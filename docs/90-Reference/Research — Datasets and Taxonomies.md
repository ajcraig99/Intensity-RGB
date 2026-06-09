---
tags: [reference, research/datasets, research/taxonomy]
status: reference
updated: 2026-06-07
---

# Research — Datasets and Taxonomies (verbatim)

> Verbatim research-agent output. Synthesized versions: [[Datasets and Benchmarks]], [[Taxonomies (IFC, Uniclass)]], [[Annotation Tools]]. See [[90-Reference/README|README]].

---

# 3D Point Cloud Semantic Segmentation: Datasets, Benchmarks, and Taxonomies for Industrial-Plant Classification

Research compiled for an industrial-plant point-cloud recolour/classification tool (pipes, structural elements, walls, floors, equipment). Emphasis on indoor/industrial/building scenes and on taxonomies that map cleanly to scan-to-BIM workflows.

---

## 1. General-purpose benchmarks

These are the "household-name" datasets the literature benchmarks against. Most are **outdoor/urban or generic-indoor** and are **non-commercial licensed** — useful for pre-training and architecture validation, but none contain plant-specific classes (pipes, vessels, valves).

| Dataset | Type / scene | Sensor | Points | Classes | License | URL | Plant suitability |
|---|---|---|---|---|---|---|---|
| **Semantic3D** | Outdoor urban, static TLS | Terrestrial laser | ~4 B labelled (semantic-8 ≈ 2 B; reduced-8 test ≈ 0.1 B) | 8: man-made terrain, natural terrain, high veg, low veg, buildings, hardscape, scanning artefacts, cars | CC BY-NC-SA 3.0 | semantic3d.net | Low. TLS like plant scans, but classes are urban. Good for TLS-density pre-training. |
| **S3DIS** (Stanford 2D-3D-S) | Indoor, 6 areas / 271 rooms | Matterport (structured) | ~273–696 M (sources vary) | 13: ceiling, floor, wall, beam, column, window, door, table, chair, sofa, bookcase, board, clutter | Academic / research use (registration via Stanford) | buildingparser.stanford.edu/dataset.html | **Medium-high.** Closest mainstream dataset for buildings — has wall/floor/ceiling/beam/column. The de-facto indoor benchmark. |
| **ScanNet** (v2) | Indoor rooms, RGB-D | RGB-D video (1513 scans, 707 scenes) | 2.5 M views; ~20 eval classes | 20 (+unannotated): wall, floor, cabinet, bed, chair, sofa, table, door, window, bookshelf, picture, counter, desk, curtain, fridge, shower curtain, toilet, sink, bathtub, otherfurniture | ScanNet Terms of Use (sign + institutional email) | github.com/ScanNet/ScanNet | Low-medium. Furniture-heavy domestic scenes; wall/floor/door transferable. |
| **SemanticKITTI** | Outdoor automotive, sequential | Velodyne HDL-64 (43k+ scans) | per-scan; sequences total billions | 28 (19/25 eval): road, sidewalk, building, car, vegetation, pole, traffic-sign, fence, terrain, person, etc. | CC BY-NC-SA | semantic-kitti.org/dataset.html | Low. Sparse automotive LiDAR; domain mismatch. Good for sequence/LiDAR research. |
| **Paris-Lille-3D (NPM3D)** | Outdoor urban, MLS | Mobile laser scanning | ~143 M (Lille1 71.3 M, Lille2 26.8 M, Paris 45.7 M) | ~50 fine classes coarsened to ~9–10 (ground, building, pole, bollard, trash can, barrier, pedestrian, car, vegetation) | CC BY-NC-ND 3.0 | npm3d.fr/paris-lille-3d | Low. Urban MLS; CC-ND blocks derivatives. |
| **NPM3D / Paris-CARLA-3D** | Same family (real + synthetic urban) | MLS + simulation | varies | urban semantic classes | CC BY-NC-* | npm3d.fr | Low. Same urban domain. |
| **DALES** | Aerial / earth scan (ALS) | Airborne LiDAR, 40 scenes, 10 km² | >0.5 B | 8: ground, vegetation, cars, trucks, poles, power lines, fences, buildings | CC BY 4.0 (permissive) | go.udayton.edu/dales3d | Low for plant interiors, but **only one with a truly open CC BY licence** — note for licensing precedent. |
| **Toronto-3D** | Outdoor urban roadway, MLS | Teledyne Optech Maverick MLS, ~1 km | ~78.3 M | 8: road, road marking, natural, building, utility line, pole, car, fence | CC BY-NC 4.0 | github.com/WeikaiTan/Toronto-3D | Low. Urban MLS. Has intensity + RGB + GPS time attributes (relevant to your intensity pipeline). |

**Takeaway:** S3DIS is the most transferable mainstream benchmark for a building/plant classifier (it already has wall, floor, ceiling, beam, column). All the others are either domestic-indoor or urban/aerial outdoor and lack process equipment. None is licensed for unrestricted commercial use except DALES (CC BY 4.0).

---

## 2. Industrial / plant / MEP / BIM-oriented datasets

This is the directly relevant category. The dominant finding from the literature is **data scarcity**: very few labelled industrial-plant point clouds are publicly downloadable, which is exactly why synthetic-data generation is the active research thread.

| Dataset | Origin / authors | Source data | Size | Classes | Public? / License | Notes & plant suitability |
|---|---|---|---|---|---|---|
| **CLOI** (CLOI-NET) | Agapaki & Brilakis, Cambridge (2020) | TLS scans of 4 real industrial plants | ~140 M points | 7 shape classes: cylinders, elbows, channels, I-beams, angles, flanges, valves (with valve subtypes: globe/ball/gate/butterfly/diaphragm/plug/check/needle/pinch) | Described as a benchmark; **not openly downloadable** (request from authors) | **Highest relevance.** Purpose-built for industrial-facility geometric digital twins. Shape-primitive taxonomy is exactly the plant domain. |
| **ResPointNet++ benchmark** | Yin/Yang et al. (Automation in Construction 2021) | Industrial process plant TLS | — | 5: pipes, pumps, tanks, I-shape beams, rectangular beams (94% OA, 87% mIoU reported) | Not openly released | Very relevant class set (pipes/pumps/tanks/beams). |
| **CIOL dataset** | Industrial facility TLS, 4 sites (warehouse, petrochemical plant, refinery, processing unit) | TLS | — | 10: I-beams, elbows, pipes, valves, handrails, … | **Not publicly accessible** | First labelled industrial-facility set; relevant taxonomy but closed. |
| **MEP multi-class dataset** (LGVT network paper) | Improved building MEP segmentation, J. Building Engineering 2024 | 4 real buildings, TLS | 92.10 M points, 56 areas | 9: cable tray, electrical conduit, wire duct, light fixture (electrical); ventilation duct, cooler (mechanical); water pipe (plumbing); hanger rod, trapeze bracket (mech+plumb) | Stated as "first publicly available MEP point-cloud dataset" (check paper for access link) | **High relevance for building services.** Pipes/ducts/trays/hangers — directly maps to MEP scope. |
| **Synthetic industrial-plant data** | Noichl & Borrmann, TU Munich (CACAIE 2024; "BIM-to-Scan" 2021) | Surface sampling + laser-scan simulation from industrial 3D/BIM models | Generatable at scale | walls, roofs, beams, pipes (+ steel structures, elbows in later work) | Method/pipeline published (mediatum.ub.tum.de); some assets via TUM repository | **Strategically important.** The recommended path to overcome scarcity: generate labelled synthetic plant clouds from CAD/BIM. Pairs naturally with your synthetic-shading pipeline. |
| **Pipework component repo** | Yeo et al. (2020) | Segmented industrial-plant pipework | — | pipe components / elbows | Repository referenced in literature | Niche, pipe-recognition focused. |
| **libE57 sample data** | libe57.org | Various TLS (incl. vendor exports) | small | unlabelled | Free to use/redistribute | Not labelled — use as **format/IO test fixtures** for your `.e57` reader/writer, not training. |
| **FARO / Leica vendor samples** | FARO SCENE, Leica RTC360/Cyclone | TLS .e57/.fls/.ptx | varies | unlabelled | Vendor terms | Realistic plant/stair scans (e.g. RTC360 staircase samples). Good unlabelled test data; not ground truth. |

**Takeaway:** There is **no large, open, commercially-licensed, labelled industrial-plant point-cloud dataset.** The practical strategy is: (a) pre-train on S3DIS/Semantic3D, (b) fine-tune on synthetic plant data generated from BIM/CAD (Noichl-Borrmann approach), (c) hand-label a small real in-house set (your own `.e57` scans) with one of the tools below, using a plant-oriented taxonomy.

---

## 3. Standard classification taxonomies (scan-to-BIM / construction)

Two ontologies dominate: **IFC** (international, buildingSMART, ISO 16739) and **Uniclass 2015** (UK, NBS). Both can express plant/MEP elements; IFC is the geometry-bearing schema, Uniclass is a coding overlay.

### 3.1 IFC element classes (IFC 4.3) relevant to plant

IFC organises physical elements under `IfcBuiltElement`/`IfcDistributionElement`. The hierarchy that matters for a plant classifier:

| Plant concept | IFC class | IFC parent / domain | Notes |
|---|---|---|---|
| Pipe run | **IfcPipeSegment** | IfcFlowSegment → IfcDistributionFlowElement | The core "pipe" class |
| Pipe bend/elbow, tee | **IfcPipeFitting** | IfcFlowFitting | Elbows, tees, reducers |
| Duct (HVAC) | **IfcDuctSegment** | IfcFlowSegment | Ventilation ducting |
| Duct fitting | **IfcDuctFitting** | IfcFlowFitting | |
| Cable tray / ladder | **IfcCableCarrierSegment** | IfcFlowSegment | Trays, ladders |
| Cable / conduit | **IfcCableSegment**, IfcCableCarrierSegment | IfcFlowSegment | |
| Valve | **IfcValve** | IfcFlowController → IfcDistributionFlowElement | "control or modulate flow of fluid" |
| Pump | **IfcPump** | IfcFlowMovingDevice | |
| Tank / vessel | **IfcTank** | IfcFlowStorageDevice | "a vessel/container in which a fluid or gas is stored." No separate `IfcVessel` — process vessels are modelled as IfcTank or IfcFlowStorageDevice (or IfcDistributionFlowElement + classification reference for process plant) |
| Beam | **IfcBeam** | IfcBuiltElement | I-beam/rectangular |
| Column | **IfcColumn** | IfcBuiltElement | Structural column |
| Wall | **IfcWall** / IfcWallStandardCase | IfcBuiltElement | |
| Floor / slab | **IfcSlab** | IfcBuiltElement | Floors and ceilings both → IfcSlab (PredefinedType FLOOR / ROOF / BASESLAB) |
| Equipment (generic) | **IfcFlowMovingDevice / IfcEnergyConversionDevice / IfcDistributionFlowElement** | — | Compressors, heat exchangers, etc. |

IFC's "flow" supertypes give a clean coarse grouping: **Segment** (linear runs: pipe/duct/tray), **Fitting** (connectors), **Controller** (valves), **MovingDevice** (pumps/fans), **StorageDevice** (tanks/vessels), plus **built elements** (wall/slab/beam/column).

> Note: classic IFC (≤4.x) is building-centric. Full **process-plant** semantics (P&ID-grade vessels, instruments) historically came from **ISO 15926** / **CFIHOS** / **DEXPI**, with **IFC 4.3** adding more infrastructure coverage. For a recolour/scan-classification tool, IFC's building + MEP classes are sufficient granularity.

### 3.2 Uniclass 2015 (UK NBS) — coding overlay

11 tables; the relevant ones for a plant classifier are **EF (Elements/Functions)**, **Ss (Systems)**, **Pr (Products)**. Codes are hierarchical (`Tt_nn_nn_nn`).

| Table | Meaning | Example relevant to plant |
|---|---|---|
| **EF** Elements/Functions | Functional part of an asset | EF_30_10 Roof; structural frame elements |
| **Ss** Systems | Collection of components forming an element/function | Ss_30_10_30_45 Light steel roof framing system; piping systems; HVAC systems |
| **Pr** Products | Individual components | Pr_20_85_08_11 Carbon steel beams; pipe products, valves, pumps |
| Co / En / SL / Ac | Complexes / Entities / Spaces / Activities | site/building/space context |

Uniclass is best used as a **secondary classification code attached to an IFC class** (IFC carries geometry + primary type; Uniclass carries the project-coding reference) — this is the standard UK scan-to-BIM convention.

### 3.3 How plant elements map across ontologies

| Plant element | IFC class | IFC flow supertype | Uniclass (table) |
|---|---|---|---|
| Pipe | IfcPipeSegment | FlowSegment | Pr (pipe products) / Ss (piping systems) |
| Elbow/fitting | IfcPipeFitting | FlowFitting | Pr |
| Valve | IfcValve | FlowController | Pr |
| Pump | IfcPump | FlowMovingDevice | Pr |
| Vessel/Tank | IfcTank | FlowStorageDevice | Pr / Ss |
| Duct | IfcDuctSegment | FlowSegment | Ss (HVAC) |
| Cable tray | IfcCableCarrierSegment | FlowSegment | Ss (electrical) |
| Beam | IfcBeam | (built element) | Pr / EF |
| Column | IfcColumn | (built element) | Pr / EF |
| Wall | IfcWall | (built element) | EF / Ss |
| Floor/Ceiling | IfcSlab | (built element) | EF |

---

## 4. Annotation tools for labelling point clouds

| Tool | Type | Modality | Strengths | Plant labelling fit |
|---|---|---|---|---|
| **CloudCompare** | Open source (desktop) | Generic point clouds, .e57 native | Free, handles huge clouds, scalar fields, segmentation/scissor tools, manual class assignment | **Best free starting point** for in-house labelling of .e57 plant scans; reads your exact format. Manual but unlimited size. |
| **labelCloud** (ch-sa, TU Dresden) | Open source (Python) | 3D bounding boxes + box-based semantic segmentation | Lightweight, 7 input formats, multiple label formats, rotated boxes; "Assign" labels all points in a box to a class | Good for **instance/component boxing** (pumps, valves, vessels) and quick semantic labels. |
| **Point Labeler** (jbehley) | Open source (C++) | LiDAR sequences, voxel grids | Polygon + brush labelling, multi-scan, plane filtering; the SemanticKITTI labelling tool | Strong for **dense brush-based per-point** labelling; geared to LiDAR sequences but usable for static scans. |
| **Segments.ai** | Commercial SaaS | Point cloud segmentation + boxes | Unlimited cloud size, tiling for fast load, merged-3D, batch mode, automated tracking, QA pipelines | **Best commercial** for scaling a real labelled plant set; segmentation-first. |
| **Supervisely** | Commercial / freemium platform | 3D LiDAR + sensor fusion | App ecosystem, AI auto-segment, image+point overlay, tracking; ~1 M points/scene practical limit | Good if you want managed workflows + ML-assisted labelling; watch per-scene point cap vs your 500 M–7 B scale. |
| **3D-Annotator**, **3D-BAT**, **ReBound** | Open source | mesh/point segmentation, boxes, active learning | Web-based; niche | Secondary options; active-learning (ReBound) useful for iterative labelling. |

**Scale caveat (relevant to your project):** your typical scans are 500 M–7 B points. CloudCompare and Segments.ai handle very large clouds; Supervisely's interactive viewport is practically limited (~1 M points/scene), so you'd tile/downsample. For a memory-flat streaming tool like Intensity-RGB, the natural workflow is: voxel-downsample a representative subset → label in CloudCompare/Segments.ai → train → infer on full-resolution streamed blocks.

---

## 5. Recommendation: taxonomy for a plant-focused tool

**Adopt a two-level taxonomy anchored on IFC, with Uniclass as an optional export code.**

**Level 1 — coarse classes (the trainable target, ~10 classes):**
This is the set to actually predict, because it matches what's separable in TLS data and aligns with both S3DIS (for pre-training) and the industrial datasets (CLOI/ResPointNet++/MEP) for fine-tuning:

1. **Floor / slab** (IfcSlab) — pairs with S3DIS floor/ceiling
2. **Wall** (IfcWall) — S3DIS wall
3. **Ceiling / roof** (IfcSlab, ROOF) — S3DIS ceiling
4. **Structural beam** (IfcBeam) — S3DIS beam, CLOI I-beam/channel/angle
5. **Structural column** (IfcColumn) — S3DIS column
6. **Pipe** (IfcPipeSegment + IfcPipeFitting) — CLOI cylinder/elbow/flange, MEP water pipe
7. **Duct** (IfcDuctSegment) — MEP ventilation duct
8. **Cable tray / conduit** (IfcCableCarrierSegment) — MEP tray/conduit
9. **Equipment** (IfcPump / IfcTank / IfcValve / generic distribution device) — CLOI valves, ResPointNet++ pumps/tanks
10. **Clutter / other** — S3DIS clutter equivalent (handrails, supports, unclassified)

**Level 2 — fine subtypes (optional, attached as attributes, not separate trained classes initially):**
Pipe→{straight, elbow, tee, flange}; Equipment→{pump, valve(ball/gate/globe/…), tank/vessel}; Beam→{I-shape, rectangular, channel, angle} — mirroring CLOI's shape taxonomy. Predict these only once Level-1 is solid, or derive them via geometric primitive fitting.

**Why this taxonomy:**
- **IFC is the lingua franca** of scan-to-BIM and is ISO-standardised (16739) — labels map directly to deliverable BIM elements and downstream Revit/IFC export.
- The Level-1 set is the **intersection of what's available in public training data** (S3DIS supplies structure; CLOI/ResPointNet++/MEP supply plant components) and **what's geometrically separable** in TLS clouds.
- IFC's **flow supertypes** (Segment/Fitting/Controller/MovingDevice/StorageDevice) give a principled, extensible grouping if you later need finer classes.
- Attach **Uniclass Ss/Pr codes** as metadata on export for UK clients — but don't train against Uniclass directly (too fine-grained: thousands of codes).

**Data strategy that fits this taxonomy:** pre-train on **S3DIS** (structure classes), fine-tune on **synthetic plant data generated from BIM/CAD** (Noichl-Borrmann method — overcomes the open-data scarcity and aligns with your existing synthetic pipeline), and validate/correct on a **small hand-labelled set of your own `.e57` scans** labelled in **CloudCompare** (native .e57, free, unlimited size) or **Segments.ai** (if scaling).

---

## Sources

- Semantic3D: [semantic3d.net](http://www.semantic3d.net/) · [arXiv 1704.03847](https://arxiv.org/abs/1704.03847)
- S3DIS / 2D-3D-S: [buildingparser.stanford.edu/dataset.html](http://buildingparser.stanford.edu/dataset.html) · [arXiv 1702.01105](https://arxiv.org/pdf/1702.01105)
- ScanNet: [github.com/ScanNet/ScanNet](https://github.com/ScanNet/ScanNet)
- SemanticKITTI: [semantic-kitti.org/dataset.html](http://semantic-kitti.org/dataset.html) · [arXiv 1904.01416](https://arxiv.org/abs/1904.01416)
- Paris-Lille-3D / NPM3D: [npm3d.fr/paris-lille-3d](https://npm3d.fr/paris-lille-3d) · [arXiv 1712.00032](https://arxiv.org/abs/1712.00032)
- DALES: [go.udayton.edu/dales3d](https://go.udayton.edu/dales3d) · [arXiv 2004.11985](https://arxiv.org/abs/2004.11985)
- Toronto-3D: [github.com/WeikaiTan/Toronto-3D](https://github.com/WeikaiTan/Toronto-3D) · [arXiv 2003.08284](https://arxiv.org/abs/2003.08284)
- CLOI / CLOI-NET: [ScienceDirect S1474034620300902](https://www.sciencedirect.com/science/article/abs/pii/S1474034620300902) · [Cambridge repository](https://www.repository.cam.ac.uk/items/409268a8-5214-429f-b338-afde4f35a43e)
- ResPointNet++: [ScienceDirect S0926580521003253](https://www.sciencedirect.com/science/article/abs/pii/S0926580521003253)
- MEP multi-class dataset (LGVT): [ScienceDirect S2352710224018795](https://www.sciencedirect.com/science/article/abs/pii/S2352710224018795)
- Synthetic plant data (Noichl & Borrmann): [Wiley 10.1111/mice.13153](https://onlinelibrary.wiley.com/doi/10.1111/mice.13153) · [TUM mediatum PDF](https://mediatum.ub.tum.de/doc/1732069/7es44l6pmu9js1shs22q2rwjd.Noichl_2024_SynthData.pdf) · ["BIM-to-Scan" 2021](https://www.researchgate.net/publication/354411827)
- libE57 sample data: [libe57.org/data.html](http://www.libe57.org/data.html)
- IFC 4.3 classes: [IfcPipeSegment](https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcPipeSegment.htm) · [IfcDuctSegment](https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcDuctSegment.htm) · [IfcValve](https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcValve.htm) · [IfcPump](https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcPump.htm) · [IfcTank](https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcTank.htm) · [IfcBeam](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/lexical/IfcBeam.htm) · [IfcColumn](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/lexical/IfcColumn.htm)
- Uniclass 2015: [uniclass.thenbs.com](https://uniclass.thenbs.com/) · [REBIM overview](https://rebim.io/classification-systems-uniclass-2015/)
- Annotation tools: [Segments.ai 8 best tools](https://segments.ai/blog/the-8-best-point-cloud-labeling-tools/) · [Supervisely 3D](https://ecosystem.supervisely.com/annotation_tools/pointcloud-labeling-tool) · [labelCloud (ch-sa)](https://github.com/ch-sa/labelCloud) · [point_labeler (jbehley)](https://github.com/jbehley/point_labeler)
