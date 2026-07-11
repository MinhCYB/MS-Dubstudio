"""
ui/views/export_view.py — Export Workspace

Theo mockup 07-export-workspace.png:
- Bên trái: Export Settings (format, resolution, fps, audio, checkboxes)
- Giữa: Video Preview
- Bên phải: Export Info (size, time) + Render Progress
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from msdubstudio.ui.main_window import MainWindow

from msdubstudio.core.render import ExportSettings
from msdubstudio.ui.widgets.video_player import VideoPlayer


class ExportView(QWidget):
    """Export Workspace — settings, preview, render progress."""

    def __init__(self, main_window: "MainWindow") -> None:
        super().__init__()
        self._mw = main_window
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        # ---- Left: Export Settings ----
        left = QWidget()
        left.setFixedWidth(220)
        left.setStyleSheet("background: #F9F9F9; border-right: 1px solid #E0E0E0;")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(12)

        grp = QGroupBox("Export Settings")
        form = QFormLayout(grp)
        form.setSpacing(8)

        self._cmb_format = QComboBox()
        self._cmb_format.addItems(["MP4 (H.264)", "MKV (H.264)", "MOV (H.264)", "MP4 (H.265)"])

        self._cmb_resolution = QComboBox()
        self._cmb_resolution.addItems([
            "1920 × 1080 (Original)",
            "1280 × 720",
            "3840 × 2160 (4K)",
        ])

        self._cmb_fps = QComboBox()
        self._cmb_fps.addItems(["30 fps", "25 fps", "24 fps", "60 fps"])

        self._cmb_audio = QComboBox()
        self._cmb_audio.addItems(["AAC", "MP3", "FLAC", "Opus"])

        self._chk_subs   = QCheckBox("Burn subtitles into video")
        self._chk_bgm    = QCheckBox("Keep original background music")
        self._chk_norm   = QCheckBox("Normalize audio  −14 LUFS")
        self._chk_bgm.setChecked(True)
        self._chk_norm.setChecked(True)

        form.addRow("Format:", self._cmb_format)
        form.addRow("Resolution:", self._cmb_resolution)
        form.addRow("Frame Rate:", self._cmb_fps)
        form.addRow("Audio Codec:", self._cmb_audio)
        form.addRow(self._chk_subs)
        form.addRow(self._chk_bgm)
        form.addRow(self._chk_norm)
        left_layout.addWidget(grp)
        left_layout.addStretch()

        self._btn_export = QPushButton("Start Export")
        self._btn_export.setFixedHeight(40)
        self._btn_export.setEnabled(False)
        self._btn_export.setStyleSheet(
            "QPushButton { background: #0078D4; color: white; border-radius: 6px;"
            "font-size: 14px; font-weight: 600; border: none; }"
            "QPushButton:disabled { background: #B3D4EF; }"
            "QPushButton:hover { background: #106EBE; }"
        )
        self._btn_export.clicked.connect(self._on_start_export)
        left_layout.addWidget(self._btn_export)

        splitter.addWidget(left)

        # ---- Center: Video Preview ----
        center = QWidget()
        center.setStyleSheet("background: #FFFFFF;")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(20, 20, 20, 20)
        center_layout.setSpacing(12)

        lbl_preview = QLabel("Preview")
        lbl_preview.setStyleSheet("font-size: 15px; font-weight: 600;")
        center_layout.addWidget(lbl_preview)

        self._player = VideoPlayer()
        center_layout.addWidget(self._player, stretch=1)

        splitter.addWidget(center)

        # ---- Right: Export Info + Render Progress ----
        right = QWidget()
        right.setFixedWidth(260)
        right.setStyleSheet("background: #F9F9F9; border-left: 1px solid #E0E0E0;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 20, 16, 20)
        right_layout.setSpacing(16)

        # Export Info
        grp_info = QGroupBox("Export Info")
        info_form = QFormLayout(grp_info)
        info_form.setSpacing(8)
        self._lbl_size  = QLabel("—")
        self._lbl_etime = QLabel("—")
        info_form.addRow("Estimated Size:", self._lbl_size)
        info_form.addRow("Estimated Time:", self._lbl_etime)
        right_layout.addWidget(grp_info)

        # Render Progress
        grp_prog = QGroupBox("Render Progress")
        prog_layout = QVBoxLayout(grp_prog)
        self._lbl_render_status = QLabel("Preparing…")
        self._lbl_render_status.setStyleSheet("color: #5A5A5A; font-size: 12px;")
        prog_layout.addWidget(self._lbl_render_status)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(8)
        prog_layout.addWidget(self._progress)

        time_row = QHBoxLayout()
        self._lbl_elapsed   = QLabel("Elapsed  00:00:00")
        self._lbl_remaining = QLabel("Remaining  --:--:--")
        self._lbl_elapsed.setStyleSheet("font-size: 11px; color: #5A5A5A;")
        self._lbl_remaining.setStyleSheet("font-size: 11px; color: #5A5A5A;")
        self._lbl_remaining.setAlignment(Qt.AlignmentFlag.AlignRight)
        time_row.addWidget(self._lbl_elapsed)
        time_row.addStretch()
        time_row.addWidget(self._lbl_remaining)
        prog_layout.addLayout(time_row)

        right_layout.addWidget(grp_prog)
        right_layout.addStretch()
        splitter.addWidget(right)

        splitter.setSizes([220, 600, 260])
        root.addWidget(splitter)

    # ------------------------------------------------------------------
    # on_activated
    # ------------------------------------------------------------------

    def on_activated(self) -> None:
        project = self._mw.project
        if not project:
            return

        video_path = project.data.video_path
        if video_path and __import__("pathlib").Path(video_path).exists():
            self._player.load_video(video_path)

        from msdubstudio.core.models import StepStatus
        voice_ok = project.data.pipeline_status.voice == StepStatus.COMPLETED
        self._btn_export.setEnabled(voice_ok)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _on_start_export(self) -> None:
        project = self._mw.project
        if not project:
            return

        from PyQt6.QtWidgets import QFileDialog
        from pathlib import Path

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Export",
            str(project.project_dir / "output" / "final" / "output.mp4"),
            "MP4 Video (*.mp4);;MKV Video (*.mkv)",
        )
        if not output_path:
            return

        settings = ExportSettings(
            output_path=output_path,
            video_codec="libx264",
            keep_bgm=self._chk_bgm.isChecked(),
            burn_subtitles=self._chk_subs.isChecked(),
            normalize_audio=self._chk_norm.isChecked(),
        )

        from msdubstudio.workers.render_worker import RenderWorker
        worker = RenderWorker(
            project=project,
            export_settings=settings,
        )
        self._mw.set_active_worker(worker)

        worker.step_log.connect(self._on_step_log)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_render_finished)
        worker.error.connect(self._on_render_error)

        project.on_export_started()
        worker.start()

    def _on_step_log(self, msg: str) -> None:
        self._lbl_render_status.setText(msg)

    def _on_progress(self, current: int, total: int) -> None:
        pct = int(current / total * 100) if total > 0 else 0
        self._progress.setValue(pct)
        self._mw._overlay.update_progress(current, total)

    def _on_render_finished(self, output_path: str) -> None:
        self._mw.project.on_export_completed()
        self._lbl_render_status.setText(f"✓ Export complete: {output_path}")
        self._progress.setValue(100)
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "Export Complete",
            f"Video exported successfully!\n\n{output_path}"
        )

    def _on_render_error(self, msg: str) -> None:
        self._mw.project.on_export_error(msg)
        self._lbl_render_status.setText(f"✕ Error: {msg}")
