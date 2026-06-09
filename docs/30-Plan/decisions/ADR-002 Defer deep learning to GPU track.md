---
tags: [decision]
status: decision
updated: 2026-06-07
---

# ADR-002 — Defer deep learning to a separate offline GPU track

## Status
**Accepted** (2026-06-07)

## Context
Deep-learning semantic segmentation ([[Deep Learning Methods]], [[Plant and Piping Methods]]) gives the best accuracy and the only credible path to fine plant classes (valve, pump, flange). But the [[Method Comparison|scorecard]] is unambiguous: **no DL model streams billions of points natively** (they need in-memory neighbourhood graphs / tiling), CPU inference is slow everywhere, and they require labelled data that [[Datasets and Benchmarks|does not exist openly]] for plant scenes. This violates the [[Constraints and Scale|core constraints]].

## Decision
Do **not** put DL inference in the streaming core. If pursued, DL is an **optional, offline, GPU-only pass** (preferring **Open3D-ML, MIT**), separate from the memory-flat pipeline, operating on tiled+downsampled windows. Note the licence trap: the official **RandLA-Net repo is CC BY-NC-SA (non-commercial)** — use the MIT Open3D-ML reimplementation.

## Consequences
- **Positive:** keeps the core CPU-only and memory-flat; avoids a hard dependency on GPUs and on nonexistent labelled data; preserves the option for high-accuracy fine classes later.
- **Negative / cost:** fine classes are unavailable until this track is built; a second, different runtime/codebase to maintain if/when it lands.
- **Revisit when:** a GPU runtime is acceptable and a labelled or synthetic-from-IFC training set exists ([[Datasets and Benchmarks]]); target [[Classification Roadmap|P4]].

## Related
[[Deep Learning Methods]] · [[ADR-001 Classical-geometric-first]] · [[Recommended Approach]]
