"""
Intensity-RGB processing engine.
Handles file chunking, parallel processing via multiprocessing, and buffered I/O.
Imported by benchmark_v2.py and the Flask web app.
"""
import os
import colorsys
import multiprocessing
import shutil
import tempfile

BATCH_SIZE = 100_000   # lines buffered per worker before flushing to disk
WRITE_BUFFER = 8 * 1024 * 1024  # 8 MB write buffer per worker
RANGE_SAMPLE = 10_000  # lines to scan for intensity range (same as V1.0)


# ---------------------------------------------------------------------------
# Intensity range detection
# ---------------------------------------------------------------------------

def get_intensity_range(filepath):
    """Scan the first RANGE_SAMPLE data lines and return (min, max) intensity."""
    min_inten = float('inf')
    max_inten = float('-inf')
    with open(filepath, 'rb') as f:
        f.readline()  # skip header
        for i in range(RANGE_SAMPLE):
            raw = f.readline()
            if not raw:
                break
            parts = raw.split()
            if len(parts) < 4:
                continue
            try:
                inten = float(parts[3])
            except ValueError:
                continue
            if inten > max_inten:
                max_inten = inten
            if inten < min_inten:
                min_inten = inten
    if min_inten == float('inf'):
        return 0.0, 255.0
    return min_inten, max_inten


# ---------------------------------------------------------------------------
# Chunk calculation
# ---------------------------------------------------------------------------

def _get_chunks(filepath, n_workers):
    """
    Divide the file into n_workers byte-range chunks aligned to line boundaries.
    Skips the header line. Returns list of (start_byte, end_byte) tuples.
    """
    size = os.path.getsize(filepath)
    chunks = []
    with open(filepath, 'rb') as f:
        header_end = len(f.readline())  # skip header, record where data starts
        data_size = size - header_end
        chunk_size = data_size // n_workers
        start = header_end
        for i in range(n_workers):
            if i == n_workers - 1:
                end = size
            else:
                target = start + chunk_size
                f.seek(target)
                f.readline()  # advance to next line boundary
                end = f.tell()
            if end > start:
                chunks.append((start, end))
            start = end
    return chunks


# ---------------------------------------------------------------------------
# Worker function (runs in subprocess)
# ---------------------------------------------------------------------------

def _process_chunk(args):
    """
    Process one byte-range chunk of the source file.
    Writes results to a temp file and returns (temp_path, line_count).
    """
    filepath, start, end, temp_path, min_inten, max_inten, hsl_l = args

    range_span = max_inten - min_inten
    if range_span == 0:
        range_span = 1.0

    buf = []
    count = 0

    with open(filepath, 'rb') as f, \
         open(temp_path, 'w', buffering=WRITE_BUFFER) as out:

        f.seek(start)
        # If this isn't the first chunk, the start may be mid-line — skip it.
        # (Chunks are aligned so start is always at a line boundary, but guard anyway.)

        while f.tell() < end:
            raw = f.readline()
            if not raw:
                break

            parts = raw.split()
            if len(parts) < 4:
                continue
            try:
                inten = float(parts[3])
            except ValueError:
                continue

            intenoriginal = inten

            # Dynamic normalization — replaces hardcoded 255/2048/4096 checks
            normalized = (inten - min_inten) / range_span
            # Clamp to [0, 1] so HSV hue stays valid
            if normalized < 0.0:
                normalized = 0.0
            elif normalized > 1.0:
                normalized = 1.0

            rgb = colorsys.hsv_to_rgb(normalized, 1.0, hsl_l)
            red   = int(rgb[0] * 255)
            green = int(rgb[1] * 255)
            blue  = int(rgb[2] * 255)

            # Preserve original x y z as strings to avoid float repr differences
            buf.append(
                f"{parts[0].decode()} {parts[1].decode()} {parts[2].decode()} "
                f"{intenoriginal} {red} {green} {blue}\n"
            )
            count += 1

            if len(buf) >= BATCH_SIZE:
                out.writelines(buf)
                buf.clear()

        if buf:
            out.writelines(buf)

    return temp_path, count


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process(filepath, output_path, min_inten, max_inten, hsl_l,
            n_workers=None, progress_callback=None):
    """
    Process a .pts file in parallel and write results to output_path.

    Args:
        filepath:          Path to source .pts file.
        output_path:       Path for output .pts file.
        min_inten:         Minimum intensity for normalization.
        max_inten:         Maximum intensity for normalization.
        hsl_l:             Brightness/lightness value (0.0 – 1.0).
        n_workers:         Number of parallel workers (defaults to CPU count).
        progress_callback: Optional callable(chunks_done, total_chunks).

    Returns:
        total point count (int)
    """
    if n_workers is None:
        n_workers = os.cpu_count() or 4

    chunks = _get_chunks(filepath, n_workers)
    tmp_dir = tempfile.mkdtemp(prefix="intensity_rgb_")

    try:
        # Build args for each worker
        worker_args = [
            (filepath, start, end,
             os.path.join(tmp_dir, f"chunk_{i}.pts"),
             min_inten, max_inten, hsl_l)
            for i, (start, end) in enumerate(chunks)
        ]

        total_points = 0
        completed_chunks = 0
        temp_files = []

        with multiprocessing.Pool(processes=n_workers) as pool:
            for temp_path, count in pool.imap_unordered(_process_chunk, worker_args):
                temp_files.append(temp_path)
                total_points += count
                completed_chunks += 1
                if progress_callback:
                    progress_callback(completed_chunks, len(chunks))

        # Merge temp files into final output in chunk order (preserve ordering)
        # Re-sort by chunk index so output order matches input order
        ordered = sorted(temp_files, key=lambda p: int(os.path.basename(p).split('_')[1].split('.')[0]))

        with open(output_path, 'wb') as out:
            for tf in ordered:
                with open(tf, 'rb') as inp:
                    shutil.copyfileobj(inp, out, length=WRITE_BUFFER)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return total_points
