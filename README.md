# Intensity-RGB V2.0

Streaming `.e57` point-cloud recolour tool. Replaces each point's photographic RGB with values derived from the per-point intensity scalar, so downstream tools that can't render intensity-shaded clouds natively (Autodesk Recap → Inventor, etc.) still display intensity-based colouring once the file is re-imported. V2.0 adds voxel-resolution Lambertian shading on top of the intensity colour so geometric structure remains visible. All processing is CPU-streaming — files are read and written one block at a time, so memory stays flat regardless of point count.

## Install from source

Linux / Windows:

```sh
pip install -e vendor/pye57/
pip install -e .
```

The vendored `pye57` fork ships the streaming + cloning substrate the pipeline depends on, so it must be installed in editable mode from `vendor/` rather than from PyPI.

## Install from bundle

A self-contained PyInstaller bundle (no Python install required) is produced by `build/build.sh` on Linux and `build/build.ps1` on Windows.

- Linux: download `dist/Intensity-RGB-linux-x86_64.zip`, unzip, run `./Intensity-RGB-linux-x86_64/Intensity-RGB`.
- Windows: the `.ps1` script is shipped but has not yet been validated on real Windows hardware (see V2.0 limitations).

## CLI usage

```sh
# 1. Byte-faithful streaming clone (writer smoke test).
python -m intensity_rgb.cli clone \
    --input  scan.e57 \
    --output scan_clone.e57

# 2. Production-path smoke: rewrite every RGB to a constant.
python -m intensity_rgb.cli recolor-test \
    --input  scan.e57 \
    --output scan_red.e57 \
    --rgb 255,0,0

# 3. Bake intensity → RGB (intensity-only, no shading).
python -m intensity_rgb.cli bake \
    --input  scan.e57 \
    --output scan_intensity.e57 \
    --auto-range --yes \
    --brightness 70

# 4. Bake with voxel-resolution Lambertian shading.
python -m intensity_rgb.cli bake \
    --input  scan.e57 \
    --output scan_shaded.e57 \
    --auto-range --yes \
    --shading lambertian \
    --voxel-size 0.5 \
    --light-dir 0,90 \
    --ambient 0.3
```

`--intensity-range MIN,MAX` overrides the auto-range estimate (auto-range samples the file and confirms before running unless `--yes` is given). `bake --help` lists all shading / orientation tunables (`--three_point`, `--normal_as_color`, `--ground-color`, `--sky-color`, `--up-vector`, `--invert-globally`, `--min-support`, `--planarity-threshold`, …).

## GUI usage

```sh
python -m intensity_rgb
```

PySide6 desktop app: pick input + output, inspect the capability panel (header-only inspection — no point read), pick shading mode, watch the worker progress, cancel mid-run. Settings persist across launches via QSettings.

Screenshot: TBD (will be added once V2.0 has been exercised on the user's workstation).

## V2.0 limitations

- **Recap visual confirmation has not been run on V2.0 output.** The G3 human gate (open a baked file in Recap and eyeball the shading) is deferred per the auto-mode build plan. The Mode-A clone path is round-trip equal at byte level (G1a, 8 tests), but Recap-side rendering of the baked file has not been spot-checked.
- **Windows bundle has not been smoke-tested on real Windows hardware.** `build/build.ps1` ships as-configured. The G4 human gate (run the bundle on a Windows box) is deferred to the user's first hardware run.
- **G2 production-scale numbers are TBD.** Peak RSS, throughput (M points/sec), and end-to-end completion time on 100M–7B-point fixtures will be populated by the user once V2.0 runs on the workstation. Streaming I/O means the algorithm is *expected* to be flat in RSS, but that has not yet been measured on production-scale files.
- **Viewpoint-free normal orientation is fundamentally heuristic.** A connected-component analysis picks a sign per component using an up-vector prior; multi-component scenes with conflicting orientations may need the `--invert-globally` flag or the per-component invert toggles in the GUI.
- **No-RGB inputs are unsupported.** Files lacking `colorRed/colorGreen/colorBlue` fields fail fast with `UnsupportedFileError`. RGB-injection for no-RGB inputs is scoped for V2.1.
- **macOS is out of scope.** `pye57` has no macOS wheels and our fork does not ship them either.
- **GPU acceleration, interactive 3D preview, view-dependent shading (Recap-style Eye-Dome Lighting), `.pts` I/O, writing modified normals back to the `.e57`, adaptive voxel subdivision, and multi-scan parallelism are all out of scope for V2.0.** Some may land in V2.1+.

## How to report a bug

File an issue with a description of the input file and the capability report attached. To get the capability report:

```sh
python -m intensity_rgb.cli   # then pick the file in the GUI; copy the capability panel text
```

The capability report includes header-only metadata (scan count, point counts, declared fields, intensity range, bounds) without reading any point data, so it is safe to attach even for confidential scans whose contents you cannot share.
