---
tags: [decision]
status: decision
updated: 2026-06-07
---

# ADR-001 — Classical-geometric-first classification

## Status
**Accepted** (2026-06-07)

## Context
The tool must classify points under [[Constraints and Scale|CPU-only, memory-flat, streaming, no-global-kNN]] constraints on 500M–7B-point scans. The [[Method Comparison|research scorecard]] shows two camps: GPU deep learning (best accuracy, richest classes) vs. classical geometric (CPU-only, streaming-native, mostly label-free). Three facts tip the balance:
1. The tool already computes per-voxel covariance eigenvalues and discards them ([[Voxel Normals and PCA]]) — the [[Geometric Features (Weinmann)|feature set]] is almost free.
2. No open, commercially-licensed, labelled plant dataset exists ([[Datasets and Benchmarks]]).
3. Mature commercial tools (EdgeWise, Cyclone 3DR) use classical geometric extraction for pipes/steel ([[Plant and Piping Methods]]).

## Decision
Build classification as a **classical geometric pipeline first**: per-voxel [[Geometric Features (Weinmann)|geometric features]] → rule-based structural layer → optional scikit-learn Random Forest → optional primitive fitting. Deep learning is deferred to a separate optional offline GPU track ([[ADR-002 Defer deep learning to GPU track]]).

## Consequences
- **Positive:** ships incrementally with no GPU and no/low labelling; reuses the existing two-pass voxel architecture; permissive licences only; value (floor/wall/ceiling) lands in [[Classification Roadmap|P1]] before any training.
- **Negative / cost:** cannot separate fine classes (valve/pump/flange) by geometry alone; accuracy below SOTA DL; needs a cross-block reconciliation pass for large primitives.
- **Revisit when:** a GPU runtime becomes acceptable AND labelled/synthetic plant data is available — then promote the [[Deep Learning Methods|DL track]] for fine classes.

## Related
[[Recommended Approach]] · [[Classification MOC]] · [[ADR-002 Defer deep learning to GPU track]] · [[ADR-003 Retain voxel eigenvalues]]
