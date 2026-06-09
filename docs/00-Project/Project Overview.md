---
tags: [project]
status: current
updated: 2026-06-07
---

# Project Overview

**Intensity-RGB V2.0** is a streaming `.e57` point-cloud recolour tool. The pipeline reads an input `.e57` block-at-a-time, replaces the photographic RGB columns with values derived from each point's **intensity** scalar (HSV → RGB), optionally **shades** the result against voxel-resolution Lambertian (or three-point / normal-as-colour) lighting computed from chunked PCA normals, and writes the modified blocks straight through to a new `.e57`.

Processing is **CPU-only and memory-flat** — point count is not bounded by RAM (see [[Constraints and Scale]]). The pipeline is exposed as both a `PySide6` desktop GUI and an `argparse` CLI; both call the same Qt-free `pipeline.py` (see [[Architecture]]).

## Why it exists

Downstream tools that can't render intensity-shaded clouds natively (e.g. Autodesk Recap → Inventor) still display intensity-based colouring once a recoloured file is re-imported. V2.0 adds voxel-resolution Lambertian shading on top of the intensity colour so geometric structure stays visible.

## What it does today

| Capability | Note |
|---|---|
| Byte-faithful streaming clone | Integrity contract for the writer path (G1a, 8 tests) |
| Intensity → RGB bake | [[Intensity Colouring]] |
| Voxel PCA normals + shading | [[Normal-based Colouring]], [[Voxel Normals and PCA]] |
| Header-only capability inspection | `capability.py` — no point read |

## Where it's going

The strategic goal is to add more colouring dimensions and ultimately **semantic classification** focused on plant elements. See [[Recolour Roadmap]] and [[Classification Colouring]].

## V2.0 status & known limitations

- **Recap visual confirmation not yet run on V2.0 output** — the human "eyeball the shading in Recap" gate is deferred. The Mode-A clone path is byte-equal (G1a), but Recap-side rendering of a baked file has not been spot-checked.
- **Windows bundle not smoke-tested on real hardware** — `build/build.ps1` ships as-configured.
- **Production-scale numbers (peak RSS, throughput, completion time) are TBD** on 100M–7B-point fixtures.
- **Viewpoint-free normal orientation is heuristic** — see [[Normal-based Colouring]]; multi-component scenes may need `--invert-globally` or per-component toggles.
- **No-RGB inputs unsupported** — files lacking `colorRed/Green/Blue` fail fast with `UnsupportedFileError`. RGB-injection is scoped for V2.1 — this directly affects how a [[ADR-005 Per-point classification scalar in E57|classification scalar]] could be written.
- **macOS out of scope** (no `pye57` wheels). GPU, interactive 3D preview, view-dependent shading, `.pts` I/O, and writing modified normals back are out of scope for V2.0.

## Related

- [[Architecture]] · [[Module Map]] · [[Streaming IO Model]] · [[Constraints and Scale]]
