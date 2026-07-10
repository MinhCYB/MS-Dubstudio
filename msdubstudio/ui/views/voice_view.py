"""
ui/views/voice_view.py — Voice Workspace

Theo mockup 06-voice-workspace.png:
- Bên trái: Speakers list + Add Speaker
- Giữa: Voice Settings (engine/voice/speed/pitch/volume/emotion) + Generate TTS
- Bên phải: Voice Preview + Speaker Mapping table
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from msdubstudio.ui.main_window import MainWindow

from msdubstudio.core.tts import DEFAULT_FEMALE_VOICE, DEFAULT_MALE_VOICE
from msdubstudio.ui.widgets.speaker_avatar import SpeakerAvatar
from msdubstudio.ui.widgets.waveform_widget import WaveformWidget


class VoiceView(QWidget):
    """Voice Workspace — speaker mapping, voice settings, TTS generation."""

    def __init__(self, main_window: "MainWindow") -> None:
        super().__init__()
        self._mw = main_window
        self._selected_speaker: Optional[str] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        # ---- Left: Speakers ----
        left = QWidget()
        left.setFixedWidth(200)
        left.setStyleSheet("background: #F9F9F9; border-right: 1px solid #E0E0E0;")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 16, 12, 16)
        left_layout.setSpacing(8)

        lbl_spk = QLabel("Speakers")
        lbl_spk.setStyleSheet("font-size: 14px; font-weight: 600;")
        left_layout.addWidget(lbl_spk)

        btn_add = QPushButton("＋  Add Speaker")
        btn_add.setFixedHeight(28)
        btn_add.setStyleSheet(
            "background: white; border: 1px dashed #0078D4;"
            "border-radius: 6px; color: #0078D4; font-size: 12px;"
        )
        btn_add.clicked.connect(self._on_add_speaker)
        left_layout.addWidget(btn_add)

        self._speaker_list = QListWidget()
        self._speaker_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; }"
            "QListWidget::item { border-radius: 6px; padding: 4px; }"
            "QListWidget::item:selected { background: #DCEEFB; }"
        )
        self._speaker_list.itemClicked.connect(self._on_speaker_selected)
        left_layout.addWidget(self._speaker_list)

        splitter.addWidget(left)

        # ---- Center: Voice Settings ----
        center = QWidget()
        center.setStyleSheet("background: #FFFFFF;")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(20, 20, 20, 20)
        center_layout.setSpacing(16)

        self._lbl_settings_title = QLabel("Voice Settings (Speaker A)")
        self._lbl_settings_title.setStyleSheet("font-size: 15px; font-weight: 600;")
        center_layout.addWidget(self._lbl_settings_title)

        grp = QGroupBox()
        grp.setStyleSheet(
            "QGroupBox { background: white; border: 1px solid #E0E0E0;"
            "border-radius: 8px; padding: 16px; }"
        )
        form = QFormLayout(grp)
        form.setSpacing(12)

        self._cmb_engine = QComboBox()
        self._cmb_engine.addItems(["Edge TTS", "Coqui TTS", "ElevenLabs"])
        self._cmb_engine.setCurrentText("Edge TTS")

        self._cmb_voice = QComboBox()
        self._cmb_voice.addItems([
            "vi-VN-NamMinhNeural (Male)",
            "vi-VN-HoaiMyNeural (Female)",
            "vi-VN-DucAnh-custom",
        ])

        self._sl_speed = QSlider(Qt.Orientation.Horizontal)
        self._sl_speed.setRange(-50, 100)
        self._sl_speed.setValue(0)
        self._lbl_speed_val = QLabel("0%")
        self._sl_speed.valueChanged.connect(
            lambda v: self._lbl_speed_val.setText(f"{v:+}%")
        )
        speed_row = QHBoxLayout()
        speed_row.addWidget(self._sl_speed)
        speed_row.addWidget(self._lbl_speed_val)

        self._sl_pitch = QSlider(Qt.Orientation.Horizontal)
        self._sl_pitch.setRange(-50, 50)
        self._sl_pitch.setValue(0)
        self._lbl_pitch_val = QLabel("0%")
        self._sl_pitch.valueChanged.connect(
            lambda v: self._lbl_pitch_val.setText(f"{v:+}%")
        )
        pitch_row = QHBoxLayout()
        pitch_row.addWidget(self._sl_pitch)
        pitch_row.addWidget(self._lbl_pitch_val)

        self._sl_volume = QSlider(Qt.Orientation.Horizontal)
        self._sl_volume.setRange(0, 200)
        self._sl_volume.setValue(100)
        self._lbl_vol_val = QLabel("100%")
        self._sl_volume.valueChanged.connect(
            lambda v: self._lbl_vol_val.setText(f"{v}%")
        )
        vol_row = QHBoxLayout()
        vol_row.addWidget(self._sl_volume)
        vol_row.addWidget(self._lbl_vol_val)

        self._cmb_emotion = QComboBox()
        self._cmb_emotion.addItems(["Neutral", "Cheerful", "Sad", "Angry", "Surprised"])

        form.addRow("Voice Engine:", self._cmb_engine)
        form.addRow("Voice:", self._cmb_voice)
        form.addRow("Speed:", speed_row)
        form.addRow("Pitch:", pitch_row)
        form.addRow("Volume:", vol_row)
        form.addRow("Emotion:", self._cmb_emotion)
        center_layout.addWidget(grp)

        # Buttons
        btn_row = QHBoxLayout()
        self._btn_preview = QPushButton("🔉  Preview Speaker")
        self._btn_preview.setFixedHeight(36)
        self._btn_preview.setStyleSheet(
            "background: white; border: 1px solid #0078D4; border-radius: 6px;"
            "color: #0078D4; font-size: 13px; padding: 0 12px;"
        )
        self._btn_preview.clicked.connect(self._on_preview)

        self._btn_test = QPushButton("🎵  Test Current Line")
        self._btn_test.setFixedHeight(36)
        self._btn_test.setStyleSheet(
            "background: white; border: 1px solid #CCCCCC; border-radius: 6px;"
            "color: #1C1C1C; font-size: 13px; padding: 0 12px;"
        )
        btn_row.addWidget(self._btn_preview)
        btn_row.addWidget(self._btn_test)
        btn_row.addStretch()
        center_layout.addLayout(btn_row)
        center_layout.addStretch()

        # Generate TTS
        self._btn_tts = QPushButton("Generate TTS")
        self._btn_tts.setFixedHeight(40)
        self._btn_tts.setEnabled(False)
        self._btn_tts.setStyleSheet(
            "QPushButton { background: #0078D4; color: white; border-radius: 6px;"
            "font-size: 14px; font-weight: 600; border: none; }"
            "QPushButton:disabled { background: #B3D4EF; }"
            "QPushButton:hover { background: #106EBE; }"
        )
        self._btn_tts.clicked.connect(self._on_generate_tts)
        center_layout.addWidget(self._btn_tts)

        splitter.addWidget(center)

        # ---- Right: Voice Preview + Mapping ----
        right = QWidget()
        right.setFixedWidth(280)
        right.setStyleSheet("background: #F9F9F9; border-left: 1px solid #E0E0E0;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 16, 12, 16)
        right_layout.setSpacing(12)

        grp_preview = QGroupBox("Voice Preview (Current Line)")
        preview_layout = QVBoxLayout(grp_preview)
        self._lbl_preview_text = QLabel("Select a segment to preview")
        self._lbl_preview_text.setWordWrap(True)
        self._lbl_preview_text.setStyleSheet("font-size: 13px; color: #5A5A5A;")
        self._preview_wave = WaveformWidget()
        self._preview_wave.setFixedHeight(50)
        preview_layout.addWidget(self._lbl_preview_text)
        preview_layout.addWidget(self._preview_wave)
        right_layout.addWidget(grp_preview)

        # Speaker Mapping
        grp_map = QGroupBox("Speaker Mapping (Auto)")
        map_layout = QVBoxLayout(grp_map)
        self._lbl_mapping = QLabel("No speakers yet")
        self._lbl_mapping.setStyleSheet("font-size: 12px; color: #ABABAB;")
        map_layout.addWidget(self._lbl_mapping)
        right_layout.addWidget(grp_map)

        right_layout.addStretch()
        splitter.addWidget(right)
        splitter.setSizes([200, 560, 280])

        root.addWidget(splitter)

    # ------------------------------------------------------------------
    # on_activated
    # ------------------------------------------------------------------

    def on_activated(self) -> None:
        project = self._mw.project
        if not project:
            return
        self._refresh_speakers()
        from msdubstudio.core.models import StepStatus
        translate_ok = (
            project.data.pipeline_status.translate == StepStatus.COMPLETED
        )
        self._btn_tts.setEnabled(translate_ok)

    def _refresh_speakers(self) -> None:
        self._speaker_list.clear()
        project = self._mw.project
        if not project:
            return
        speakers = list(project.data.speakers.values())
        if not speakers:
            # Auto-detect từ segments
            speaker_ids = sorted(
                set(s.speaker for s in project.data.segments if s.speaker)
            )
            for sid in speaker_ids:
                self._add_speaker_item(sid)
        else:
            for sp in speakers:
                self._add_speaker_item(sp.id, sp.name)

    def _add_speaker_item(self, speaker_id: str, name: Optional[str] = None) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, speaker_id)
        widget = SpeakerAvatar(speaker_id, name, size=32)
        item.setSizeHint(widget.sizeHint())
        self._speaker_list.addItem(item)
        self._speaker_list.setItemWidget(item, widget)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_speaker_selected(self, item: QListWidgetItem) -> None:
        speaker_id = item.data(Qt.ItemDataRole.UserRole)
        self._selected_speaker = speaker_id
        self._lbl_settings_title.setText(f"Voice Settings (Speaker {speaker_id})")

    def _on_add_speaker(self) -> None:
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Add Speaker", "Speaker ID (A-Z):")
        if ok and name.strip():
            self._add_speaker_item(name.strip().upper())

    def _on_preview(self) -> None:
        """Tổng hợp + phát âm mẫu."""
        voice_id = DEFAULT_MALE_VOICE  # TODO: lấy từ current selection
        try:
            import asyncio, edge_tts, tempfile, os
            text = "Xin chào, đây là giọng đọc mẫu."
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp = f.name

            async def _synth():
                comm = edge_tts.Communicate(text, voice_id)
                await comm.save(tmp)

            asyncio.run(_synth())
            self._preview_wave.load_audio(tmp)
            self._lbl_preview_text.setText(text)
        except Exception as e:
            self._lbl_preview_text.setText(f"Preview error: {e}")

    def _on_generate_tts(self) -> None:
        project = self._mw.project
        if not project:
            return

        from msdubstudio.workers.tts_worker import TTSWorker
        speakers = project.data.speakers

        worker = TTSWorker(
            segments=project.data.segments,
            speakers=speakers,
            voice_dir=str(project.project_dir / "audio" / "voices"),
            settings=project.data.settings,
        )
        self._mw.set_active_worker(worker)

        worker.step_log.connect(lambda msg: self._lbl_preview_text.setText(msg))
        worker.finished.connect(self._on_tts_finished)
        worker.error.connect(lambda e: print(f"TTS Error: {e}"))
        worker.progress.connect(self._on_progress)

        project.on_voice_started()
        worker.start()

    def _on_progress(self, current: int, total: int) -> None:
        self._mw._overlay.update_progress(current, total)

    def _on_tts_finished(self) -> None:
        if self._mw.project:
            self._mw.project.on_voice_completed()
        self._btn_tts.setEnabled(True)
