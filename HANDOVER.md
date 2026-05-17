# Intensity-RGB V2.0 — Handover

Auto-mode build of V2.0 is complete on `master` and tagged `v2.0.0` (local; pushed alongside this commit). 106 local tests pass. The deferred human gates from the auto-mode plan — Recap visual checks, Windows hardware smoke, and production-scale validation — are yours to run. Everything you need is in this file.

Architecture and module map live in [README.md](README.md) and [CLAUDE.md](CLAUDE.md). This document is the **operator checklist**, not the design.

---

## TL;DR

| Item | State |
|---|---|
| `master` tip | `d6d88a9` (release commit) |
| Tag | `v2.0.0` (annotated) |
| Test suite | 106/106 pass on this machine |
| Linux bundle | `dist/Intensity-RGB-linux-x86_64.zip` — 144 MB, smoke-tested |
| Windows bundle | not built (script `build/build.ps1` written but untested on hardware) |
| V1 files | deleted (`Intensity-RGB_V1.0.py`, `Intensity-RGB_V1.1.exe`) — recover from `git show v2.0.0~1` if needed |

If anything below fails, see [Rollback](#rollback) at the bottom.

---

## Step 1 — Sanity check on this machine (5 minutes)

```sh
cd /home/arron/projects/Intensity-RGB

# Tests
python3 -m pytest tests/ -q
# expected: 106 passed in ~26s

# CLI smoke against the in-tree fixture
python3 -m intensity_rgb.cli clone \
    --input carpark_stairs.e57 --output /tmp/handover_clone.e57

python3 -m intensity_rgb.cli bake \
    --input carpark_stairs.e57 --output /tmp/handover_bake.e57 \
    --auto-range --yes --shading lambertian --voxel-size 0.5

# GUI (headless smoke — just confirms it loads)
QT_QPA_PLATFORM=offscreen timeout 3 python3 -m intensity_rgb
# expected: exit 124 (timeout fired before the event loop blocked), no errors on stderr
```

If pytest is green and both CLI runs print a "Done. Output: …" summary, this machine is healthy.

---

## Step 2 — Open a baked file in Recap (G3, the headline check)

This is the gate the auto-mode plan deferred to you. Until a real human eyeballs a V2.0 baked file in Recap, no one knows if the shading actually looks right downstream.

Recommended fixture: a small-to-medium scan you already have on the workstation, ideally one you've previously opened in Recap with V1 so you have a visual baseline.

1. Copy or scp the input `.e57` to your workstation.
2. Run:
   ```sh
   python -m intensity_rgb.cli bake \
       --input  my_scan.e57 \
       --output my_scan_baked.e57 \
       --auto-range --yes \
       --shading lambertian \
       --voxel-size 0.5 \
       --brightness 70
   ```
3. Open both `my_scan.e57` and `my_scan_baked.e57` in Recap, side by side.

Things to look for, in priority order:

- **Coordinates match exactly.** XYZ is bit-identical between source and output; if Recap reports a translation/rotation drift the prototype clone is broken.
- **Intensity gradient is preserved.** The baked RGB should follow the same hot/cold pattern as the source's intensity-based shading. If it looks inverted, try `--brightness 50` instead of 70.
- **Lambertian shading is sane.** Planar surfaces should have visible directional shading consistent with light coming roughly from above (`--light-dir 0,90` is straight up). If shading is patchy or noisy, the voxel grid is probably too coarse — try `--voxel-size 0.25`.
- **All scans present.** Multi-scan files: confirm every scan from the source is in the output (Recap's scan list panel).
- **Embedded images survive.** If the source has photos under `/images2D` (some scanners ship pinhole-projected colour photos), they should be present in the output.

If any of those fail, save the Recap session for diagnosis and file a defect. Don't tag a release as v2.0.1 yet.

### G1b — also worth doing while you're at it

Same workflow but use the pure clone path instead of bake, on the same file:

```sh
python -m intensity_rgb.cli clone --input my_scan.e57 --output my_scan_clone.e57
```

Open `my_scan_clone.e57` in Recap. It should be **visually indistinguishable** from the source — same colours, same intensity ramp, same image attachments. If anything looks different, the clone path has a problem the byte-level G1a test missed, and we need to fix it before relying on Mode B's "everything cloned except RGB" guarantee.

---

## Step 3 — Production-scale measurement (G2)

The plan's acceptance table has `TBD` for every production-scale number. Time to populate it.

Pick the largest representative scan you have (100M points up to your full 7B range). Run:

```sh
/usr/bin/time -v python -m intensity_rgb.cli bake \
    --input  huge_scan.e57 \
    --output huge_scan_baked.e57 \
    --auto-range --yes \
    --shading lambertian \
    --voxel-size 0.5 \
    --block-size 1000000
```

Record from `/usr/bin/time -v`:

- **Maximum resident set size (kbytes)** → divide by 1024 for MB. This is peak RAM.
- **Elapsed (wall clock) time**.
- Output file size (`ls -lh huge_scan_baked.e57`).

Derive throughput: `total_points / elapsed_seconds` (M pts/sec).

Expected based on carpark (4.1M points, 3.2 s) extrapolation: **~1.3 M pts/sec** for bake-normals on a single CPU core, RSS bounded by the voxel grid (linear in spatial extent / voxel_size³, not in point count). A 1 B-point scan covering 100 m × 100 m × 30 m at 0.5 m voxels should peak around 200 MB. If RSS grows linearly with point count instead, something is leaking — file a defect.

For pure clone (no shading): throughput should be 4–6 M pts/sec, RSS under 200 MB regardless of point count.

Once you have numbers for at least one production-scale fixture, drop them into [README.md](README.md)'s "V2.0 limitations" section (the G2 bullet) and tag a `v2.0.1` patch.

---

## Step 4 — Windows bundle (G4)

The build script exists but has never been run on Windows. Workflow:

1. On a Windows box, `git clone https://github.com/ajcraig99/Intensity-RGB.git && cd Intensity-RGB && git checkout v2.0.0`.
2. Install Python 3.10+ and `pip install pyinstaller`. (Building `pye57` from source on Windows usually needs MSVC build tools + a libE57Format build — this is the most likely failure point.)
3. `pip install -e vendor/pye57/` — if this fails because of missing C++ toolchain, install Visual Studio Build Tools (C++ workload). pye57 wheels for Python 3.13+ may not exist on PyPI yet, so source build may be unavoidable.
4. `pip install -e .`
5. `powershell -ExecutionPolicy Bypass -File build/build.ps1`
6. Expect `dist\Intensity-RGB-windows-x86_64.zip`. Unzip somewhere and double-click `Intensity-RGB-windows-x86_64\intensity-recolor.exe` — should open the GUI.
7. Repeat Step 2's Recap test on Windows hardware to confirm the bundled app actually works end-to-end.

If `build/build.ps1` fails, the most likely reasons:

- pye57 won't build (toolchain). Fix: install MSVC Build Tools.
- PyInstaller misses Qt platform plugins. Symptom: the GUI shows a black window or crashes with "could not load the Qt platform plugin 'windows'". Fix: add `binaries=collect_dynamic_libs("PySide6")` to `build/intensity_rgb.spec` — the Linux build worked because PySide6's Linux hook is mature; Windows hook may be flakier.
- Bundle exceeds 250 MB. Symptom: build.ps1 errors out. Fix: add more entries to the spec's `excludes` list — the Linux build already trims torch/triton/tensorflow/sympy/pandas/lxml/cryptography/gi/PIL; Windows may pull in different transitive cruft.

Document any fixes as a patch commit and tag `v2.0.1`.

---

## Step 5 — Push the rest

After this commit + the `v2.0.0` tag are pushed, the GitHub repo will show V2.0 as the head. You may want to:

- Cut a GitHub release pointing at the `v2.0.0` tag, attaching `dist/Intensity-RGB-linux-x86_64.zip` as a release asset.
- Update the GitHub repo description (it probably still says "single Tkinter script that…" — V2 is a different beast).
- Decide what to do with the Windows binary: either build it locally and attach to the GitHub release, or leave it as "build it yourself from the script" for now.

The Linux bundle is large (144 MB) but well under the 250 MB target. Both the bundle and `carpark_stairs.e57` (79 MB) are out-of-tree (`dist/` is gitignored; `carpark_stairs.e57` is untracked). Treat them as release assets, not commits.

---

## Known caveats

Things I noticed during the build that don't break anything but are worth your awareness:

- **carpark_stairs.e57 is intentionally untracked.** It was already untracked when V2 work started. Wave 1's `tests/test_clone_fidelity.py` and Wave 3's `tests/test_pipeline.py` use it as a fixture by absolute path — if the file moves or is removed, all the carpark-parametrised tests fail. Consider committing it (~80 MB) so the test suite is self-contained, or replacing it with a smaller fixture for CI.
- **`build/_entry.py` is a dispatcher I added** that wasn't in the original plan. The plan literally said the bundle's entry should be `intensity_rgb/__main__.py`, but that always launches the GUI — incompatible with `intensity-recolor --help` and the CLI smoke tests. The dispatcher routes argv-with-args to `cli.main` and bare-invocation to `app.main`. If you want CLI-only or GUI-only single-purpose bundles in the future, this is the file to point a separate spec at.
- **The vendored pye57 `.so` is built against Python 3.14** (the system Python on this dev box). End users on different Python ABIs will need to rebuild — `pip install -e vendor/pye57/` from source. The bundle ships its own Python interpreter so this is only an issue for source installs.
- **QSettings persists across V1 → V2 upgrades** on the same machine — but V1 didn't write any QSettings, so this is a non-issue today. Future schema changes to the persisted keys should bump an `app/schema_version` value.
- **Auto-range on descaled intensity fields reports `[0, 1]`** rather than `[0, 4096]` because pye57 returns intensity descaled via libE57's ScaledIntegerNode handling. The pipeline rescales internally, so this is correct end-to-end, but if a user manually copies the `Auto-detect`'d numbers into the intensity-range fields they'll get a different (correct-but-confusing) result than typing `0,4096` by hand. Not a bug; worth a tooltip clarification in V2.0.1.
- **n_components on carpark is 1**, meaning the whole scan is one connected voxel component. That's expected for a single-scanner outdoor scan; on merged multi-scanner datasets you'll see multiple components and the per-component invert chips in the GUI will become useful. Right now the chips are read-only (V2.1 will wire live invert; placeholder in worker + UI is already there).

---

## V2.0.1 candidates

Things to consider for the patch release:

1. **Fix the 138 vs 144 MB drift** in the `v2.0.0` tag message (cosmetic — real bundle is 144 MB, tag annotation says 138).
2. **Tune the Lambertian shading defaults** if Step 2's Recap check surfaces visual issues. Most likely: increase ambient from 0.3 → 0.4 if surfaces look too dark, or change the default light_dir from straight-up `(0, 90)` to something like `(45, 60)` for more visible directional shading.
3. **Add `--save-config FILE` / `--load-config FILE`** to the CLI so users can capture a known-good parameter set and re-run it across multiple files.
4. **Capability panel runtime estimate** is currently always "TBD (measured at start of job)" — wire a one-off measured throughput from the most recent run via QSettings so subsequent capability inspections can show "Estimated runtime: ~3 minutes" based on last-run-pts-per-sec.
5. **G2 numbers in [README.md](README.md)** once Step 3 produces them.

---

## Rollback

If V2.0 falls over and you need V1 back temporarily:

```sh
# Restore V1 source + binary from the commit before the deletion.
git checkout v2.0.0~1 -- Intensity-RGB_V1.0.py Intensity-RGB_V1.1.exe
# Run V1 as before:
python Intensity-RGB_V1.0.py
```

Or revert the entire V2 effort:

```sh
git revert --no-commit v2.0.0~19..v2.0.0   # reverts all 20 V2 commits in one go
git commit -m "revert: V2.0 release (see HANDOVER.md)"
```

Neither rollback affects the `v2.0.0` tag — it's a permanent marker of "this is what V2.0 looked like at release," which is useful for diagnosing whatever failed.

---

## Questions to come back to me with

- Recap behaviour on the baked file (Step 2). Send a screenshot if anything looks off — that's the highest-priority signal.
- Production-scale numbers (Step 3). Even partial — peak RSS on one fixture — closes the biggest unknown.
- Whether the Windows build succeeds (Step 4). If it doesn't, the failure mode tells me whether it's a toolchain issue, a Qt-plugin issue, or a pye57-source-build issue, and they all have different fixes.
