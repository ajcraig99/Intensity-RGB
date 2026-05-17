"""QSettings persistence + components-info tests for MainWindow (D3 scope).

We point ``QSettings`` at a tmp_path-backed directory via the environment
variables Qt's INI backend honours so the host's real settings are
untouched. ``QT_QPA_PLATFORM=offscreen`` keeps the tests headless.

D3 surface under test:

* ``MainWindow._save_settings`` / ``_load_settings`` round-trip for the
  paths and bake/* keys named in the prompt.
* Stale-path scrubbing: a saved input path that no longer exists must
  not be restored.
* ``_on_components_info`` populates non-interactive chips when the
  worker emits a payload.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from intensity_rgb.app import MainWindow, QSETTINGS_APP, QSETTINGS_ORG


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture(autouse=True)
def isolated_qsettings(tmp_path, monkeypatch):
    """Redirect QSettings storage to a per-test directory so we don't
    touch the developer's real config or pollute neighbouring tests.

    We force INI format globally and route the UserScope path for
    ``(QSETTINGS_ORG, QSETTINGS_APP)`` into ``tmp_path``. This works
    regardless of what backend the host would normally use.
    """
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(
        QSettings.IniFormat, QSettings.UserScope, str(tmp_path)
    )
    QSettings.setPath(
        QSettings.IniFormat, QSettings.SystemScope, str(tmp_path / "system")
    )
    yield


def test_qsettings_roundtrip_paths(qapp, tmp_path):
    """A path that *exists* must survive a save/load cycle into a fresh window."""
    input_file = tmp_path / "fake.e57"
    input_file.write_bytes(b"")  # exists but isn't a real .e57; we only
    # test the path-restore plumbing here, not capability parsing.
    out_file = tmp_path / "out.e57"

    w1 = MainWindow()
    w1.set_output_path(str(out_file))
    w1.input_path_edit.setText(str(input_file))  # bypass capability parsing
    w1._save_settings()
    w1.close()

    w2 = MainWindow()
    assert w2.input_path_text() == str(input_file), (
        "saved input path must round-trip into a new MainWindow"
    )
    assert w2.output_path_text() == str(out_file)


def test_qsettings_stale_input_blanked(qapp, tmp_path):
    """A saved input path whose file no longer exists must NOT be restored."""
    gone = tmp_path / "deleted.e57"
    gone.write_bytes(b"")

    w1 = MainWindow()
    w1.input_path_edit.setText(str(gone))
    w1._save_settings()
    w1.close()

    # Simulate the file being deleted between sessions.
    gone.unlink()

    w2 = MainWindow()
    assert w2.input_path_text() == "", (
        "stale input paths must be scrubbed, not silently re-displayed"
    )


def test_qsettings_bake_keys_roundtrip(qapp, tmp_path):
    """The bake/* keys named in the D3 prompt must survive a round trip."""
    w1 = MainWindow()
    w1.intensity_min_spin.setValue(5.0)
    w1.intensity_max_spin.setValue(2048.0)
    w1.brightness_slider.setValue(55)
    w1.voxel_size_spin.setValue(0.25)
    w1.light_azimuth_spin.setValue(90.0)
    w1.light_elevation_spin.setValue(30.0)
    w1.ambient_slider.setValue(45)
    w1.shade_three_pt_radio.setChecked(True)
    w1.up_x_spin.setValue(0.1)
    w1.up_y_spin.setValue(0.2)
    w1.up_z_spin.setValue(0.9)
    w1.invert_normals_check.setChecked(True)
    # Color pickers — exercise the property/text round-trip too.
    w1.ground_picker_button.setProperty("rgb", (10, 20, 30))
    w1.sky_picker_button.setProperty("rgb", (200, 220, 240))
    w1._save_settings()
    w1.close()

    w2 = MainWindow()
    assert w2.intensity_min_spin.value() == pytest.approx(5.0)
    assert w2.intensity_max_spin.value() == pytest.approx(2048.0)
    assert w2.brightness_slider.value() == 55
    assert w2.voxel_size_spin.value() == pytest.approx(0.25)
    assert w2.light_azimuth_spin.value() == pytest.approx(90.0)
    assert w2.light_elevation_spin.value() == pytest.approx(30.0)
    # Ambient is stored as 0..1, slider is 0..100 — allow rounding slack.
    assert abs(w2.ambient_slider.value() - 45) <= 1
    assert w2.shade_three_pt_radio.isChecked()
    assert w2.up_x_spin.value() == pytest.approx(0.1)
    assert w2.up_y_spin.value() == pytest.approx(0.2)
    assert w2.up_z_spin.value() == pytest.approx(0.9)
    assert w2.invert_normals_check.isChecked()
    assert w2.ground_picker_button.property("rgb") == (10, 20, 30)
    assert w2.sky_picker_button.property("rgb") == (200, 220, 240)


def test_components_info_populates_chips(qapp):
    """``_on_components_info`` builds one chip per entry and shows the group."""
    w = MainWindow()
    assert not w.components_group.isVisibleTo(w), (
        "components groupbox is hidden until the worker emits a payload"
    )
    payload = [
        {"id": 0, "voxel_count": 1234, "mean_normal": [0.0, 0.0, 1.0]},
        {"id": 1, "voxel_count": 567, "mean_normal": [1.0, 0.0, 0.0]},
    ]
    w._on_components_info(payload)
    assert w.components_group.isVisibleTo(w)
    assert len(w._component_chips) == 2
    # Chip text carries the id and the human-friendly count.
    assert "#0" in w._component_chips[0].text()
    assert "voxels" in w._component_chips[0].text()
    # Tooltip carries the mean-normal direction.
    assert "0.000" in w._component_chips[0].toolTip() or "+0.000" in w._component_chips[0].toolTip()
    # Empty payload hides the group and clears the chips.
    w._on_components_info([])
    assert not w.components_group.isVisibleTo(w)
    assert w._component_chips == []
