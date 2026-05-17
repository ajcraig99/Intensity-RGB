"""
V2 benchmark script - multiprocessing engine with buffered I/O.
Usage: python benchmark_v2.py <source.pts> [--workers N]
Output saved to Desktop with timestamp.
"""
import time
import math
import os
import sys
from datetime import datetime

import processor

BRIGHTNESS = 0.7  # same default as V1.0

BASELINE = {
    "points":   61_285_523,
    "time_sec": 806.39,   # 13m 26s
}


def convert_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])


def main():
    if len(sys.argv) < 2:
        print("Usage: python benchmark_v2.py <source.pts> [--workers N]")
        sys.exit(1)

    source = sys.argv[1]
    n_workers = None
    if "--workers" in sys.argv:
        idx = sys.argv.index("--workers")
        n_workers = int(sys.argv[idx + 1])

    if not os.path.exists(source):
        print(f"File not found: {source}")
        sys.exit(1)

    if n_workers is None:
        n_workers = os.cpu_count() or 4

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    desktop = "/mnt/c/Users/arron.craig/Desktop"
    output = os.path.join(desktop, f"intensity_rgb_v2_{timestamp}.pts")

    src_size = os.stat(source).st_size
    print(f"\n=== Intensity-RGB V2 Benchmark ===")
    print(f"Source:      {source}")
    print(f"Source size: {convert_size(src_size)}")
    print(f"Output:      {output}")
    print(f"Workers:     {n_workers}")
    print(f"Brightness:  {int(BRIGHTNESS * 100)}%")

    print(f"\nScanning first {processor.RANGE_SAMPLE} lines for intensity range...")
    min_inten, max_inten = processor.get_intensity_range(source)
    print(f"Intensity range: {min_inten} – {max_inten}")

    chunks_done = [0]
    def on_progress(done, total):
        chunks_done[0] = done
        pct = int(done / total * 100)
        print(f"  Chunks complete: {done}/{total}  ({pct}%)")

    print(f"\nProcessing with {n_workers} workers...")
    start = time.time()
    points = processor.process(
        source, output, min_inten, max_inten, BRIGHTNESS,
        n_workers=n_workers,
        progress_callback=on_progress,
    )
    elapsed = time.time() - start

    out_size = os.stat(output).st_size
    hours, rem = divmod(elapsed, 3600)
    minutes, seconds = divmod(rem, 60)

    speedup = BASELINE["time_sec"] / elapsed if elapsed > 0 else 0

    print(f"\n=== Results ===")
    print(f"Points processed: {'{:,}'.format(points)}")
    print(f"Processing time:  {int(hours):02d}:{int(minutes):02d}:{seconds:05.2f}")
    print(f"Output size:      {convert_size(out_size)}")
    print(f"Output saved to:  {output}")
    print(f"\n=== vs Baseline ===")
    print(f"V1.0 time:  00:13:26.39  ({'{:,}'.format(BASELINE['points'])} points)")
    print(f"V2   time:  {int(hours):02d}:{int(minutes):02d}:{seconds:05.2f}  ({'{:,}'.format(points)} points)")
    print(f"Speedup:    {speedup:.1f}x faster")


if __name__ == "__main__":
    main()
