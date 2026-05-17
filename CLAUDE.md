# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Intensity-RGB V2.0 is a streaming `.e57` point-cloud recolour tool. The pipeline reads an input `.e57` block-at-a-time, replaces the photographic RGB columns with values derived from each point's intensity scalar (HSV → RGB), optionally shades the result against voxel-resolution Lambertian (or three-point / normal-as-colour) lighting computed from chunked PCA normals, and writes the modified blocks straight through to a new `.e57`. Processing is CPU-only and memory-flat — point count is not bounded by RAM. The pipeline is exposed as both a `PySide6` desktop GUI and an `argparse` CLI; both call the same Qt-free `pipeline.py`.

## Module map

- `intensity_rgb/io/e57_clone.py` — `E57CloneReader` / `E57CloneWriter` / `FieldBuffer` streaming I/O over the vendored `pye57` cloning substrate.
- `intensity_rgb/processing/intensity.py` — vectorised intensity → HSV → RGB.
- `intensity_rgb/processing/voxel_normals.py` — chunked voxel accumulator + PCA per-voxel normal estimation.
- `intensity_rgb/processing/shading.py` — Lambertian, three-point, and normal-as-colour shaders.
- `intensity_rgb/processing/orientation.py` — viewpoint-free per-component normal orientation with up-vector prior + optional global invert.
- `intensity_rgb/pipeline.py` — orchestration: clone / bake-intensity / bake-normals (two-pass when shading is on). Qt-free; both UI and CLI call into it.
- `intensity_rgb/capability.py` — header-only file inspection (scan count, fields, intensity range, bounds) without touching point data.
- `intensity_rgb/cli.py` — argparse entrypoint exposing `clone`, `recolor-test`, `bake`.
- `intensity_rgb/app.py` — PySide6 `QMainWindow`: capability panel, job UI, QSettings persistence, per-component invert toggles.
- `intensity_rgb/worker.py` — `QThread` wrapper around the pipeline with cancellation support.
- `vendor/pye57/` — forked `davidcaron/pye57` extended with the streaming + cloning substrate (`pye57.streaming`, `pye57.cloning`). Zero added C++. See `vendor/pye57/NEW_API.md`.

## Run

```sh
# CLI
python -m intensity_rgb.cli clone --input scan.e57 --output scan_clone.e57
python -m intensity_rgb.cli bake  --input scan.e57 --output scan_baked.e57 \
    --auto-range --yes --shading lambertian --voxel-size 0.5

# GUI
python -m intensity_rgb

# Linux PyInstaller bundle (Windows: build/build.ps1)
bash build/build.sh
```

Install: `pip install -e vendor/pye57/` then `pip install -e .` (the vendored fork must be installed in editable mode before the package).

## Test

```sh
pytest tests/
```

106 tests total: 66 numpy module tests (intensity / voxel_normals / shading / orientation), 8 G1a clone-fidelity tests (the M1 gate — Mode A byte-faithful clone is the integrity contract for the writer path), 20 pipeline + capability tests, 7 UI tests, 5 settings tests.

## Gotchas

The vendored `pye57` fork patches four pybind11 sharp edges that any future binding work will hit again. `Node.type()` is not exposed on cast subclasses (`FloatNode`, `IntegerNode`, etc.) — call `.type()` on the raw `Node` returned by `Node.get(i)`, then re-cast for typed accessors. `libe57.CompressedVectorNode(node)` rejects an already-cast `CompressedVectorNode` with a pybind11 dynamic_cast error; guard re-wraps with `isinstance`. `ScanBlockWriter.write_block` must return its per-block count or callers cannot sum throughput. Walk unknown vendor-extension subtrees with the generic `Node.type()` dispatch — Float / Integer / ScaledInteger / String / Blob / Structure / Vector / CompressedVector — never assume the eight canonical Recap fields. See `vendor/pye57/NEW_API.md` for the full substrate API.
