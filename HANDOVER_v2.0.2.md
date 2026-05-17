# Intensity-RGB V2.0.2 — Handover (post-GUI-smoke fixes)

V2.0.1 made the Windows bundle build and start. First real GUI smoke on Windows surfaced two issues — one a blocker, one cosmetic. This document describes both and how to ship V2.0.2.

Starting point: `master` at v2.0.1 (commit `71321db`), local-only tag. Bundle at `dist/Intensity-RGB-windows-x86_64.zip` (203 MB).

---

## Fix 1 — `bake_normals` mode dispatch (blocker)

### Symptom

Selecting any shading mode other than **None** in the GUI and clicking **Start** produces a `Job failed` dialog:

- "unknown mode 'bake_normals_lambertian'"
- "unknown mode 'bake_normals_three_point'"
- "unknown mode 'bake_normals_normal_as_color'"

`bake_intensity` (shading = None) works correctly — the bug is specific to the three normal-bake variants, i.e. three of four shading options are unusable.

### Root cause

`intensity_rgb/worker.py:192` only accepts three mode values:

```python
if mode not in ("clone", "bake_intensity", "bake_normals"):
    self.finished.emit(False, f"unknown mode {mode!r}")
    return
```

The shading kind is supposed to flow via a *separate* `shading_mode` field in the job spec — and `intensity_rgb/app.py:854` already sets it correctly:

```python
"shading_mode": shading if shading != "none" else None,
```

But `app.py:839-848` builds compound `mode` strings the worker doesn't recognise:

```python
if shading == "none":
    mode = "bake_intensity"
elif shading == "lambertian":
    mode = "bake_normals_lambertian"          # invalid
elif shading == "three_point":
    mode = "bake_normals_three_point"         # invalid
elif shading == "normal_as_color":
    mode = "bake_normals_normal_as_color"     # invalid
else:
    mode = "bake_intensity"
```

The worker then dispatches on `mode == "bake_normals"` and passes `spec["shading_mode"]` into `pipeline_bake_normals` (`worker.py:244`). The GUI just needs to send the canonical mode.

### Fix

Replace `intensity_rgb/app.py:839-848` with:

```python
if shading == "none":
    mode = "bake_intensity"
else:
    mode = "bake_normals"
```

Two lines net. Don't touch the `shading_mode` field — it's already correct.

### Verification

1. Rebuild bundle: `powershell -ExecutionPolicy Bypass -File build/build.ps1` (~50 s).
2. Launch the GUI: `dist\Intensity-RGB-windows-x86_64\intensity-recolor.exe`.
3. For each of **Lambertian**, **3-pt**, **Norm**: load the same `.e57`, click **Start**, confirm the job actually runs (progress bar advances, log shows `Starting bake_normals → ...`) rather than instantly failing.
4. Bake-with-Lambertian → open output in Recap (G3 from V2.0 HANDOVER).

---

## Fix 2 — Verdict chip labels say "GREEN" (cosmetic)

### Symptom

Capability panel's three mode-verdict chips display the literal word "GREEN" / "YELLOW" / "RED" as their button label. This is confusing — the colour already conveys the verdict, and "GREEN" as text reads like a placeholder. See screenshot at v2.0.1 smoke time: three chips under labels *Intensity only*, *Intensity + Lambertian*, *Normal-as-color*, all reading "GREEN" on a green background.

### Where

`intensity_rgb/app.py` — the chip creation loop near line 245-260 and the update path `_update_verdict_chips` near line 685-687. The chip's `setText(verdict)` (or equivalent) is using the verdict enum value as the label.

### Suggested fix

Two reasonable options — pick one:

- **Option A** (minimal): replace the chip text with a fixed symbol per verdict — `"●"` or `"OK"` / `"!"` / `"✕"`. Colour carries the verdict; text just confirms there's content.
- **Option B**: hide the chip text entirely (small fixed-width coloured swatch). The label above already names the mode; the chip's job is just "go / caution / no".

Either is a ~5-line change in `_update_verdict_chips` plus possibly the initial creation. Not a blocker; defer if v2.0.2 needs to ship fast.

---

## Optional — Misc UX polish noticed during smoke

These are observations from the same GUI smoke. None block v2.0.2; flag for V2.0.3 if not addressed here.

- **Progress line units are ambiguous.** Status row shows `Throughput: 1.5  Peak RSS: —  ETA: 55  Voxel quality: —`. Add unit suffixes (`M pts/s`, `MB`, `s` or `m:ss`) so a glance is enough.
- **Voxel quality stays "—" throughout the bake-intensity run.** Either populate it once Pass 2 has run, or hide the field when it isn't applicable to the current mode (bake_intensity has no voxel quality).
- **Peak RSS stays "—" on Windows.** Expected, per v2.0.1 — `_peak_rss_bytes()` degrades to 0 on Windows. Either implement the ctypes PSAPI version (`GetProcessMemoryInfo` → `PeakWorkingSetSize`) or hide the field on Windows.

---

## Ship checklist

1. Edit `intensity_rgb/app.py` per Fix 1.
2. (Optional) Edit `intensity_rgb/app.py` per Fix 2.
3. Rerun pytest on Linux to confirm no regression: `python3 -m pytest tests/ -q` — expected 106 passed.
4. Rebuild Windows bundle: `powershell -ExecutionPolicy Bypass -File build/build.ps1`.
5. Manual GUI smoke on Windows: all three shading modes start and progress past 0% (Fix 1 verification above).
6. Commit + tag:
   ```sh
   git add intensity_rgb/app.py
   git commit -m "fix: V2.0.2 — GUI bake_normals mode dispatch (and verdict chip labels)"
   git tag -a v2.0.2 -m "Intensity-RGB V2.0.2 — GUI shading dispatch fix"
   ```
7. Push if appropriate: `git push origin master --follow-tags`.
8. Replace the v2.0.1 Windows bundle on the GitHub release with the v2.0.2 rebuild (or cut a new release).

---

## What V2.0.2 does NOT do

Still deferred from earlier handovers, NOT addressed here:

- **G2 production-scale numbers** in README — needs a 100M+ scan, peak RSS + throughput.
- **G3 Recap visual check** on a baked file — until this passes once, "the shading is correct downstream" is unverified.
- **GitHub release** — repo description still mentions Tkinter; v2.0.0 release page not yet cut.
- **Carpark fixture commit / smaller fixture** for self-contained tests.
- **`carpark_stairs.e57` fixture** is still required by name for some pipeline tests.
