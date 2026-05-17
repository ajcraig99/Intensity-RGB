"""
Baseline benchmark script - replicates exact algorithm from Intensity-RGB_V1.0.py
No GUI, runs headlessly from CLI. Output saved to Desktop with timestamp.
Usage: python benchmark_v1.py <source.pts>
"""
import time
import math
import os
import colorsys
import sys
from datetime import datetime

BRIGHTNESS = 0.7       # same default as V1.0 (70%)
RANGE_SAMPLE = 10000   # same as V1.0


def convert_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])


def get_intensity_range(filepath):
    max_inten = 0
    min_inten = 0
    with open(filepath) as f:
        next(f)  # skip header line (same as V1.0)
        for i, line in enumerate(f):
            if i >= RANGE_SAMPLE:
                break
            floatlist = [float(x) for x in line.split()]
            inten = floatlist[3]
            if inten > max_inten:
                max_inten = inten
            if inten < min_inten:
                min_inten = inten
    return min_inten, max_inten


def process(filepath, newfilepath, min_inten, max_inten, hsl_l):
    linecount = 0
    nfile = open(newfilepath, "w+")
    with open(filepath) as ptsfile:
        next(ptsfile)  # skip header (same as V1.0)
        for line in ptsfile:
            linecount += 1
            pointline = line.split()
            floatlist = [float(x) for x in pointline]
            inten = floatlist[3]
            intenoriginal = inten
            x = floatlist[0]
            y = floatlist[1]
            z = floatlist[2]
            # --- exact same scaling logic as V1.0 ---
            if max_inten == 255:
                inten = inten / max_inten
            if max_inten == 2048:
                inten = (inten + max_inten) / max_inten
            if max_inten == 4096:
                inten = inten / max_inten
            rgb = colorsys.hsv_to_rgb(inten, 1, hsl_l)
            red   = int(rgb[0] * 255)
            green = int(rgb[1] * 255)
            blue  = int(rgb[2] * 255)
            nfile.write(f"{x} {y} {z} {intenoriginal} {red} {green} {blue} \n")
    nfile.close()
    return linecount


def main():
    if len(sys.argv) < 2:
        print("Usage: python benchmark_v1.py <source.pts>")
        sys.exit(1)

    source = sys.argv[1]
    if not os.path.exists(source):
        print(f"File not found: {source}")
        sys.exit(1)

    # Output to Desktop with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    desktop = "/mnt/c/Users/arron.craig/Desktop"
    output = os.path.join(desktop, f"intensity_rgb_baseline_{timestamp}.pts")

    src_size = os.stat(source).st_size
    print(f"\n=== Intensity-RGB V1.0 Baseline Benchmark ===")
    print(f"Source:      {source}")
    print(f"Source size: {convert_size(src_size)}")
    print(f"Output:      {output}")
    print(f"Brightness:  {int(BRIGHTNESS*100)}%")

    print(f"\nScanning first {RANGE_SAMPLE} lines for intensity range...")
    min_inten, max_inten = get_intensity_range(source)
    print(f"Intensity range: {min_inten} - {max_inten}")

    print(f"\nProcessing...")
    start = time.time()
    points = process(source, output, min_inten, max_inten, BRIGHTNESS)
    elapsed = time.time() - start

    out_size = os.stat(output).st_size
    hours, rem = divmod(elapsed, 3600)
    minutes, seconds = divmod(rem, 60)

    print(f"\n=== Results ===")
    print(f"Points processed: {'{:,}'.format(points)}")
    print(f"Processing time:  {int(hours):02d}:{int(minutes):02d}:{seconds:05.2f}")
    print(f"Output size:      {convert_size(out_size)}")
    print(f"Output saved to:  {output}")


if __name__ == "__main__":
    main()
