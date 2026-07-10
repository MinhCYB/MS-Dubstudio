"""
ui/widgets/waveform_widget.py — Waveform display với playhead và segment highlight

Render waveform từ file WAV/audio bằng numpy + QPainter.
Đồng bộ playhead với VideoPlayer qua set_position().
Click vào waveform → seek_requested signal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget


class WaveformWidget(QWidget):
    """Vẽ waveform từ audio file với playhead và segment highlight.

    Signals:
        seek_requested(float): Emit khi user click — giá trị là thời gian (giây).
    """

    seek_requested = pyqtSignal(float)

    # Visual config
    _BG_COLOR        = QColor("#F8F9FA")
    _WAVE_COLOR      = QColor("#0078D4")
    _WAVE_DIM        = QColor("#B3D4EF")
    _PLAYHEAD_COLOR  = QColor("#D13438")
    _SEG_COLOR       = QColor(0, 120, 212, 35)   # highlight segment
    _SEG_BORDER      = QColor(0, 120, 212, 100)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(80)
        self.setMinimumWidth(200)

        self._samples: list[float] = []      # normalized [-1, 1], downsampled
        self._duration_s: float = 0.0
        self._position_s: float = 0.0         # playhead vị trí hiện tại
        self._highlighted_start: float = -1.0  # segment highlight start
        self._highlighted_end: float = -1.0    # segment highlight end
        self._loaded = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_audio(self, audio_path: str) -> None:
        """Load và downsample audio để vẽ waveform.

        Nếu numpy/soundfile không có → hiện placeholder.
        """
        try:
            self._load_samples(audio_path)
            self._loaded = True
        except Exception as e:
            # Fallback: show placeholder waveform
            self._samples = []
            self._duration_s = 0.0
            self._loaded = False
        self.update()

    def set_duration(self, duration_s: float) -> None:
        """Set total duration (dùng khi không có audio file nhưng biết độ dài)."""
        self._duration_s = duration_s
        self.update()

    def set_position(self, position_s: float) -> None:
        """Cập nhật playhead (gọi từ VideoPlayer hoặc timer)."""
        self._position_s = position_s
        self.update()

    def highlight_segment(self, start_s: float, end_s: float) -> None:
        """Highlight vùng thời gian [start_s, end_s] trên waveform."""
        self._highlighted_start = start_s
        self._highlighted_end = end_s
        self.update()

    def clear_highlight(self) -> None:
        self._highlighted_start = -1.0
        self._highlighted_end = -1.0
        self.update()

    def clear(self) -> None:
        self._samples = []
        self._duration_s = 0.0
        self._position_s = 0.0
        self._loaded = False
        self.clear_highlight()

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        # Background
        p.fillRect(0, 0, w, h, self._BG_COLOR)

        if not self._loaded or not self._samples:
            self._paint_placeholder(p, w, h)
        else:
            self._paint_waveform(p, w, h)

        # Segment highlight
        if self._duration_s > 0 and self._highlighted_start >= 0:
            x1 = self._time_to_x(self._highlighted_start, w)
            x2 = self._time_to_x(self._highlighted_end, w)
            p.fillRect(
                QRectF(x1, 0, x2 - x1, h),
                self._SEG_COLOR,
            )
            p.setPen(QPen(self._SEG_BORDER, 1))
            p.drawLine(QPointF(x1, 0), QPointF(x1, h))
            p.drawLine(QPointF(x2, 0), QPointF(x2, h))

        # Playhead
        if self._duration_s > 0:
            px = self._time_to_x(self._position_s, w)
            p.setPen(QPen(self._PLAYHEAD_COLOR, 2))
            p.drawLine(QPointF(px, 0), QPointF(px, h))
            # Playhead triangle top
            tri_size = 6
            p.setBrush(self._PLAYHEAD_COLOR)
            p.setPen(Qt.PenStyle.NoPen)
            from PyQt6.QtGui import QPolygonF
            tri = QPolygonF([
                QPointF(px - tri_size, 0),
                QPointF(px + tri_size, 0),
                QPointF(px, tri_size * 1.5),
            ])
            p.drawPolygon(tri)

    def _paint_waveform(self, p: QPainter, w: int, h: int) -> None:
        cy = h / 2
        n = len(self._samples)
        if n == 0:
            return

        bar_w = max(1.0, w / n)
        playhead_x = self._time_to_x(self._position_s, w) if self._duration_s > 0 else w

        for i, amp in enumerate(self._samples):
            x = i * bar_w
            bar_h = max(2, abs(amp) * cy * 0.9)

            color = self._WAVE_COLOR if x <= playhead_x else self._WAVE_DIM
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(
                QRectF(x, cy - bar_h, max(1.0, bar_w - 1), bar_h * 2),
                1, 1,
            )

    def _paint_placeholder(self, p: QPainter, w: int, h: int) -> None:
        """Hiện waveform giả khi chưa load audio."""
        import math
        cy = h / 2
        p.setPen(QPen(QColor("#DCDCDC"), 1))
        step = max(1, w // 120)
        for x in range(0, w, step):
            amp = 0.15 + 0.35 * abs(math.sin(x * 0.08)) * abs(math.sin(x * 0.03))
            bar_h = max(2, amp * cy * 0.8)
            p.drawLine(QPointF(x, cy - bar_h), QPointF(x, cy + bar_h))

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self._duration_s > 0:
            t = self._x_to_time(event.position().x(), self.width())
            self._position_s = t
            self.update()
            self.seek_requested.emit(t)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if event.buttons() & Qt.MouseButton.LeftButton and self._duration_s > 0:
            t = self._x_to_time(event.position().x(), self.width())
            self._position_s = t
            self.update()
            self.seek_requested.emit(t)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _time_to_x(self, t: float, w: int) -> float:
        if self._duration_s <= 0:
            return 0.0
        return max(0.0, min(w, t / self._duration_s * w))

    def _x_to_time(self, x: float, w: int) -> float:
        if w <= 0 or self._duration_s <= 0:
            return 0.0
        return max(0.0, min(self._duration_s, x / w * self._duration_s))

    def _load_samples(self, audio_path: str, target_samples: int = 800) -> None:
        """Đọc audio và downsample về target_samples điểm."""
        try:
            import numpy as np
            import soundfile as sf  # type: ignore

            data, sr = sf.read(audio_path, dtype="float32", always_2d=True)
            # Mono: lấy kênh đầu tiên
            mono = data[:, 0] if data.ndim > 1 else data
            total = len(mono)
            self._duration_s = total / sr

            if total == 0:
                self._samples = []
                return

            # Downsample: tính RMS mỗi chunk
            chunk = max(1, total // target_samples)
            peaks = []
            for i in range(0, total, chunk):
                segment = mono[i : i + chunk]
                rms = float(np.sqrt(np.mean(segment ** 2)))
                peaks.append(rms)

            # Normalize
            max_val = max(peaks) if peaks else 1.0
            if max_val > 0:
                self._samples = [v / max_val for v in peaks]
            else:
                self._samples = [0.0] * len(peaks)

        except ImportError:
            # soundfile / numpy không có → placeholder
            self._samples = []
            self._duration_s = 0.0
            raise
