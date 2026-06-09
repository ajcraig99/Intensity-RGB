---
tags: [decision]
status: decision
updated: 2026-06-07
---

# ADR-005 — Per-point classification scalar in the output `.e57`

## Status
**Proposed / open question** (2026-06-07) — to be resolved in [[Classification Roadmap|P2]].

## Context
[[Classification Colouring]] decides a class per voxel, looked up per point in Pass 2. Beyond recolouring the RGB columns, it is valuable to persist the **class id itself** as a per-point scalar in the output `.e57` (so downstream tools can filter/recolour by class). But the [[Streaming IO Model|I/O substrate]] today only **rewrites existing** fields: `E57CloneWriter` preserves each field's `prototype_node` from the source. A source scan typically has **no prototype node for a `classification` field**, so emitting one requires synthesising a new ScaledInteger/Float node in the codec — work in the vendored `pye57` fork. (The standard E57 field for this is `cartesianInvalidState`-style scalars; `classification` is a common LAS-style attribute but not guaranteed present.)

## Decision
Two-step, lowest-risk-first:
1. **Ship a sidecar fallback first** — write class ids to a compact sidecar file (e.g. per-point `.npy`/parquet keyed by scan+index, or a `.las`/`.csv`) alongside the recoloured `.e57`. No codec changes; unblocks P2.
2. **Then add a native E57 scalar** — extend the `pye57` fork to synthesise a prototype node for a new `classification` field and emit it. Gate behind a flag; round-trip test it.

## Consequences
- **Positive:** delivers persisted classes immediately via sidecar; defers the riskier codec work; keeps the byte-faithful clone contract intact for non-classification modes.
- **Negative / cost:** sidecar is a second artifact to manage; native scalar touches the vendored fork (the [[Module Map|gotcha-prone]] binding layer) and needs its own fidelity tests.
- **Revisit when:** P2 implementation reveals whether common source scans already declare a usable scalar prototype (some Leica/FARO exports do), which could let step 2 reuse an existing node.

## Related
[[Streaming IO Model]] · [[Classification Colouring]] · [[Classification Roadmap]] · [[Project Overview]]
