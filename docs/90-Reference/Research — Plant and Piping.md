---
tags: [reference, research/plant]
status: reference
updated: 2026-06-07
---

# Research — Plant and Piping (verbatim)

> Verbatim research-agent output. Synthesized version: [[Plant and Piping Methods]]. See [[90-Reference/README|README]].

---

# Point Cloud Classification / Segmentation for Industrial Plant & Piping (Scan-to-BIM / Scan-to-CAD)

Target context: a CPU-only, block-streaming `.e57` tool on 500M–7B-point unstructured scans (no GPU, never load whole cloud, no global kNN). Target classes: pipes, pumps, beams, columns, walls, floors, vessels/tanks, valves, flanges, cable trays, ducts, structural steel.

---

## 1. Academic methodologies & surveys

### Survey / review papers

| Survey | Year | Scope | Key takeaways |
|---|---|---|---|
| Semantic PCSS with DL for the Construction Industry: A Survey (MDPI Appl. Sci. 13(16):9146) | 2023 | DL PCSS for AEC | Taxonomy of projection-, voxel-, and point-based (PointNet → PointNet++ → KPConv → transformers); plant/MEP classes under-represented and data-scarce. |
| Advancements in Point Cloud-Based 3D Defect Detection… A Comprehensive Survey (arXiv 2402.12923) | 2024 | Industrial defect + classification | Covers geometric (RANSAC/region-growing) vs learning pipelines for industrial assets. |
| Automatic Scan-to-BIM — Impact of Semantic Segmentation Accuracy (MDPI Buildings 15(7):1126) | 2025 | Error propagation | Quantifies how segmentation mIoU feeds downstream model fidelity. |

### Deep-learning segmentation methods (industrial/MEP-relevant)

| Method | Authors / Year | Approach | Classes | Reported accuracy | GPU? |
|---|---|---|---|---|---|
| **CLOI-NET** | Agapaki & Brilakis, 2020 (Adv. Eng. Informatics) | Enhanced **PointNet++** + geometric post-processing; the **CLOI dataset** (TLS, 4 industrial sites; CLOI = C/L/O/I shape families) | straight pipe, elbow, I-beam, channel, angle, CHS, flange, valve, conduit, solid bar (10) | **82% mean class acc**, 75% per-point, AUC ~90% | Yes |
| **CLOI benchmark / geometric digital twins** | Agapaki & Brilakis, 2021 (arXiv 2101.01355) | Class seg → instance → fitting benchmark | CLOI classes | framework | Yes |
| **ResPointNet++** | Yin et al., 2021 (Automation in Construction) | Deep **residual** learning fused into PointNet++ | pipes, pumps, tanks, I-beams, rectangular beams (5) | high per-class IoU on ~80M-pt, 4-scene LiDAR | Yes |
| **SE-PseudoGrid** | Yin et al., 2022 (Automation in Construction) | Squeeze-and-Excite local aggregation on PseudoGrid; piping-component **classification** | tee/elbow/flange/reducer/pipe/valve etc. | **OA 96.3%, avg class acc 97.5%** | Yes; **code OSS** |
| **Scan2BIM-NET** | Perez-Perez, Golparvar-Fard et al. (UIUC) | 2× CNN + 1× RNN ensemble | beam, ceiling, column, floor, **pipe**, wall (6) | OA in paper (building MEP) | Yes |
| **Noichl et al. — synthetic data for plants** | Noichl & Borrmann (TUM), 2024 (CACAIE / mice.13153) | **KP-FCNN (KPConv)**; synthetic training via laser-scan simulation from as-designed IFC, tested on real TLS (cooling plant + factory hall) | 14: wall, floor, ceiling, beam, railing, **pipe fitting, pipe accessories, ventilation duct, cable routing, bracing, tank**, equipment, clutter, noise | Simulation-based synthetic raised mean class F1 **~27%**; beat sampling-based **8.3%**; hybrid best. No public dataset. | Yes (voxel 0.02m, kernel 1.5m) |
| Yin et al. (cited in Noichl) | 2021 | PointNet++ using **normal & curvature to detect pipes** | pipes + industrial | — | Yes |
| Label-efficient / weakly-supervised industrial seg. | 2023 (Automation in Construction) | Weak supervision to cut labelling cost | industrial MEP/structural | competitive mIoU at low label budget | Yes |

**Generic backbones (for class sets / scalability context):** PointNet/PointNet++ (Qi 2017, can't ingest >~10⁶ pts/pass); KPConv/KP-FCNN (Thomas 2019, strong on S3DIS); **RandLA-Net** (Hu CVPR 2020) — random sampling + MLP aggregator, handles ~10⁶ pts/pass, evaluated on Semantic3D (8 classes, up to 10⁸ pts/cloud), SemanticKITTI, S3DIS. Still GPU, still tiles.

---

## 2. Pipe / cylinder extraction (the CPU-friendly geometric family)

| Technique | Representative work | How it works | Strengths / limits |
|---|---|---|---|
| **Efficient RANSAC** | **Schnabel, Wahl & Klein 2007** (CGF); CGAL impl. | Minimal random samples fit plane/sphere/**cylinder**/cone/torus; octree-local sampling + lazy scoring. Cylinder axis = cross-product of two sampled normals; radius from projected circle | Fast, robust, **label-free**; mistakes pipe bends for cylinders, misses small parts; octree sampling is **streaming-friendly** |
| **Region growing on normals/curvature** | PCL `RegionGrowing`; Nurunnabi (robust normals); Vo et al. (large clouds) | Per-point normals; grow where normal-angle + curvature thresholds hold; planar → walls/floors/beams, smooth-curved → pipe candidates | Local, **chunkable**; sensitive to normal quality at block seams; great RANSAC pre-segmenter |
| **Hough / Gaussian-sphere axis clustering** | Rabbani & van den Heuvel; Pang & Neumann (Springer 2014) | Project normals + perpendiculars on Gaussian sphere, cluster axis directions, then circle-Hough perpendicular to axis | Good for axis-aligned runs; **global accumulator is memory-heavy** — keep per-tile/per-direction |
| **Connectivity-based cylinder detection** | Tran, Khoshelham et al. 2019 | Local connectivity to avoid spurious fits | Fewer false positives than naive RANSAC |
| **Skeleton / centerline (Laplacian contraction)** | **Alex & Stoppe (DLR) 2025** (arXiv 2506.22118) | Laplacian contraction → longest path → endpoint elongation → rolling-sphere + 2D circle fit recentre → 3D spline smooth → RDP → hull | Recovers straight/bent/curved pipes; **IoU 0.65, radius 88%, length 86%** (synthetic). Needs connected component resident |
| **Adaptive as-built pipeline recon.** | Automation in Construction (S0926580516304745) | Region grow → cylinder fit → joint/elbow detect → topology closure | Produces connected CAD pipe runs |
| **Statistical-similarity pipe-run recon.** | Pang & Neumann 2014 | Normal statistics → primitive similarities guide fitting; auto joint detection closes gaps | Robust to noise/incompleteness; full-site scale |
| **Iterative seg + LM fitting** | Nature Sci. Reports 2025 | Iterative segmentation + Levenberg-Marquardt cylinder refinement (+ normals) | Cuts RANSAC false alarms on bends; sub-mm fit |
| **DeepPipes** | Yu et al. 2020 (Graphical Models 111) | Prior-based: CNN part detection + model fitting + graph aggregation | pipe parts | precision/recall/F1 = **0.95/0.90/0.92** on real; GPU |

**Recurring pattern:** normals → region-grow (planar vs cylindrical) → RANSAC/Hough cylinder per region → join into runs. Fitting primitives are CPU-only and label-free; only connectivity/skeleton stages want a connected component in memory.

---

## 3. Datasets

| Dataset | Origin | Content | Classes | Public? |
|---|---|---|---|---|
| **CLOI** | Agapaki & Brilakis (Cambridge) 2020–21 | TLS, 4 industrial sites incl. oil & gas | pipe, elbow, I-beam, channel, angle, CHS, flange, valve, conduit, solid bar (10) | Cambridge repository, gated (request/registration) |
| **Industrial LiDAR (ResPointNet++)** | Yin 2021 | ~80M pts, 4 scenes, ~4000 m² | pipes, pumps, tanks, I-beams, rect. beams (5) | Tied to paper |
| **Piping classification (SE-PseudoGrid)** | Yin 2022 | Per-component piping benchmark | tee/elbow/flange/reducer/pipe/valve | Code public; check repo for data |
| **Noichl synthetic plant** | TUM 2024 | Synthetic-from-IFC + 2 real TLS | 14 (pipe fitting/accessories, duct, cable routing, beam, bracing, tank…) | **Not released** |
| **S3DIS** | Stanford | Indoor offices | ceiling, floor, wall, **beam, column**, window, door, furniture, clutter (13) | Public. **No pipes/valves/tanks** |
| **Semantic3D** | ETH Zurich | Outdoor TLS, up to 10⁸ pts/cloud | terrain, veg, buildings, hardscape, artefacts, cars (8) | Public. Good **streaming-scale** benchmark, **no plant classes** |

**Bottom line:** no free, fully-labelled industrial-plant cloud exists. CLOI is the nearest (gated). The field's workaround is **synthetic-from-CAD/IFC** (Noichl; J.W. Ma 2020). S3DIS/Semantic3D only transfer for generic structural classes (wall/floor/beam/column), not pipes/valves/flanges/vessels.

---

## 4. Commercial tools (context only)

| Tool | Vendor | Classes / features | Approach |
|---|---|---|---|
| **EdgeWise** | ClearEdge3D (Topcon) | **pipes**, structural steel, ducts, walls, conduit, **cable trays**; spec-driven fitting; billion-pt viz | Classical feature extraction + object recognition; low-false-positive pipe extraction |
| **Cyclone / Cyclone 3DR** | Leica | Auto pipe & steel extraction; **Region Grow** auto-extracts cylindrical pipe networks | Region growing + cylinder fitting |
| **RealWorks** | Trimble | Pipe-run modelling, auto floor extraction | Geometric extraction |
| **PointCab Origins** | PointCab | 2D plan/section extraction | Slice/section based |
| **aurivus (Plant AI)** | aurivus | pipes, fittings, steel beams, walls, doors, windows, stairs; length/orientation/diameter; Revit plug-in | **Deep learning** cloud/GPU service; 25–70% time saved |

Note the split: established CAD vendors (EdgeWise, Cyclone Region Grow) use **classical geometric extraction** — the CPU-friendly family — while newer aurivus uses GPU deep learning as a service.

---

## 5. Open-source projects

| Project | URL | Approach | License | Accuracy |
|---|---|---|---|---|
| **SE-PseudoGrid** | github.com/PointCloudYC/se-pseudogrid | SE-aggregation net, piping classification | (check repo) | OA 96.3% |
| **PyPipes (DeepPipes impl.)** | github.com/ZENULI/PyPipes | CNN classify → cluster → graph aggregate → pipe model | **MIT** | impl. of DeepPipes |
| **PCL** (`SACSegmentation`, `RegionGrowing`, `SampleConsensusModelCylinder`) | pointclouds.org | Classical RANSAC plane/cylinder, region growing, normals | **BSD** | geometric |
| **CGAL** Point Set Shape Detection | doc.cgal.org | Schnabel 2007 efficient RANSAC | **GPL/commercial dual** | geometric |
| **Open3D** | open3d.org | RANSAC plane seg, normals, clustering | **MIT** | geometric |

---

## 6. Methodology comparison — CPU & streaming suitability

| Method family | CPU-only? | Streamable (no whole-cloud load)? | Needs labels? | Target classes | Verdict for 500M–7B streamed |
|---|---|---|---|---|---|
| **RANSAC cylinder fit** (Schnabel; PCL/CGAL) | ✅ | ✅ octree-local per tile; merge across borders | ❌ | pipes; reuse → vessels, some columns | **Best fit** — label-free, deterministic, inherently chunked |
| **Region growing on normals/curvature** | ✅ | ✅ per-block + halo to stitch | ❌ | planes → walls/floors/beam-column faces/tray sides; curved → pipe candidates | **Strong** as RANSAC pre-segmenter; watch seams |
| **Hough / Gaussian-sphere axis** | ✅ | ⚠️ accumulator must stay per-tile | ❌ | pipe axes/runs | OK if local; global accumulator breaks memory-flat |
| **Skeleton/centerline (Laplacian)** | ✅ | ⚠️ needs connected component resident | ❌ | centerlines, bends, diameters, topology | **Post-step on isolated pipe clusters only** |
| **PointNet++/CLOI-NET/ResPointNet++** | ❌ GPU | ❌ >10⁶ pts/pass | ✅ | all incl. valve/flange/pump/tank | Off-spec |
| **KPConv/KP-FCNN (Noichl)** | ❌ GPU | ❌ voxel-tiled GPU | ✅ (synthetic ok) | 14 plant classes | Off-spec |
| **RandLA-Net** | ❌ GPU | ⚠️ ~10⁶-pt tiles, GPU | ✅ | generic + trained plant | Most scalable DL, still GPU/labels |

---

## 7. Recommendations for a CPU-only streaming tool

1. **Anchor on a classical geometric pipeline, not deep learning.** Every CPU-only, label-free, streamable approach in the literature is geometric. All the DL methods (CLOI-NET, ResPointNet++, KPConv/Noichl, RandLA-Net) assume GPU + labelled data + tiling that conflicts with the memory-flat 500M–7B constraint. This also matches what mature CAD tools (EdgeWise, Cyclone 3DR Region Grow) actually do.

2. **Per-block primitive segmentation built on the existing voxel/normal infrastructure.** This project already computes voxel-resolution chunked PCA normals (`processing/voxel_normals.py`) — exactly what region growing and cylinder RANSAC consume. Reuse it: block-stream → per-voxel normals → region-grow on normal-angle + curvature (peel planar walls/floors/beam-column faces/tray-duct faces from smoothly-curved pipe/vessel candidates) → efficient-RANSAC cylinder fit on the curved class, plane fit on the planar class → emit primitive params (axis, radius, plane normal/offset) per block with a small halo so a pipe/wall spanning a boundary stitches in a cheap merge pass keyed on matching axis+radius / plane equation.

3. **Keep heavy steps off the raw cloud.** Cylinder/plane fitting is local and tile-safe. Reserve Laplacian skeleton/centerline (Alex & Stoppe 2025) and pipe-run connectivity/joint closure (Pang & Neumann; adaptive as-built) for **after** a pipe instance is isolated into a small cluster — run them per-instance, never globally. Same for any Hough accumulator: cluster axis directions per tile, never one global accumulator.

4. **Realistic class scope for a geometric tool.** Reliably yields: straight **pipes** (cylinders), **walls/floors** (large planes), **beams/columns/structural steel** (plane sets / I-profiles), **vessels/tanks** (large cylinders + caps), **ducts/cable trays** (planar boxes). **Valves, flanges, pumps are NOT separable by primitive fitting alone** — they need a learned classifier (off-spec) or rule-based heuristics near pipe joints (flange = annular thickening / paired close circles on the axis; valve = a bulge between two flanges). Treat these as a downstream heuristic layer on the extracted pipe graph, and be explicit that fine fitting classes are out of geometric scope.

5. **If labelled classification ever becomes a requirement, the data problem dominates.** No free fully-labelled plant dataset exists (CLOI is nearest and gated). The proven route is synthetic-from-CAD/IFC (Noichl 2024: simulation-based synthetic raised mean class F1 ~27%). But that pulls in GPU training and breaks the CPU-only premise — pursue only if a hard requirement appears, and keep inference as an optional offline GPU pass separate from the streaming core.

6. **Permissive OSS to lean on:** PCL (BSD) — `RegionGrowing`, normal estimation, `SampleConsensusModelCylinder`; Open3D (MIT) — RANSAC plane + clustering; CGAL Efficient RANSAC for the Schnabel primitive set (**GPL/commercial dual — verify against this project's licensing before vendoring**). Avoid the DL repos (PyPipes/SE-PseudoGrid) for the core path; they're GPU/training and don't suit streaming.
