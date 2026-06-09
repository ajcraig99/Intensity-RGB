---
tags: [project]
status: current
updated: 2026-06-07
---

# Streaming I/O Model

All point data flows through `io/e57_clone.py` (a thin layer over the vendored `pye57` fork) one **block** at a time. This is what keeps the tool [[Constraints and Scale|memory-flat]] on billion-point scans.

## The block

A block is a `Dict[str, FieldBuffer]` — one entry per declared field in the scan's `points` CompressedVector. `ScanReader.iter_blocks(block_size)` yields blocks of up to `block_size` points (default 1,000,000).

### `FieldBuffer`
| Attribute | Meaning |
|---|---|
| `name` | field name, e.g. `cartesianX`, `intensity`, `colorRed` |
| `numpy_array` | a **view** into a reusable per-block buffer — **copy if you retain it past the next block** |
| `prototype_node` | the libE57 node defining type/scale/offset; preserved on write so dtype + descaling round-trip |
| `descaled` | whether `pye57` has already descaled the raw integer to float |

### Fields present per point
- **Standard:** `cartesianX/Y/Z` (f64, descaled from ScaledInteger), `intensity` (optional), `colorRed/Green/Blue` (uint8/uint16, optional), `rowIndex/columnIndex` (organized scans only).
- **Vendor extensions:** e.g. `nor:normalX/Y/Z` (Leica) or `normalX/Y/Z`. The writer walks unknown subtrees generically (Float / Integer / ScaledInteger / String / Blob / Structure / Vector / CompressedVector) — never assumes the eight canonical Recap fields.

## Read → transform → write

```mermaid
sequenceDiagram
    participant R as E57CloneReader
    participant P as pipeline.py
    participant W as E57CloneWriter
    R->>P: iter_blocks() yields Dict[str, FieldBuffer]
    P->>P: rewrite colorRed/Green/Blue in place
    P->>W: write_block(block) -> int (points written)
    Note over W: preserves dtype, scale/offset,<br/>vendor subtrees; sums throughput
```

`write_block` **must return its per-block count** or callers can't sum throughput (a `pye57` fork gotcha).

## Two-pass mode

`pipeline_bake_normals` re-opens the reader for a second pass (see [[Architecture]]). Pass 1 builds the [[Voxel Normals and PCA|voxel model]] in RAM; Pass 2 streams again and writes. RAM is bounded by the voxel grid (scene AABB ÷ voxel size), **not** total points.

## Extension point — writing a new scalar field

To emit a per-point [[ADR-005 Per-point classification scalar in E57|classification scalar]] into the output `.e57`, a new `FieldBuffer` would be added to the block dict before `write_block`. **Caveat:** V2.0 only *rewrites existing* fields; the source file may not declare a prototype node for a new `classification` field, so synthesising one needs codec work in the `pye57` fork (or a sidecar file as fallback). This is the open question in [[ADR-005 Per-point classification scalar in E57]].

## Related

- [[Architecture]] · [[Module Map]] · [[Voxel Normals and PCA]] · [[Constraints and Scale]]
