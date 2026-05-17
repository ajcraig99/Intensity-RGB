"""Smoke tests for the PipelineWorker QThread wrapper.

Confirms that:

* ``pipeline_clone`` driven via the worker emits at least one progress
  signal and one terminal ``finished`` signal within 30 s on the
  ``carpark_stairs.e57`` fixture.
* :meth:`PipelineWorker.cancel` interrupts a running ``bake_intensity``
  job promptly (well under the 8 s slack budget on the test machine).

Implementation notes
--------------------
Signal receivers are wrapped in a tiny :class:`_SignalCollector` QObject
that lives on the main thread. PySide6's auto-connection chooses
QueuedConnection when the sender (PipelineWorker) lives in a worker
thread, so the slot runs on the main thread's event loop — exactly the
contract real GUI code relies on, and what ``app.processEvents`` is
guaranteed to deliver. Bare ``lambda`` receivers behave more
unpredictably across runs (no thread affinity), which is fine for
production code but flaky as a test oracle.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import gc
import sys
import time

import pytest

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, Slot

from intensity_rgb.worker import PipelineWorker, create_worker_thread  # noqa: F401


@pytest.fixture(scope="module")
def app() -> QCoreApplication:
    instance = QCoreApplication.instance()
    if instance is None:
        instance = QCoreApplication(sys.argv)
    yield instance


class _SignalCollector(QObject):
    """Main-thread QObject that captures worker signals as plain Python state.

    Using a QObject (not a lambda) ensures the slots run on this
    object's thread via QueuedConnection — which is the main thread in
    these tests, so ``app.processEvents`` always delivers them.
    """

    def __init__(self) -> None:
        super().__init__()
        self.progress_count = 0
        self.finished: tuple | None = None
        self.last_done = 0
        self.on_first_progress = None

    @Slot(int, int)
    def slot_progress(self, done: int, total: int) -> None:
        self.progress_count += 1
        self.last_done = done
        if self.progress_count == 1 and self.on_first_progress is not None:
            self.on_first_progress()

    @Slot(bool, str)
    def slot_finished(self, ok: bool, msg: str) -> None:
        self.finished = (ok, msg)


def _shutdown(thread, worker, collector, app):
    """Tear down worker/thread/collector so the next test starts clean."""
    thread.quit()
    thread.wait(5000)
    worker.deleteLater()
    thread.deleteLater()
    collector.deleteLater()
    app.processEvents(QEventLoop.AllEvents, 50)
    gc.collect()
    app.processEvents(QEventLoop.AllEvents, 50)


def test_run_pipeline_clone_emits_signals(app, tmp_path):
    spec = {
        "mode": "clone",
        "input": "carpark_stairs.e57",
        "output": str(tmp_path / "out.e57"),
        "block_size": 500_000,
    }
    thread, worker = create_worker_thread(spec)
    collector = _SignalCollector()
    worker.progress.connect(collector.slot_progress)
    worker.finished.connect(collector.slot_finished)
    thread.start()
    # Wait up to 30s for finished signal
    deadline = time.time() + 30
    while collector.finished is None and time.time() < deadline:
        app.processEvents(QEventLoop.AllEvents, 100)
    try:
        assert collector.finished is not None, "worker didn't finish in 30s"
        ok, msg = collector.finished
        assert ok, f"worker failed: {msg}"
        assert collector.progress_count >= 1, "no progress signals emitted"
    finally:
        _shutdown(thread, worker, collector, app)


def test_cancel_exits_promptly(app, tmp_path):
    spec = {
        "mode": "bake_intensity",
        "input": "carpark_stairs.e57",
        "output": str(tmp_path / "cancel.e57"),
        "intensity_range": (0.0, 4096.0),
        "brightness": 70.0,
        "block_size": 500_000,
    }
    thread, worker = create_worker_thread(spec)
    collector = _SignalCollector()
    collector.on_first_progress = worker.cancel
    worker.progress.connect(collector.slot_progress)
    worker.finished.connect(collector.slot_finished)
    t0 = time.time()
    thread.start()
    deadline = time.time() + 10
    while collector.finished is None and time.time() < deadline:
        app.processEvents(QEventLoop.AllEvents, 100)
    elapsed = time.time() - t0
    try:
        assert collector.finished is not None, "worker didn't finish in 10s"
        # Cancel should exit within a couple of blocks (~ 0.5 s on carpark);
        # allow 8s slack for slow machines.
        assert elapsed < 8.0, f"cancel took {elapsed:.1f}s, expected < 8s"
    finally:
        _shutdown(thread, worker, collector, app)
