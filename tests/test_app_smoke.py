"""Headless smoke tests for the PySide6 UI (Wave 4 / D1).

These never call ``window.show()`` so they don't require an X server.
They run under ``QT_QPA_PLATFORM=offscreen`` which we set at import time
so that simply running ``pytest tests/test_app_smoke.py`` works from a
fresh shell.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest

from PySide6.QtWidgets import QApplication

from intensity_rgb.app import MainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_main_window_constructs(qapp):
    w = MainWindow()
    assert w.windowTitle(), "MainWindow should have a non-empty title"
    # Capability panel hooks should exist as attrs.
    assert hasattr(w, "input_path_edit")
    assert hasattr(w, "capability_text_widget")
    # Mode verdict chips exist for all three modes.
    assert set(w.verdict_chips.keys()) == {
        "intensity_only",
        "intensity_lambertian",
        "normal_as_color",
    }


def test_start_button_disabled_initially(qapp):
    w = MainWindow()
    assert not w.start_button.isEnabled(), (
        "Start must stay disabled until input + output paths are usable."
    )
    # Cancel is disabled with no running worker.
    assert not w.cancel_button.isEnabled()


def test_set_input_path_missing_file_shows_banner(qapp, tmp_path):
    w = MainWindow()
    fake_path = str(tmp_path / "does_not_exist.e57")
    w.set_input_path(fake_path)
    qapp.processEvents()
    # ``isVisible()`` only reports True once the parent window is shown,
    # which the smoke test deliberately skips. ``isVisibleTo`` reflects
    # the widget's intended visibility within its parent.
    assert w.capability_banner.isVisibleTo(w)
    assert "not found" in w.capability_banner.text().lower()
    # Verdict chips revert to neutral.
    for chip in w.verdict_chips.values():
        assert chip.text() in ("—", "")


def test_capability_updates_on_input_path(qapp):
    """If carpark_stairs.e57 exists in CWD, set_input_path should
    populate the capability panel within a single event-loop spin.
    Otherwise this test is skipped — same behaviour as the prompt
    requested.
    """
    w = MainWindow()
    fixture = "carpark_stairs.e57"
    if not os.path.isfile(fixture):
        pytest.skip("carpark_stairs.e57 not in CWD; skipping populated-panel check")
    w.set_input_path(fixture)
    qapp.processEvents()
    assert w.capability_text_widget is not None
    text = w.capability_text_widget.toPlainText()
    assert text, "Capability text should be populated for a valid .e57"
    # Some signal that the verdicts panel filled in.
    chip_text = w.verdict_chips["intensity_only"].text()
    assert chip_text in ("GREEN", "YELLOW", "RED")


def test_job_spec_shape(qapp):
    """Job spec dict has the keys the D2 worker contract expects."""
    w = MainWindow()
    spec = w._build_job_spec()
    expected_keys = {
        "input_path",
        "output_path",
        "mode",
        "shading_mode",
        "intensity_range",
        "brightness",
        "voxel_size",
        "light_dir",
        "ambient",
        "ground_color",
        "sky_color",
        "invert_globally",
    }
    assert expected_keys.issubset(spec.keys()), (
        f"missing keys: {expected_keys - set(spec.keys())}"
    )
    # Light dir is a 3-tuple of unit-ish floats.
    assert len(spec["light_dir"]) == 3
