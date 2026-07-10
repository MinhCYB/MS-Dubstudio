"""
ui/overlay.py — ProcessingOverlay

Widget đè lên toàn bộ cửa sổ khi STT / Translate / Voice / Export đang chạy.
Theo mockup: card trắng ở giữa, icon animated, % lớn, progress bar, elapsed/remaining, Cancel.

Chặn click-through: overlay là QWidget full-size, raise_() lên trên cùng.
"""

from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Spinner Widget (frame-based CSS animation fallback)
# ---------------------------------------------------------------------------

_STEP_LABELS = {
    "import":    ("📥", "Importing Video"),
    "stt":       ("🎙️", "Running Speech to Text (Whisper)"),
    "translate": ("🌐", "Translating with Gemini"),
    "voice":     ("🔊", "Generating Voices (TTS)"),
    "export":    ("🎬", "Rendering Video"),
}


def _format_time(seconds: float) -> str:
    """Format giây → 00:00:00."""
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


# ---------------------------------------------------------------------------
# SpinnerWidget — rotating dots
# ---------------------------------------------------------------------------

class SpinnerWidget(QWidget):
    """Đơn giản: 8 chấm tròn xoay theo vòng. Pure QPainter."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._step = 0
        self._n_dots = 8
        self._dot_r = 5
        self.setFixedSize(48, 48)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(100)  # 10fps

    def _tick(self) -> None:
        self._step = (self._step + 1) % self._n_dots
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        orbit = min(cx, cy) - self._dot_r - 2
        import math
        for i in range(self._n_dots):
            angle = 2 * math.pi * i / self._n_dots - math.pi / 2
            x = cx + orbit * math.cos(angle)
            y = cy + orbit * math.sin(angle)
            age = (i - self._step) % self._n_dots
            alpha = max(30, 255 - age * 28)
            color = QColor(0, 120, 212, alpha)
            p.setBrush(color)
            p.setPen(Qt.PenStyle.NoPen)
            r = self._dot_r * (1.0 - age * 0.08)
            p.drawEllipse(
                QPoint(int(x), int(y)),
                max(2, int(r)),
                max(2, int(r)),
            )

    def start(self) -> None:
        self._timer.start(100)

    def stop(self) -> None:
        self._timer.stop()


# ---------------------------------------------------------------------------
# ProcessingOverlay
# ---------------------------------------------------------------------------

class ProcessingOverlay(QWidget):
    """Full-screen semi-transparent overlay với card xử lý ở giữa.

    Usage:
        overlay = ProcessingOverlay(parent=main_window)
        overlay.cancelled.connect(worker.cancel)
        overlay.show_for("stt")
        overlay.update_progress(50, 100, elapsed_s=30.0, remaining_s=30.0)
        overlay.hide()
    """

    cancelled = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._start_time: float = 0.0
        self._current_step: str = ""

        self._setup_ui()
        self.hide()

        # Cập nhật elapsed mỗi giây khi đang chạy
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        # Nền mờ — vẽ bằng paintEvent
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Card container (centered)
        card_container = QWidget()
        card_container.setObjectName("overlay_bg")
        card_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        cc_layout = QVBoxLayout(card_container)
        cc_layout.setContentsMargins(0, 0, 0, 0)
        cc_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Card trắng
        self._card = QWidget()
        self._card.setObjectName("overlay_card")
        self._card.setFixedWidth(420)
        self._card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self._build_card()
        cc_layout.addWidget(self._card)
        main_layout.addWidget(card_container)

    def _build_card(self) -> None:
        layout = QVBoxLayout(self._card)
        layout.setSpacing(12)
        layout.setContentsMargins(32, 32, 32, 32)

        # Row: spinner + title
        header_row = QHBoxLayout()
        header_row.setSpacing(16)

        self._spinner = SpinnerWidget(self._card)
        header_row.addWidget(self._spinner)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self._lbl_title = QLabel("Processing…")
        self._lbl_title.setObjectName("overlay_title")
        self._lbl_subtitle = QLabel("")
        self._lbl_subtitle.setObjectName("overlay_subtitle")
        title_col.addWidget(self._lbl_title)
        title_col.addWidget(self._lbl_subtitle)
        header_row.addLayout(title_col)
        header_row.addStretch()
        layout.addLayout(header_row)

        # Percent
        self._lbl_pct = QLabel("0%")
        self._lbl_pct.setObjectName("overlay_pct")
        self._lbl_pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._lbl_pct)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setObjectName("progress_large")
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        layout.addWidget(self._progress)

        # Detail label (e.g. "312 / 512 segments")
        self._lbl_detail = QLabel("")
        self._lbl_detail.setObjectName("caption")
        self._lbl_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._lbl_detail)

        # Time row
        time_row = QHBoxLayout()
        self._lbl_elapsed = QLabel("Elapsed 00:00")
        self._lbl_elapsed.setObjectName("caption")
        self._lbl_remaining = QLabel("Remaining --:--")
        self._lbl_remaining.setObjectName("caption")
        self._lbl_remaining.setAlignment(Qt.AlignmentFlag.AlignRight)
        time_row.addWidget(self._lbl_elapsed)
        time_row.addStretch()
        time_row.addWidget(self._lbl_remaining)
        layout.addLayout(time_row)

        # Cancel button
        cancel_row = QHBoxLayout()
        cancel_row.addStretch()
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.setObjectName("btn_cancel")
        self._btn_cancel.setFixedWidth(120)
        self._btn_cancel.clicked.connect(self._on_cancel_clicked)
        cancel_row.addWidget(self._btn_cancel)
        cancel_row.addStretch()
        layout.addLayout(cancel_row)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_for(self, step: str, subtitle: str = "") -> None:
        """Hiện overlay cho bước xử lý.

        Args:
            step: "import" | "stt" | "translate" | "voice" | "export"
            subtitle: Mô tả phụ (VD: "Batch 1/5" hoặc "")
        """
        self._current_step = step
        self._start_time = time.time()

        icon, label = _STEP_LABELS.get(step, ("⚙️", step.title()))
        self._lbl_title.setText(f"{icon}  {label}")
        self._lbl_subtitle.setText(subtitle)
        self._lbl_pct.setText("0%")
        self._progress.setValue(0)
        self._lbl_detail.setText("")
        self._lbl_elapsed.setText("Elapsed 00:00")
        self._lbl_remaining.setText("Remaining --:--")
        self._btn_cancel.setEnabled(True)

        self._spinner.start()
        self._elapsed_timer.start(1000)

        # Fit to parent size
        if self.parent():
            parent = self.parent()
            if hasattr(parent, "size"):
                self.resize(parent.size())  # type: ignore[arg-type]
        self.show()
        self.raise_()

    def update_progress(
        self,
        current: int,
        total: int,
        elapsed_s: Optional[float] = None,
        remaining_s: Optional[float] = None,
        detail: str = "",
    ) -> None:
        """Cập nhật tiến độ.

        Args:
            current: Số đã xử lý.
            total: Tổng số.
            elapsed_s: Thời gian đã qua (giây). None = tự tính từ start_time.
            remaining_s: Thời gian còn lại ước tính (giây). None = tự ước tính.
            detail: Chuỗi chi tiết VD "312 / 512 segments".
        """
        pct = int(current / total * 100) if total > 0 else 0
        pct = max(0, min(100, pct))
        self._progress.setValue(pct)
        self._lbl_pct.setText(f"{pct}%")

        if detail:
            self._lbl_detail.setText(detail)
        elif total > 0:
            self._lbl_detail.setText(f"{current:,} / {total:,}")

        now = time.time()
        elapsed = elapsed_s if elapsed_s is not None else (now - self._start_time)
        self._lbl_elapsed.setText(f"Elapsed {_format_time(elapsed)}")

        if remaining_s is not None:
            self._lbl_remaining.setText(f"Remaining {_format_time(remaining_s)}")
        elif current > 0 and total > 0:
            rate = current / elapsed if elapsed > 0 else 0
            if rate > 0:
                remaining = (total - current) / rate
                self._lbl_remaining.setText(f"Remaining {_format_time(remaining)}")

    def set_cancel_enabled(self, enabled: bool) -> None:
        """Disable nút Cancel (VD khi đang wrap-up sau cancel)."""
        self._btn_cancel.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        """Vẽ nền mờ."""
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self._spinner.stop()
        self._elapsed_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # type: ignore[override]
        # Đảm bảo fit parent khi resize
        if self.parent():
            p = self.parent()
            if hasattr(p, "size"):
                self.resize(p.size())  # type: ignore[arg-type]
        super().showEvent(event)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _on_cancel_clicked(self) -> None:
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.setText("Cancelling…")
        self.cancelled.emit()

    def _tick_elapsed(self) -> None:
        """Cập nhật elapsed label mỗi giây."""
        elapsed = time.time() - self._start_time
        self._lbl_elapsed.setText(f"Elapsed {_format_time(elapsed)}")
