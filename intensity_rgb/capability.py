"""Header-only ``.e57`` file inspection for the V2.0 capability panel.

This module is the Wave 3 / C3 contract referenced by the Wave 4 UI
(``intensity_rgb.app``). It produces a :class:`CapabilityReport` from the
XML header of an ``.e57`` file in well under one second, regardless of
point count, because we never touch the binary CompressedVector payload
in :func:`inspect_file`.

The verdict math (max possible chunk count, upper-bound RAM, Green/
Yellow/Red thresholds) is the canonical contract from
``stateful-hatching-kitten.md`` §"Capability panel (header-only)".

An optional :func:`estimate_touched_chunks` helper streams the first
``sample_blocks`` of scan 0 to tighten the upper bound when the user
clicks the "Estimate touched chunks" button in the UI — that path *is*
allowed to read binary data, but only on explicit user request.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from pye57 import E57, libe57

from intensity_rgb.io.e57_clone import E57CloneReader


__all__ = [
    "CapabilityReport",
    "inspect_file",
    "estimate_touched_chunks",
]


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------


# Pass-1 per-voxel state in the chunked-dense accumulator: 10 float64 slots
# per voxel (3 sum_xyz + 3 sum_xyz_sq off-diag + 3 sum_xyz_sq_diag + 1 count).
_PASS1_FLOATS_PER_VOXEL = 10
_FLOAT_BYTES = 8

# Pass-2 per-voxel state: 3 frozen float32 normals + 1 bool quality.
_PASS2_BYTES_PER_VOXEL = 3 * 4 + 1

# A bit of slack on top of the rigorous AABB upper bound so the UI doesn't
# need to know about block buffers, numpy overhead, libE57 internals.
_OVERHEAD_CONST_BYTES = 64 * 1024 * 1024  # 64 MiB

# Per-point block buffer cost: ~8 fields × 8 bytes ~= 64 bytes/point worst
# case for the descaled-double path. We use 80 to be generous.
_BLOCK_BYTES_PER_POINT = 80

# Fallback system RAM when we can't introspect: 8 GiB.
_FALLBACK_SYSTEM_RAM = 8 * 1024 * 1024 * 1024

# Verdict thresholds (fraction of system RAM).
_GREEN_MAX = 0.25
_YELLOW_MAX = 0.75


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass
class CapabilityReport:
    file_path: str
    file_size_bytes: int
    scan_count: int
    total_points: int
    per_scan_point_counts: list
    per_scan_aabb_min: list
    per_scan_aabb_max: list
    file_aabb_min: Optional[tuple]
    file_aabb_max: Optional[tuple]
    rgb_present_in_all_scans: bool
    organized_in_any_scan: bool
    embedded_normals_in_any_scan: bool
    max_possible_chunk_count: int
    pass1_peak_ram_upper_bound_bytes: int
    pass2_peak_ram_upper_bound_bytes: int
    verdicts: dict = field(default_factory=dict)
    verdict_reasons: dict = field(default_factory=dict)
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# System RAM detection
# ---------------------------------------------------------------------------


def _detect_system_ram_bytes() -> int:
    """Return total physical RAM in bytes.

    Tries ``psutil`` first (cross-platform), falls back to parsing
    ``/proc/meminfo`` on Linux, finally returns 8 GiB if neither works.
    """
    try:
        import psutil  # type: ignore
        return int(psutil.virtual_memory().total)
    except Exception:
        pass
    try:
        with open("/proc/meminfo", "r") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    # MemTotal value is in kB.
                    return int(parts[1]) * 1024
    except Exception:
        pass
    return _FALLBACK_SYSTEM_RAM


# ---------------------------------------------------------------------------
# XML walking helpers
# ---------------------------------------------------------------------------


def _read_cartesian_bounds(scan_node: "libe57.StructureNode"):
    """Return (min_xyz, max_xyz) tuples or (None, None) if absent.

    Some scans may carry only some axes (defensive coding); we treat any
    missing axis as "header AABB unavailable" and propagate Nones for the
    whole scan so the verdict can flag it.
    """
    if not scan_node.isDefined("cartesianBounds"):
        return None, None
    cb_raw = scan_node.get("cartesianBounds")
    cb = cb_raw if isinstance(cb_raw, libe57.StructureNode) else libe57.StructureNode(cb_raw)
    keys = (
        ("xMinimum", "xMaximum"),
        ("yMinimum", "yMaximum"),
        ("zMinimum", "zMaximum"),
    )
    mins = []
    maxs = []
    for kmin, kmax in keys:
        if not (cb.isDefined(kmin) and cb.isDefined(kmax)):
            return None, None
        try:
            vmin_raw = cb.get(kmin)
            vmax_raw = cb.get(kmax)
            vmin = libe57.FloatNode(vmin_raw).value()
            vmax = libe57.FloatNode(vmax_raw).value()
        except Exception:
            return None, None
        if not (math.isfinite(vmin) and math.isfinite(vmax)):
            return None, None
        mins.append(vmin)
        maxs.append(vmax)
    return (mins[0], mins[1], mins[2]), (maxs[0], maxs[1], maxs[2])


def _prototype_field_names(scan_node: "libe57.StructureNode") -> list:
    """Enumerate every child name in this scan's points CompressedVector
    prototype — does not depend on pye57's ``SUPPORTED_POINT_FIELDS``
    filter, so we'll see ``nor:normalX``-style vendor fields too.
    """
    cv_raw = scan_node["points"]
    cv = cv_raw if isinstance(cv_raw, libe57.CompressedVectorNode) else libe57.CompressedVectorNode(cv_raw)
    proto = libe57.StructureNode(cv.prototype())
    return [proto.get(i).elementName() for i in range(proto.childCount())]


def _has_rgb(field_names: list) -> bool:
    return all(c in field_names for c in ("colorRed", "colorGreen", "colorBlue"))


def _has_xyz(field_names: list) -> bool:
    return all(c in field_names for c in ("cartesianX", "cartesianY", "cartesianZ"))


def _has_organized(field_names: list) -> bool:
    return ("rowIndex" in field_names) or ("columnIndex" in field_names)


def _has_normals(field_names: list) -> bool:
    """Detect embedded normal fields written by Leica / FARO / etc.

    Common spellings: ``nor:normalX/Y/Z`` (Leica vendor extension),
    bare ``normalX/Y/Z`` (occasional). We check for any of these.
    """
    candidates = (
        "nor:normalX", "nor:normalY", "nor:normalZ",
        "normalX", "normalY", "normalZ",
    )
    return any(c in field_names for c in candidates)


# ---------------------------------------------------------------------------
# Chunk count + RAM math
# ---------------------------------------------------------------------------


def _max_chunks_from_aabb(
    aabb_min: Optional[tuple],
    aabb_max: Optional[tuple],
    voxel_size: float,
    chunk: int,
) -> int:
    """Upper bound on touched chunks if every chunk in the AABB cuboid
    happens to contain at least one point.

    Returns 0 when the AABB is unknown — callers should treat this as
    "header AABB missing" (Yellow verdict) rather than "no chunks".
    """
    if aabb_min is None or aabb_max is None:
        return 0
    chunk_extent = voxel_size * chunk  # metres covered by one chunk per axis
    if chunk_extent <= 0:
        return 0
    product = 1
    for lo, hi in zip(aabb_min, aabb_max):
        extent = max(0.0, hi - lo)
        n = max(1, math.ceil(extent / chunk_extent))
        product *= n
    return int(product)


def _pass1_ram_bytes(max_chunks: int, chunk: int, block_size: int) -> int:
    """Pass-1 peak RAM upper bound = chunk grids + block buffers + overhead."""
    chunk_cost = max_chunks * (chunk ** 3) * _PASS1_FLOATS_PER_VOXEL * _FLOAT_BYTES
    block_cost = block_size * _BLOCK_BYTES_PER_POINT
    return int(chunk_cost + block_cost + _OVERHEAD_CONST_BYTES)


def _pass2_ram_bytes(max_chunks: int, chunk: int, block_size: int) -> int:
    """Pass-2 peak RAM upper bound (frozen float32 normals + bool quality)."""
    chunk_cost = max_chunks * (chunk ** 3) * _PASS2_BYTES_PER_VOXEL
    block_cost = block_size * _BLOCK_BYTES_PER_POINT
    return int(chunk_cost + block_cost + _OVERHEAD_CONST_BYTES)


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------


def _classify_ram(ram_bytes: int, system_ram_bytes: int) -> str:
    """Return 'GREEN' / 'YELLOW' / 'RED' for one RAM-vs-budget comparison."""
    if system_ram_bytes <= 0:
        return "YELLOW"
    frac = ram_bytes / system_ram_bytes
    if frac <= _GREEN_MAX:
        return "GREEN"
    if frac <= _YELLOW_MAX:
        return "YELLOW"
    return "RED"


def _fmt_bytes(n: int) -> str:
    units = [("GiB", 1024 ** 3), ("MiB", 1024 ** 2), ("KiB", 1024)]
    for label, scale in units:
        if n >= scale:
            return f"{n / scale:.2f} {label}"
    return f"{n} B"


def _compute_verdicts(
    *,
    rgb_present_all: bool,
    xyz_present_all: bool,
    has_aabb: bool,
    embedded_normals: bool,
    pass1_ram: int,
    pass2_ram: int,
    system_ram: int,
) -> tuple:
    """Build the per-mode verdict + reason dicts.

    Three modes:
      - ``intensity_only``  : V1-style intensity → RGB rewrite. No voxel
        work. Only needs RGB columns to exist and XYZ to exist (the latter
        is a baseline requirement for any .e57 we'd process).
      - ``intensity_lambertian`` : Pass 1 (voxel accumulation + normals)
        then Pass 2 (shade). Needs RGB *and* fits in RAM.
      - ``normal_as_color`` : Debug mode — overwrites RGB with the
        normal-as-color encoding. Needs voxel work but ironically does
        not need the source to have RGB (we'll write the column anyway
        via the bake path; but to stay safe we still require RGB present
        because the production path is the same RGB-rewriting path).
    """
    verdicts: dict = {}
    reasons: dict = {}

    # ---- intensity_only --------------------------------------------------
    if not xyz_present_all:
        verdicts["intensity_only"] = "RED"
        reasons["intensity_only"] = (
            "cartesianX/Y/Z absent from one or more scans — cannot read points."
        )
    elif not rgb_present_all:
        verdicts["intensity_only"] = "RED"
        reasons["intensity_only"] = (
            "RGB (colorRed/Green/Blue) absent from one or more scans. "
            "V2.0 rewrites existing RGB columns; it does not inject color into "
            "intensity-only files."
        )
    else:
        # Intensity-only mode has no voxel grid; only the block buffer matters.
        # Always GREEN given the precondition checks above.
        verdicts["intensity_only"] = "GREEN"
        reasons["intensity_only"] = (
            "RGB present in all scans; streaming rewrite needs only block buffer "
            "RAM (~independent of point count)."
        )

    # ---- intensity_lambertian -------------------------------------------
    if not xyz_present_all:
        verdicts["intensity_lambertian"] = "RED"
        reasons["intensity_lambertian"] = (
            "cartesianX/Y/Z absent from one or more scans."
        )
    elif not rgb_present_all:
        verdicts["intensity_lambertian"] = "RED"
        reasons["intensity_lambertian"] = (
            "RGB absent from one or more scans; shading bakes into existing "
            "RGB columns (no injection in V2.0)."
        )
    else:
        ram_verdict = _classify_ram(max(pass1_ram, pass2_ram), system_ram)
        if ram_verdict == "RED":
            verdicts["intensity_lambertian"] = "RED"
            reasons["intensity_lambertian"] = (
                f"Upper-bound peak RAM ({_fmt_bytes(max(pass1_ram, pass2_ram))}) "
                f"exceeds 75% of system RAM ({_fmt_bytes(system_ram)}). "
                "Coarsen voxel_size or run the sampling pre-pass."
            )
        elif ram_verdict == "YELLOW":
            verdicts["intensity_lambertian"] = "YELLOW"
            reasons["intensity_lambertian"] = (
                f"Upper-bound peak RAM ({_fmt_bytes(max(pass1_ram, pass2_ram))}) "
                f"is 25-75% of system RAM ({_fmt_bytes(system_ram)}). "
                "Likely fine; sampling pre-pass available to tighten the estimate."
            )
        elif not has_aabb:
            verdicts["intensity_lambertian"] = "YELLOW"
            reasons["intensity_lambertian"] = (
                "Header AABB missing on at least one scan; RAM upper bound is "
                "not derivable from the header alone. Will be measured during job."
            )
        elif not embedded_normals:
            # Not fatal — we estimate normals via voxel PCA.
            verdicts["intensity_lambertian"] = "GREEN"
            reasons["intensity_lambertian"] = (
                f"RGB present, peak RAM upper bound "
                f"({_fmt_bytes(max(pass1_ram, pass2_ram))}) well under system "
                f"RAM ({_fmt_bytes(system_ram)}). Embedded normals absent — "
                "will estimate via voxel PCA."
            )
        else:
            verdicts["intensity_lambertian"] = "GREEN"
            reasons["intensity_lambertian"] = (
                f"RGB + embedded normals present; peak RAM upper bound "
                f"({_fmt_bytes(max(pass1_ram, pass2_ram))}) well under system "
                f"RAM ({_fmt_bytes(system_ram)})."
            )

    # ---- normal_as_color -------------------------------------------------
    if not xyz_present_all:
        verdicts["normal_as_color"] = "RED"
        reasons["normal_as_color"] = (
            "cartesianX/Y/Z absent from one or more scans."
        )
    elif not rgb_present_all:
        # Same RGB-rewriting path as the other modes; if no RGB columns
        # exist, we have nowhere to write the diagnostic color.
        verdicts["normal_as_color"] = "RED"
        reasons["normal_as_color"] = (
            "RGB absent from one or more scans; normal-as-color writes into "
            "existing RGB columns."
        )
    else:
        ram_verdict = _classify_ram(max(pass1_ram, pass2_ram), system_ram)
        if ram_verdict == "RED":
            verdicts["normal_as_color"] = "RED"
            reasons["normal_as_color"] = (
                f"Upper-bound peak RAM ({_fmt_bytes(max(pass1_ram, pass2_ram))}) "
                f"exceeds 75% of system RAM ({_fmt_bytes(system_ram)})."
            )
        elif ram_verdict == "YELLOW":
            verdicts["normal_as_color"] = "YELLOW"
            reasons["normal_as_color"] = (
                f"Upper-bound peak RAM ({_fmt_bytes(max(pass1_ram, pass2_ram))}) "
                f"is 25-75% of system RAM ({_fmt_bytes(system_ram)})."
            )
        elif not has_aabb:
            verdicts["normal_as_color"] = "YELLOW"
            reasons["normal_as_color"] = (
                "Header AABB missing on at least one scan; will measure during "
                "job."
            )
        else:
            verdicts["normal_as_color"] = "GREEN"
            reasons["normal_as_color"] = (
                f"Diagnostic mode; peak RAM upper bound "
                f"({_fmt_bytes(max(pass1_ram, pass2_ram))}) well under system "
                f"RAM ({_fmt_bytes(system_ram)})."
            )

    return verdicts, reasons


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def inspect_file(
    path: str,
    *,
    voxel_size: float = 0.5,
    chunk: int = 32,
    block_size: int = 1_000_000,
    system_ram_bytes: Optional[int] = None,
) -> CapabilityReport:
    """Build a :class:`CapabilityReport` from XML header metadata only.

    Does *not* read the binary CompressedVector payload — completes in
    well under 1 second on any file size.
    """
    t0 = time.perf_counter()

    if system_ram_bytes is None:
        system_ram_bytes = _detect_system_ram_bytes()

    try:
        file_size = os.path.getsize(path)
    except OSError:
        file_size = 0

    e57 = E57(path, mode="r")
    try:
        scan_count = e57.scan_count
        data3d = e57.data3d

        per_scan_point_counts: list = []
        per_scan_aabb_min: list = []
        per_scan_aabb_max: list = []
        rgb_present_in_all_scans = True
        xyz_present_in_all_scans = True
        organized_in_any_scan = False
        embedded_normals_in_any_scan = False

        file_aabb_min: Optional[list] = None
        file_aabb_max: Optional[list] = None

        for i in range(scan_count):
            raw = data3d.get(i)
            scan_node = raw if isinstance(raw, libe57.StructureNode) else libe57.StructureNode(raw)

            # Prototype field names — drives RGB / XYZ / organized / normals.
            field_names = _prototype_field_names(scan_node)
            if not _has_rgb(field_names):
                rgb_present_in_all_scans = False
            if not _has_xyz(field_names):
                xyz_present_in_all_scans = False
            if _has_organized(field_names):
                organized_in_any_scan = True
            if _has_normals(field_names):
                embedded_normals_in_any_scan = True

            # Point count comes from the CompressedVector header (no payload read).
            cv_raw = scan_node["points"]
            cv = (
                cv_raw
                if isinstance(cv_raw, libe57.CompressedVectorNode)
                else libe57.CompressedVectorNode(cv_raw)
            )
            per_scan_point_counts.append(int(cv.childCount()))

            aabb_min, aabb_max = _read_cartesian_bounds(scan_node)
            per_scan_aabb_min.append(aabb_min)
            per_scan_aabb_max.append(aabb_max)

            if aabb_min is not None and aabb_max is not None:
                if file_aabb_min is None:
                    file_aabb_min = list(aabb_min)
                    file_aabb_max = list(aabb_max)
                else:
                    for ax in range(3):
                        file_aabb_min[ax] = min(file_aabb_min[ax], aabb_min[ax])
                        file_aabb_max[ax] = max(file_aabb_max[ax], aabb_max[ax])
    finally:
        try:
            e57.close()
        except Exception:
            pass

    total_points = sum(per_scan_point_counts)

    file_aabb_min_t: Optional[tuple] = tuple(file_aabb_min) if file_aabb_min is not None else None
    file_aabb_max_t: Optional[tuple] = tuple(file_aabb_max) if file_aabb_max is not None else None

    has_aabb_all = all(
        amin is not None and amax is not None
        for amin, amax in zip(per_scan_aabb_min, per_scan_aabb_max)
    ) and scan_count > 0

    # Max possible chunk count derived from the *file-level* (union) AABB.
    # If any scan is missing its AABB, max_chunks falls back to 0 (treated
    # as "unknown") and the verdict logic gates on `has_aabb_all`.
    if has_aabb_all and file_aabb_min_t is not None and file_aabb_max_t is not None:
        max_chunks = _max_chunks_from_aabb(
            file_aabb_min_t, file_aabb_max_t, voxel_size, chunk
        )
    else:
        max_chunks = 0

    pass1_ram = _pass1_ram_bytes(max_chunks, chunk, block_size)
    pass2_ram = _pass2_ram_bytes(max_chunks, chunk, block_size)

    verdicts, reasons = _compute_verdicts(
        rgb_present_all=rgb_present_in_all_scans and scan_count > 0,
        xyz_present_all=xyz_present_in_all_scans and scan_count > 0,
        has_aabb=has_aabb_all,
        embedded_normals=embedded_normals_in_any_scan,
        pass1_ram=pass1_ram,
        pass2_ram=pass2_ram,
        system_ram=system_ram_bytes,
    )

    elapsed = time.perf_counter() - t0

    return CapabilityReport(
        file_path=path,
        file_size_bytes=file_size,
        scan_count=scan_count,
        total_points=total_points,
        per_scan_point_counts=per_scan_point_counts,
        per_scan_aabb_min=per_scan_aabb_min,
        per_scan_aabb_max=per_scan_aabb_max,
        file_aabb_min=file_aabb_min_t,
        file_aabb_max=file_aabb_max_t,
        rgb_present_in_all_scans=bool(rgb_present_in_all_scans and scan_count > 0),
        organized_in_any_scan=bool(organized_in_any_scan),
        embedded_normals_in_any_scan=bool(embedded_normals_in_any_scan),
        max_possible_chunk_count=int(max_chunks),
        pass1_peak_ram_upper_bound_bytes=int(pass1_ram),
        pass2_peak_ram_upper_bound_bytes=int(pass2_ram),
        verdicts=verdicts,
        verdict_reasons=reasons,
        elapsed_seconds=float(elapsed),
    )


# ---------------------------------------------------------------------------
# Optional sampling pre-pass
# ---------------------------------------------------------------------------


def estimate_touched_chunks(
    reader: "E57CloneReader",
    *,
    sample_blocks: int = 10,
    block_size: int = 200_000,
    voxel_size: float = 0.5,
    chunk: int = 32,
) -> dict:
    """Stream the first ``sample_blocks`` blocks of scan 0 to count the
    chunks actually occupied; extrapolate to a whole-file estimate.

    This **does** read binary data (one ScanBlockReader pass) — the UI
    only triggers it when the user clicks the "Estimate touched chunks"
    button.

    Returns
    -------
    dict
        ``{sample_points, total_points, chunks_in_sample,
        estimated_total_chunks, estimated_peak_ram_bytes}``.
    """
    chunk_extent = voxel_size * chunk
    if chunk_extent <= 0:
        raise ValueError("voxel_size * chunk must be positive")

    sample_points = 0
    chunk_ids: set = set()
    total_points = 0
    blocks_seen = 0

    for scan in reader.iter_scans():
        total_points += scan.total_points

    # Sample only scan 0. This matches the design ("first ~1% of blocks"
    # heuristic — extrapolation across scans is approximate by nature).
    scan0 = next(reader.iter_scans(), None)
    if scan0 is not None:
        for block in scan0.iter_blocks(block_size=block_size):
            cx = block.get("cartesianX")
            cy = block.get("cartesianY")
            cz = block.get("cartesianZ")
            if (
                cx is None or cx.numpy_array is None
                or cy is None or cy.numpy_array is None
                or cz is None or cz.numpy_array is None
            ):
                break
            x = cx.numpy_array
            y = cy.numpy_array
            z = cz.numpy_array
            # Integer chunk coordinates. Use floor-division on float64.
            cxs = np.floor_divide(x, chunk_extent).astype(np.int64)
            cys = np.floor_divide(y, chunk_extent).astype(np.int64)
            czs = np.floor_divide(z, chunk_extent).astype(np.int64)
            # Combine into a hashable ID; numpy view-as-bytes is fastest
            # for the size of blocks we expect (≤ block_size points).
            stacked = np.stack([cxs, cys, czs], axis=1).astype(np.int64)
            for row in stacked:
                chunk_ids.add((int(row[0]), int(row[1]), int(row[2])))
            sample_points += int(x.shape[0])
            blocks_seen += 1
            if blocks_seen >= sample_blocks:
                break

    chunks_in_sample = len(chunk_ids)
    if sample_points > 0 and total_points > 0:
        # Linear extrapolation with a ceiling at the dense-AABB upper
        # bound. Cap by `chunks_in_sample` × (total / sample) but never
        # below `chunks_in_sample` itself.
        ratio = total_points / sample_points
        # Saturation: once chunks_in_sample is already ~ all of them,
        # extrapolation should plateau. We don't have AABB context here,
        # so we just multiply and let the caller compare against the
        # header-derived upper bound.
        estimated_total_chunks = max(chunks_in_sample, int(math.ceil(chunks_in_sample * ratio)))
    else:
        estimated_total_chunks = chunks_in_sample

    estimated_peak_ram = _pass1_ram_bytes(
        estimated_total_chunks, chunk, block_size
    )

    return {
        "sample_points": int(sample_points),
        "total_points": int(total_points),
        "chunks_in_sample": int(chunks_in_sample),
        "estimated_total_chunks": int(estimated_total_chunks),
        "estimated_peak_ram_bytes": int(estimated_peak_ram),
    }
