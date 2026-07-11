"""
ui/views/stt_view.py — STT Workspace

Theo mockup 02-stt-workspace.png:
- Bên trái: Whisper Settings panel + Start STT button
- Giữa: WaveformWidget (tabs Waveform / Live Transcript) + Segments table
- Bên phải: Segment Inspector + AI Console
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from msdubstudio.ui.main_window import MainWindow

from msdubstudio.core.models import Segment
from msdubstudio.ui.widgets.ai_console import AIConsole
from msdubstudio.ui.widgets.confidence_badge import ConfidenceBadge
from msdubstudio.ui.widgets.segment_table import COLUMNS_STT, SegmentTableView
from msdubstudio.ui.widgets.waveform_widget import WaveformWidget


class STTView(QWidget):
    """STT Workspace — Whisper settings, waveform, transcript table, segment inspector."""

    def __init__(self, main_window: "MainWindow") -> None:
        super().__init__()
        self._mw = main_window
        self._selected_segment: Optional[Segment] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        # ---- Left: Whisper Settings ----
        left = QWidget()
        left.setFixedWidth(220)
        left.setStyleSheet("background: #F9F9F9; border-right: 1px solid #E0E0E0;")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(12)

        grp = QGroupBox("Whisper Settings")
        form = QFormLayout(grp)
        form.setSpacing(8)

        self._cmb_model = QComboBox()
        self._cmb_model.addItems(["tiny", "base", "small", "medium", "large-v2", "large-v3"])
        self._cmb_model.setCurrentText("large-v3")

        self._cmb_lang = QComboBox()
        self._cmb_lang.addItems(["Chinese", "Japanese", "Korean", "Auto Detect"])
        self._cmb_lang.setCurrentText("Chinese")

        self._chk_auto_lang = QCheckBox("Auto Detect Language")
        self._chk_auto_lang.setChecked(True)

        self._cmb_task = QComboBox()
        self._cmb_task.addItems(["Transcribe", "Translate"])

        self._cmb_device = QComboBox()
        self._cmb_device.addItems(["auto", "cpu", "cuda"])

        self._cmb_compute = QComboBox()
        self._cmb_compute.addItems(["float16", "float32", "int8"])

        lbl_beam = QLabel("Beam Size")
        self._sl_beam = QSlider(Qt.Orientation.Horizontal)
        self._sl_beam.setRange(1, 10)
        self._sl_beam.setValue(5)
        self._lbl_beam_val = QLabel("5")
        self._sl_beam.valueChanged.connect(
            lambda v: self._lbl_beam_val.setText(str(v))
        )
        beam_row = QHBoxLayout()
        beam_row.addWidget(self._sl_beam)
        beam_row.addWidget(self._lbl_beam_val)

        lbl_bestof = QLabel("Best Of")
        self._sl_bestof = QSlider(Qt.Orientation.Horizontal)
        self._sl_bestof.setRange(1, 10)
        self._sl_bestof.setValue(5)
        self._lbl_bestof_val = QLabel("5")
        self._sl_bestof.valueChanged.connect(
            lambda v: self._lbl_bestof_val.setText(str(v))
        )
        bestof_row = QHBoxLayout()
        bestof_row.addWidget(self._sl_bestof)
        bestof_row.addWidget(self._lbl_bestof_val)

        self._chk_punct = QCheckBox("Detect Punctuation")
        self._chk_punct.setChecked(True)

        form.addRow("Model:", self._cmb_model)
        form.addRow("Language:", self._cmb_lang)
        form.addRow(self._chk_auto_lang)
        form.addRow("Task:", self._cmb_task)
        form.addRow("Device:", self._cmb_device)
        form.addRow("Compute Type:", self._cmb_compute)
        form.addRow(lbl_beam, beam_row)
        form.addRow(lbl_bestof, bestof_row)
        form.addRow(self._chk_punct)
        left_layout.addWidget(grp)
        left_layout.addStretch()

        self._btn_stt = QPushButton("Start STT")
        self._btn_stt.setFixedHeight(40)
        self._btn_stt.setEnabled(False)
        self._btn_stt.setStyleSheet(
            "QPushButton { background: #0078D4; color: white; border-radius: 6px;"
            "font-size: 14px; font-weight: 600; border: none; }"
            "QPushButton:disabled { background: #B3D4EF; }"
            "QPushButton:hover { background: #106EBE; }"
        )
        self._btn_stt.clicked.connect(self._on_start_stt)
        left_layout.addWidget(self._btn_stt)

        splitter.addWidget(left)

        # ---- Center: Waveform + Segment Table ----
        center = QWidget()
        center.setStyleSheet("background: #FFFFFF;")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(16, 16, 16, 16)
        center_layout.setSpacing(12)

        # Tabs: Waveform / Live Transcript
        tabs = QTabWidget()
        tabs.setFixedHeight(130)
        tabs.setStyleSheet(
            "QTabBar::tab { padding: 6px 16px; }"
            "QTabBar::tab:selected { color: #0078D4; border-bottom: 2px solid #0078D4; }"
        )

        self._waveform = WaveformWidget()
        tabs.addTab(self._waveform, "Waveform")

        self._lbl_live = QLabel("Live transcript will appear here during STT…")
        self._lbl_live.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_live.setStyleSheet("color: #ABABAB;")
        tabs.addTab(self._lbl_live, "Live Transcript")
        center_layout.addWidget(tabs)

        # Segment count label
        self._lbl_count = QLabel("Segments (0)")
        self._lbl_count.setStyleSheet("font-size: 13px; font-weight: 600;")
        center_layout.addWidget(self._lbl_count)

        # Segment Table
        self._table = SegmentTableView(columns=COLUMNS_STT, show_search=True)
        self._table.segment_selected.connect(self._on_segment_selected)
        center_layout.addWidget(self._table, stretch=1)

        splitter.addWidget(center)

        # ---- Right: Segment Inspector + AI Console ----
        right = QWidget()
        right.setFixedWidth(260)
        right.setStyleSheet("background: #F9F9F9; border-left: 1px solid #E0E0E0;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 16, 12, 16)
        right_layout.setSpacing(12)

        self._inspector = QGroupBox("Segment Inspector")
        ins_form = QFormLayout(self._inspector)
        ins_form.setSpacing(6)
        self._ins_id       = QLabel("—")
        self._ins_start    = QLabel("—")
        self._ins_end      = QLabel("—")
        self._ins_duration = QLabel("—")
        self._ins_speaker  = QLabel("—")
        self._ins_conf     = ConfidenceBadge(0.0)
        self._ins_lang     = QLabel("—")
        ins_form.addRow("Segment #:", self._ins_id)
        ins_form.addRow("Start:", self._ins_start)
        ins_form.addRow("End:", self._ins_end)
        ins_form.addRow("Duration:", self._ins_duration)
        ins_form.addRow("Speaker:", self._ins_speaker)
        ins_form.addRow("Confidence:", self._ins_conf)
        ins_form.addRow("Language:", self._ins_lang)
        right_layout.addWidget(self._inspector)

        # Audio preview mini (waveform mini)
        grp_audio = QGroupBox("Audio Preview")
        audio_layout = QVBoxLayout(grp_audio)
        self._mini_wave = WaveformWidget()
        self._mini_wave.setFixedHeight(50)
        audio_layout.addWidget(self._mini_wave)
        right_layout.addWidget(grp_audio)

        right_layout.addStretch()

        # AI Console
        self._console = AIConsole(title="AI Console")
        self._console.setFixedHeight(200)
        right_layout.addWidget(self._console)

        splitter.addWidget(right)
        splitter.setSizes([220, 640, 260])

        root.addWidget(splitter)

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def on_activated(self) -> None:
        """Gọi khi tab STT được chọn."""
        project = self._mw.project
        if project:
            segs = project.data.segments
            self._table.set_segments(segs)
            self._lbl_count.setText(f"Segments ({len(segs)})")
            self._btn_stt.setEnabled(True)

            # Load waveform nếu có audio
            audio_path = project.project_dir / "audio" / "audio.wav"
            if audio_path.exists():
                self._waveform.load_audio(str(audio_path))

    # ------------------------------------------------------------------
    # STT
    # ------------------------------------------------------------------

    def _on_start_stt(self) -> None:
        project = self._mw.project
        if not project:
            return

        from msdubstudio.workers.stt_worker import STTWorker

        settings = project.data.settings
        # Override với UI values
        settings.whisper_model = self._cmb_model.currentText()
        settings.whisper_language = (
            None if self._chk_auto_lang.isChecked()
            else self._cmb_lang.currentText().lower()
        )
        settings.whisper_task = self._cmb_task.currentText().lower()

        worker = STTWorker(
            project=project,
            audio_path=str(project.project_dir / "audio" / "audio.wav"),
        )
        self._mw.set_active_worker(worker)

        worker.step_log.connect(self._console.log)
        worker.segment_done.connect(self._on_segment_done)
        worker.finished.connect(self._on_stt_finished)
        worker.error.connect(self._on_stt_error)
        worker.progress.connect(self._on_progress)

        # Xóa bảng cũ
        self._table.set_segments([])
        self._lbl_count.setText("Segments (0)")
        self._console.log("Loading model " + settings.whisper_model + "…")

        project.on_stt_started()
        worker.start()

    def _on_progress(self, current: int, total: int) -> None:
        self._mw._overlay.update_progress(current, total)

    def _on_segment_done(self, seg_dict: dict) -> None:
        """Nhận segment từng cái từ STTWorker → append vào bảng."""
        from msdubstudio.core.models import Segment
        try:
            seg = Segment(**seg_dict)
        except Exception:
            return
        self._table.append_segment(seg)
        count = self._table.model.rowCount()
        self._lbl_count.setText(f"Segments ({count})")
        self._console.log_batch(f"Segment {seg.id}: {seg.text_zh[:40]}")

    def _on_stt_finished(self, segments: list) -> None:
        from msdubstudio.core.models import Segment as Seg
        segs = [Seg(**s) if isinstance(s, dict) else s for s in segments]
        self._mw.project.on_stt_completed(segs)
        count = len(segs)
        self._lbl_count.setText(f"Segments ({count})")
        self._console.log_success(f"{count} segments created")

    def _on_stt_error(self, msg: str) -> None:
        self._mw.project.on_stt_error(msg)
        self._console.log_error(f"STT Error: {msg}")

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_segment_selected(self, seg: Segment) -> None:
        self._selected_segment = seg
        self._ins_id.setText(str(seg.id))
        self._ins_start.setText(f"{seg.start:.3f}s")
        self._ins_end.setText(f"{seg.end:.3f}s")
        self._ins_duration.setText(f"{seg.end - seg.start:.2f}s")
        self._ins_speaker.setText(seg.speaker)
        self._ins_conf.set_score(seg.confidence)
        self._ins_lang.setText("Chinese")

        # Highlight trong waveform
        self._waveform.highlight_segment(seg.start, seg.end)
