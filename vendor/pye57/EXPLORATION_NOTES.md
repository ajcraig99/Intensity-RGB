# Phase 1 — exploration notes (Wave 2 / B1)

**Verdict: TRACTABLE. No pivot needed.** The vendored fork already exposes
~95% of the libE57Format C++ surface we need. The only missing piece is a
Python-level recursive `StructureNode` clone helper, and that can be written
entirely in Python on top of the existing pybind11 bindings — no new C++
required for the core M1 contract.

## What pybind11 already exposes (`vendor/pye57/src/pye57/libe57_wrapper.cpp`)

### Node types — all 8 exposed with full ctor + accessor surface

| C++ class | Exposed? | Notes |
|---|---|---|
| `Node` | yes | `type()`, `parent()`, `pathName()`, `elementName()`, `isAttached()` |
| `StructureNode` | yes | `set(...)` for **every** child type; `get(int)`, `get(str)`, `__getitem__`, `__len__`, `childCount()` |
| `VectorNode` | yes | `append(...)` for **every** child type; same getters as Structure; `allowHeteroChildren()` |
| `CompressedVectorNode` | yes | `prototype()`, `codecs()`, `childCount()`, `reader(dbufs)`, `writer(sbufs)` |
| `IntegerNode` | yes | `value()`, `minimum()`, `maximum()` |
| `ScaledIntegerNode` | yes | `rawValue()`, `scaledValue()`, `scale()`, `offset()`, min/max scaled+raw |
| `FloatNode` | yes | `value()`, `precision()`, `minimum()`, `maximum()` |
| `StringNode` | yes | `value()` |
| `BlobNode` | yes | `byteCount()`, `read(buf,start,count)`, `write(buf,start,count)`, `read_buffer()` (allocates fresh numpy bytes array) |

### Streaming I/O — already wired

- `CompressedVectorReader.read()` / `read(dbufs)` — exposed
- `CompressedVectorReader.seek()`, `close()`, `isOpen()`, `compressedVectorNode()` — exposed
- `CompressedVectorWriter.write(count)` / `write(sbufs, count)` / `close()` / `isOpen()` — exposed
- `SourceDestBuffer(imf, pathName, np_array, capacity, doConversion, doScaling, stride)` — numpy buffer-protocol bridge, supports b/B/h/H/l/L/q/?/f/d dtypes. `doScaling` already handles `ScaledIntegerNode` descaling.
- `VectorSourceDestBuffer` (`std::vector<SourceDestBuffer>` opaque container) for assembling the dbufs/sbufs list.

### File-level

- `ImageFile(path, mode, checksumPolicy)` — exposed (`r`, `w`)
- `ImageFile.root()`, `close()`, `cancel()`, `isOpen()`, `isWritable()`, `fileName()` — exposed
- `ImageFile.extensionsAdd(prefix, uri)`, `extensionsCount()`, `extensionsPrefix(i)`, `extensionsUri(i)`, `extensionsLookupPrefix(prefix, uri)`, `extensionsLookupUri(uri, prefix)` — exposed. **Namespace preservation is free.**
- `NodeType` enum, `FloatPrecision` enum, `MemoryRepresentation` enum, all `ErrorCode`s — exposed.

### `cast_node()` helper

There is an internal `cast_node(Node&)` that dispatches a generic `Node` to the concrete subclass for `__getitem__`. This means any recursive walk in Python over `StructureNode.__getitem__` / `VectorNode.__getitem__` lands on the right subclass automatically — invariant: the first thing you can do with a child is `isinstance` it against `libe57.StructureNode` / `libe57.VectorNode` / ... etc.

## Critical observation: `Image2DNode` does not exist

libE57Format's public header (`E57Format.h`) declares no `Image2DNode` class. The E57 standard models the `/images2D` subtree as **a plain `VectorNode` of `StructureNode` children**. Each image2D child has:

- a `guid` `StringNode`
- a `name` / `description` `StringNode`
- a `pose` `StructureNode` (rotation quaternion + translation)
- a representation child, **one of**: `pinholeRepresentation`, `sphericalRepresentation`, `cylindricalRepresentation` (all `StructureNode`s)
- inside the representation: blob children `jpegImage`, `pngImage`, `imageMask`, plus float/integer projection parameters

**Implication**: "Image2DNode enumeration + copy" is **not a new C++ binding** — it is `StructureNode` recursive clone with a small Python helper that walks `root["images2D"]` and re-uses the same generic clone machinery. The blob copy uses the existing `BlobNode.read/write` API.

## Coverage matrix — design requirements vs current bindings

| Design requirement (M1 / B1) | Status | What it needs |
|---|---|---|
| Block-iter read over `CompressedVectorReader::read` | **already exposed** | Thin Python iterator wrapping repeated `.read()` calls on a pre-built `VectorSourceDestBuffer` |
| Block-iter write over `CompressedVectorWriter::write` | **already exposed** | Thin Python context-manager wrapping `prototype.writer(sbufs)` |
| `StructureNode` recursive clone (incl. unknown subtrees) | **partially exposed** — C++ primitives all present, no Python helper exists yet | Pure-Python recursive walk using `Node.type()` + `cast_node`-style dispatch + `set/append` |
| `BlobNode` byte streams | **already exposed** | Already has `read`, `write`, `read_buffer`, `byteCount`. Need a small Python convenience for bytes-in/bytes-out |
| `Image2DNode` enumeration | **already exposed** (as plain StructureNode children of `/images2D` VectorNode) | Python helper to walk and project metadata vs blob children |
| `Image2DNode` copy | **already exposed** | Falls out of recursive StructureNode clone + BlobNode read/write |

## Estimated work

- **C++ to add: ~0–30 lines.** The only candidate addition is a tiny convenience for `BlobNode` like `read_to_pybytes(start, count)` returning `py::bytes` instead of a numpy uint8 array — currently we have `read_buffer()` which already returns the whole blob as a numpy uint8 array; that's actually sufficient. I expect to add **zero new C++ in Phase 2** unless I hit something during smoke testing.
- **Python to add: ~300–450 lines** across:
  - `vendor/pye57/src/pye57/cloning.py` (new) — `clone_structure_node`, `clone_vector_node`, blob helpers
  - `vendor/pye57/src/pye57/streaming.py` (new) — `ScanBlockReader`, `ScanBlockWriter`, `FieldBuffer` dataclass, `prototype_to_buffer_spec`
  - `vendor/pye57/src/pye57/e57.py` (extend) — `E57.iter_scan_blocks`, `E57.begin_scan`, `E57.images2D` property
  - `vendor/pye57/src/pye57/__init__.py` (extend) — re-exports

## Why this is not the libE57Format rewrite scenario

The risk register's "pivot to fresh libE57Format bindings" only fires if the pybind surface is so thin that **fundamental traversal isn't possible** — i.e. you can't get from a generic `Node` to its concrete subclass, or you can't enumerate `StructureNode` children. Here, both of those things work today (`StructureNode.__getitem__`, `StructureNode.childCount`, `Node.type()`, plus the `cast_node` dispatch baked into the `__getitem__` lambdas). A pure-Python recursive walk is straightforward.

The only adversarial corner is **unknown vendor field semantics inside a `CompressedVector`** — the prototype might have a `ScaledIntegerNode` with custom scale we don't recognize. But: the binding **already does `doScaling` correctly** because that flag is on `SourceDestBuffer`, and the prototype itself is just a `StructureNode` we can clone child-by-child. We do not need to interpret the field's semantics to round-trip it.

## 3-day timebox: achievable

Day budget estimate (single agent, no parallelism within B1):
- Phase 2.1 — `cloning.py` recursive node clone + blob copy: **0.5 day**
- Phase 2.2 — `streaming.py` block reader + writer + `FieldBuffer`: **0.5 day**
- Phase 2.3 — `E57.iter_scan_blocks` + `E57.begin_scan` + `E57.images2D`: **0.5 day**
- Phase 2.4 — extension smoke test on `carpark_stairs.e57` + synthetic fixtures: **0.5 day**
- Buffer for unforeseen libE57 quirks (e.g. ScaledInteger prototype reconstruction, codecs propagation): **1 day**

Total: 3 days. Within budget.

## What B2 (caller) should expect

- New module: `pye57.cloning` with `clone_structure_node(src, dst_parent, name)`, `clone_node(src, dst_parent, name)` (generic dispatch), and `copy_blob(src, dst)` helpers.
- New module: `pye57.streaming` with `FieldBuffer` namedtuple, `ScanBlockReader`, `ScanBlockWriter`.
- New `E57` methods: `iter_scan_blocks(scan_idx, block_size)` and `begin_scan(scan_metadata, prototype) -> ScanBlockWriter` context manager.
- New `E57` property: `images2D` returning a list of opaque `StructureNode`s (already-existing libe57 type) — B2 will wrap these with its own `Image2D` dataclass to project metadata/blob_streams.

## What stays untouched (contract preservation)

- `E57.read_scan_raw(index, ignore_unsupported_fields=False) -> Dict`: unchanged. A7's `tests/synthetic_e57.py` uses it.
- `E57.write_scan_raw(data, *, name, rotation, translation, scan_header)`: unchanged.
- `E57.read_scan(...)`, `E57.scan_position(...)`, `E57.make_buffer(s)(...)`: unchanged.
- All existing `libe57` pybind11 classes/methods: untouched, only additions.

## Proceeding to Phase 2.
