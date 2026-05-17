"""G1a clone-fidelity test suite (Wave 2 / B3).

Gates M1 of the I/O substrate. For each fixture and each mode, asserts the
cloned `.e57` is bit-identical (Mode A), bit-identical except for RGB +
colorLimits (Mode B), or that the call fails fast with the documented
exception (Mode C).

Test contract is against `intensity_rgb.io.e57_clone` (built by Wave 2 / B2).
Tests will fail with ImportError until B2 lands — that's the intended TDD
signal.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import numpy as np
import pytest

import pye57
from pye57 import libe57

from intensity_rgb.io.e57_clone import (
    UnsupportedFileError,
    clone_file,
    constant_rgb_transform,
    identity_transform,
)
from tests.synthetic_e57 import (
    make_intensity_only,
    make_multi_scan,
    make_single_scan_rgb,
)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIXTURES_DIR = os.path.join(REPO_ROOT, "tests", "artifacts")
SYN_SINGLE = os.path.join(FIXTURES_DIR, "single_scan_rgb.e57")
SYN_MULTI = os.path.join(FIXTURES_DIR, "multi_scan.e57")
SYN_INT_ONLY = os.path.join(FIXTURES_DIR, "intensity_only.e57")
CARPARK = os.path.join(REPO_ROOT, "carpark_stairs.e57")


# ---------------------------------------------------------------------------
# Fixture setup
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def ensure_synthetic_fixtures():
    """Create the three synthetic fixtures if they're absent."""
    os.makedirs(FIXTURES_DIR, exist_ok=True)
    if not os.path.exists(SYN_SINGLE):
        make_single_scan_rgb(SYN_SINGLE, n_points=2000, seed=0)
    if not os.path.exists(SYN_MULTI):
        make_multi_scan(SYN_MULTI, n_scans=3, n_points_per_scan=500, seed=0)
    if not os.path.exists(SYN_INT_ONLY):
        make_intensity_only(SYN_INT_ONLY, n_points=1500, seed=0)
    yield


# ---------------------------------------------------------------------------
# Point-block bit-identity helpers
# ---------------------------------------------------------------------------


def read_all_scan_blocks(path):
    """Return list of dicts (one per scan): {field_name: ndarray}.

    Uses pye57.E57.read_scan_raw which materializes whatever the scan's
    prototype defines, descaled into natural units.
    """
    e = pye57.E57(path, mode="r")
    try:
        out = []
        for i in range(e.scan_count):
            data = e.read_scan_raw(i)
            out.append({k: np.asarray(v) for k, v in data.items()})
        return out
    finally:
        # pye57.E57 has no explicit close; drop the reference to release
        # the underlying libe57 ImageFile.
        del e


def assert_scans_bit_identical(src_path, dst_path, allowlist_fields=()):
    """Assert every scan's point block round-trips with bit-identical fields.

    Floats are compared with `np.allclose` at machine-epsilon tolerance
    (libE57's ScaledInteger encoding can introduce ULP-level drift but
    should otherwise be exact). Integer / uint8 fields are compared with
    `np.array_equal`.

    `allowlist_fields`: field names to skip entirely (used by Mode B for
    the RGB triple, since those are the ones we're rewriting).
    """
    src = read_all_scan_blocks(src_path)
    dst = read_all_scan_blocks(dst_path)
    assert len(src) == len(dst), (
        f"scan count differs: src={len(src)} dst={len(dst)}"
    )
    allow = set(allowlist_fields)
    for i, (s, d) in enumerate(zip(src, dst)):
        s_keys = set(s.keys())
        d_keys = set(d.keys())
        assert s_keys == d_keys, (
            f"scan {i} field set differs: only-in-src={s_keys - d_keys} "
            f"only-in-dst={d_keys - s_keys}"
        )
        for k in s_keys:
            if k in allow:
                continue
            a = s[k]
            b = d[k]
            assert a.shape == b.shape, (
                f"scan {i} field {k} shape differs: {a.shape} vs {b.shape}"
            )
            if np.issubdtype(a.dtype, np.floating) or np.issubdtype(
                b.dtype, np.floating
            ):
                if a.size == 0:
                    continue
                ok = np.allclose(a, b, rtol=1e-12, atol=1e-12)
                if not ok:
                    delta = np.abs(a.astype(np.float64) - b.astype(np.float64))
                    pytest.fail(
                        f"scan {i} field {k} not allclose: "
                        f"max |delta|={delta.max():.3e} "
                        f"(rtol=atol=1e-12)"
                    )
            else:
                assert np.array_equal(a, b), (
                    f"scan {i} field {k} integer bytes differ "
                    f"(first mismatch at index "
                    f"{int(np.argmax(a != b))})"
                )


# ---------------------------------------------------------------------------
# XML structural-equality helpers
# ---------------------------------------------------------------------------


# Map from libe57 NodeType enum value to a stable string tag we use in the
# walk descriptor. We use the cast-class isinstance check to derive this
# tag — `Node.type()` on a casted subclass is not exposed (NEW_API.md).
def _node_kind(node) -> str:
    if isinstance(node, libe57.StructureNode):
        return "Structure"
    if isinstance(node, libe57.VectorNode):
        return "Vector"
    if isinstance(node, libe57.CompressedVectorNode):
        return "CompressedVector"
    if isinstance(node, libe57.IntegerNode):
        return "Integer"
    if isinstance(node, libe57.ScaledIntegerNode):
        return "ScaledInteger"
    if isinstance(node, libe57.FloatNode):
        return "Float"
    if isinstance(node, libe57.StringNode):
        return "String"
    if isinstance(node, libe57.BlobNode):
        return "Blob"
    raise TypeError(f"Unknown node type: {type(node)!r}")


def _cast_node(parent, name_or_index):
    """Fetch a child by name (StructureNode) or index (VectorNode) and cast.

    Mirrors `pye57.utils.get_node` but accepts either lookup form. The cast
    is needed because the raw `Node` returned by `.get(...)` doesn't expose
    subclass-specific accessors like `.value()` / `.childCount()`.
    """
    raw = parent.get(name_or_index)
    t = raw.type()
    cast = {
        libe57.NodeType.E57_BLOB: libe57.BlobNode,
        libe57.NodeType.E57_COMPRESSED_VECTOR: libe57.CompressedVectorNode,
        libe57.NodeType.E57_FLOAT: libe57.FloatNode,
        libe57.NodeType.E57_INTEGER: libe57.IntegerNode,
        libe57.NodeType.E57_SCALED_INTEGER: libe57.ScaledIntegerNode,
        libe57.NodeType.E57_STRING: libe57.StringNode,
        libe57.NodeType.E57_STRUCTURE: libe57.StructureNode,
        libe57.NodeType.E57_VECTOR: libe57.VectorNode,
    }[t]
    return cast(raw)


def _walk_descriptor(node, path_name, ignore_substrings):
    """Return a hashable nested tuple describing `node`'s subtree.

    Subtree descriptor is a tuple of:
      (path_name, kind, payload_descriptor, children_descriptor)

    `payload_descriptor` captures leaf-node attributes that are invariant
    across an identity clone (e.g. ScaledInteger scale/offset, Integer
    min/max, Float precision). It deliberately ignores the *value* held
    inside a CompressedVector prototype's leaves — point payload identity
    is checked separately by `assert_scans_bit_identical`.

    `ignore_substrings`: subtrees whose pathName contains any of these are
    skipped entirely. Used to allowlist the file GUID + creationDateTime
    which change on every write.
    """
    # Allowlist skip: this whole subtree is invisible to the diff.
    for needle in ignore_substrings:
        if needle in path_name:
            return ("SKIP", path_name)

    kind = _node_kind(node)

    if kind == "Structure":
        children = []
        for i in range(node.childCount()):
            child = _cast_node(node, i)
            name = child.elementName()
            child_path = f"{path_name}/{name}"
            children.append(
                _walk_descriptor(child, child_path, ignore_substrings)
            )
        return (path_name, kind, None, tuple(children))

    if kind == "Vector":
        children = []
        for i in range(node.childCount()):
            child = _cast_node(node, i)
            child_path = f"{path_name}/{i}"
            children.append(
                _walk_descriptor(child, child_path, ignore_substrings)
            )
        payload = ("allowHeteroChildren", node.allowHeteroChildren())
        return (path_name, kind, payload, tuple(children))

    if kind == "CompressedVector":
        # We descend into the prototype + codecs for structural equality
        # but deliberately DO NOT enumerate the child records (those are
        # the point payload, validated via read_scan_raw separately).
        # `CompressedVectorNode.prototype()` and `.codecs()` already
        # return cast StructureNode / VectorNode — don't re-wrap.
        proto = node.prototype()
        if not isinstance(proto, libe57.StructureNode):
            proto = libe57.StructureNode(proto)
        codecs = node.codecs()
        if not isinstance(codecs, libe57.VectorNode):
            codecs = libe57.VectorNode(codecs)
        proto_desc = _walk_descriptor(
            proto, f"{path_name}/prototype", ignore_substrings
        )
        codecs_desc = _walk_descriptor(
            codecs, f"{path_name}/codecs", ignore_substrings
        )
        payload = ("childCount", node.childCount())
        return (path_name, kind, payload, (proto_desc, codecs_desc))

    if kind == "Integer":
        payload = (
            "minimum", node.minimum(),
            "maximum", node.maximum(),
        )
        # NOTE: we deliberately do NOT include .value() for leaf-Integer
        # children of a CompressedVector prototype (it's always 0 — the
        # prototype is a template, not data). For standalone Integer nodes
        # (e.g. inside indexBounds), .value() is meaningful, so include it.
        # The simple heuristic: include .value() — it's harmless for
        # prototype leaves (0 == 0) and load-bearing elsewhere.
        payload = payload + ("value", node.value())
        return (path_name, kind, payload, ())

    if kind == "ScaledInteger":
        payload = (
            "minimum", node.minimum(),
            "maximum", node.maximum(),
            "scale", node.scale(),
            "offset", node.offset(),
            "rawValue", node.rawValue(),
        )
        return (path_name, kind, payload, ())

    if kind == "Float":
        payload = (
            "precision", int(node.precision()),
            "minimum", node.minimum(),
            "maximum", node.maximum(),
            "value", node.value(),
        )
        return (path_name, kind, payload, ())

    if kind == "String":
        payload = ("value", node.value())
        return (path_name, kind, payload, ())

    if kind == "Blob":
        # Compare blob payload byte-by-byte using a hash to keep the
        # descriptor compact. Reading the full buffer is fine for the
        # fixtures we test (synthetic + carpark_stairs has no blobs).
        import hashlib

        n_bytes = node.byteCount()
        h = hashlib.sha256()
        if n_bytes:
            buf = node.read_buffer()
            h.update(bytes(buf))
        payload = (
            "byteCount", n_bytes,
            "sha256", h.hexdigest(),
        )
        return (path_name, kind, payload, ())

    raise AssertionError(f"unhandled node kind: {kind}")


def _format_walk_diff(left, right, indent=0):
    """Best-effort diff between two walk descriptors for error messages."""
    pad = "  " * indent
    if left == right:
        return ""
    if not isinstance(left, tuple) or not isinstance(right, tuple):
        return f"{pad}{left!r} != {right!r}\n"
    if len(left) != len(right):
        return f"{pad}tuple length differs: {len(left)} vs {len(right)}\n"
    parts = []
    for a, b in zip(left, right):
        if a != b:
            if isinstance(a, tuple) and isinstance(b, tuple):
                parts.append(_format_walk_diff(a, b, indent + 1))
            else:
                parts.append(f"{pad}{a!r} != {b!r}\n")
    return "".join(parts) or f"{pad}{left!r} != {right!r}\n"


def assert_xml_structurally_equal(src_path, dst_path, ignore_xpath_substrings=()):
    """Open both files, walk the root structure, assert descriptors match.

    Skips any subtree whose pathName contains a substring in
    `ignore_xpath_substrings` (used to allowlist the file GUID and per-scan
    creationDateTime nodes that legitimately change on every write).
    """
    src = pye57.E57(src_path, mode="r")
    dst = pye57.E57(dst_path, mode="r")
    try:
        # `E57.root` returns an already-cast StructureNode (pybind11
        # cast_node); don't wrap it again, that would fail the
        # __init__(Node n) overload because it's no longer a base Node.
        src_root = src.root
        dst_root = dst.root
        src_desc = _walk_descriptor(src_root, "/", ignore_xpath_substrings)
        dst_desc = _walk_descriptor(dst_root, "/", ignore_xpath_substrings)
    finally:
        del src
        del dst
    if src_desc != dst_desc:
        diff = _format_walk_diff(src_desc, dst_desc)
        pytest.fail(
            "XML structural mismatch between source and clone:\n" + diff[:8000]
        )


# ---------------------------------------------------------------------------
# colorLimits assertion (used by Mode B)
# ---------------------------------------------------------------------------


def _read_color_limits(path):
    """Return a list (one per scan) of (rmin, rmax, gmin, gmax, bmin, bmax)
    pulled from each scan's `/data3D[i]/colorLimits` StructureNode.

    Raises AssertionError if a scan lacks `colorLimits` — callers use this
    only after asserting RGB is present.
    """
    e = pye57.E57(path, mode="r")
    try:
        # `E57.root` is already a cast StructureNode; don't re-wrap it.
        root = e.root
        # root.get(name) returns base Node; wrap to VectorNode.
        data3d = libe57.VectorNode(root.get("data3D"))
        out = []
        for i in range(data3d.childCount()):
            scan = libe57.StructureNode(data3d.get(i))
            assert scan.isDefined("colorLimits"), (
                f"scan {i} missing colorLimits"
            )
            cl = libe57.StructureNode(scan.get("colorLimits"))
            vals = []
            for key in (
                "colorRedMinimum",
                "colorRedMaximum",
                "colorGreenMinimum",
                "colorGreenMaximum",
                "colorBlueMinimum",
                "colorBlueMaximum",
            ):
                node = _cast_node(cl, key)
                if isinstance(
                    node, (libe57.IntegerNode, libe57.ScaledIntegerNode)
                ):
                    vals.append(int(node.value()) if isinstance(
                        node, libe57.IntegerNode
                    ) else float(node.scaledValue()))
                elif isinstance(node, libe57.FloatNode):
                    vals.append(float(node.value()))
                else:
                    raise AssertionError(
                        f"unexpected colorLimits child type for {key}: "
                        f"{type(node)}"
                    )
            out.append(tuple(vals))
        return out
    finally:
        del e


# ---------------------------------------------------------------------------
# Optional libE57 validator
# ---------------------------------------------------------------------------


def maybe_run_e57validate(path):
    """Run libE57Format's e57validate CLI if available; no-op otherwise.

    We deliberately do NOT call `pytest.skip` here — the rest of the test
    (which is the actual fidelity assertion) has already passed by the
    time this runs. Skipping at this point would mask the pass as SKIPPED
    in the test report. Instead we just return when the validator is
    absent; CI can install libE57Format to opt into the extra check.
    """
    exe = shutil.which("e57validate") or shutil.which("e57_validate")
    if not exe:
        return
    r = subprocess.run([exe, path], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, (
        f"e57validate failed: stdout={r.stdout!r} stderr={r.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Mode A — pure clone, identity transform
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "src",
    [
        SYN_SINGLE,
        SYN_MULTI,
        CARPARK,
    ],
    ids=["single_scan_rgb", "multi_scan", "carpark_stairs"],
)
def test_mode_a_pure_clone_bit_identical_scans(src, tmp_path):
    """Identity-clone every scan and assert point blocks are bit-identical."""
    if not os.path.exists(src):
        pytest.skip(f"fixture missing: {src}")
    dst = str(tmp_path / "clone.e57")
    result = clone_file(
        src, dst, transform=identity_transform, update_color_limits=False
    )
    assert isinstance(result, dict), f"clone_file should return a dict, got {type(result)}"
    assert result.get("scan_count", 0) >= 1, (
        f"clone_file reported scan_count={result.get('scan_count')!r}"
    )
    assert os.path.exists(dst), "clone output not created"
    assert_scans_bit_identical(src, dst, allowlist_fields=())
    maybe_run_e57validate(dst)


# Allowlisted XML paths whose content legitimately changes on every write:
#   /guid                  — file-level GUID; libE57 mints a fresh one.
#   /creationDateTime      — file-level write timestamp.
#   /e57LibraryVersion     — the writing library's self-stamp (different
#                            writer code path between the original fixture
#                            and pye57's wrapper, so this drifts even on
#                            an "identity" clone).
_IDENTITY_CLONE_ALLOWLIST = ("/guid", "/creationDateTime", "/e57LibraryVersion")


def test_mode_a_xml_structurally_equal_carpark(tmp_path):
    """Whole-file XML structural equality on the real carpark fixture."""
    if not os.path.exists(CARPARK):
        pytest.skip(f"carpark fixture missing: {CARPARK}")
    dst = str(tmp_path / "clone.e57")
    clone_file(CARPARK, dst, transform=identity_transform)
    assert_xml_structurally_equal(
        CARPARK,
        dst,
        ignore_xpath_substrings=_IDENTITY_CLONE_ALLOWLIST,
    )


def test_mode_a_xml_structurally_equal_multi(tmp_path):
    """Multi-scan structural equality — exercises Vector/Structure walks."""
    dst = str(tmp_path / "clone_multi.e57")
    clone_file(SYN_MULTI, dst, transform=identity_transform)
    assert_xml_structurally_equal(
        SYN_MULTI,
        dst,
        ignore_xpath_substrings=_IDENTITY_CLONE_ALLOWLIST,
    )


# ---------------------------------------------------------------------------
# Mode B — constant-RGB transform
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "src",
    [
        SYN_SINGLE,
        CARPARK,
    ],
    ids=["single_scan_rgb", "carpark_stairs"],
)
def test_mode_b_constant_rgb_rewrites_only_color(src, tmp_path):
    """Constant-RGB transform rewrites color, leaves all other fields intact."""
    if not os.path.exists(src):
        pytest.skip(f"fixture missing: {src}")
    dst = str(tmp_path / "constrgb.e57")
    rgb = (255, 0, 0)
    clone_file(
        src,
        dst,
        transform=constant_rgb_transform(rgb),
        update_color_limits=True,
    )

    # RGB columns are constant at the requested triple.
    out_blocks = read_all_scan_blocks(dst)
    for i, scan in enumerate(out_blocks):
        for ch, expected in zip(
            ("colorRed", "colorGreen", "colorBlue"), rgb
        ):
            assert ch in scan, f"scan {i}: clone is missing {ch}"
            uniq = np.unique(scan[ch])
            assert uniq.size == 1 and int(uniq[0]) == expected, (
                f"scan {i} {ch} not constant {expected}: "
                f"unique values {uniq.tolist()[:8]}"
            )

    # Non-RGB fields must still match the source exactly.
    assert_scans_bit_identical(
        src,
        dst,
        allowlist_fields=("colorRed", "colorGreen", "colorBlue"),
    )

    # colorLimits in the destination XML must report [0, 255] on every
    # channel for every scan.
    limits = _read_color_limits(dst)
    assert len(limits) == len(out_blocks)
    for i, lim in enumerate(limits):
        rmin, rmax, gmin, gmax, bmin, bmax = lim
        assert (rmin, gmin, bmin) == (0, 0, 0), (
            f"scan {i} colorLimits min not 0: {(rmin, gmin, bmin)}"
        )
        assert (rmax, gmax, bmax) == (255, 255, 255), (
            f"scan {i} colorLimits max not 255: {(rmax, gmax, bmax)}"
        )

    maybe_run_e57validate(dst)


# ---------------------------------------------------------------------------
# Mode C — fail-fast on intensity-only fixture
# ---------------------------------------------------------------------------


def test_mode_c_intensity_only_raises(tmp_path):
    """clone_file must raise UnsupportedFileError when RGB fields are absent."""
    dst = str(tmp_path / "should_not_exist.e57")
    with pytest.raises(UnsupportedFileError) as excinfo:
        clone_file(
            SYN_INT_ONLY,
            dst,
            transform=constant_rgb_transform((1, 2, 3)),
            update_color_limits=True,
        )
    # The documented error string from the B2 contract.
    assert "no RGB fields" in str(excinfo.value), (
        f"unexpected error message: {excinfo.value!r}"
    )
    assert not os.path.exists(dst), (
        "output file must not be created on fail-fast"
    )
