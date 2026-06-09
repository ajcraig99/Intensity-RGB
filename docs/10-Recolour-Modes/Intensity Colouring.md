---
tags: [recolour-mode]
status: current
updated: 2026-06-07
---

# Intensity Colouring

The original and default colouring mode. Implemented in `processing/intensity.py`.

## How it works

`bake_rgb_from_intensity(intensity, *, max_inten, brightness)` maps each point's intensity scalar to a **hue**, then converts `HSV(h, saturation=1, value=brightness/100)` to RGB (uint8). Saturation is fixed at 1 for `colorsys` parity.

### Normalisation sentinels
| `max_inten` | hue mapping |
|---|---|
| 255 or 4096 | `h = intensity / max_inten` |
| 2048 | `h = (intensity + 2048) / 2048` (offset path) |
| other | raw intensity as hue (fallback) |

The intensity range is either supplied (`--intensity-range LO,HI`) or auto-estimated by sampling the file ([[Module Map|get_aabb_and_intensity_range]]); auto-range confirms before running unless `--yes` is given.

## Relationship to other modes

Intensity colouring produces the **base RGB** that the [[Normal-based Colouring|shaders]] then modulate. When shading is off (`--shading none`), this base is written directly. See [[Recolour Roadmap]].

## Related

- [[Normal-based Colouring]] · [[Elevation Colouring]] · [[Project Overview]]
