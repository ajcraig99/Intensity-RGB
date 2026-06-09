---
tags: [recolour-mode]
status: planned
updated: 2026-06-07
---

# Classification Colouring (planned — strategic goal)

The strategic prize: colour each point by its **semantic class**, focused on industrial-**plant** elements. This note is the hub linking the recolour pipeline to the research and the plan.

## Target classes

> pipes · pumps · beams · columns · walls · floors · vessels / tanks · valves · flanges · ducts · cable trays

The trainable Level-1 set and how it maps to IFC/Uniclass is defined in [[Target Class Taxonomy]].

## The core tension

Classification is the **most demanding** colouring mode against the [[Constraints and Scale|hard constraints]]: CPU-only, memory-flat, streaming, no global kNN. That tension is what the entire [[Classification MOC|research effort]] resolves. The short version:

- **Deep-learning semantic segmentation** ([[Deep Learning Methods]], [[Plant and Piping Methods]]) gives the best accuracy and the richest classes (valves, pumps, flanges) — but every viable model is **GPU-bound and label-hungry**, and no method streams billions of points natively. → a future offline GPU track, [[ADR-002 Defer deep learning to GPU track]].
- **Classical geometric methods** ([[Classical Geometric Methods]]) — per-voxel [[Geometric Features (Weinmann)|geometric features]] + rules / a Random Forest, plus RANSAC primitive fitting — are **CPU-only, streaming-native, and mostly label-free**. They map directly onto the [[Voxel Normals and PCA|voxel PCA the tool already runs]]. → the [[Recommended Approach|recommended path]].

## How it plugs into the pipeline

```mermaid
flowchart LR
    P1[Pass 1 voxel accumulate] --> F[per-voxel features<br/>+ eigenvalues retained]
    F --> CL[classify voxel -> class id]
    CL --> P2[Pass 2 lookup]
    P2 --> COL[map class id -> colour LUT]
    COL --> W[write RGB block]
```

Class is decided **per voxel** (consistent, bounded memory — see [[Constraints and Scale]]), looked up per point in Pass 2 exactly like normals are today, then mapped through a class→colour LUT. Optionally the class id is also written as a [[ADR-005 Per-point classification scalar in E57|per-point scalar]] into the output `.e57`.

## Plan

See [[Recommended Approach]] for the pipeline design and [[Classification Roadmap]] for the phased rollout (P0 retain eigenvalues → P1 rule-based floor/wall/ceiling → P2 colour-by-class + scalar output → P3 Random Forest → P4 primitive fitting / DL track).

## Related

- [[Recommended Approach]] · [[Target Class Taxonomy]] · [[Classification MOC]] · [[Recolour Roadmap]]
