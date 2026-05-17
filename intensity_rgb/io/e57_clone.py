"""E57 streaming clone reader/writer built on the Wave 2 / B1 substrate.

This module sits on top of ``pye57.streaming`` (block I/O) and
``pye57.cloning`` (recursive node copy) and exposes the surface that
``intensity_rgb.processing.pipeline`` (Wave 3) and the G1a smoke / fidelity
tests (Wave 2 / B3) drive:

* :class:`E57CloneReader` — context-managed source-file view that yields one
  :class:`ScanReader` per scan. Each ``ScanReader`` exposes per-block
  ``Dict[str, FieldBuffer]`` iteration via the underlying
  :class:`pye57.streaming.ScanBlockReader`.
* :class:`E57CloneWriter` — context-managed destination-file view that
  mirrors file-level header, ``images2D``, ``pointGroupingSchemes``, and
  arbitrary vendor extensions. ``begin_scan`` returns a :class:`ScanWriter`
  which round-trips one scan's points through a transform.
* :func:`clone_file` — one-call orchestration matching the contract in
  ``stateful-hatching-kitten.md``. ``intensity_rgb.processing.pipeline``
  invokes this with a real intensity-->RGB transform; G1a Mode A/B use
  :func:`identity_transform` / :func:`constant_rgb_transform`.

Public contract is frozen for B3's tests. Don't change the function
signatures.
"""

from __future__ import annotations

import os
from typing import Callable, Dict, Iterator, List, Optional

import numpy as np

from pye57 import E57, libe57
from pye57.cloning import (
    clone_node,
    copy_extensions,
    finalize_blob_copies,
)
from pye57.streaming import (
    FieldBuffer,  # re-exported for caller convenience
    ScanBlockReader,
    ScanBlockWriter,
    clone_prototype,
    resolve_field_specs,
)
from pye57.utils import get_node


__all__ = [
    "FieldBuffer",
    "E57CloneReader",
    "E57CloneWriter",
    "ScanReader",
    "ScanWriter",
    "UnsupportedFileError",
    "identity_transform",
    "constant_rgb_transform",
    "clone_file",
]


# E57 root-level child names defined by the ASTM E57 standard. Anything
# the source root contains *outside* this set is treated as a vendor /
# unknown extension subtree and propagated verbatim via ``clone_node``.
_STANDARD_ROOT_CHILDREN = frozenset({
    "formatName",
    "guid",
    "versionMajor",
    "versionMinor",
    "e57LibraryVersion",
    "coordinateMetadata",
    "creationDateTime",
    "data3D",
    "images2D",
    "pointGroupingSchemes",
})


class UnsupportedFileError(Exception):
    """Raised when a source file cannot be processed under the requested
    transform — most often because a scan lacks RGB fields but the
    caller asked us to bake / update colours.
    """


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------


class ScanReader:
    """Per-scan view: metadata dict, prototype field names, block iterator.

    The reader holds onto the source ``libe57.StructureNode`` so the
    matching :class:`ScanWriter` can clone the scan's metadata + prototype
    exactly.
    """

    def __init__(self, parent: "E57CloneReader", index: int):
        self._parent = parent
        self._index = index
        # VectorNode.get(i) returns the base Node; cast manually.
        raw = parent._data3d.get(index)
        self._scan_node = libe57.StructureNode(raw)
        cv_any = self._scan_node["points"]
        if isinstance(cv_any, libe57.CompressedVectorNode):
            self._cv = cv_any
        else:
            self._cv = libe57.CompressedVectorNode(cv_any)
        self._prototype = libe57.StructureNode(self._cv.prototype())
        self._field_specs = resolve_field_specs(self._prototype)

    # -- Introspection ------------------------------------------------------

    @property
    def index(self) -> int:
        return self._index

    @property
    def scan_node(self) -> "libe57.StructureNode":
        """Source ``StructureNode`` for this scan. Used by ``begin_scan``."""
        return self._scan_node

    @property
    def total_points(self) -> int:
        return self._cv.childCount()

    @property
    def prototype_field_names(self) -> List[str]:
        return [s.name for s in self._field_specs]

    @property
    def metadata(self) -> dict:
        """Best-effort scalar metadata dict (name/guid/pose/etc.).

        Only nodes that have an obvious scalar representation are surfaced
        here; structure / vector / compressed-vector children are
        omitted. Callers that need to clone the full tree must use the
        underlying ``scan_node`` — the destination ``ScanWriter`` already
        does this automatically.
        """
        meta: dict = {}
        for i in range(self._scan_node.childCount()):
            raw = self._scan_node.get(i)
            ntype = raw.type()
            name = raw.elementName()
            if name == "points":
                continue
            if ntype == libe57.NodeType.E57_STRING:
                meta[name] = libe57.StringNode(raw).value()
            elif ntype == libe57.NodeType.E57_FLOAT:
                meta[name] = libe57.FloatNode(raw).value()
            elif ntype == libe57.NodeType.E57_INTEGER:
                meta[name] = libe57.IntegerNode(raw).value()
            elif ntype == libe57.NodeType.E57_SCALED_INTEGER:
                node = libe57.ScaledIntegerNode(raw)
                meta[name] = node.rawValue() * node.scale() + node.offset()
            # Structure / Vector children (pose, indexBounds, etc.) are
            # represented as their element name with value=True so callers
            # can detect presence without recursing.
            else:
                meta[name] = True
        return meta

    def has_rgb(self) -> bool:
        names = self.prototype_field_names
        return all(c in names for c in ("colorRed", "colorGreen", "colorBlue"))

    def iter_blocks(
        self, block_size: int = 1_000_000
    ) -> Iterator[Dict[str, FieldBuffer]]:
        """Iterate ``Dict[str, FieldBuffer]`` blocks for this scan.

        Each ``FieldBuffer.numpy_array`` is a view into a buffer the
        underlying reader reuses across blocks. Copy if you need to retain.
        """
        with ScanBlockReader(
            self._parent._image_file, self._cv, block_size=block_size
        ) as reader:
            for block in reader:
                yield block


class E57CloneReader:
    """Context-managed E57 source view used by the clone pipeline."""

    def __init__(self, path: str):
        self._path = path
        self._e57: Optional[E57] = None
        self._image_file = None
        self._data3d = None

    def __enter__(self) -> "E57CloneReader":
        self._e57 = E57(self._path, mode="r")
        self._image_file = self._e57.image_file
        self._data3d = self._e57.data3d
        return self

    def __exit__(self, *exc):
        if self._e57 is not None:
            try:
                self._e57.close()
            except Exception:
                pass
            self._e57 = None
            self._image_file = None
            self._data3d = None

    # -- Introspection ------------------------------------------------------

    @property
    def path(self) -> str:
        return self._path

    @property
    def scan_count(self) -> int:
        return self._e57.scan_count

    @property
    def image_file(self):
        return self._image_file

    @property
    def root(self):
        return self._e57.root

    @property
    def file_header(self) -> dict:
        """Parsed file-level metadata: formatName, guid, versionMajor,
        versionMinor, e57LibraryVersion, coordinateMetadata,
        creationDateTime.dateTimeValue, creationDateTime.isAtomicClockReferenced.

        Returned dict carries Python scalars only — clone the underlying
        XML subtrees via :meth:`E57CloneWriter.clone_node` if you need to
        preserve a non-scalar field.
        """
        root = self.root
        h: dict = {}
        for key in ("formatName", "guid", "e57LibraryVersion", "coordinateMetadata"):
            if root.isDefined(key):
                node_raw = root.get(key)
                if node_raw.type() == libe57.NodeType.E57_STRING:
                    h[key] = libe57.StringNode(node_raw).value()
        for key in ("versionMajor", "versionMinor"):
            if root.isDefined(key):
                node_raw = root.get(key)
                if node_raw.type() == libe57.NodeType.E57_INTEGER:
                    h[key] = libe57.IntegerNode(node_raw).value()
        if root.isDefined("creationDateTime"):
            cdt = libe57.StructureNode(root.get("creationDateTime"))
            if cdt.isDefined("dateTimeValue"):
                h["creationDateTime.dateTimeValue"] = libe57.FloatNode(
                    cdt.get("dateTimeValue")
                ).value()
            if cdt.isDefined("isAtomicClockReferenced"):
                h["creationDateTime.isAtomicClockReferenced"] = libe57.IntegerNode(
                    cdt.get("isAtomicClockReferenced")
                ).value()
        return h

    def iter_scans(self) -> Iterator[ScanReader]:
        for i in range(self.scan_count):
            yield ScanReader(self, i)

    @property
    def images2D(self) -> list:
        """List of source ``StructureNode``s under ``/images2D`` (one per
        2D image). Opaque to the caller — pass each to
        :meth:`E57CloneWriter.copy_image2D` to copy.
        """
        root = self.root
        if not root.isDefined("images2D"):
            return []
        vec_raw = root.get("images2D")
        vec = vec_raw if isinstance(vec_raw, libe57.VectorNode) else libe57.VectorNode(vec_raw)
        out: list = []
        for i in range(vec.childCount()):
            child_raw = vec.get(i)
            out.append(libe57.StructureNode(child_raw))
        return out

    @property
    def extra_nodes(self) -> list:
        """Top-level XML children outside the ASTM standard schema.

        Returned as raw libe57 ``Node`` handles (callers should not try to
        introspect — use :meth:`E57CloneWriter.clone_node` to forward each
        to the destination root).
        """
        root = self.root
        out: list = []
        for i in range(root.childCount()):
            raw = root.get(i)
            if raw.elementName() in _STANDARD_ROOT_CHILDREN:
                continue
            out.append(raw)
        return out


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


class ScanWriter:
    """Per-scan writer.

    Built by :meth:`E57CloneWriter.begin_scan`. Internally wires the
    destination scan ``StructureNode`` (with cloned metadata except
    ``points``) into ``/data3D`` and opens a streaming
    :class:`pye57.streaming.ScanBlockWriter` against a freshly-cloned
    prototype.
    """

    def __init__(
        self,
        dst_image,
        dst_scan: "libe57.StructureNode",
        dst_cv: "libe57.CompressedVectorNode",
        writer: ScanBlockWriter,
        *,
        owns_color_limits: bool,
    ):
        self._dst_image = dst_image
        self._dst_scan = dst_scan
        self._dst_cv = dst_cv
        self._writer = writer
        # If True, this writer is responsible for inserting a fresh
        # ``colorLimits`` StructureNode before close (set via
        # :meth:`update_color_limits`). If False, ``colorLimits`` was
        # already cloned from source by ``begin_scan``.
        self._owns_color_limits = owns_color_limits
        self._color_limits_set = False

    def __enter__(self) -> "ScanWriter":
        return self

    def __exit__(self, *exc):
        self.close()

    @property
    def points_written(self) -> int:
        return self._writer.points_written

    def write_block(self, block: Dict[str, FieldBuffer]) -> int:
        return self._writer.write_block(block)

    def update_color_limits(
        self,
        *,
        r_min: int = 0,
        r_max: int = 255,
        g_min: int = 0,
        g_max: int = 255,
        b_min: int = 0,
        b_max: int = 255,
    ) -> None:
        """Write the destination scan's ``colorLimits`` StructureNode.

        Called on the RGB-rewrite path (G1a Mode B / production bake) to
        record the new colour range. Must only be invoked when this
        ``ScanWriter`` was created with ``owns_color_limits=True``
        (i.e. the caller asked :class:`E57CloneWriter.begin_scan` to
        defer the colour-limits clone so we can rewrite them).
        """
        if not self._owns_color_limits:
            raise RuntimeError(
                "update_color_limits called on a ScanWriter whose colorLimits "
                "were already cloned from source; "
                "create the writer via begin_scan(..., own_color_limits=True) "
                "to enable this."
            )
        if self._color_limits_set:
            raise RuntimeError("colorLimits already written for this scan")
        cl = libe57.StructureNode(self._dst_image)
        cl.set("colorRedMinimum", libe57.IntegerNode(self._dst_image, r_min))
        cl.set("colorRedMaximum", libe57.IntegerNode(self._dst_image, r_max))
        cl.set("colorGreenMinimum", libe57.IntegerNode(self._dst_image, g_min))
        cl.set("colorGreenMaximum", libe57.IntegerNode(self._dst_image, g_max))
        cl.set("colorBlueMinimum", libe57.IntegerNode(self._dst_image, b_min))
        cl.set("colorBlueMaximum", libe57.IntegerNode(self._dst_image, b_max))
        self._dst_scan.set("colorLimits", cl)
        self._color_limits_set = True

    def close(self):
        self._writer.close()


class E57CloneWriter:
    """Context-managed E57 destination view used by the clone pipeline."""

    def __init__(self, path: str, source: E57CloneReader):
        self._path = path
        self._source = source
        self._e57: Optional[E57] = None
        self._image_file = None
        self._data3d = None
        self._closed_scans: list = []

    def __enter__(self) -> "E57CloneWriter":
        # E57(mode="w") auto-calls write_default_header which already
        # creates formatName/guid/versionMajor/versionMinor/
        # e57LibraryVersion/coordinateMetadata/creationDateTime/data3D/
        # images2D. We *don't* recreate any of these; copy_file_header
        # will overwrite-only the ones that make sense to preserve.
        self._e57 = E57(self._path, mode="w")
        self._image_file = self._e57.image_file
        self._data3d = self._e57.data3d
        copy_extensions(self._source.image_file, self._image_file)
        return self

    def __exit__(self, *exc):
        if self._e57 is not None:
            try:
                self._e57.close()
            except Exception:
                pass
            self._e57 = None
            self._image_file = None
            self._data3d = None

    # -- File-level header & extras ---------------------------------------

    def copy_file_header(self) -> None:
        """Mirror file-level metadata that ``write_default_header`` left at
        defaults — currently ``coordinateMetadata`` only.

        Most file-level header fields (formatName/guid/versionMajor/
        versionMinor/e57LibraryVersion/creationDateTime) are
        intentionally not overwritten: libE57 already produced a valid
        fresh set, and re-using the source guid would violate "each
        file has a unique guid".
        """
        src_root = self._source.root
        if src_root.isDefined("coordinateMetadata"):
            cm_raw = src_root.get("coordinateMetadata")
            if cm_raw.type() == libe57.NodeType.E57_STRING:
                # The default header already set "" — we just have to
                # mutate the existing StringNode's value, but libE57
                # StringNodes are immutable. Re-set the child instead.
                # libE57 supports re-setting an existing child with the
                # same name only if it carries the same node type +
                # signature; StringNode-on-StringNode is fine.
                dst_root = self._image_file.root()
                try:
                    dst_root.set(
                        "coordinateMetadata",
                        libe57.StringNode(self._image_file, libe57.StringNode(cm_raw).value()),
                    )
                except libe57.E57Exception:
                    # libE57 rejects re-set; keep the default empty string.
                    pass

    def copy_image2D(self, image_node: "libe57.StructureNode") -> None:
        """Append a cloned ``images2D`` entry to the destination root."""
        dst_root = self._image_file.root()
        images2d_raw = dst_root.get("images2D")
        images2d = (
            images2d_raw
            if isinstance(images2d_raw, libe57.VectorNode)
            else libe57.VectorNode(images2d_raw)
        )
        cloned, cv_pairs, blob_pairs = clone_node(image_node, self._image_file)
        images2d.append(cloned)
        finalize_blob_copies(blob_pairs)
        if cv_pairs:
            # images2D entries should not contain CompressedVectorNode
            # children in any known E57 producer. Surface loudly if we
            # ever see one.
            raise NotImplementedError(
                "images2D entry contains a CompressedVectorNode child; "
                "this is not supported by E57CloneWriter."
            )

    def clone_node(self, src_node) -> None:
        """Forward a top-level extra (vendor-extension) node into the
        destination root, preserving its element name."""
        name = src_node.elementName()
        dst_root = self._image_file.root()
        if dst_root.isDefined(name):
            # Standard children (formatName, etc.) shouldn't be passed
            # through here. If we get a conflict, log loudly.
            raise ValueError(
                f"clone_node: destination root already has child {name!r}; "
                "extras must not collide with standard E57 schema."
            )
        cloned, cv_pairs, blob_pairs = clone_node(src_node, self._image_file)
        dst_root.set(name, cloned)
        finalize_blob_copies(blob_pairs)
        if cv_pairs:
            raise NotImplementedError(
                f"extra_node {name!r} contains a CompressedVectorNode child; "
                "streaming copy of file-level extras is not in V2.0 scope."
            )

    def copy_pointGroupingSchemes_if_present(self) -> None:
        src_root = self._source.root
        if not src_root.isDefined("pointGroupingSchemes"):
            return
        src_node = src_root.get("pointGroupingSchemes")
        dst_root = self._image_file.root()
        cloned, cv_pairs, blob_pairs = clone_node(src_node, self._image_file)
        dst_root.set("pointGroupingSchemes", cloned)
        finalize_blob_copies(blob_pairs)
        if cv_pairs:
            raise NotImplementedError(
                "pointGroupingSchemes contains a CompressedVectorNode; "
                "streaming copy is not in V2.0 scope."
            )

    # -- Scan-level writer entrypoint --------------------------------------

    def begin_scan(
        self,
        scan_reader: ScanReader,
        *,
        block_size: int = 1_000_000,
        own_color_limits: bool = False,
    ) -> ScanWriter:
        """Open a streaming writer for one destination scan.

        Clones the scan's metadata (every child except ``points``) and
        constructs a fresh ``points`` CompressedVectorNode with a cloned
        prototype.

        Parameters
        ----------
        own_color_limits:
            When True, the destination scan is created **without** a
            cloned ``colorLimits`` child. The caller must subsequently
            invoke :meth:`ScanWriter.update_color_limits` so the
            destination scan ends up with a valid (rewritten)
            ``colorLimits`` before the file is closed. This branch is
            taken on the G1a Mode B / production bake path where we
            overwrite RGB values and therefore must also rewrite the
            recorded colour range.
        """
        src_scan = scan_reader.scan_node
        # Build the destination scan StructureNode. We re-implement the
        # core of `build_scan_writer` locally so we can selectively skip
        # `colorLimits` when we plan to rewrite it.
        dst_scan = libe57.StructureNode(self._image_file)
        deferred_blobs = []
        deferred_cvs = []
        for i in range(src_scan.childCount()):
            child = get_node(src_scan, i)
            name = child.elementName()
            if name == "points":
                continue
            if name == "colorLimits" and own_color_limits:
                continue
            cloned, cv_pairs, blob_pairs = clone_node(child, self._image_file)
            dst_scan.set(name, cloned)
            deferred_blobs.extend(blob_pairs)
            deferred_cvs.extend(cv_pairs)

        # Prototype clone + fresh CompressedVectorNode.
        src_cv_any = src_scan["points"]
        if isinstance(src_cv_any, libe57.CompressedVectorNode):
            src_cv = src_cv_any
        else:
            src_cv = libe57.CompressedVectorNode(src_cv_any)
        src_prototype = libe57.StructureNode(src_cv.prototype())
        dst_prototype = clone_prototype(src_prototype, self._image_file)
        dst_codecs = libe57.VectorNode(self._image_file, True)
        dst_cv = libe57.CompressedVectorNode(
            self._image_file, dst_prototype, dst_codecs
        )
        dst_scan.set("points", dst_cv)

        # Attach to /data3D *before* opening the streaming writer.
        self._data3d.append(dst_scan)
        finalize_blob_copies(deferred_blobs)
        if deferred_cvs:
            raise NotImplementedError(
                "Scan-level CompressedVector children outside /points are "
                "not supported by E57CloneWriter.begin_scan."
            )

        specs = resolve_field_specs(src_prototype)
        block_writer = ScanBlockWriter(
            self._image_file, dst_cv, specs, block_size=block_size
        )
        return ScanWriter(
            self._image_file,
            dst_scan,
            dst_cv,
            block_writer,
            owns_color_limits=own_color_limits,
        )


# ---------------------------------------------------------------------------
# Transform contract
# ---------------------------------------------------------------------------


Transform = Callable[[Dict[str, FieldBuffer]], Dict[str, FieldBuffer]]


def identity_transform(block: Dict[str, FieldBuffer]) -> Dict[str, FieldBuffer]:
    """Pure-clone transform — returns the block unmodified.

    Used by G1a Mode A (round-trip fidelity check) and by callers that
    only want to mirror a file without touching point data.
    """
    return block


def constant_rgb_transform(rgb=(255, 0, 0)) -> Transform:
    """Return a transform that overwrites colorRed/Green/Blue with a
    constant ``(r, g, b)`` triplet.

    Used by G1a Mode B testing to verify the RGB-rewrite path produces
    a file whose RGB columns read back as the baked constant. The
    transform preserves the prototype-node reference + ``descaled`` flag
    so the writer round-trips dtype/scale correctly.
    """
    r, g, b = rgb

    def _t(block: Dict[str, FieldBuffer]) -> Dict[str, FieldBuffer]:
        # Block length comes from cartesianX (the only field guaranteed
        # to be present on every scan in V2.0 scope).
        cx = block.get("cartesianX")
        if cx is None or cx.numpy_array is None:
            return block
        n = cx.numpy_array.shape[0]
        for ch, val in zip(("colorRed", "colorGreen", "colorBlue"), (r, g, b)):
            if ch not in block:
                continue
            existing = block[ch]
            existing_dtype = (
                existing.numpy_array.dtype
                if existing.numpy_array is not None
                else np.uint8
            )
            new_arr = np.full(n, val, dtype=existing_dtype)
            block[ch] = FieldBuffer(
                name=ch,
                numpy_array=new_arr,
                prototype_node=existing.prototype_node,
                raw_bytes=None,
                descaled=existing.descaled,
            )
        return block

    return _t


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def clone_file(
    input_path: str,
    output_path: str,
    *,
    transform: Transform = identity_transform,
    update_color_limits: bool = False,
    block_size: int = 1_000_000,
) -> dict:
    """High-level streaming clone: read every scan, push each block
    through ``transform``, write to ``output_path``.

    Parameters
    ----------
    input_path / output_path:
        Source and destination ``.e57`` file paths.
    transform:
        Per-block transform callable. Defaults to :func:`identity_transform`
        (pure-clone, G1a Mode A). Pass :func:`constant_rgb_transform`
        for G1a Mode B testing; pass the intensity-->RGB transform from
        ``intensity_rgb.processing.pipeline`` for the production bake.
    update_color_limits:
        When True, every scan must already carry ``colorRed/Green/Blue``
        in its prototype (G1a Mode C precondition), and each
        destination scan's ``colorLimits`` is rewritten to the standard
        ``[0, 255]`` triplet at scan-close time. Raises
        :class:`UnsupportedFileError` if any scan fails the
        precondition.
    block_size:
        Points per streaming block. Defaults to 1,000,000 — matches the
        B1 substrate default and is well above the libE57 packet size
        floor.

    Returns
    -------
    dict
        ``{"scan_count", "total_points", "blocks_written",
        "output_size_bytes"}``.
    """
    with E57CloneReader(input_path) as reader:
        # Precondition check: if we're rewriting colorLimits we need RGB.
        if update_color_limits:
            for scan in reader.iter_scans():
                if not scan.has_rgb():
                    raise UnsupportedFileError(
                        f"scan '{scan.metadata.get('name', '?')}' has no RGB "
                        "fields; V2.0 does not inject RGB into intensity-only scans"
                    )

        total_points = 0
        blocks_written = 0
        with E57CloneWriter(output_path, source=reader) as writer:
            writer.copy_file_header()
            for img in reader.images2D:
                writer.copy_image2D(img)
            for extra in reader.extra_nodes:
                writer.clone_node(extra)
            writer.copy_pointGroupingSchemes_if_present()
            for scan_reader in reader.iter_scans():
                with writer.begin_scan(
                    scan_reader,
                    block_size=block_size,
                    own_color_limits=update_color_limits,
                ) as scan_writer:
                    for block in scan_reader.iter_blocks(block_size=block_size):
                        out_block = transform(block)
                        n = scan_writer.write_block(out_block)
                        total_points += n
                        blocks_written += 1
                    if update_color_limits:
                        scan_writer.update_color_limits()
        return {
            "scan_count": reader.scan_count,
            "total_points": total_points,
            "blocks_written": blocks_written,
            "output_size_bytes": os.path.getsize(output_path),
        }
