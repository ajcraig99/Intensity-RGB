from pye57 import libe57
from pye57.scan_header import ScanHeader
from pye57.e57 import E57

# Wave 2 / B1: streaming + cloning substrate.
# These names are part of the documented vendor-fork extension surface
# (see vendor/pye57/NEW_API.md). Importing them at package level keeps
# consumers (intensity_rgb.io.e57_clone) one-stop.
from pye57.streaming import (
    FieldBuffer,
    FieldSpec,
    ScanBlockReader,
    ScanBlockWriter,
    resolve_field_specs,
    clone_prototype,
    build_scan_writer,
)
from pye57.cloning import (
    clone_node,
    clone_structure_node,
    copy_blob,
    read_blob_bytes,
    write_blob_bytes,
    copy_extensions,
    finalize_blob_copies,
    iter_struct_children,
    iter_vector_children,
)

__all__ = [
    "libe57",
    "ScanHeader",
    "E57",
    "FieldBuffer",
    "FieldSpec",
    "ScanBlockReader",
    "ScanBlockWriter",
    "resolve_field_specs",
    "clone_prototype",
    "build_scan_writer",
    "clone_node",
    "clone_structure_node",
    "copy_blob",
    "read_blob_bytes",
    "write_blob_bytes",
    "copy_extensions",
    "finalize_blob_copies",
    "iter_struct_children",
    "iter_vector_children",
]
