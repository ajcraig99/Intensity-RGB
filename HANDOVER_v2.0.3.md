# Intensity-RGB — Status & Handover after V2.0.2

Date: 2026-05-18. Owner pickup point after the first end-to-end Windows GUI smoke session and a deep dive on a suspected writer-path bug.

`master` tip: `efb6b05` (V2.0.2 mode-dispatch fix). Tags `v2.0.1` and `v2.0.2` are now pushed alongside this doc.

---

## TL;DR

| Item | State |
|---|---|
| Linux bundle | built on the build machine — see V2.0 HANDOVER |
| Windows bundle | **built and CLI-smoke-tested** — `dist\Intensity-RGB-windows-x86_64.zip` (203 MB) |
| Windows GUI smoke | **all four shading modes start & run end-to-end** (post-Fix 1) |
| Recap import (G3) | **not yet conclusively passed** — see below |
| G2 production-scale numbers | still TBD |

V2.0.2 closes two real Windows-only bugs from the V2.0 release. The remaining open item is whether Recap actually imports baked output cleanly. Investigation summary below.

---

## What changed since V2.0.0

**v2.0.1** (`71321db`) — Windows build compatibility.
- `intensity_rgb/cli.py` — guarded the Unix-only `resource` import (`_peak_rss_bytes()` returns 0 on Windows). Without this, the bundle crashes at import.
- `vendor/pye57/scripts/install_xerces_c.ps1` — added `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` so the xerces-c 3.2.3 source build works with modern CMake (CMake 4+ dropped support for pre-3.5 `cmake_minimum_required`).

**v2.0.2** (`efb6b05`) — GUI shading-mode dispatch.
- `intensity_rgb/app.py:839-848` — was sending compound mode strings (`bake_normals_lambertian` etc.) the worker doesn't recognize. Worker only accepts `clone` / `bake_intensity` / `bake_normals`; the shading kind flows via a separate `shading_mode` field. Three of four GUI shading options were unusable until this was fixed.
- Added `HANDOVER_v2.0.2.md` for context.

---

## Recap-import investigation (open, low confidence in any writer bug)

### Triggering report

After the V2.0.2 GUI smoke on a Fonterra-Whareroa scan, the user found that bake outputs imported cleanly into CloudCompare but were rejected by Recap with `could not import scan!`. The same source `.e57` imports into Recap correctly.

### Diagnostic findings

The user's `_output1.e57` (266 MB, 9,460,133 points) differed structurally from the source:
- `cartesianBounds` missing
- `acquisitionStart` / `acquisitionEnd` added (not in source)
- Scan child order matches pye57's high-level `write_scan_raw` template (which `E57CloneWriter` does *not* use)
- Only 9% of the source's points

To check whether the **current bundle** is responsible, I ran each pipeline mode via the bundle CLI on the same source. Results:

| File | cartesianBounds | acquisitionStart | Points | Size |
|---|---|---|---|---|
| SOURCE                          | Y | N | 107,439,036 | 3.3 GB |
| `clone_test.e57` (CLI clone)    | Y | N | 107,439,036 | 3.2 GB |
| `bake_test.e57` (CLI bake)      | Y | N | 107,439,036 | 3.2 GB |
| `bake_normals_test.e57` (CLI)   | Y | N | 107,439,036 | 3.2 GB |
| `_output1.e57` (user, broken)   | N | Y |   9,460,133 | 266 MB |

All four current code paths preserve `cartesianBounds` and produce full-size output. The user's broken file is anomalous in both content (truncated to ~9%) and structure (carries the pye57 `write_scan_raw` shape, which our pipeline never invokes). Strong conclusion: **`_output1.e57` was not produced by the current bundle.**

### Where it most likely came from

Most likely origin: a leftover output from an earlier ad-hoc script that used pye57's high-level `write_scan_raw` API, or a partially-written file from an aborted job that left a synthesis from another producer. The mtime falls between bundle builds in the same session, so it was definitely written today — just not by our pipeline.

### Outstanding gate

The decisive G3 test is now: open one of the three fresh CLI outputs in Recap. They live in `C:\Users\arron.craig\Downloads\` on the dev workstation (gitignored — they're release-asset-grade artifacts, ~3.2 GB each). Priority order:

1. `bake_test.e57` — single-pass intensity bake. If this opens, the bake path is fine.
2. `bake_normals_test.e57` — two-pass bake with Lambertian shading. If this opens, every shading mode is fine.
3. `clone_test.e57` — byte-faithful clone. If even this fails, the writer has a real bug independent of any recolor logic.

If any of the bake variants opens, V2.0.2 effectively passes G3 and the investigation closes.

---

## Other items observed but not fixed

Captured in `HANDOVER_v2.0.2.md`; reproduced here briefly:

- **Verdict chips show "GREEN" / "YELLOW" / "RED" as their button label.** Confusing — colour already conveys the verdict. Suggest replacing with a fixed symbol or hiding the text. ~5-line change in `_update_verdict_chips`.
- **Progress-line units are ambiguous.** "Throughput: 1.5" should be "1.5 M pts/s"; "ETA: 55" should be "ETA: 55s" or "0:55". Same place in `app.py`.
- **"Voxel quality" stays "—" through `bake_intensity` jobs.** Either populate after Pass 2 or hide on modes that don't compute it.
- **Peak RSS stays "—" on Windows.** Expected per v2.0.1 (returns 0). Implementing `ctypes.windll.psapi.GetProcessMemoryInfo` → `PeakWorkingSetSize` would close the gap.

None are blockers; defer to v2.0.3 if scope-creep is OK there.

---

## Still deferred (carried through every handover so far)

- **G2 production-scale numbers** in the README. Needs a 100M+ point scan and a `/usr/bin/time -v`-equivalent (`Get-Process` peak working set on Windows). Update `README.md`'s "V2.0 limitations" once measured.
- **GitHub release pointing at the `v2.0.0` (or now `v2.0.2`) tag**, with the Linux bundle as a release asset, optionally the Windows zip too. Repo description still says "Tkinter".
- **Carpark fixture** — `tests/test_clone_fidelity.py` and `tests/test_pipeline.py` reference `carpark_stairs.e57` by absolute path. Commit a smaller fixture or move the file into the tree so the suite is self-contained.

---

## Ship checklist for v2.0.3 (only if Recap test fails or you decide to ship UX polish)

1. Address whichever of the items in "Other items observed" you want included.
2. If the Recap test on `bake_test.e57` fails, dive into the writer. Hypotheses to rule out:
   - `update_color_limits` building IntegerNode limits when the colorRed/Green/Blue field types in the scan prototype are something else.
   - Some scan-level child being silently dropped during `clone_node` recursion for a node type not exercised by the in-tree synthetic fixture.
3. Rebuild Windows bundle: `powershell -ExecutionPolicy Bypass -File build/build.ps1`.
4. Commit + tag annotated.
5. Push: `git push origin master --follow-tags`.
6. Update / re-cut the GitHub release with the new Windows zip.

---

## Build prerequisites for a fresh Windows machine

Single-session build of the Windows bundle from a clean VS-toolchain-free Windows install takes ~30 min:

1. `winget install Kitware.CMake` (CMake 4.x is fine post-policy fix in v2.0.1).
2. Visual Studio 2022 Build Tools with the **C++ build tools** workload.
3. `powershell -ExecutionPolicy Bypass -File vendor\pye57\scripts\install_xerces_c.ps1` — builds xerces-c 3.2.3 into `%TEMP%/xerces_c` (~10–15 min compile).
4. `python -m pip install -e vendor\pye57\` — builds pye57 + libE57Format against the xerces above (~5 min compile of ~190 C++ files).
5. `python -m pip install -e .` — installs intensity_rgb editable. `pip install pyinstaller` if not present.
6. `powershell -ExecutionPolicy Bypass -File build\build.ps1` — produces `dist\Intensity-RGB-windows-x86_64.zip` (~50 s).

The bundle is `console=True` so the .exe routes argv at runtime: bare invocation launches the Qt GUI; any subcommand (`clone` / `recolor-test` / `bake`) goes through `cli.main`. See `build/_entry.py`.
