"""
ui/widgets/video_player.py — Video preview widget (QMediaPlayer wrapper)

Tích hợp QMediaPlayer + QVideoWidget cho preview video trong app.
Hỗ trợ: play/pause, seek, volume, tốc độ phát.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QTimer, Qt, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)


def _ms_to_str(ms: int) -> str:
    """Milliseconds → '00:00:00'"""
    s = ms // 1000
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


class VideoPlayer(QWidget):
    """Video player với controls bar.

    Signals:
        position_changed(float): Position thay đổi → giây (float).
        duration_changed(float): Duration của video → giây (float).
    """

    position_changed = pyqtSignal(float)   # giây
    duration_changed = pyqtSignal(float)   # giây

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._duration_ms: int = 0
        self._dragging_slider: bool = False

        self._setup_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Video widget
        self._video = QVideoWidget()
        self._video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._video.setStyleSheet("background-color: #000000;")
        layout.addWidget(self._video)

        # Controls row
        controls = QWidget()
        controls.setStyleSheet("background-color: #F3F3F3; border-top: 1px solid #E0E0E0;")
        ctrl_layout = QHBoxLayout(controls)
        ctrl_layout.setContentsMargins(8, 4, 8, 4)
        ctrl_layout.setSpacing(8)

        # Play/Pause button
        self._btn_play = QPushButton("▶")
        self._btn_play.setFixedSize(28, 28)
        self._btn_play.setStyleSheet(
            "background: #0078D4; color: white; border-radius: 14px; font-size: 11px;"
        )
        ctrl_layout.addWidget(self._btn_play)

        # Position label
        self._lbl_pos = QLabel("00:00:00")
        self._lbl_pos.setFixedWidth(64)
        self._lbl_pos.setStyleSheet("font-size: 12px; color: #5A5A5A;")
        ctrl_layout.addWidget(self._lbl_pos)

        # Seek slider
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 1000)
        self._slider.setValue(0)
        ctrl_layout.addWidget(self._slider, stretch=1)

        # Duration label
        self._lbl_dur = QLabel("00:00:00")
        self._lbl_dur.setFixedWidth(64)
        self._lbl_dur.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._lbl_dur.setStyleSheet("font-size: 12px; color: #5A5A5A;")
        ctrl_layout.addWidget(self._lbl_dur)

        # Volume icon + slider
        lbl_vol = QLabel("🔊")
        lbl_vol.setFixedWidth(20)
        ctrl_layout.addWidget(lbl_vol)

        self._vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(80)
        self._vol_slider.setFixedWidth(72)
        ctrl_layout.addWidget(self._vol_slider)

        layout.addWidget(controls)

        # QMediaPlayer
        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)
        self._player.setVideoOutput(self._video)
        self._audio_output.setVolume(0.8)

    def _connect_signals(self) -> None:
        self._btn_play.clicked.connect(self._toggle_play)
        self._player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._slider.sliderPressed.connect(lambda: setattr(self, "_dragging_slider", True))
        self._slider.sliderReleased.connect(self._on_slider_released)
        self._vol_slider.valueChanged.connect(
            lambda v: self._audio_output.setVolume(v / 100.0)
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_video(self, video_path: str) -> None:
        """Load video file."""
        url = QUrl.fromLocalFile(str(Path(video_path).resolve()))
        self._player.setSource(url)

    def seek(self, position_s: float) -> None:
        """Seek đến vị trí (giây)."""
        if self._duration_ms > 0:
            ms = int(position_s * 1000)
            self._player.setPosition(ms)

    def play(self) -> None:
        self._player.play()

    def pause(self) -> None:
        self._player.pause()

    def stop(self) -> None:
        self._player.stop()

    def set_volume(self, volume: float) -> None:
        """Volume 0.0 – 1.0."""
        self._audio_output.setVolume(max(0.0, min(1.0, volume)))

    # ------------------------------------------------------------------
    # Private slots
    # ------------------------------------------------------------------

    def _toggle_play(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._btn_play.setText("⏸")
        else:
            self._btn_play.setText("▶")

    def _on_position_changed(self, ms: int) -> None:
        if not self._dragging_slider and self._duration_ms > 0:
            pct = int(ms / self._duration_ms * 1000)
            self._slider.setValue(pct)
        self._lbl_pos.setText(_ms_to_str(ms))
        self.position_changed.emit(ms / 1000.0)

    def _on_duration_changed(self, ms: int) -> None:
        self._duration_ms = ms
        self._lbl_dur.setText(_ms_to_str(ms))
        self.duration_changed.emit(ms / 1000.0)

    def _on_slider_released(self) -> None:
        self._dragging_slider = False
        if self._duration_ms > 0:
            pct = self._slider.value() / 1000.0
            ms = int(pct * self._duration_ms)
            self._player.setPosition(ms)
