---
tags: [research/dl]
status: research
updated: 2026-06-07
---

# Deep Learning Methods

State-of-the-art accuracy, but **GPU-bound and label-hungry** — framed here as a *future optional offline track*, not part of the streaming core. See [[ADR-002 Defer deep learning to GPU track]]. Full source report: [[Research — Deep Learning Frameworks]].

> [!warning] The decisive constraint
> **No DL model streams billions of points natively.** Every modern network builds neighbourhood graphs / FPS / sparse-voxel hashes that assume a tile fits in memory. The realistic pattern is **tile → voxel-downsample a window to ~10⁵–10⁶ points → infer → scatter labels back**. CPU inference is slow everywhere. This conflicts with [[Constraints and Scale|memory-flat 500M–7B streaming]].

## Frameworks

| Tool | Licence | Maintained '25–26 | Pretrained | CPU inference | Notes |
|---|---|---|---|---|---|
| **Open3D-ML** | **MIT** | ✅ v0.19 (Jan 2025) | ✅ zoo (RandLA-Net, KPConv, SparseConvUnet, PointTransformer) | possible, slow | **Strongest framework match**; pairs with Open3D I/O |
| Pointcept (hosts PTv3) | MIT | ✅ very active | ✅ HF (PTv3, Sonata) | poor (CUDA/FlashAttn) | best accuracy, GPU-first |
| Torch-Points3D | BSD-3 | ❌ (2021) | ✅ (W&B) | poor | stale, version rot |
| MMDetection3D | Apache-2.0 | slowing | detection-first | poor | wrong primary task |
| PyTorch3D | BSD-3 | ✅ | — | — | rendering, **not** segmentation |

## Architectures

| Model | Licence | CPU feasibility | Large-tile capacity | Inputs |
|---|---|---|---|---|
| PointNet / PointNet++ | MIT | **good** (fixed small blocks) | low | coord (+RGB) |
| KPConv | MIT | poor | ~0.54M pts/pass | coord +feat |
| **RandLA-Net** | ⚠️ official repo **CC BY-NC-SA (non-commercial)**; use **MIT Open3D-ML reimpl** | slow | **~1.03M pts/pass** | coord + colour/intensity |
| SuperPoint Transformer | MIT | slow (GPU-first) | **best (18M+/tile)** | coord +RGB |
| Point Transformer v3 | MIT | poor | high | coord +color +normal |
| Minkowski Engine | MIT | **official CPU build** (but unmaintained 2021) | high (voxel) | sparse voxels |

> [!caution] Licence watch-out
> The **official RandLA-Net repo is CC BY-NC-SA 4.0 — non-commercial**. Use the **MIT** Open3D-ML reimplementation for anything shipped.

## Ranking (for a CPU-only streaming tool)

1. **Open3D-ML (MIT)** — if/when a GPU track is built. Real weights, intensity- and RGB-trained, CPU-capable, MIT.
2. **PointNet++ (MIT)** — most CPU-friendly baseline (fixed small blocks, pure python).
3. **SuperPoint Transformer (MIT)** — most scalable per tile; tiny model; aerial-LiDAR (DALES) weights.
4. **Pointcept / PTv3 (MIT)** — best accuracy, GPU-bound; great weights source.

## Why deferred, not rejected

DL is the only path to the **fine** plant classes (valves, pumps, flanges) that primitive fitting can't separate ([[Target Class Taxonomy|Level-2]]). But it requires GPU + labelled data ([[Datasets and Benchmarks]] shows none exists openly), so it belongs in a separate offline pass once the [[Recommended Approach|classical core]] is delivering value. See [[ADR-002 Defer deep learning to GPU track]].

## Sources

Open3D-ML https://github.com/isl-org/Open3D-ML · Pointcept https://github.com/Pointcept/Pointcept · SuperPoint Transformer https://github.com/drprojects/superpoint_transformer · RandLA-Net https://github.com/QingyongHu/RandLA-Net · PointNet++ https://github.com/yanx27/Pointnet_Pointnet2_pytorch

## Related

- [[Plant and Piping Methods]] · [[Method Comparison]] · [[Datasets and Benchmarks]] · [[Research — Deep Learning Frameworks]]
