# pye57 vendor build notes

## Summary

**Build result: CLEAN** — built from source against system Python 3.14 +
numpy 2.4.4 using upstream davidcaron/pye57 HEAD with no patches.

## Versions

- Python: 3.14.4 (system, `/usr/lib/python3.14`)
- numpy: 2.4.4
- pye57 (vendored): 0.4.19 — upstream `davidcaron/pye57` @
  `b8d20999f3037c580bf1fe1dcb239c50a8f764ad`
- libE57Format (submodule): `d885ae35147dabd0ad9f6a85e46538b27b1b701c`
  (`asmaloney/libE57Format`)
- xerces-c: system, `/usr/lib/libxerces-c-3.3.so`

## Install command

```sh
pip install --user --break-system-packages -e vendor/pye57/
```

`--break-system-packages` was required because the Arch system Python is
PEP 668 externally-managed. This is acceptable for this project because
the plan explicitly targets the system interpreter. If a future
contributor prefers isolation, a `python -m venv .venv` works equally well
and the editable install command is the same minus the flag.

## What got installed

- `pye57==0.4.19` (editable; points at `vendor/pye57/src/pye57/`)
- `pyquaternion==0.9.9` (runtime dep, fetched from PyPI)

The compiled extension `_pye57*.so` lives inside `vendor/pye57/src/pye57/`
because the install is editable — Wave 2 can rebuild in place by re-running
the same `pip install -e` command after touching C++ sources.

## No patches required

There were no numpy 2.x C-API issues and no libE57Format build failures.
The build pulled in pybind11 as a build-system requirement (PEP 517) and
compiled cleanly. `setup.py` already links against the system xerces-c.

## Caveats for Wave 2

1. **Submodule is gone.** `libE57Format/.git` was deleted along with the
   parent `.git/` (we are vendoring, not submoduling). The full source
   tree is present and buildable. SHAs are pinned in `UPSTREAM_SHA.txt`.
2. **Editable install** means any edits to `src/pye57/*.py` are live, but
   edits to the pybind11 C++ layer (`src/pye57/*.cpp`, `*.h`) require
   re-running `pip install --user --break-system-packages -e vendor/pye57/`
   to recompile the extension.
3. **Smoke test sits at the vendor root**, not under `tests/`. It exercises
   the real `carpark_stairs.e57` fixture (4.1 M points, 1 scan, fields:
   cartesianX/Y/Z, intensity, colorRed/Green/Blue).
4. `pye57.__version__` is exposed as a submodule, not a string — the smoke
   test prints the module repr. Wave 2 may want to expose a proper
   `__version__` string when extending the package.
