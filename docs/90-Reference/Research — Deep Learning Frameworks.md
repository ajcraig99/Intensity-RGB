---
tags: [reference, research/dl]
status: reference
updated: 2026-06-07
---

# Research — Deep Learning Frameworks (verbatim)

> Verbatim research-agent output. Synthesized version: [[Deep Learning Methods]]. See [[90-Reference/README|README]].

---

# Deep-Learning Frameworks & Pretrained Models for 3D Point-Cloud Semantic Segmentation — Research Report (June 2026)

## Context & hard constraints

Target deployment is **CPU-only**, processing `.e57` scans of **500M–7B points**, **streamed block-at-a-time**, with **no global kNN possible in RAM**. This is the decisive lens: nearly every modern point-cloud segmentation network was designed for GPU and assumes the whole scene (or a cropped tile) fits in memory so it can build neighbourhood graphs / FPS / sparse-voxel hashes globally. None of them natively stream a multi-billion-point cloud. The realistic integration pattern is **tile → voxel-downsample a spatial window to ~10^5–10^6 points → infer → scatter labels back**. The tools differ mostly in how painful CPU inference and tiling are.

## Frameworks (integration platforms)

### Open3D-ML
- Repo: https://github.com/isl-org/Open3D-ML
- License: **MIT** (confirmed in LICENSE).
- Last activity: Actively maintained; v0.19.0 released **Jan 2025**.
- Pretrained: Yes, real downloadable zoo. Seg: **RandLA-Net, KPConv, SparseConvUnet, PointTransformer**. Detection: PointPillars, PointRCNN.
- Classes/datasets: SemanticKITTI (~19, outdoor LiDAR), S3DIS (13, indoor), Semantic3D (8, outdoor), Toronto-3D, Paris-Lille-3D, ScanNet (20, indoor).
- Hardware: PyTorch 2.0 / TF 2.13; CUDA optional. CPU path exists via PyTorch backend, slow.
- Inputs: coords always; RGB and/or intensity per the dataset weights were trained on (SemanticKITTI uses intensity; S3DIS uses RGB). No fixed block size; pipelines voxelize internally.
- Suitability: **Strongest framework match** — MIT, real weights, intensity- and RGB-trained options, CPU-capable, pairs with Open3D for big-cloud I/O.

### Pointcept (SOTA research codebase; hosts PTv3)
- Repo: https://github.com/Pointcept/Pointcept — License **MIT**.
- Last activity: Extremely active **2025–2026** (Utonia ICML'26, Concerto NeurIPS'25, Sonata CVPR'25).
- Models: PTv1/v2/**v3**, SparseUNet (SpConv + Minkowski), OA-CNNs, SPVCNN, OctFormer, Swin3D, PointGroup.
- Pretrained: Yes via HuggingFace (PTv3, Sonata, Concerto) — ScanNet, S3DIS, SemanticKITTI, nuScenes, Waymo.
- Hardware: GPU-centric; PTv3 uses FlashAttention (CUDA ≥11.6), can disable (`enable_flash=False`) but CPU impractical at scale.
- Inputs: coord + optional color + optional normal.
- Suitability: Best accuracy + permissive license, but firmly GPU-oriented. Great source of architectures/weights for a future GPU path.

### Torch-Points3D
- Repo: https://github.com/torch-points3d/torch-points3d — License **BSD-3-Clause**.
- Last activity: **Dormant** — v1.3.0 (Apr 2021), not updated for current PyTorch.
- Models: PointNet/++, KPConv, RandLA-Net, PointCNN, RSConv, Minkowski, PVCNN, MS-SVConv, VoteNet, PointGroup; PretrainedRegistry (W&B, mostly S3DIS).
- Suitability: Broad but stale; version rot makes 2026 setup painful. Superseded by Pointcept/Open3D-ML.

### MMDetection3D (OpenMMLab)
- Repo: https://github.com/open-mmlab/mmdetection3d — License **Apache-2.0**.
- Last activity: Maintained but org slowed 2024–25.
- Focus: **3D object detection** first (PointPillars, CenterPoint, VoteNet); some seg (PointNet++, MinkUNet, Cylinder3D).
- Suitability: Wrong primary task + heavy mmcv stack. Not recommended for a recolor tool.

### PyTorch3D (FAIR)
- Repo: https://github.com/facebookresearch/pytorch3d — License **BSD-3-Clause**.
- Focus: Differentiable **rendering**, meshes, NeRF, camera ops — **not segmentation, ships no seg weights**.
- Suitability: **Not applicable** to intensity/semantic recolor.

## Architectures / standalone implementations

### PointNet / PointNet++
- Repos: https://github.com/fxia22/pointnet.pytorch , https://github.com/yanx27/Pointnet_Pointnet2_pytorch (maintained, pretrained ModelNet/ShapeNet/S3DIS). **MIT**.
- Inputs: coords (+ optional RGB); fixed small blocks (e.g. 4096 pts) — naturally tile-friendly.
- Hardware: Lightweight; **CPU inference genuinely feasible**. Accuracy dated.
- Suitability: **Most CPU-friendly / lowest-memory**; safest CPU-only baseline.

### KPConv / KPConv-PyTorch
- Repos: https://github.com/HuguesTHOMAS/KPConv , https://github.com/HuguesTHOMAS/KPConv-PyTorch — **MIT**.
- Last activity: Issues active into late 2024; code older. Also bundled in Open3D-ML / Torch-Points3D with weights.
- Datasets: S3DIS, ScanNet, Semantic3D, NPM3D, SemanticKITTI.
- Hardware: GPU-oriented; **~0.54M points max per pass** (memory-heavy neighborhoods), custom C++ neighbor ops.
- Inputs: coords + optional RGB/intensity.
- Suitability: Strong accuracy, intensity-capable, but heavy; consume via Open3D-ML rather than standalone.

### RandLA-Net
- Repo (official, TF): https://github.com/QingyongHu/RandLA-Net — License **CC BY-NC-SA 4.0 → NON-COMMERCIAL ⚠**.
- The **Open3D-ML reimplementation is MIT** — use that for any commercial product.
- Datasets: SemanticKITTI, Semantic3D, S3DIS, Toronto-3D, NPM3D.
- Hardware: Built for **large-scale** clouds via random sampling — **highest per-pass capacity (~1.03M pts)**. GPU-targeted; CPU slow.
- Inputs: **3D coords + color only** (no normals); intensity usable as the feature channel.
- Suitability: Best architecture for large tiles + lightest neighborhood scheme — via the **MIT Open3D-ML version**.

### SuperPoint Transformer (SPT) / SuperCluster / EZ-SP
- Repo: https://github.com/drprojects/superpoint_transformer — **MIT**.
- Last activity: Very active — EZ-SP (ICRA'26, Jan 2026), GPU-partition release Nov 2025.
- Pretrained (Zenodo): S3DIS 6-fold (76.0% mIoU), KITTI-360, **DALES (aerial LiDAR)**, ScanNet.
- Hardware: **Most scalable** (7.8 km² / 18M-pt tile in ~10 s on 1 GPU; only ~212k params), 64 GB RAM recommended. GPU-first; superpoint preprocessing is CPU-heavy.
- Inputs: coords + RGB (+ optional geometric features); intensity usable as a channel.
- Suitability: **Best for very large scenes**, MIT, tiny model. Top candidate if a GPU is ever available; CPU slow but the superpoint reduction helps more than any other method here.

### PointNeXt
- Repo: https://github.com/guochengqian/PointNeXt — **MIT**.
- Last activity: **Inactive since ~2022**; CUDA-11.3 + custom CUDA ops.
- Pretrained (Google Drive): S3DIS, ScanObjectNN, ModelNet40, ShapeNetPart.
- Suitability: Good indoor accuracy but stale + poor CPU story. Not recommended.

### Point Transformer v1/v2/v3
- Repo: https://github.com/Pointcept/PointTransformerV3 (and in Pointcept) — **MIT**.
- SOTA accuracy (PTv3 CVPR'24 oral; 2024 Waymo seg winner). FlashAttention/CUDA-centric — CPU impractical at scale.
- Suitability: Best-in-class accuracy, MIT, but GPU-bound.

### Minkowski Engine (sparse convs)
- Repo: https://github.com/NVIDIA/MinkowskiEngine — **MIT**.
- Last activity: **Inactive** — v0.5.4 (May 2021); known GCC/CUDA/PyTorch build pain.
- CPU: **Explicitly supports a CPU-only build** (rare among these libs).
- Inputs: sparse voxelized tensors (coords + features); you pick voxel size — naturally tileable.
- Suitability: Notable CPU build but unmaintained and hard to compile in 2026. Live alternative **SpConv** (https://github.com/traveller59/spconv, Apache-2.0, maintained) is CUDA-only. Prefer SparseUNet via Pointcept/Open3D-ML over building Minkowski directly.

## Comparison table

| Tool / Method | Type | License | Maintained '25–26 | Pretrained | Predicts (datasets) | CPU inference | Large-tile capacity | Inputs |
|---|---|---|---|---|---|---|---|---|
| **Open3D-ML** | Framework | MIT | Yes (v0.19) | Yes (zoo) | SemKITTI, S3DIS, Sem3D, ScanNet | Possible, slow | Model-dep. | coord +RGB/intensity |
| Pointcept | Framework | MIT | Yes (very) | Yes (HF) | ScanNet, S3DIS, SemKITTI, nuScenes | Poor (CUDA) | High | coord +color +normal |
| Torch-Points3D | Framework | BSD-3 | No (2021) | Yes (W&B) | S3DIS etc. | Poor | Med | coord +feat |
| MMDetection3D | Framework | Apache-2.0 | Slowing | Yes (det.) | KITTI/nuScenes (detection) | Poor | n/a | LiDAR |
| PyTorch3D | Rendering | BSD-3 | Yes | N/A | — | — | — | meshes |
| PointNet/++ | Arch | MIT | Yes (comm.) | Yes | S3DIS, ModelNet, ShapeNet | **Good** | Low (blocks) | coord (+RGB) |
| KPConv | Arch | MIT | Semi ('24) | Yes (via fw) | S3DIS, ScanNet, Sem3D, NPM3D | Poor | ~0.54M/pass | coord +feat |
| RandLA-Net (official) | Arch | **CC BY-NC-SA ⚠** | No | Yes | SemKITTI, Sem3D, S3DIS | Slow | **~1.03M/pass** | coord +color |
| RandLA-Net (Open3D-ML) | Arch | **MIT** | Yes | Yes | SemKITTI, S3DIS, Sem3D | Possible, slow | High | coord +color/intensity |
| **SuperPoint Transformer** | Arch | MIT | Yes (very) | Yes (Zenodo) | S3DIS, KITTI-360, DALES, ScanNet | Slow (GPU-first) | **Best (18M+/tile)** | coord +RGB |
| PointNeXt | Arch | MIT | No (~2022) | Yes | S3DIS, ScanObjectNN | Poor (CUDA) | Med | coord +feat |
| Point Transformer v3 | Arch | MIT | Yes | Yes (HF) | ScanNet, SemKITTI | Poor | High | coord +color +normal |
| Minkowski Engine | Sparse conv | MIT | No (2021) | via fw | — | **Official CPU build** | High (voxel) | sparse voxels |
| SpConv | Sparse conv | Apache-2.0 | Yes | via fw | — | CUDA-only | High | sparse voxels |

## Recommendation ranking (CPU-only, streaming `.e57` recolor)

1. **Open3D-ML (MIT)** — primary pick. Permissive, real downloadable weights, both intensity-trained (SemanticKITTI) and RGB-trained (S3DIS/Semantic3D) options, CPU-capable PyTorch backend, pairs naturally with Open3D for reading/voxelizing big clouds. Wrap in a tile→downsample→infer→scatter loop. RandLA-Net inside it is best for large tiles and needs only coords+color/intensity (no normals) — well-suited to an intensity-driven tool.
2. **PointNet++ (yanx27, MIT)** — realistic CPU baseline. Pure-Python, fixed small blocks, lowest memory, genuinely runs on CPU. Lower accuracy but cleanest fit for strict block streaming.
3. **SuperPoint Transformer (MIT)** — plan toward this if a GPU ever appears. Most scalable per tile, tiny model, active into 2026, has aerial-LiDAR (DALES) weights relevant to survey scans.
4. **Pointcept / PTv3 (MIT)** — best accuracy and a great source of weights/architectures, but GPU-bound; keep for a future GPU path.
5. Everything else: MMDetection3D (wrong task), PyTorch3D (rendering only), Torch-Points3D / PointNeXt / Minkowski (unmaintained or build-fragile), and the **official RandLA-Net repo — avoid, CC BY-NC-SA non-commercial; use the Open3D-ML MIT reimplementation**.

### Key caveats
- **No DL model streams billions of points natively** — you must tile + voxel-downsample to a ~10^5–10^6-pt budget per window; global kNN/FPS over the full cloud is off the table (matches your constraint).
- **CPU inference is slow everywhere** — only PointNet/++ and Minkowski's CPU build are built to tolerate it; budget minutes-to-hours per large scan.
- **License watch-out:** official RandLA-Net is **non-commercial**; the Open3D-ML version is MIT.
- **Inputs:** RandLA-Net and PointNet need only coords (+ one color/intensity channel) — best aligned with an intensity recolor pipeline. KPConv/PTv3 can take normals (which you already compute via PCA) as extra accuracy features.

Sources: [Open3D-ML](https://github.com/isl-org/Open3D-ML), [Open3D-ML LICENSE](https://github.com/isl-org/Open3D-ML/blob/main/LICENSE), [Pointcept](https://github.com/Pointcept/Pointcept), [PointTransformerV3](https://github.com/Pointcept/PointTransformerV3), [Torch-Points3D](https://github.com/torch-points3d/torch-points3d), [MMDetection3D](https://github.com/open-mmlab/mmdetection3d), [PyTorch3D](https://github.com/facebookresearch/pytorch3d), [PointNet++ (yanx27)](https://github.com/yanx27/Pointnet_Pointnet2_pytorch), [KPConv-PyTorch](https://github.com/HuguesTHOMAS/KPConv-PyTorch), [RandLA-Net (official)](https://github.com/QingyongHu/RandLA-Net), [SuperPoint Transformer](https://github.com/drprojects/superpoint_transformer), [PointNeXt](https://github.com/guochengqian/PointNeXt), [MinkowskiEngine](https://github.com/NVIDIA/MinkowskiEngine).
