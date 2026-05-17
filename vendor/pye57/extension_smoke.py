"""B1 extension smoke test: exercise streaming + cloning on carpark_stairs.e57.

Reads scan 0 in blocks via ScanBlockReader, writes back a clone via
ScanBlockWriter + clone_node. Validates round-trip block iteration works
and the cloned file opens.
"""
from __future__ import annotations

import os
import sys
import tempfile

from pye57 import (
    E57,
    libe57,
    ScanBlockReader,
    ScanBlockWriter,
    resolve_field_specs,
    build_scan_writer,
    copy_extensions,
)


def smoke(input_path: str) -> dict:
    out = {}

    src = E57(input_path, mode="r")
    out["src_scan_count"] = src.scan_count

    # --- read side: cast_node makes src_root["data3D"] already a VectorNode --
    src_root = src.root
    src_data3d = src_root["data3D"]
    assert isinstance(src_data3d, libe57.VectorNode), type(src_data3d)
    src_scan_raw = src_data3d.get(0)
    # VectorNode.get(i) returns a generic Node; cast manually.
    src_scan = libe57.StructureNode(src_scan_raw)
    src_cv_raw = src_scan["points"]
    src_cv = libe57.CompressedVectorNode(src_cv_raw) if not isinstance(src_cv_raw, libe57.CompressedVectorNode) else src_cv_raw
    src_prototype = libe57.StructureNode(src_cv.prototype())

    reader = ScanBlockReader(src.image_file, src_cv, block_size=500_000)
    out["field_names"] = reader.field_names
    total_read = 0
    blocks = 0
    first_x = None
    for block in reader:
        blocks += 1
        cx = block["cartesianX"].numpy_array
        if first_x is None and cx is not None and cx.size > 0:
            first_x = float(cx[0])
        total_read += int(cx.size) if cx is not None else 0
    reader.close()
    out["blocks_read"] = blocks
    out["total_points_read"] = total_read
    out["first_cartesianX"] = first_x

    # --- write side: build clone scan + open streaming writer for /points ---
    tmpdir = tempfile.mkdtemp(prefix="b1_smoke_")
    out_path = os.path.join(tmpdir, "smoke_out.e57")

    dst = E57(out_path, mode="w")
    copy_extensions(src.image_file, dst.image_file)

    # E57(path, mode="w") already creates /data3D via write_default_header.
    # __getitem__ returns the casted VectorNode directly.
    dst_data3d = dst.data3d  # this is the data3D VectorNode

    dst_scan, writer = build_scan_writer(
        dst.image_file, dst_data3d, src_scan, block_size=500_000
    )

    reader = ScanBlockReader(src.image_file, src_cv, block_size=500_000)
    written_blocks = 0
    written_points = 0
    for block in reader:
        n = writer.write_block(block)
        written_blocks += 1
        written_points += n
    reader.close()
    writer.close()
    out["blocks_written"] = written_blocks
    out["total_points_written"] = written_points

    dst.close()
    src.close()

    # --- verify destination opens and has matching point count -------------
    chk = E57(out_path, mode="r")
    out["chk_scan_count"] = chk.scan_count
    chk_data3d = chk.root["data3D"]
    chk_scan = libe57.StructureNode(chk_data3d.get(0))
    chk_cv_raw = chk_scan["points"]
    chk_cv = chk_cv_raw if isinstance(chk_cv_raw, libe57.CompressedVectorNode) else libe57.CompressedVectorNode(chk_cv_raw)
    out["chk_total_points"] = chk_cv.childCount()
    chk.close()

    out["output_path"] = out_path
    out["output_size_bytes"] = os.path.getsize(out_path)
    return out


if __name__ == "__main__":
    input_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "..", "..", "carpark_stairs.e57"
    )
    input_path = os.path.abspath(input_path)
    print(f"Input: {input_path}")
    result = smoke(input_path)
    for k, v in result.items():
        print(f"{k}: {v}")
