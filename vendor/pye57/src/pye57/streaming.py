"""Streaming block-iter readers and writers for E57 CompressedVector scans.

This is the Wave 2 / B1 substrate that B2 (`intensity_rgb/io/e57_clone.py`)
sits on top of. The design contract (`stateful-hatching-kitten.md`
§"I/O substrate detail") requires:

1. The reader yields one ``dict[str, FieldBuffer]`` per fixed-size block of
   points, descaling known numeric fields into natural units.
2. Each ``FieldBuffer`` carries: the descaled numpy array, the source
   prototype node (so the writer can replicate dtype/scale/offset/precision
   exactly), and an optional raw-bytes handle for unknown vendor fields
   whose semantics we don't interpret.
3. The writer accepts the same ``dict[str, FieldBuffer]`` per block,
   round-tripping unknown fields by identity. Non-RGB fields **must** be
   the same Python object in/out — the writer doesn't allocate copies.

Prototype field selection
-------------------------
For every named field in the source CompressedVector's prototype, we pick a
numpy dtype that matches the prototype node's E57 storage type. The dtype
choices mirror what ``E57.make_buffer`` does for the V1 read path:

* ``FloatNode``     -> ``float64`` (E57_DOUBLE) or ``float32`` (E57_SINGLE)
* ``IntegerNode``   -> the smallest signed/unsigned int that fits min/max
* ``ScaledIntegerNode`` -> ``float64`` with ``doScaling=True`` so libE57
  descales raw -> raw*scale+offset transparently on read; on write we feed
  ``float64`` back and libE57 re-scales.
* ``StringNode`` in a CompressedVector -> not currently supported by the
  underlying SourceDestBuffer numpy bridge; we surface this as a raw
  passthrough field if it ever appears. (No known vendor uses string-typed
  point fields in practice; this branch is defensive.)

Unknown prototype node types
----------------------------
If the prototype contains a node type the binding can't bridge to numpy
(e.g. a nested StructureNode point field — vanishingly rare in real
scans), the reader marks that field as ``passthrough_bytes`` and the
writer round-trips the raw libE57 SourceDestBuffer with no numpy
interpretation. **Production V2.0 does not exercise this branch on the
known fixtures** (carpark_stairs and the synthetic set are pure numeric
point fields), but the contract is in place so vendor extensions don't
break us.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np

from pye57 import libe57
from pye57.libe57 import NodeType, FloatPrecision
from pye57.utils import get_fields, get_node


# ---------------------------------------------------------------------------
# FieldBuffer dataclass
# ---------------------------------------------------------------------------

@dataclass
class FieldBuffer:
    """One block of one field, ready for descaled-numpy reads or byte
    passthrough writes.

    Attributes
    ----------
    name:
        Field element name (e.g. ``"cartesianX"``, ``"colorRed"``).
    numpy_array:
        Per-block descaled values. Length is ``block_size`` for full
        blocks, less for the trailing block. ``None`` iff this is a
        passthrough field.
    prototype_node:
        The libe57 node from the **source** CompressedVector prototype
        (FloatNode / IntegerNode / ScaledIntegerNode / ...). Required for
        the writer to re-create an equivalent prototype.
    raw_bytes:
        Optional raw-bytes handle for unknown vendor fields. ``None`` for
        known numeric fields.
    descaled:
        True if ``numpy_array`` is already in natural units (descaled
        from raw integer storage). False indicates raw storage values
        (used for non-scaled integer/float fields where there is no
        "natural unit" distinction).
    """
    name: str
    numpy_array: Optional[np.ndarray]
    prototype_node: object
    raw_bytes: Optional[bytes] = None
    descaled: bool = True

    @property
    def is_passthrough(self) -> bool:
        return self.numpy_array is None and self.raw_bytes is not None


# ---------------------------------------------------------------------------
# Prototype inspection
# ---------------------------------------------------------------------------

@dataclass
class FieldSpec:
    """Resolved numpy dtype + scaling flags for one prototype field."""
    name: str
    node_type: NodeType
    prototype_node: object
    dtype: Optional[np.dtype]      # None for passthrough
    do_conversion: bool
    do_scaling: bool
    passthrough: bool


def _integer_dtype(min_v: int, max_v: int) -> np.dtype:
    """Pick the narrowest numpy int dtype that round-trips ``[min, max]``.

    Note libE57 SourceDestBuffer's numpy bridge supports
    int8/uint8/int16/uint16/int32/uint32/int64/bool/float32/float64. We
    avoid uint64 (libe57 binding does not advertise it).
    """
    if min_v >= 0:
        if max_v <= 1:
            return np.dtype(np.uint8)
        if max_v <= 0xFF:
            return np.dtype(np.uint8)
        if max_v <= 0xFFFF:
            return np.dtype(np.uint16)
        if max_v <= 0xFFFFFFFF:
            return np.dtype(np.uint32)
        return np.dtype(np.int64)
    if min_v >= -128 and max_v <= 127:
        return np.dtype(np.int8)
    if min_v >= -32768 and max_v <= 32767:
        return np.dtype(np.int16)
    if min_v >= -2_147_483_648 and max_v <= 2_147_483_647:
        return np.dtype(np.int32)
    return np.dtype(np.int64)


def resolve_field_specs(prototype_struct: "libe57.StructureNode") -> List[FieldSpec]:
    """Inspect a CompressedVector prototype and return one FieldSpec per
    child field, in declared XML order.
    """
    specs: List[FieldSpec] = []
    for i in range(prototype_struct.childCount()):
        # Use raw Node (not cast) so .type() is accessible. Then cast for
        # type-specific methods. utils.get_node returns the cast subclass
        # whose .type() pybind binding is not surfaced.
        child_raw = prototype_struct.get(i)
        ntype = child_raw.type()
        name = child_raw.elementName()

        if ntype == NodeType.E57_FLOAT:
            child = libe57.FloatNode(child_raw)
            precision = child.precision()
            dtype = (
                np.dtype(np.float32)
                if precision == FloatPrecision.E57_SINGLE
                else np.dtype(np.float64)
            )
            specs.append(FieldSpec(
                name=name,
                node_type=ntype,
                prototype_node=child,
                dtype=dtype,
                do_conversion=True,
                do_scaling=False,
                passthrough=False,
            ))

        elif ntype == NodeType.E57_INTEGER:
            child = libe57.IntegerNode(child_raw)
            dtype = _integer_dtype(child.minimum(), child.maximum())
            specs.append(FieldSpec(
                name=name,
                node_type=ntype,
                prototype_node=child,
                dtype=dtype,
                do_conversion=True,
                do_scaling=False,
                passthrough=False,
            ))

        elif ntype == NodeType.E57_SCALED_INTEGER:
            child = libe57.ScaledIntegerNode(child_raw)
            specs.append(FieldSpec(
                name=name,
                node_type=ntype,
                prototype_node=child,
                dtype=np.dtype(np.float64),
                do_conversion=True,
                do_scaling=True,
                passthrough=False,
            ))

        else:
            # Strings or nested structures in point prototypes are vanishingly
            # rare; route through passthrough so we don't drop the field.
            specs.append(FieldSpec(
                name=name,
                node_type=ntype,
                prototype_node=child_raw,
                dtype=None,
                do_conversion=False,
                do_scaling=False,
                passthrough=True,
            ))
    return specs


# ---------------------------------------------------------------------------
# Block-iter reader
# ---------------------------------------------------------------------------

class ScanBlockReader:
    """Iterates blocks of a single scan's CompressedVector point stream.

    Usage::

        reader = ScanBlockReader(image_file, compressed_vector_node, block_size=1_000_000)
        for block in reader:
            # block: Dict[str, FieldBuffer]
            ...
        reader.close()

    The reader holds onto its own numpy arrays and re-fills them per
    block; consumers that need to retain data across blocks must copy.
    The reader exposes ``field_specs`` for callers who want to introspect
    the prototype before iteration.
    """

    def __init__(
        self,
        image_file: "libe57.ImageFile",
        compressed_vector: "libe57.CompressedVectorNode",
        block_size: int = 1_000_000,
    ):
        if block_size < 1:
            raise ValueError("block_size must be >= 1")
        self._image_file = image_file
        self._cv = compressed_vector
        self._block_size = int(block_size)
        self._total_points = compressed_vector.childCount()
        self._points_read = 0

        prototype_struct = libe57.StructureNode(compressed_vector.prototype())
        self.field_specs: List[FieldSpec] = resolve_field_specs(prototype_struct)

        # Allocate persistent buffers + dbufs vector for the libE57 reader.
        self._np_arrays: Dict[str, Optional[np.ndarray]] = {}
        self._dbufs = libe57.VectorSourceDestBuffer()
        self._passthrough_fields: List[str] = []

        for spec in self.field_specs:
            if spec.passthrough:
                # No numpy buffer; libE57 will not see this field on read
                # and the value cannot be round-tripped through this
                # reader. Mark it for the FieldBuffer so the caller knows.
                self._np_arrays[spec.name] = None
                self._passthrough_fields.append(spec.name)
                continue
            arr = np.empty(self._block_size, dtype=spec.dtype)
            self._np_arrays[spec.name] = arr
            buf = libe57.SourceDestBuffer(
                self._image_file,
                spec.name,
                arr,
                self._block_size,
                spec.do_conversion,
                spec.do_scaling,
            )
            self._dbufs.append(buf)

        self._libe57_reader = compressed_vector.reader(self._dbufs)
        self._closed = False

    @property
    def total_points(self) -> int:
        return self._total_points

    @property
    def block_size(self) -> int:
        return self._block_size

    @property
    def field_names(self) -> List[str]:
        return [s.name for s in self.field_specs]

    def __iter__(self) -> Iterator[Dict[str, FieldBuffer]]:
        return self

    def __next__(self) -> Dict[str, FieldBuffer]:
        if self._closed or self._points_read >= self._total_points:
            self.close()
            raise StopIteration

        got = self._libe57_reader.read()
        if got == 0:
            self.close()
            raise StopIteration

        # Build per-field FieldBuffer with slices of length ``got``. We
        # slice rather than copy so the caller can do zero-copy reads
        # of full blocks; the slice is a view into the persistent
        # buffer and must not be retained past the next iteration.
        # For correctness B2 should copy if it stashes blocks.
        block: Dict[str, FieldBuffer] = {}
        for spec in self.field_specs:
            arr = self._np_arrays.get(spec.name)
            if arr is None:
                # Passthrough field — no data this iteration.
                block[spec.name] = FieldBuffer(
                    name=spec.name,
                    numpy_array=None,
                    prototype_node=spec.prototype_node,
                    raw_bytes=b"",
                    descaled=False,
                )
            else:
                block[spec.name] = FieldBuffer(
                    name=spec.name,
                    numpy_array=arr[:got],
                    prototype_node=spec.prototype_node,
                    raw_bytes=None,
                    descaled=spec.do_scaling,
                )

        self._points_read += got
        return block

    def close(self):
        if self._closed:
            return
        try:
            if self._libe57_reader.isOpen():
                self._libe57_reader.close()
        except Exception:
            pass
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ---------------------------------------------------------------------------
# Block-iter writer
# ---------------------------------------------------------------------------

def clone_prototype(
    src_prototype_struct: "libe57.StructureNode",
    dst_image: "libe57.ImageFile",
) -> "libe57.StructureNode":
    """Build a fresh prototype StructureNode in ``dst_image`` mirroring
    ``src_prototype_struct`` field-by-field.

    Each scalar field is re-created with identical type, precision,
    bounds, scale, and offset. This is what makes scale/offset/min-max
    round-trip exactly.
    """
    out = libe57.StructureNode(dst_image)
    for i in range(src_prototype_struct.childCount()):
        # Use raw Node for .type() access; cast for typed-method access.
        child_raw = src_prototype_struct.get(i)
        ntype = child_raw.type()
        name = child_raw.elementName()
        if ntype == NodeType.E57_FLOAT:
            child = libe57.FloatNode(child_raw)
            out.set(name, libe57.FloatNode(
                dst_image,
                child.value(),
                child.precision(),
                child.minimum(),
                child.maximum(),
            ))
        elif ntype == NodeType.E57_INTEGER:
            child = libe57.IntegerNode(child_raw)
            out.set(name, libe57.IntegerNode(
                dst_image,
                child.value(),
                child.minimum(),
                child.maximum(),
            ))
        elif ntype == NodeType.E57_SCALED_INTEGER:
            child = libe57.ScaledIntegerNode(child_raw)
            out.set(name, libe57.ScaledIntegerNode(
                dst_image,
                child.rawValue(),
                child.minimum(),
                child.maximum(),
                child.scale(),
                child.offset(),
            ))
        else:
            raise NotImplementedError(
                f"Cloning prototype field {name!r} of type {ntype} "
                "is not supported. Vendor extension fields with "
                "string/structure types are not in V2.0 scope."
            )
    return out


class ScanBlockWriter:
    """Streaming writer over a freshly-created CompressedVector scan.

    Built around a pre-cloned prototype StructureNode (use
    :func:`clone_prototype`) and a parent scan StructureNode that has
    been ``set("points", ...)`` to the new CompressedVectorNode. The
    construction order matters: the prototype, the scan node, and the
    appended scan-in-data3D must all be wired before any block is
    written, because libE57 writes the binary section incrementally.

    Use :func:`E57.begin_scan` or construct via :class:`ScanWriterBuilder`
    for the common path.
    """

    def __init__(
        self,
        image_file: "libe57.ImageFile",
        compressed_vector: "libe57.CompressedVectorNode",
        field_specs: List[FieldSpec],
        block_size: int = 1_000_000,
    ):
        if block_size < 1:
            raise ValueError("block_size must be >= 1")
        self._image_file = image_file
        self._cv = compressed_vector
        self._field_specs = field_specs
        self._block_size = int(block_size)

        # Reuse the same numpy buffers across blocks; we copy block data
        # into them before each write call.
        self._np_arrays: Dict[str, np.ndarray] = {}
        self._sbufs = libe57.VectorSourceDestBuffer()
        for spec in field_specs:
            if spec.passthrough:
                raise NotImplementedError(
                    f"Writing passthrough field {spec.name!r} is not "
                    "supported. Vendor extension fields with unknown "
                    "semantics cannot be written via the streaming "
                    "writer in V2.0."
                )
            arr = np.empty(self._block_size, dtype=spec.dtype)
            self._np_arrays[spec.name] = arr
            buf = libe57.SourceDestBuffer(
                self._image_file,
                spec.name,
                arr,
                self._block_size,
                spec.do_conversion,
                spec.do_scaling,
            )
            self._sbufs.append(buf)

        self._libe57_writer = compressed_vector.writer(self._sbufs)
        self._closed = False
        self._points_written = 0

    @property
    def points_written(self) -> int:
        return self._points_written

    def write_block(self, block: Dict[str, FieldBuffer]) -> int:
        """Write one block. All fields in ``self._field_specs`` must be
        present in ``block`` and carry matching-length numpy arrays.
        Returns the number of points written.
        """
        if self._closed:
            raise RuntimeError("ScanBlockWriter is closed")

        # Determine block length from the first known field.
        n = None
        for spec in self._field_specs:
            fb = block.get(spec.name)
            if fb is None:
                raise KeyError(
                    f"write_block: missing field {spec.name!r} "
                    f"(prototype declares {[s.name for s in self._field_specs]})"
                )
            if fb.numpy_array is None:
                raise ValueError(
                    f"write_block: field {spec.name!r} has no numpy_array "
                    "(passthrough fields cannot be written)"
                )
            if n is None:
                n = fb.numpy_array.shape[0]
            elif fb.numpy_array.shape[0] != n:
                raise ValueError(
                    f"write_block: field {spec.name!r} length "
                    f"{fb.numpy_array.shape[0]} != first field length {n}"
                )

        if n is None or n == 0:
            return
        if n > self._block_size:
            raise ValueError(
                f"write_block: block size {n} exceeds writer "
                f"block_size {self._block_size}"
            )

        # Copy into the persistent buffers, dtype-casting if needed.
        for spec in self._field_specs:
            src = block[spec.name].numpy_array
            dst = self._np_arrays[spec.name]
            if src.dtype != dst.dtype:
                # Cast lazily — the caller's transform may have produced
                # a different dtype (e.g. uint8 from intensity baking
                # into colorRed's IntegerNode which we stored as uint8).
                dst[:n] = src.astype(dst.dtype, copy=False)
            else:
                dst[:n] = src

        self._libe57_writer.write(n)
        self._points_written += n
        return n

    def close(self):
        if self._closed:
            return
        try:
            if self._libe57_writer.isOpen():
                self._libe57_writer.close()
        except Exception:
            pass
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ---------------------------------------------------------------------------
# High-level helper: build a destination scan with a cloned prototype
# ---------------------------------------------------------------------------

def build_scan_writer(
    dst_image: "libe57.ImageFile",
    dst_data3d: "libe57.VectorNode",
    src_scan_node: "libe57.StructureNode",
    *,
    block_size: int = 1_000_000,
    field_specs_override: Optional[List[FieldSpec]] = None,
) -> Tuple["libe57.StructureNode", ScanBlockWriter]:
    """Create a destination scan StructureNode mirroring ``src_scan_node``
    (metadata + prototype) and attach a :class:`ScanBlockWriter`.

    The destination scan is appended to ``dst_data3d`` immediately so
    libE57's writer can begin emitting binary packets. All scan-level
    metadata children except ``points`` are cloned via
    :func:`pye57.cloning.clone_node`; ``points`` is freshly constructed
    with a cloned prototype.

    Returns ``(dst_scan_node, writer)``. Caller is responsible for
    ``writer.close()`` (or use as a context manager).

    Parameters
    ----------
    field_specs_override:
        If provided, used instead of resolving from the source prototype.
        Lets callers (B2) inject a transform-aware spec list e.g. to
        force ``colorRed/Green/Blue`` to ``uint8`` dtype for baked RGB.
        When ``None``, specs are resolved from the source prototype.
    """
    from pye57.cloning import clone_node, finalize_blob_copies

    # __getitem__ returns the already-cast CompressedVectorNode; re-wrap
    # would fail pybind11's type check. Trust the cast.
    src_cv_any = src_scan_node["points"]
    if isinstance(src_cv_any, libe57.CompressedVectorNode):
        src_cv = src_cv_any
    else:
        src_cv = libe57.CompressedVectorNode(src_cv_any)
    src_prototype = libe57.StructureNode(src_cv.prototype())

    # Build the destination scan StructureNode, copying every metadata
    # child except ``points`` (which gets a fresh CompressedVectorNode).
    dst_scan = libe57.StructureNode(dst_image)
    deferred_blobs = []
    deferred_cvs = []
    for i in range(src_scan_node.childCount()):
        child = get_node(src_scan_node, i)
        name = child.elementName()
        if name == "points":
            continue
        cloned, cv_pairs, blob_pairs = clone_node(child, dst_image)
        dst_scan.set(name, cloned)
        deferred_blobs.extend(blob_pairs)
        deferred_cvs.extend(cv_pairs)

    # Build the destination prototype + an empty codecs VectorNode, then
    # the CompressedVectorNode itself.
    dst_prototype = clone_prototype(src_prototype, dst_image)
    dst_codecs = libe57.VectorNode(dst_image, True)
    dst_cv = libe57.CompressedVectorNode(dst_image, dst_prototype, dst_codecs)
    dst_scan.set("points", dst_cv)

    # Attach the scan to data3d *before* opening the writer, so the
    # binary section can be allocated.
    dst_data3d.append(dst_scan)

    # Finalize any blobs that came along in the metadata clone (e.g.
    # vendor extension binary payloads at the scan level — rare but
    # possible).
    finalize_blob_copies(deferred_blobs)

    if deferred_cvs:
        # Scan-level CompressedVectorNode children outside ``points`` are
        # not expected in V2.0 scope. If they appear, the caller must
        # handle them.
        raise NotImplementedError(
            "Scan-level CompressedVector children outside /points are "
            "not supported by build_scan_writer. Found: "
            f"{[p['in'].elementName() for p in deferred_cvs]}"
        )

    specs = field_specs_override or resolve_field_specs(src_prototype)
    writer = ScanBlockWriter(
        dst_image, dst_cv, specs, block_size=block_size
    )
    return dst_scan, writer
