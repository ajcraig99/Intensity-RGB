---
tags: [recolour-mode]
status: planned
updated: 2026-06-07
---

# Elevation Colouring (planned)

The cheapest next colouring mode and a deliberate warm-up for [[Classification Colouring|classification]] — it establishes the "colour-by-a-scalar with a ramp + legend" UI pattern that classification reuses.

## Design sketch

Elevation is a direct function of `cartesianZ`, present in every [[Streaming IO Model|block]]. No voxel grid, no second pass.

1. Pass 0 (already exists): [[Module Map|get_aabb_and_intensity_range]] returns `aabb_min`/`aabb_max`, so the Z range is known before streaming — or accept an explicit `--elevation-range LO,HI`.
2. Per block: normalise `t = (z − z_min) / (z_max − z_min)`, clamp to `[0,1]`.
3. Map `t` through a **colour ramp** (e.g. viridis / turbo / a configurable LUT) → RGB uint8, write to the colour columns.

## Estimated effort

Small. A new `processing/elevation.py` (≈ one function, mirroring `bake_rgb_from_intensity`), a `--shading`-sibling mode flag (or a new `--colour-by {intensity,elevation}` switch), a CLI/GUI ramp selector, and tests mirroring `test_intensity.py`. No new dependencies; reuses the existing single-pass write path.

## Open questions

- **Colour ramp library vs. hand-rolled LUT** — matplotlib colormaps are already a transitive dependency (in the bundle), or a small hand-rolled LUT keeps it dependency-free.
- **Per-scan vs. file-global Z range** — file-global is simpler and matches how intensity range works today.

## Related

- [[Recolour Roadmap]] · [[Intensity Colouring]] · [[Classification Colouring]]
