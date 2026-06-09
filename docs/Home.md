---
tags: [project, moc]
status: current
updated: 2026-06-07
---

# Intensity-RGB — Knowledge Vault

This vault documents the **Intensity-RGB** point-cloud recolour tool and the research behind extending it to **semantic classification** of industrial-plant scans.

> [!info] What this tool does today
> Intensity-RGB V2.0 streams an `.e57` point cloud block-at-a-time, replaces each point's photographic RGB with a colour derived from its **intensity** scalar, and optionally **shades** the result against voxel-resolution PCA normals. It is **CPU-only and memory-flat** — point count is not bounded by RAM. See [[Project Overview]].

## Start here

1. **Understand the tool** → [[Project Overview]] → [[Architecture]] → [[Module Map]]
2. **Understand the goal** → [[Recolour Roadmap]] (intensity → normals → elevation → **classification**)
3. **Survey the options** → [[Classification MOC]]
4. **See the recommendation** → [[Recommended Approach]] + the [[ADR-001 Classical-geometric-first|decision log]]

## The three pillars

| Pillar | Entry note | What it covers |
|---|---|---|
| 🏗️ The current tool | [[Project Overview]] | Architecture, modules, streaming model, constraints |
| 🔬 Classification research | [[Classification MOC]] | Classical, deep-learning, plant-specific methods; datasets; taxonomies |
| 🧭 The plan | [[Recommended Approach]] | Recommended path, target taxonomy, phased roadmap, ADRs |

## The strategic goal

The user wants Intensity-RGB to colour points not only by intensity / normals / elevation, but by **semantic class**, focused on **plant** elements:

> pipes · pumps · beams · columns · walls · floors · vessels / tanks · valves · flanges · ducts · cable trays

See [[Classification Colouring]] and [[Target Class Taxonomy]].

## Why one finding shapes everything

[[Voxel Normals and PCA]] shows the tool already computes per-voxel covariance eigenvalues via `np.linalg.eigh`, then **throws the eigenvalues away** and keeps only the normal. Those discarded eigenvalues are exactly the input to the [[Geometric Features (Weinmann)|Weinmann geometric features]] that every CPU-friendly classifier needs. Retaining them ([[ADR-003 Retain voxel eigenvalues]]) is the cheapest possible on-ramp to classification — it anchors [[Recommended Approach|the whole recommended path]].

## Tag legend

- `#project` — documents the current tool
- `#recolour-mode` — a colouring dimension (current or planned)
- `#research/classical` · `#research/dl` · `#research/plant` · `#research/datasets` · `#research/taxonomy`
- `#decision` — an [[ADR-000 Template|architecture decision record]]
- `#reference` — verbatim research appendix (see [[90-Reference/README|README]])

## Map of folders

- `00-Project/` — what the tool is and how it works
- `10-Recolour-Modes/` — each colouring dimension
- `20-Classification-Research/` — synthesized research
- `30-Plan/` — recommendation, taxonomy, roadmap, `decisions/`
- `90-Reference/` — the four research reports, verbatim
