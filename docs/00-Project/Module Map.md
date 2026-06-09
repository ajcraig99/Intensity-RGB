---
tags: [project]
status: current
updated: 2026-06-07
---

# Module Map

Per-module reference for the `intensity_rgb` package. File references point at the functions that matter for extending the tool toward [[Classification Colouring|classification]].

## Wave 1 — pure-numpy processing

### `processing/voxel_normals.py` — voxel accumulator + PCA normals
The single most important module for classification. See the dedicated note [[Voxel Normals and PCA]].
- `class VoxelAccumulator` — `add_block(xyz)` accumulates **10 moments** per voxel; `finalize()` dilates under-supported voxels then runs `finalize_chunk` per 32³ chunk.
- `finalize_chunk(chunk, min_support, planarity_threshold)` — compact-then-`eigh`: builds covariance from moments, `np.linalg.eigh`, takes smallest eigenvector as normal, computes `planarity = 1 - λ0/λ1`. **Eigenvalues are discarded** after this (see [[ADR-003 Retain voxel eigenvalues]]).
- `class FrozenChunk` — Pass-2 lookup table: `normals (C,C,C,3) f32`, `quality (C,C,C) bool`, `means (C,C,C,3) f32`.
- `lookup_normals(frozen, origin, voxel_size, chunk_size, xyz)` → `(normals, quality)` — vectorised per-point lookup.

### `processing/intensity.py` — intensity → HSV → RGB
- `bake_rgb_from_intensity(intensity, *, max_inten, brightness)` → `(N,3) uint8`. Three normalisation sentinels (`max_inten ∈ {255, 4096, 2048}`). See [[Intensity Colouring]].

### `processing/shading.py` — three shaders
- `lambertian(base, normals, quality, *, light_dir, ambient, ground_color, sky_color)` — hemispherical ambient + `max(0, N·L)`.
- `three_point(base, normals, quality, *, key/fill/back dirs+intensities, ambient)`.
- `normal_as_color(normals, quality, *, fallback_color)` — debug viz `(n+1)*127.5`.

### `processing/orientation.py` — viewpoint-free normal orientation
- `orient_normals(frozen_chunks, *, up_vector, top_k, voxel_size)` → `OrientationResult` — union-find connected components, BFS sign propagation from an up-vector prior.
- `invert_component(frozen_chunks, component)` — in-place flip for the GUI per-component toggle.

## Wave 2 — streaming I/O

### `io/e57_clone.py` — clone reader/writer
See [[Streaming IO Model]] for the block data model.
- `class E57CloneReader` / `ScanReader.iter_blocks(block_size)` — yields `Dict[str, FieldBuffer]`.
- `class E57CloneWriter` / `ScanWriter.write_block(block) -> int` — preserves dtype, scale/offset, vendor subtrees.
- `class FieldBuffer` — `name`, `numpy_array` (a **view** into a reusable buffer — copy if retained), `prototype_node`, `raw_bytes`, `descaled`.
- `identity_transform`, `constant_rgb_transform(rgb)`, `clone_file(...)`.

## Wave 3 — orchestration

### `pipeline.py`
- `pipeline_clone(...)`, `pipeline_bake_intensity(...)`, `pipeline_bake_normals(...)` → `PipelineResult`.
- `get_aabb_and_intensity_range(reader, ...)` — Pass-0 sampling for voxel-grid origin + auto intensity range.
- `class ProgressEvent`, `class PipelineResult`, `class PipelineCancelled`.

### `capability.py` — header-only inspection
- `inspect_file(path, ...)` → `CapabilityReport` (scan count, point counts, AABB, RGB/organized/normals presence, RAM upper bounds, per-mode verdicts). No payload read.
- `estimate_touched_chunks(reader, ...)` — optional sampling pre-pass.

### `cli.py` — argparse entrypoint
- Subcommands `clone`, `recolor-test`, `bake`. `bake` exposes intensity range, brightness, `--shading`, voxel/chunk/support/planarity tunables, light dir, colours, up-vector, `--invert-globally`.

## Wave 4 — GUI

### `app.py` — `MainWindow`
QMainWindow with Input / Capability / Output / Color+Shading / Job / Log sections; QSettings persistence; per-component invert toggles.

### `worker.py` — `PipelineWorker(QObject)`
QThread worker; slot `run_job(spec)`, `cancel()`; signals for progress, throughput, peak RSS, voxel quality, ETA, log, stage, component info.

## Tests (`tests/`)
106 tests: 66 numpy module tests, 8 clone-fidelity (the M1 gate), 20 pipeline+capability, 7 UI, 5 settings. Fixtures via `tests/synthetic_e57.py`.

## Related

- [[Architecture]] · [[Streaming IO Model]] · [[Voxel Normals and PCA]]
