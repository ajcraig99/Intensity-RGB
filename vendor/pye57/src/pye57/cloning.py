"""Recursive E57 node cloning helpers (Wave 2 / B1).

This module builds the **structural clone primitives** the M1 I/O substrate
relies on. The heavy lifting (recursive descent through every node type) is
already done by ``pye57.utils.copy_node``; this module wraps it with the
friendlier surface B2 (`E57CloneWriter`) needs, and finalizes the deferred
``BlobNode`` byte copies that ``copy_node`` cannot do until both source and
destination are attached to their respective ``ImageFile``.

Why deferred blobs matter
-------------------------
``BlobNode`` byte payloads sit in the *binary* section of an E57 file, not
in the XML tree. libE57Format requires the destination blob to be attached
to a writable ``ImageFile`` before bytes can be written. ``copy_node``
returns a list of ``(src_blob, dst_blob)`` pairs; this module's
``finalize_blob_copies`` walks them after the destination tree is wired up.

Compressed-vector children are similar but more involved — their data is
encoded point-stream rather than raw bytes — so they get their own
streaming wrapper in ``pye57.streaming``. ``copy_node`` returns a list of
those pairs too, which the caller uses to drive per-scan streaming copies.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from pye57 import libe57
from pye57.utils import copy_node, get_node


CompressedVectorPair = dict  # {'in': CompressedVectorNode, 'out': CompressedVectorNode}
BlobPair = dict              # {'in': BlobNode, 'out': BlobNode}


# Buffer size for streaming blob copies. 4 MiB is well below libE57's
# default packet size cap and well above filesystem page granularity.
_BLOB_CHUNK_BYTES = 4 * 1024 * 1024


def clone_node(
    src_node,
    dst_image: "libe57.ImageFile",
) -> Tuple[object, List[CompressedVectorPair], List[BlobPair]]:
    """Recursively clone any libE57 node into ``dst_image``.

    Returns the cloned node plus the deferred work lists. The cloned node
    is **not** yet attached to a parent — the caller is responsible for
    calling ``dst_parent.set(name, cloned)`` or ``.append(cloned)``.

    The returned blob pairs must be passed to :func:`finalize_blob_copies`
    after the destination tree has been wired up.

    The returned compressed-vector pairs must be drained by the caller
    via :mod:`pye57.streaming` — this module deliberately does not own
    point-stream copying because production callers transform per-block
    data and reuse the writer machinery.

    This is a thin wrapper around :func:`pye57.utils.copy_node` exposing
    the same return value with a slightly clearer name. Existing callers
    of ``copy_node`` keep working.
    """
    return copy_node(src_node, dst_image)


def clone_structure_node(
    src_struct: "libe57.StructureNode",
    dst_parent,
    name: str,
) -> Tuple["libe57.StructureNode", List[CompressedVectorPair], List[BlobPair]]:
    """Clone ``src_struct`` and attach it under ``dst_parent`` as ``name``.

    Convenience over :func:`clone_node` that wires the result into place.
    Works for either ``StructureNode`` or ``VectorNode`` destination
    parents (the latter ignores ``name`` and appends).
    """
    dst_image = dst_parent.destImageFile()
    cloned, cv_pairs, blob_pairs = clone_node(src_struct, dst_image)
    if isinstance(dst_parent, libe57.VectorNode):
        dst_parent.append(cloned)
    else:
        dst_parent.set(name, cloned)
    return cloned, cv_pairs, blob_pairs


def finalize_blob_copies(blob_pairs: List[BlobPair]) -> None:
    """Stream-copy bytes from each source blob into its destination.

    Both blobs must already be attached to their respective ``ImageFile``
    instances. Source must be in a readable image, destination in a
    writable image.
    """
    for pair in blob_pairs:
        copy_blob(pair["in"], pair["out"])


def copy_blob(src: "libe57.BlobNode", dst: "libe57.BlobNode") -> None:
    """Byte-for-byte stream copy of a ``BlobNode`` payload.

    Uses chunked I/O so multi-GB blobs (e.g. embedded JPEGs in
    ``images2D``) do not need to be held in RAM all at once.
    """
    import numpy as np

    n = src.byteCount()
    if dst.byteCount() != n:
        raise ValueError(
            f"copy_blob: destination byteCount ({dst.byteCount()}) "
            f"differs from source ({n}); destination must be constructed "
            f"with the same byteCount as the source."
        )
    if n == 0:
        return

    buf = np.empty(min(_BLOB_CHUNK_BYTES, n), dtype=np.uint8)
    offset = 0
    while offset < n:
        chunk = min(_BLOB_CHUNK_BYTES, n - offset)
        if chunk != buf.size:
            buf = np.empty(chunk, dtype=np.uint8)
        src.read(buf, offset, chunk)
        dst.write(buf, offset, chunk)
        offset += chunk


def read_blob_bytes(blob: "libe57.BlobNode") -> bytes:
    """Return the full blob payload as a Python ``bytes`` object.

    For small blobs (typical image masks, etc.). For large blobs prefer
    :func:`copy_blob` to avoid the round-trip through Python memory.
    """
    arr = blob.read_buffer()  # numpy uint8 array
    return bytes(arr)


def write_blob_bytes(
    dst_image: "libe57.ImageFile", payload: bytes
) -> "libe57.BlobNode":
    """Create an attached ``BlobNode`` and write ``payload`` to it.

    The blob is *unparented* — caller is responsible for setting it under
    a StructureNode or appending to a VectorNode.
    """
    import numpy as np

    n = len(payload)
    blob = libe57.BlobNode(dst_image, n)
    if n:
        arr = np.frombuffer(payload, dtype=np.uint8)
        blob.write(arr, 0, n)
    return blob


def copy_extensions(src_image: "libe57.ImageFile", dst_image: "libe57.ImageFile") -> None:
    """Mirror ``src_image``'s XML extension namespaces into ``dst_image``.

    libE57 already mounts the default ``E57_V1_0_URI`` (empty prefix), so
    we skip exact duplicates of that single mapping but copy everything
    else. Required so the destination XML serializes vendor-extension
    element names correctly.
    """
    n_ext = src_image.extensionsCount()
    for i in range(n_ext):
        prefix = src_image.extensionsPrefix(i)
        uri = src_image.extensionsUri(i)
        # libe57 raises if you try to re-add an existing (prefix, uri)
        # pair, so probe first.
        try:
            existing_uri = ""
            if dst_image.extensionsLookupPrefix(prefix, existing_uri):
                # Already present — skip. We can't actually read
                # ``existing_uri`` back through the pybind11 binding
                # (it's a non-const-reference out-param that pybind
                # surfaces as a boolean), so we trust libe57's identity
                # check and move on.
                continue
        except libe57.E57Exception:
            pass
        try:
            dst_image.extensionsAdd(prefix, uri)
        except libe57.E57Exception:
            # If the namespace is already registered under a different
            # prefix we just continue — the destination tree will still
            # validate.
            continue


def iter_struct_children(struct_node):
    """Yield ``(name, child_node)`` pairs for a StructureNode.

    Children are returned in their declared XML order (which is the order
    libE57 reports them via ``StructureNode.get(i)``).
    """
    for i in range(struct_node.childCount()):
        child = get_node(struct_node, i)
        yield child.elementName(), child


def iter_vector_children(vec_node):
    """Yield child nodes of a VectorNode in declared order."""
    for i in range(vec_node.childCount()):
        yield get_node(vec_node, i)
