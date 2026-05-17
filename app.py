"""
Intensity-RGB Web App
Local Flask application — run with: python app.py
Opens automatically in browser at http://localhost:5000
"""
import json
import math
import os
import threading
import time
import uuid
import webbrowser
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

import processor

app = Flask(__name__)
DESKTOP = "/mnt/c/Users/arron.craig/Desktop"

# In-memory job store: job_id -> state dict
jobs: dict = {}


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def normalize_path(path: str) -> str:
    """Convert Windows or WSL path to a usable WSL path."""
    path = path.strip().strip('"').strip("'")
    # Windows path: C:\foo\bar  or  C:/foo/bar
    if len(path) >= 2 and path[1] == ':':
        drive = path[0].lower()
        rest = path[2:].replace('\\', '/')
        return f'/mnt/{drive}{rest}'
    return path


def convert_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    return f"{round(size_bytes / p, 2)} {size_name[i]}"


# ---------------------------------------------------------------------------
# Background job runner
# ---------------------------------------------------------------------------

def run_job(job_id: str, source: str, output: str, min_inten: float,
            max_inten: float, brightness: float):
    job = jobs[job_id]
    job['status'] = 'running'
    job['started'] = time.time()

    def on_progress(done, total):
        job['done'] = done
        job['total'] = total

    try:
        n_workers = os.cpu_count() or 4
        job['workers'] = n_workers
        points = processor.process(
            source, output,
            min_inten, max_inten, brightness,
            n_workers=n_workers,
            progress_callback=on_progress,
        )
        elapsed = time.time() - job['started']
        hours, rem = divmod(elapsed, 3600)
        minutes, seconds = divmod(rem, 60)
        job.update({
            'status':    'done',
            'points':    points,
            'elapsed':   elapsed,
            'time_str':  f"{int(hours):02d}:{int(minutes):02d}:{seconds:05.2f}",
            'out_size':  convert_size(os.path.getsize(output)),
            'out_path':  output,
        })
    except Exception as exc:
        job.update({'status': 'error', 'error': str(exc)})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/detect-range', methods=['POST'])
def detect_range():
    data = request.get_json()
    path = normalize_path(data.get('path', ''))
    if not os.path.exists(path):
        return jsonify({'error': f'File not found: {path}'}), 400
    try:
        min_i, max_i = processor.get_intensity_range(path)
        size = convert_size(os.path.getsize(path))
        return jsonify({'min': min_i, 'max': max_i, 'size': size})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@app.route('/process', methods=['POST'])
def start_process():
    data = request.get_json()
    source = normalize_path(data.get('source', ''))
    if not os.path.exists(source):
        return jsonify({'error': f'File not found: {source}'}), 400

    try:
        min_inten  = float(data.get('min_inten', 0))
        max_inten  = float(data.get('max_inten', 255))
        brightness = float(data.get('brightness', 70)) / 100.0
    except ValueError as exc:
        return jsonify({'error': f'Invalid parameter: {exc}'}), 400

    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    output     = os.path.join(DESKTOP, f"intensity_rgb_{timestamp}.pts")
    job_id     = uuid.uuid4().hex[:8]

    jobs[job_id] = {
        'status':  'queued',
        'done':    0,
        'total':   1,
        'source':  source,
        'output':  output,
    }

    t = threading.Thread(
        target=run_job,
        args=(job_id, source, output, min_inten, max_inten, brightness),
        daemon=True,
    )
    t.start()
    return jsonify({'job_id': job_id})


@app.route('/stream/<job_id>')
def stream(job_id):
    """SSE endpoint — pushes job state every 500 ms until done or error."""
    def generate():
        while True:
            job = jobs.get(job_id)
            if job is None:
                yield f'data: {json.dumps({"status": "not_found"})}\n\n'
                break
            yield f'data: {json.dumps(job)}\n\n'
            if job['status'] in ('done', 'error'):
                break
            time.sleep(0.5)

    return Response(stream_with_context(generate()),
                    mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    port = 5000
    url  = f'http://localhost:{port}'
    # Open browser after a short delay so Flask has time to start
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f'\n  Intensity-RGB  →  {url}\n')
    app.run(host='127.0.0.1', port=port, debug=False, threaded=True)
