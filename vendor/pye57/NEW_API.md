# Vendor fork additions — Wave 2 / B1

This fork extends `davidcaron/pye57` with the streaming + cloning surface
needed by `intensity_rgb.io.e57_clone` (Wave 2 / B2). **Zero C++ added**;
all extensions are pure Python on top of the existing pybind11 bindings.

## New modules

### `pye57.streaming`

```python
from pye57 import (
    FieldSpec,            # prototype-field metadata
    FieldBuffer,          # one block's worth of one field's data
    ScanBlockReader,      # iterates blocks of a scan's CompressedVector
    ScanBlockWriter,      # writes blocks back to a destination scan
    resolve_field_specs,  # introspect a CompressedVector prototype
    clone_prototype,      # build a fresh prototype StructureNode mirror
    build_scan_writer,    # high-level helper: clone scan metadata + open writer
)
```

`FieldBuffer` shape:

```python
@dataclass
class FieldBuffer:
    name: str
    numpy_array: Optional[np.ndarray]   # descaled into natural units
    prototype_node: object              # source prototype Node (for round-trip)
    raw_bytes: Optional[bytes]          # passthrough for unknown extension fields
    descaled: bool                      # True if libE57 applied scale/offset
```

`ScanBlockReader` usage:

```python
reader = ScanBlockReader(image_file, compressed_vector_node, block_size=1_000_000)
for block in reader:
    # block: Dict[str, FieldBuffer]
    xyz = np.stack([block["cartesianX"].numpy_array,
                    block["cartesianY"].numpy_array,
                    block["cartesianZ"].numpy_array], axis=-1)
    ...
reader.close()
```

The reader holds persistent numpy buffers and re-fills them per block; the
FieldBuffer numpy arrays are *views* into those persistent buffers and must
not be retained past the next iteration. Copy if you need to.

`build_scan_writer` is the high-level helper that B2 will call:

```python
dst_scan, writer = build_scan_writer(
    dst_image_file, dst_data3d_vector, src_scan_struct_node,
    block_size=1_000_000,
    # Optional override if the transform changes prototype dtypes
    # (e.g. baking RGB into uint8 IntegerNode fields).
    field_specs_override=None,
)
for block in reader:
    transformed = transform(block)
    writer.write_block(transformed)
writer.close()
```

### `pye57.cloning`

```python
from pye57 import (
    clone_node,             # recursive node clone (returns (cloned, cv_pairs, blob_pairs))
    clone_structure_node,   # convenience wrapper for StructureNode-rooted clones
    copy_blob,              # blob byte-stream copy
    read_blob_bytes,        # BlobNode -> bytes
    write_blob_bytes,       # bytes -> BlobNode
    copy_extensions,        # mirror file-level XML namespace registrations
    finalize_blob_copies,   # execute deferred blob copy tasks
    iter_struct_children,   # yields (name, child_node) for a StructureNode
    iter_vector_children,   # yields child_node for a VectorNode
)
```

The recursive `clone_node` handles arbitrary node-type trees including:
Float / Integer / ScaledInteger / String / Blob / Structure / Vector /
CompressedVector. Unknown vendor extension subtrees are walked the same
way — type dispatch is via `Node.type()` on the base node.

## Internal corrections applied to B1's output

The B1 agent's run hit a stream timeout before it could smoke-test. The
coordinator applied four fixes to make the smoke pass:

1. `streaming.resolve_field_specs` — pybind11 does **not** expose
   `Node.type()` on cast subclasses (`FloatNode`, etc.). The original
   used `utils.get_node` which returns the casted subclass, then called
   `.type()` and got AttributeError. Fixed to use raw `Node.get(i)` for
   `.type()` access, then re-cast for typed accessors.
2. `streaming.clone_prototype` — same issue, same fix.
3. `streaming.build_scan_writer` — `libe57.CompressedVectorNode(node)` on
   an already-cast `CompressedVectorNode` is rejected by pybind11's
   dynamic_cast logic ("Invoked with: <CompressedVectorNode 'points'>").
   Fixed with `isinstance` guard before re-wrapping.
4. `ScanBlockWriter.write_block` — was returning `None`; changed to
   return the per-block count so callers can sum throughput.

See `SMOKE_RESULT.txt` for the round-trip evidence on the four fixtures.

## What's still TODO for B2

- An `E57CloneReader.images2D` enumeration in Python. The `cloning.clone_node`
  primitive handles `images2D` structurally (each is a StructureNode child
  of the `/images2D` VectorNode, walked recursively). B2 wraps these for the
  caller's convenience but the binding work is done.
- File-header / data3d-vector boilerplate (open dst E57, get `dst.data3d`,
  iterate `src.scan_count`). The substrate exposes everything needed.
- Constant-RGB transform helper for G1a Mode B. Trivial wrapper.
- Fail-fast `colorRed/Green/Blue absent` check for G1a Mode C. Inspect
  `reader.field_specs` for the three RGB field names.

## What's intentionally NOT here

- `E57.iter_scan_blocks` / `E57.begin_scan` / `E57.images2D` were
  contemplated as methods on the `E57` class itself. They were left off
  because the substrate is already usable from `pye57.streaming` / `pye57.cloning`
  directly, and adding them to `E57` would require deferring to those
  modules anyway. B2 calls the substrate functions.
