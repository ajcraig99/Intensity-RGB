"""Smoke test for vendored pye57 build.

Opens carpark_stairs.e57, lists scan count, prints scan 0's prototype field
names, and reads ~10 points.
"""
import sys
from pathlib import Path

import pye57

E57_PATH = Path(__file__).resolve().parents[2] / "carpark_stairs.e57"


def main() -> int:
    print(f"pye57 version: {getattr(pye57, '__version__', 'unknown')}")
    print(f"pye57 module:  {pye57.__file__}")
    print(f"Opening:       {E57_PATH}")
    if not E57_PATH.exists():
        print(f"ERROR: file not found: {E57_PATH}", file=sys.stderr)
        return 1

    e57 = pye57.E57(str(E57_PATH))
    scan_count = e57.scan_count
    print(f"scan_count:    {scan_count}")

    if scan_count == 0:
        print("ERROR: file has no scans", file=sys.stderr)
        return 2

    # Prototype field names for scan 0
    header = e57.get_header(0)
    field_names = list(header.point_fields)
    print(f"scan[0] point_fields ({len(field_names)}):")
    for name in field_names:
        print(f"  - {name}")

    # Read ~10 points. read_scan returns a dict of np.ndarray.
    data = e57.read_scan_raw(0)
    sample_n = min(10, len(next(iter(data.values()))))
    print(f"scan[0] total points: {len(next(iter(data.values())))}")
    print(f"scan[0] first {sample_n} points (raw):")
    for i in range(sample_n):
        row = {k: float(v[i]) for k, v in data.items()}
        print(f"  [{i}] {row}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
