"""PySide6 desktop UI for Intensity-RGB V2.0 (Wave 4 / D1).

Plans:
    /home/arron/.claude/plans/quizzical-humming-metcalfe.md  (Wave 4 / D1)
    /home/arron/.claude/plans/stateful-hatching-kitten.md    (§"UI" — layout)

This module is the single-window UI surface. It wraps two Qt-free
collaborators:

* :mod:`intensity_rgb.capability` — header-only inspection of an .e57,
  populating the Capability panel on input-path change. Sub-millisecond
  per C3's report, so it's safe to call on the UI thread.

* :mod:`intensity_rgb.worker` — QThread worker that drives the streaming
  pipeline (:mod:`intensity_rgb.pipeline`). All long-running work goes
  through this worker; the UI thread never calls a pipeline function
  directly.

The UI follows the ASCII sketch in design §"UI" (Input / Capability /
Output / Color+Shading / Job / Log). Fusion dark palette via QPalette.

Public surface
--------------

* :class:`MainWindow` — the QMainWindow subclass. Tests construct this
  directly under ``QT_QPA_PLATFORM=offscreen`` for smoke verification.
* :func:`main` — the program entrypoint (called from ``__main__``).
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal, QSettings, QByteArray
from PySide6.QtGui import QColor, QPalette, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QButtonGroup,
    QSizePolicy,
)

from intensity_rgb import capability as cap_mod
from intensity_rgb.io.e57_clone import E57CloneReader


__all__ = ["MainWindow", "main"]


# QSettings identity per Wave 4 / D3 prompt. Organization is a short id;
# application carries the human-readable product name + version so future
# V2.x can opt into a clean keyspace without colliding with V2.0.
QSETTINGS_ORG = "intensity-rgb"
QSETTINGS_APP = "Intensity-RGB V2.0"


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------


def _apply_fusion_dark_palette(app: QApplication) -> None:
    """Apply the Fusion dark palette referenced in design §"UI"."""
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(45, 45, 45))
    pal.setColor(QPalette.WindowText, QColor(220, 220, 220))
    pal.setColor(QPalette.Base, QColor(30, 30, 30))
    pal.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
    pal.setColor(QPalette.ToolTipBase, QColor(220, 220, 220))
    pal.setColor(QPalette.ToolTipText, QColor(20, 20, 20))
    pal.setColor(QPalette.Text, QColor(220, 220, 220))
    pal.setColor(QPalette.Button, QColor(53, 53, 53))
    pal.setColor(QPalette.ButtonText, QColor(220, 220, 220))
    pal.setColor(QPalette.BrightText, QColor(255, 60, 60))
    pal.setColor(QPalette.Highlight, QColor(38, 130, 200))
    pal.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(120, 120, 120))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(120, 120, 120))
    app.setPalette(pal)


_VERDICT_COLORS = {
    "GREEN": "#4caf50",
    "YELLOW": "#ffc107",
    "RED": "#f44336",
}


def _chip_stylesheet(verdict: str) -> str:
    color = _VERDICT_COLORS.get(verdict, "#9e9e9e")
    fg = "#000000" if verdict == "YELLOW" else "#ffffff"
    return (
        f"QLabel {{ background-color: {color}; color: {fg}; "
        f"padding: 2px 8px; border-radius: 6px; font-weight: bold; }}"
    )


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------


def _hline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    return line


def _path_row(line_edit: QLineEdit, browse_button: QPushButton) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addWidget(line_edit, stretch=1)
    row.addWidget(browse_button)
    return row


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    """Single-window UI: Input / Capability / Output / Color+Shading / Job / Log.

    The capability panel auto-populates whenever the input path is
    edited (debounced ~200 ms via ``QTimer.singleShot``). The Start
    button is enabled only when input + output paths look usable and
    the selected mode's verdict is not RED. All pipeline work runs on
    the D2 :mod:`intensity_rgb.worker` QThread; this class never calls
    a pipeline function directly.
    """

    # Optional signal a smoke test can connect to in lieu of polling.
    capability_updated = Signal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Intensity-RGB V2.0")
        self.resize(900, 920)

        self._worker = None  # late-bound on Start
        self._worker_thread = None  # late-bound on Start (owns the worker)
        self._current_stage: str = ""  # set by worker.stage signal
        self._cap_report: Optional[cap_mod.CapabilityReport] = None
        self._cap_debounce = QTimer(self)
        self._cap_debounce.setSingleShot(True)
        self._cap_debounce.setInterval(200)
        self._cap_debounce.timeout.connect(self._refresh_capability)

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        root.addWidget(self._build_input_section())
        root.addWidget(self._build_capability_section())
        root.addWidget(self._build_output_section())
        root.addWidget(self._build_color_shading_section())
        root.addWidget(self._build_job_section())
        root.addWidget(self._build_log_section(), stretch=1)

        # Restore prior session state (window geometry, path entries, all
        # bake/* settings). Tolerant of missing or stale keys — the
        # defaults already baked into each widget remain authoritative
        # when QSettings is empty.
        self._load_settings()

        self._update_start_enabled()

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_input_section(self) -> QGroupBox:
        box = QGroupBox("Input")
        layout = QVBoxLayout(box)

        self.input_path_edit = QLineEdit()
        self.input_path_edit.setPlaceholderText("Path to .e57 file…")
        self.input_path_edit.textChanged.connect(self._on_input_text_changed)
        self.input_path_edit.editingFinished.connect(self._refresh_capability)

        self.input_browse_button = QPushButton("Browse…")
        self.input_browse_button.clicked.connect(self._browse_input)

        layout.addLayout(_path_row(self.input_path_edit, self.input_browse_button))
        return box

    def _build_capability_section(self) -> QGroupBox:
        box = QGroupBox("Capability (instant, from header)")
        layout = QVBoxLayout(box)

        self.capability_banner = QLabel("")
        self.capability_banner.setVisible(False)
        self.capability_banner.setStyleSheet(
            "QLabel { background-color: #f44336; color: white; "
            "padding: 4px 8px; border-radius: 4px; }"
        )
        layout.addWidget(self.capability_banner)

        # Multi-line read-only widget for the textual summary.
        self.capability_text_widget = QTextEdit()
        self.capability_text_widget.setReadOnly(True)
        self.capability_text_widget.setMinimumHeight(120)
        self.capability_text_widget.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred
        )
        self.capability_text_widget.setPlaceholderText(
            "Enter a .e57 path above to populate header capability info."
        )
        layout.addWidget(self.capability_text_widget)

        # Estimate-touched-chunks button. Runs on UI thread for small samples;
        # TODO: push to worker if visibly slow on huge files (>1 M points).
        self.estimate_chunks_button = QPushButton("Estimate touched chunks via sampling")
        self.estimate_chunks_button.setEnabled(False)
        self.estimate_chunks_button.clicked.connect(self._on_estimate_chunks)
        layout.addWidget(self.estimate_chunks_button)

        # Mode verdict chips.
        verdict_row = QHBoxLayout()
        self.verdict_chips = {}
        for mode_key, mode_label in (
            ("intensity_only", "Intensity only"),
            ("intensity_lambertian", "Intensity + Lambertian"),
            ("normal_as_color", "Normal-as-color"),
        ):
            sub = QVBoxLayout()
            sub.addWidget(QLabel(mode_label))
            chip = QLabel("—")
            chip.setAlignment(Qt.AlignCenter)
            chip.setMinimumWidth(80)
            chip.setStyleSheet(_chip_stylesheet(""))
            sub.addWidget(chip)
            self.verdict_chips[mode_key] = chip
            verdict_row.addLayout(sub)
        verdict_row.addStretch(1)
        layout.addLayout(verdict_row)

        self.estimated_runtime_label = QLabel(
            "Estimated runtime: TBD (measured at start of job)"
        )
        layout.addWidget(self.estimated_runtime_label)
        return box

    def _build_output_section(self) -> QGroupBox:
        box = QGroupBox("Output")
        layout = QVBoxLayout(box)
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("Path to write .e57 file…")
        self.output_path_edit.textChanged.connect(lambda _t: self._update_start_enabled())
        self.output_browse_button = QPushButton("Browse…")
        self.output_browse_button.clicked.connect(self._browse_output)
        layout.addLayout(_path_row(self.output_path_edit, self.output_browse_button))
        return box

    def _build_color_shading_section(self) -> QGroupBox:
        box = QGroupBox("Color + Shading")
        layout = QVBoxLayout(box)

        # --- Base radios ---
        base_row = QHBoxLayout()
        base_row.addWidget(QLabel("Base:"))
        self.base_intensity_radio = QRadioButton("Intensity-mapped")
        self.base_original_radio = QRadioButton("Original")
        self.base_single_radio = QRadioButton("Single")
        self.base_intensity_radio.setChecked(True)
        self.base_group = QButtonGroup(self)
        for r in (
            self.base_intensity_radio,
            self.base_original_radio,
            self.base_single_radio,
        ):
            self.base_group.addButton(r)
            base_row.addWidget(r)
        base_row.addStretch(1)
        layout.addLayout(base_row)

        # --- Intensity range + auto-detect ---
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("Intensity range"))
        self.intensity_min_spin = QDoubleSpinBox()
        self.intensity_min_spin.setRange(-1e9, 1e9)
        self.intensity_min_spin.setDecimals(3)
        self.intensity_min_spin.setValue(0.0)
        self.intensity_max_spin = QDoubleSpinBox()
        self.intensity_max_spin.setRange(-1e9, 1e9)
        self.intensity_max_spin.setDecimals(3)
        self.intensity_max_spin.setValue(4096.0)
        self.auto_detect_button = QPushButton("Auto-detect")
        self.auto_detect_button.clicked.connect(self._on_auto_detect)
        range_row.addWidget(self.intensity_min_spin)
        range_row.addWidget(self.intensity_max_spin)
        range_row.addWidget(self.auto_detect_button)
        range_row.addStretch(1)
        layout.addLayout(range_row)

        # --- Brightness slider ---
        bright_row = QHBoxLayout()
        bright_row.addWidget(QLabel("Brightness"))
        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setRange(0, 100)
        self.brightness_slider.setValue(70)
        self.brightness_label = QLabel("70")
        self.brightness_slider.valueChanged.connect(
            lambda v: self.brightness_label.setText(str(v))
        )
        bright_row.addWidget(self.brightness_slider, stretch=1)
        bright_row.addWidget(self.brightness_label)
        layout.addLayout(bright_row)

        layout.addWidget(_hline())

        # --- Shading radios ---
        shading_row = QHBoxLayout()
        shading_label = QLabel("Shading:")
        shading_row.addWidget(shading_label)
        self.shade_none_radio = QRadioButton("None")
        self.shade_lambertian_radio = QRadioButton("Lambertian")
        self.shade_three_pt_radio = QRadioButton("3-pt")
        self.shade_normal_radio = QRadioButton("Norm")
        self.shade_lambertian_radio.setChecked(True)
        self.shading_group = QButtonGroup(self)
        for r in (
            self.shade_none_radio,
            self.shade_lambertian_radio,
            self.shade_three_pt_radio,
            self.shade_normal_radio,
        ):
            self.shading_group.addButton(r)
            shading_row.addWidget(r)
        shading_row.addStretch(1)
        layout.addLayout(shading_row)

        # Tooltip per design §"Normal orientation": viewpoint-free normal
        # orientation is fundamentally heuristic; signs can flip for
        # unusual scene geometries (e.g. fully-enclosed indoor scans
        # without a sky-facing surface). Inform the user up front.
        _shading_tip = (
            "Voxel normals are oriented without a viewpoint, using the "
            "up-vector (and ground heuristic) only. Orientation is "
            "fundamentally heuristic and may be flipped for unusual scene "
            "geometries — toggle 'Invert normals globally' if the lit "
            "side of the cloud appears reversed."
        )
        shading_label.setToolTip(_shading_tip)
        for r in (
            self.shade_none_radio,
            self.shade_lambertian_radio,
            self.shade_three_pt_radio,
            self.shade_normal_radio,
        ):
            r.setToolTip(_shading_tip)

        # --- Light dir azimuth / elevation ---
        light_row = QHBoxLayout()
        light_row.addWidget(QLabel("light dir azimuth"))
        self.light_azimuth_spin = QDoubleSpinBox()
        self.light_azimuth_spin.setRange(-360.0, 360.0)
        self.light_azimuth_spin.setSuffix(" °")
        self.light_azimuth_spin.setValue(135.0)
        light_row.addWidget(self.light_azimuth_spin)
        light_row.addWidget(QLabel("elevation"))
        self.light_elevation_spin = QDoubleSpinBox()
        self.light_elevation_spin.setRange(-90.0, 90.0)
        self.light_elevation_spin.setSuffix(" °")
        self.light_elevation_spin.setValue(45.0)
        light_row.addWidget(self.light_elevation_spin)
        light_row.addStretch(1)
        layout.addLayout(light_row)

        # --- Ambient slider ---
        amb_row = QHBoxLayout()
        amb_row.addWidget(QLabel("Ambient"))
        self.ambient_slider = QSlider(Qt.Horizontal)
        self.ambient_slider.setRange(0, 100)
        self.ambient_slider.setValue(30)
        self.ambient_label = QLabel("0.30")
        self.ambient_slider.valueChanged.connect(
            lambda v: self.ambient_label.setText(f"{v / 100.0:.2f}")
        )
        amb_row.addWidget(self.ambient_slider, stretch=1)
        amb_row.addWidget(self.ambient_label)
        layout.addLayout(amb_row)

        # --- Voxel size + ground/sky pickers (placeholders) ---
        voxel_row = QHBoxLayout()
        voxel_row.addWidget(QLabel("voxel size"))
        self.voxel_size_spin = QDoubleSpinBox()
        self.voxel_size_spin.setRange(0.01, 100.0)
        self.voxel_size_spin.setDecimals(3)
        self.voxel_size_spin.setSingleStep(0.05)
        self.voxel_size_spin.setSuffix(" m")
        self.voxel_size_spin.setValue(0.5)
        voxel_row.addWidget(self.voxel_size_spin)
        voxel_row.addWidget(QLabel("ground"))
        self.ground_picker_button = QPushButton("(60,40,30)")
        self.ground_picker_button.clicked.connect(
            lambda: self._pick_color(self.ground_picker_button, default=(60, 40, 30))
        )
        voxel_row.addWidget(self.ground_picker_button)
        voxel_row.addWidget(QLabel("sky"))
        self.sky_picker_button = QPushButton("(180,210,255)")
        self.sky_picker_button.clicked.connect(
            lambda: self._pick_color(self.sky_picker_button, default=(180, 210, 255))
        )
        voxel_row.addWidget(self.sky_picker_button)
        voxel_row.addStretch(1)
        layout.addLayout(voxel_row)

        # --- Up vector row -------------------------------------------------
        # Survey data is almost always gravity-aligned (+Z up); we expose
        # editable XYZ components anyway so non-standard scans aren't a
        # dead end. Tooltip notes the default rationale.
        up_row = QHBoxLayout()
        up_label = QLabel("Up vector")
        up_row.addWidget(up_label)
        self.up_x_spin = QDoubleSpinBox()
        self.up_x_spin.setRange(-1.0, 1.0)
        self.up_x_spin.setDecimals(3)
        self.up_x_spin.setSingleStep(0.1)
        self.up_x_spin.setValue(0.0)
        self.up_y_spin = QDoubleSpinBox()
        self.up_y_spin.setRange(-1.0, 1.0)
        self.up_y_spin.setDecimals(3)
        self.up_y_spin.setSingleStep(0.1)
        self.up_y_spin.setValue(0.0)
        self.up_z_spin = QDoubleSpinBox()
        self.up_z_spin.setRange(-1.0, 1.0)
        self.up_z_spin.setDecimals(3)
        self.up_z_spin.setSingleStep(0.1)
        self.up_z_spin.setValue(1.0)
        for label_text, spin in (("X", self.up_x_spin), ("Y", self.up_y_spin), ("Z", self.up_z_spin)):
            up_row.addWidget(QLabel(label_text))
            up_row.addWidget(spin)
        up_row.addStretch(1)
        layout.addLayout(up_row)

        _up_tip = (
            "Up vector used to orient voxel normals consistently across "
            "the cloud. Survey data is typically gravity-aligned, so +Z up "
            "(0, 0, 1) is the correct default for nearly all scans."
        )
        up_label.setToolTip(_up_tip)
        for s in (self.up_x_spin, self.up_y_spin, self.up_z_spin):
            s.setToolTip(_up_tip)

        self.invert_normals_check = QCheckBox("Invert normals globally")
        self.invert_normals_check.setToolTip(
            "Flip every per-voxel normal after orientation. Use this if "
            "the heuristic orientation produced an inverted shading "
            "result for the scene as a whole."
        )
        layout.addWidget(self.invert_normals_check)

        return box

    def _build_job_section(self) -> QGroupBox:
        box = QGroupBox("Job")
        layout = QVBoxLayout(box)

        prog_row = QHBoxLayout()
        prog_row.addWidget(QLabel("Progress:"))
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_text_label = QLabel("0 / 0 pts")
        prog_row.addWidget(self.progress_bar, stretch=1)
        prog_row.addWidget(self.progress_text_label)
        layout.addLayout(prog_row)

        stats_row = QHBoxLayout()
        self.throughput_label = QLabel("Throughput: —")
        self.peak_rss_label = QLabel("Peak RSS: —")
        self.eta_label = QLabel("ETA: —")
        self.voxel_quality_label = QLabel("Voxel quality: —")
        for w in (
            self.throughput_label,
            self.peak_rss_label,
            self.eta_label,
            self.voxel_quality_label,
        ):
            stats_row.addWidget(w)
        stats_row.addStretch(1)
        layout.addLayout(stats_row)

        button_row = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self._on_start)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel)
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.cancel_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        # --- Components panel (per design §"Normal orientation") ---------
        # V2.0 scope: read-only chips populated after Pass 1 of a
        # bake_normals job. One QToolButton per top-K component, text
        # "#{id}: {n} voxels", tooltip carrying the mean-normal direction.
        # Hidden by default; shown only once ``components_info`` fires.
        # Collapsible via the groupbox's checkable hint. V2.1 will add
        # live single-component invert handling on click.
        self.components_group = QGroupBox("Components (top by size)")
        self.components_group.setCheckable(True)
        self.components_group.setChecked(True)
        self.components_group.setVisible(False)
        self.components_group.setToolTip(
            "Per-component diagnostic chips populated after the "
            "orientation pass. Each chip shows a connected normal "
            "component's voxel count; hover for its mean normal "
            "direction. In V2.0 these chips are informational only; "
            "use 'Invert normals globally' if the overall orientation "
            "is wrong."
        )
        self._components_layout = QHBoxLayout(self.components_group)
        self._components_layout.setContentsMargins(8, 4, 8, 4)
        self._components_layout.addStretch(1)
        # Show/hide the inner widgets when the group is unchecked.
        self.components_group.toggled.connect(
            lambda checked: [
                self._components_layout.itemAt(i).widget().setVisible(checked)
                for i in range(self._components_layout.count())
                if self._components_layout.itemAt(i).widget() is not None
            ]
        )
        # We track chip widgets separately so _on_components_info can
        # wipe them cleanly between runs.
        self._component_chips: list = []
        layout.addWidget(self.components_group)

        return box

    def _build_log_section(self) -> QGroupBox:
        box = QGroupBox("Log")
        box.setCheckable(True)
        box.setChecked(True)
        layout = QVBoxLayout(box)
        self.log_widget = QTextEdit()
        self.log_widget.setReadOnly(True)
        layout.addWidget(self.log_widget)
        # Collapsible: hide inner widget when group is unchecked.
        box.toggled.connect(self.log_widget.setVisible)
        return box

    # ------------------------------------------------------------------
    # Capability panel population
    # ------------------------------------------------------------------

    def set_input_path(self, path: str) -> None:
        """Programmatically set the input path. Triggers a synchronous
        capability refresh — used by tests and external callers.
        """
        self.input_path_edit.setText(path)
        # Bypass the debounce timer; do it now for predictability.
        self._refresh_capability()

    def _on_input_text_changed(self, _text: str) -> None:
        # Debounce: rapid typing collapses to a single refresh.
        self._cap_debounce.start()
        self._update_start_enabled()

    def _refresh_capability(self) -> None:
        path = self.input_path_edit.text().strip()
        self.capability_banner.setVisible(False)
        if not path:
            self.capability_text_widget.setPlainText("")
            self._cap_report = None
            self._update_verdict_chips({})
            self.estimate_chunks_button.setEnabled(False)
            self._update_start_enabled()
            return

        if not os.path.isfile(path):
            self._show_capability_error(f"File not found: {path}")
            self._cap_report = None
            self._update_verdict_chips({})
            self.estimate_chunks_button.setEnabled(False)
            self._update_start_enabled()
            return

        try:
            voxel = float(self.voxel_size_spin.value())
            report = cap_mod.inspect_file(path, voxel_size=voxel)
        except Exception as exc:  # pragma: no cover - surfaced to UI
            self._show_capability_error(f"Failed to read .e57 header: {exc}")
            self._cap_report = None
            self._update_verdict_chips({})
            self.estimate_chunks_button.setEnabled(False)
            self._update_start_enabled()
            return

        self._cap_report = report
        self.capability_text_widget.setPlainText(self._format_capability(report))
        self._update_verdict_chips(report.verdicts)
        self.estimate_chunks_button.setEnabled(True)
        self.capability_updated.emit(report)

        # Seed intensity-range spin defaults if user hasn't touched them
        # and the report says the file looks normal. We don't auto-fill
        # because the header doesn't carry intensity min/max — that comes
        # from the Auto-detect button or the user.

        self._update_start_enabled()

    def _show_capability_error(self, message: str) -> None:
        self.capability_banner.setText(message)
        self.capability_banner.setVisible(True)
        self.capability_text_widget.setPlainText("")

    def _format_capability(self, report: cap_mod.CapabilityReport) -> str:
        lines = []
        organized_str = "yes" if report.organized_in_any_scan else "no"
        lines.append(
            f"Scans: {report.scan_count} "
            f"({_format_points(report.total_points)} pts, organized={organized_str})"
        )
        if report.file_aabb_min is not None and report.file_aabb_max is not None:
            extent = tuple(
                report.file_aabb_max[i] - report.file_aabb_min[i] for i in range(3)
            )
            lines.append(
                f"Bounds: {extent[0]:.1f} × {extent[1]:.1f} × {extent[2]:.1f} m"
            )
        else:
            lines.append("Bounds: (header AABB missing)")

        rgb_state = "present" if report.rgb_present_in_all_scans else "missing"
        normals_state = (
            " (embedded normals detected)"
            if report.embedded_normals_in_any_scan
            else ""
        )
        lines.append(f"RGB fields: {rgb_state}{normals_state}")

        voxel = float(self.voxel_size_spin.value())
        lines.append(f"Voxel @ {voxel:.2f}m, chunk C=32:")
        if report.max_possible_chunk_count > 0:
            lines.append(
                f"  Max touched chunks: {report.max_possible_chunk_count:,} (upper bound)"
            )
        else:
            lines.append("  Max touched chunks: (header AABB missing)")
        lines.append(
            f"  Peak RAM upper bound: ~{_format_bytes(max(report.pass1_peak_ram_upper_bound_bytes, report.pass2_peak_ram_upper_bound_bytes))}"
        )

        lines.append("Mode verdicts:")
        for mode_key, mode_label in (
            ("intensity_only", "Intensity only"),
            ("intensity_lambertian", "Intensity + Lambertian"),
            ("normal_as_color", "Normal-as-color"),
        ):
            verdict = report.verdicts.get(mode_key, "?")
            reason = report.verdict_reasons.get(mode_key, "")
            lines.append(f"  {mode_label:<26s} [{verdict}] {reason}")

        return "\n".join(lines)

    def _update_verdict_chips(self, verdicts: dict) -> None:
        for key, chip in self.verdict_chips.items():
            v = verdicts.get(key, "")
            chip.setText(v if v else "—")
            chip.setStyleSheet(_chip_stylesheet(v))

    # ------------------------------------------------------------------
    # File pickers + auto-detect
    # ------------------------------------------------------------------

    def _browse_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose .e57 input file", "", "E57 files (*.e57);;All files (*.*)"
        )
        if path:
            self.input_path_edit.setText(path)
            self._refresh_capability()

    def _browse_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Choose .e57 output file", "", "E57 files (*.e57);;All files (*.*)"
        )
        if path:
            if not path.lower().endswith(".e57"):
                path = path + ".e57"
            self.output_path_edit.setText(path)

    def _pick_color(self, button: QPushButton, default: tuple) -> None:
        # Late import to keep top-level imports light.
        from PySide6.QtWidgets import QColorDialog
        current = QColor(*default)
        # Stored as a button.property would be ideal; we just re-pick.
        new = QColorDialog.getColor(current, self, "Pick color")
        if new.isValid():
            button.setText(f"({new.red()},{new.green()},{new.blue()})")
            button.setProperty("rgb", (new.red(), new.green(), new.blue()))

    def _on_auto_detect(self) -> None:
        """Sample scan 0 to compute intensity_min/max and fill the spinboxes.

        Uses the pipeline helper (synchronous; first ~10 blocks of scan 0
        only — fast enough to be UI-thread safe per design plan).
        """
        path = self.input_path_edit.text().strip()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "Auto-detect", "Set a valid input path first.")
            return
        try:
            from intensity_rgb.pipeline import get_aabb_and_intensity_range
            with E57CloneReader(path) as reader:
                summary = get_aabb_and_intensity_range(reader)
            self.intensity_min_spin.setValue(float(summary["intensity_min"]))
            self.intensity_max_spin.setValue(float(summary["intensity_max"]))
            self._log(
                f"Auto-detect: intensity range = "
                f"[{summary['intensity_min']:.3f}, {summary['intensity_max']:.3f}] "
                f"over {summary['points_seen']:,} sampled pts."
            )
        except Exception as exc:
            QMessageBox.warning(
                self, "Auto-detect", f"Failed to sample intensity range: {exc}"
            )

    def _on_estimate_chunks(self) -> None:
        path = self.input_path_edit.text().strip()
        if not path or not os.path.isfile(path):
            return
        try:
            voxel = float(self.voxel_size_spin.value())
            with E57CloneReader(path) as reader:
                result = cap_mod.estimate_touched_chunks(
                    reader, voxel_size=voxel
                )
            msg = (
                f"Sampled {result['sample_points']:,} pts of "
                f"{result['total_points']:,}; observed {result['chunks_in_sample']:,} "
                f"chunks. Extrapolated total ≈ {result['estimated_total_chunks']:,}; "
                f"estimated peak RAM ≈ {_format_bytes(result['estimated_peak_ram_bytes'])}."
            )
            self._log(msg)
            QMessageBox.information(self, "Estimate touched chunks", msg)
        except Exception as exc:
            QMessageBox.warning(
                self, "Estimate touched chunks", f"Sampling failed: {exc}"
            )

    # ------------------------------------------------------------------
    # Start / Cancel + worker wiring
    # ------------------------------------------------------------------

    def _selected_shading_mode(self) -> str:
        if self.shade_lambertian_radio.isChecked():
            return "lambertian"
        if self.shade_three_pt_radio.isChecked():
            return "three_point"
        if self.shade_normal_radio.isChecked():
            return "normal_as_color"
        return "none"

    def _selected_verdict_key(self) -> str:
        shading = self._selected_shading_mode()
        if shading == "none":
            return "intensity_only"
        if shading == "normal_as_color":
            return "normal_as_color"
        # Both lambertian and three_point use the voxel-normal pipeline.
        return "intensity_lambertian"

    def _update_start_enabled(self) -> None:
        input_path = self.input_path_edit.text().strip()
        output_path = self.output_path_edit.text().strip()
        ok = bool(input_path) and os.path.isfile(input_path)
        ok = ok and bool(output_path)
        if ok and self._cap_report is not None:
            verdict = self._cap_report.verdicts.get(self._selected_verdict_key(), "")
            if verdict == "RED":
                ok = False
        elif ok and self._cap_report is None:
            ok = False
        # Don't enable Start while a worker is running.
        if self._worker is not None and getattr(self._worker, "isRunning", lambda: False)():
            ok = False
        self.start_button.setEnabled(ok)

    def _build_job_spec(self) -> dict:
        """Gather all UI state into a worker-friendly dict.

        Worker contract (per D2 prompt — keep loose; the worker normalizes):
            input_path, output_path, mode ("intensity"|"intensity_lambertian"|
            "normal_as_color"|"clone"), intensity_range, brightness,
            voxel_size, shading_mode, light_dir (xyz tuple), ambient,
            ground_color, sky_color, invert_globally.
        """
        # Convert azimuth/elevation to a unit XYZ vector. Convention:
        # azimuth around world Z (counter-clockwise from +X), elevation
        # above the XY plane.
        import math
        az = math.radians(self.light_azimuth_spin.value())
        el = math.radians(self.light_elevation_spin.value())
        ce = math.cos(el)
        light_dir = (
            math.cos(az) * ce,
            math.sin(az) * ce,
            math.sin(el),
        )

        ground = self.ground_picker_button.property("rgb") or (60, 40, 30)
        sky = self.sky_picker_button.property("rgb") or (180, 210, 255)

        shading = self._selected_shading_mode()
        if shading == "none":
            mode = "bake_intensity"
        else:
            mode = "bake_normals"

        return {
            "input_path": self.input_path_edit.text().strip(),
            "output_path": self.output_path_edit.text().strip(),
            "mode": mode,
            "shading_mode": shading if shading != "none" else None,
            "intensity_range": (
                float(self.intensity_min_spin.value()),
                float(self.intensity_max_spin.value()),
            ),
            "brightness": float(self.brightness_slider.value()),
            "voxel_size": float(self.voxel_size_spin.value()),
            "light_dir": light_dir,
            "ambient": float(self.ambient_slider.value()) / 100.0,
            "ground_color": tuple(int(c) for c in ground),
            "sky_color": tuple(int(c) for c in sky),
            "up_vector": (
                float(self.up_x_spin.value()),
                float(self.up_y_spin.value()),
                float(self.up_z_spin.value()),
            ),
            "invert_globally": bool(self.invert_normals_check.isChecked()),
        }

    def _on_start(self) -> None:
        spec = self._build_job_spec()
        try:
            # Late import: lets the UI module load (and smoke-test) even
            # if D2's worker module isn't on disk yet.
            from intensity_rgb.worker import create_worker_thread
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Worker unavailable",
                f"Could not import intensity_rgb.worker: {exc}\n\n"
                "D2 worker module may not be available yet.",
            )
            return

        # Reset job UI.
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_text_label.setText("0 / 0 pts")
        self.throughput_label.setText("Throughput: —")
        self.peak_rss_label.setText("Peak RSS: —")
        self.eta_label.setText("ETA: —")
        self.voxel_quality_label.setText("Voxel quality: —")
        # Wipe the component chips from any previous run.
        self._clear_component_chips()
        self.components_group.setVisible(False)
        self._log(f"Starting job: {spec['mode']} → {spec['output_path']}")

        # Worker spec keys are slightly different from the UI dict (D2
        # contract uses "input"/"output", not "input_path"/"output_path");
        # adapt here so the rest of the file stays UI-shaped.
        worker_spec = dict(spec)
        worker_spec["input"] = spec["input_path"]
        worker_spec["output"] = spec["output_path"]

        thread, worker = create_worker_thread(worker_spec)
        self._worker_thread = thread
        self._worker = worker
        worker.progress.connect(self._on_progress)
        worker.throughput.connect(self._on_throughput)
        worker.peak_rss.connect(self._on_peak_rss)
        worker.voxel_quality.connect(self._on_voxel_quality)
        worker.eta_seconds.connect(self._on_eta)
        worker.log.connect(self._log)
        worker.finished.connect(self._on_finished)
        worker.components_info.connect(self._on_components_info)
        worker.stage.connect(self._on_stage)
        thread.start()
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

    def _on_cancel(self) -> None:
        if self._worker is None:
            return
        self._log("Cancellation requested.")
        try:
            self._worker.cancel()
        except Exception as exc:  # pragma: no cover - defensive
            self._log(f"Worker cancel raised: {exc}")

    # ------------------------------------------------------------------
    # Worker signal slots
    # ------------------------------------------------------------------

    def _on_progress(self, done: int, total: int) -> None:
        # Matches worker.progress = Signal(int, int) — (points_done, points_total).
        # The worker also emits a separate `stage` signal we plumb below.
        if total > 0:
            pct = max(0, min(100, int(done * 100 / total)))
            self.progress_bar.setValue(pct)
            self.progress_text_label.setText(
                f"{_format_points(done)} / {_format_points(total)} pts"
                + (f" ({self._current_stage})" if self._current_stage else "")
            )
        else:
            self.progress_text_label.setText(
                f"{_format_points(done)} pts"
                + (f" ({self._current_stage})" if self._current_stage else "")
            )

    def _on_stage(self, stage: str) -> None:
        self._current_stage = stage or ""

    def _on_components_info(self, components: list) -> None:
        """Receive top-K orientation components from the worker and
        populate the read-only chip row in the Job section.

        Each chip is a non-interactive QToolButton with text
        ``#{id}: {voxel_count} voxels`` and a tooltip describing the
        mean-normal direction. Per D3 scope decision, live per-component
        invert is V2.1; clicking the chip in V2.0 only logs a note.
        """
        self._clear_component_chips()
        if not components:
            self.components_group.setVisible(False)
            return
        for entry in components:
            try:
                cid = int(entry.get("id", 0))
                vc = int(entry.get("voxel_count", 0))
                mn = entry.get("mean_normal") or (0.0, 0.0, 0.0)
                mx, my, mz = float(mn[0]), float(mn[1]), float(mn[2])
            except Exception:
                continue
            chip = QToolButton(self.components_group)
            chip.setText(f"#{cid}: {_format_points(vc)} voxels")
            chip.setToolTip(
                f"Component #{cid}\n"
                f"voxel count: {vc:,}\n"
                f"mean normal: ({mx:+.3f}, {my:+.3f}, {mz:+.3f})\n"
                "(v2.1: click to invert this component)"
            )
            chip.setAutoRaise(True)
            # Click logs a placeholder. V2.1 will wire single-component invert.
            chip.clicked.connect(
                lambda _checked=False, _c=cid: self._log(
                    f"Per-component invert is a V2.1 feature (component #{_c})."
                )
            )
            # Insert before the trailing stretch so chips left-align.
            self._components_layout.insertWidget(
                self._components_layout.count() - 1, chip
            )
            self._component_chips.append(chip)
        self.components_group.setVisible(True)

    def _clear_component_chips(self) -> None:
        """Remove and delete every chip currently in the components row."""
        for chip in self._component_chips:
            try:
                self._components_layout.removeWidget(chip)
                chip.deleteLater()
            except Exception:
                pass
        self._component_chips = []

    def _on_throughput(self, pts_per_sec: float) -> None:
        if pts_per_sec and pts_per_sec > 0:
            self.throughput_label.setText(
                f"Throughput: {_format_points(int(pts_per_sec))} pts/s"
            )
        else:
            self.throughput_label.setText("Throughput: —")

    def _on_peak_rss(self, bytes_used: int) -> None:
        if bytes_used and bytes_used > 0:
            self.peak_rss_label.setText(f"Peak RSS: {_format_bytes(bytes_used)}")
        else:
            self.peak_rss_label.setText("Peak RSS: —")

    def _on_voxel_quality(self, fraction: float) -> None:
        if fraction is None:
            self.voxel_quality_label.setText("Voxel quality: —")
        else:
            self.voxel_quality_label.setText(
                f"Voxel quality: {fraction * 100:.1f}% valid"
            )

    def _on_eta(self, seconds: float) -> None:
        if seconds is None or seconds < 0:
            self.eta_label.setText("ETA: —")
        else:
            self.eta_label.setText(f"ETA: {_format_duration(seconds)}")

    def _on_finished(self, ok: bool, message: str) -> None:
        self.cancel_button.setEnabled(False)
        self._update_start_enabled()
        if ok:
            self._log(f"Job finished: {message}")
        else:
            self._log(f"Job failed: {message}")
            QMessageBox.warning(self, "Job failed", message)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, line: str) -> None:
        self.log_widget.append(line)
        cursor = self.log_widget.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_widget.setTextCursor(cursor)

    # ------------------------------------------------------------------
    # Public path helpers (used by tests & external callers)
    # ------------------------------------------------------------------

    def set_output_path(self, path: str) -> None:
        """Programmatically set the output path. Used by tests and the
        QSettings restore path; mirrors :meth:`set_input_path` for
        symmetry.
        """
        self.output_path_edit.setText(path)

    def input_path_text(self) -> str:
        return self.input_path_edit.text()

    def output_path_text(self) -> str:
        return self.output_path_edit.text()

    # ------------------------------------------------------------------
    # QSettings persistence (per Wave 4 / D3)
    # ------------------------------------------------------------------

    def _qsettings(self) -> QSettings:
        """Return the per-window QSettings.

        Uses :meth:`QSettings.defaultFormat` so a test fixture can swap
        the backend to ``IniFormat`` and redirect storage via
        :meth:`QSettings.setPath` without our code needing to know.
        """
        return QSettings(
            QSettings.defaultFormat(),
            QSettings.UserScope,
            QSETTINGS_ORG,
            QSETTINGS_APP,
        )

    def _save_settings(self) -> None:
        """Persist window + bake settings to QSettings.

        Keys live under two namespaces: ``window/*`` for layout and
        ``paths/*`` + ``bake/*`` for everything the user adjusts before
        pressing Start. Tolerant of widgets being torn down mid-close.
        """
        try:
            s = self._qsettings()
            s.setValue("window/geometry", self.saveGeometry())
            s.setValue("window/state", self.saveState())
            s.setValue("paths/last_input", self.input_path_edit.text())
            s.setValue("paths/last_output", self.output_path_edit.text())
            s.setValue(
                "bake/intensity_range_min",
                float(self.intensity_min_spin.value()),
            )
            s.setValue(
                "bake/intensity_range_max",
                float(self.intensity_max_spin.value()),
            )
            s.setValue("bake/brightness", int(self.brightness_slider.value()))
            s.setValue("bake/shading_mode", str(self._selected_shading_mode()))
            s.setValue("bake/voxel_size", float(self.voxel_size_spin.value()))
            s.setValue(
                "bake/light_azimuth",
                float(self.light_azimuth_spin.value()),
            )
            s.setValue(
                "bake/light_elevation",
                float(self.light_elevation_spin.value()),
            )
            s.setValue(
                "bake/ambient",
                float(self.ambient_slider.value()) / 100.0,
            )
            ground = self.ground_picker_button.property("rgb") or (60, 40, 30)
            sky = self.sky_picker_button.property("rgb") or (180, 210, 255)
            s.setValue("bake/ground_color", QColor(*ground))
            s.setValue("bake/sky_color", QColor(*sky))
            s.setValue(
                "bake/up_vector",
                f"{self.up_x_spin.value()},{self.up_y_spin.value()},{self.up_z_spin.value()}",
            )
            s.setValue(
                "bake/invert_globally",
                bool(self.invert_normals_check.isChecked()),
            )
            s.sync()
        except Exception:  # pragma: no cover - defensive
            pass

    def _load_settings(self) -> None:
        """Restore window + bake settings from QSettings.

        Missing keys leave each widget at its default. Saved input/output
        paths that no longer exist on disk are blanked rather than
        re-displayed — matches the D3 prompt's "don't show stale path"
        requirement.
        """
        try:
            s = self._qsettings()
        except Exception:  # pragma: no cover - defensive
            return

        # Window geometry / dock state.
        geom = s.value("window/geometry")
        if isinstance(geom, (QByteArray, bytes)):
            try:
                self.restoreGeometry(QByteArray(geom))
            except Exception:
                pass
        state = s.value("window/state")
        if isinstance(state, (QByteArray, bytes)):
            try:
                self.restoreState(QByteArray(state))
            except Exception:
                pass

        # Paths — validate existence before restoring.
        last_in = s.value("paths/last_input", "")
        if isinstance(last_in, str) and last_in and os.path.isfile(last_in):
            self.input_path_edit.setText(last_in)
        # else: leave blank (don't restore stale paths)

        last_out = s.value("paths/last_output", "")
        if isinstance(last_out, str) and last_out:
            # Output is a file we're about to write — validate by checking
            # the *parent directory* exists. If the dir is gone, blank it.
            parent = os.path.dirname(last_out) or "."
            if os.path.isdir(parent):
                self.output_path_edit.setText(last_out)

        # Bake settings — each guarded individually so a corrupted value
        # for one key doesn't take out the rest.
        def _f(key: str, default: float) -> float:
            v = s.value(key, default)
            try:
                return float(v)
            except (TypeError, ValueError):
                return float(default)

        def _i(key: str, default: int) -> int:
            v = s.value(key, default)
            try:
                return int(v)
            except (TypeError, ValueError):
                return int(default)

        def _b(key: str, default: bool) -> bool:
            v = s.value(key, default)
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.lower() in ("1", "true", "yes", "on")
            try:
                return bool(int(v))
            except (TypeError, ValueError):
                return default

        self.intensity_min_spin.setValue(_f("bake/intensity_range_min", 0.0))
        self.intensity_max_spin.setValue(_f("bake/intensity_range_max", 4096.0))
        self.brightness_slider.setValue(_i("bake/brightness", 70))

        shading = s.value("bake/shading_mode", "lambertian")
        if shading == "none":
            self.shade_none_radio.setChecked(True)
        elif shading == "lambertian":
            self.shade_lambertian_radio.setChecked(True)
        elif shading == "three_point":
            self.shade_three_pt_radio.setChecked(True)
        elif shading == "normal_as_color":
            self.shade_normal_radio.setChecked(True)

        self.voxel_size_spin.setValue(_f("bake/voxel_size", 0.5))
        self.light_azimuth_spin.setValue(_f("bake/light_azimuth", 135.0))
        self.light_elevation_spin.setValue(_f("bake/light_elevation", 45.0))
        self.ambient_slider.setValue(int(round(_f("bake/ambient", 0.30) * 100)))

        ground = s.value("bake/ground_color")
        if isinstance(ground, QColor) and ground.isValid():
            rgb = (ground.red(), ground.green(), ground.blue())
            self.ground_picker_button.setText(f"({rgb[0]},{rgb[1]},{rgb[2]})")
            self.ground_picker_button.setProperty("rgb", rgb)
        sky = s.value("bake/sky_color")
        if isinstance(sky, QColor) and sky.isValid():
            rgb = (sky.red(), sky.green(), sky.blue())
            self.sky_picker_button.setText(f"({rgb[0]},{rgb[1]},{rgb[2]})")
            self.sky_picker_button.setProperty("rgb", rgb)

        up_str = s.value("bake/up_vector", "")
        if isinstance(up_str, str) and up_str:
            try:
                ux, uy, uz = [float(x) for x in up_str.split(",")]
                self.up_x_spin.setValue(ux)
                self.up_y_spin.setValue(uy)
                self.up_z_spin.setValue(uz)
            except (ValueError, TypeError):
                pass

        self.invert_normals_check.setChecked(_b("bake/invert_globally", False))

    def closeEvent(self, event) -> None:
        """Persist QSettings on every window close."""
        self._save_settings()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Number formatting
# ---------------------------------------------------------------------------


def _format_points(n: int) -> str:
    n = int(n)
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _format_bytes(n: int) -> str:
    n = int(n)
    for unit, scale in (("GiB", 1024 ** 3), ("MiB", 1024 ** 2), ("KiB", 1024)):
        if n >= scale:
            return f"{n / scale:.2f} {unit}"
    return f"{n} B"


def _format_duration(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[list] = None) -> int:
    """Launch the desktop UI. Returns the Qt event-loop exit code."""
    if argv is None:
        argv = sys.argv

    app = QApplication.instance()
    created_app = False
    if app is None:
        app = QApplication(argv)
        created_app = True

    _apply_fusion_dark_palette(app)

    try:
        window = MainWindow()
        window.show()
    except Exception:
        traceback.print_exc()
        return 3

    if created_app:
        return int(app.exec())
    return 0


if __name__ == "__main__":
    sys.exit(main())
