"""
ui/widgets/speaker_avatar.py — Icon tròn + tên speaker

Widget nhỏ hiển thị avatar hình tròn với chữ cái đầu của speaker
và tên speaker bên cạnh (dùng trong voice_view / review_view).
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QFont, QPainter, QBrush, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget


# Màu avatar theo speaker ID (A→Z → cycling palette)
_AVATAR_COLORS = [
    "#0078D4",  # A — Windows Blue
    "#107C10",  # B — Green
    "#D13438",  # C — Red
    "#FF8C00",  # D — Orange
    "#881798",  # E — Purple
    "#038387",  # F — Teal
    "#C239B3",  # G — Magenta
    "#498205",  # H — Light Green
]


def _avatar_color(speaker_id: str) -> str:
    """Chọn màu avatar dựa vào speaker_id."""
    idx = ord(speaker_id[0].upper()) - ord("A") if speaker_id else 0
    return _AVATAR_COLORS[idx % len(_AVATAR_COLORS)]


# ---------------------------------------------------------------------------
# AvatarCircle — chỉ vẽ hình tròn có chữ cái
# ---------------------------------------------------------------------------

class AvatarCircle(QWidget):
    """Hình tròn có chữ cái đầu, màu theo speaker."""

    def __init__(
        self,
        speaker_id: str = "A",
        size: int = 32,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._speaker_id = speaker_id
        self.setFixedSize(size, size)
        self._size = size

    def set_speaker(self, speaker_id: str) -> None:
        self._speaker_id = speaker_id
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        color = QColor(_avatar_color(self._speaker_id))
        p.setBrush(QBrush(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(0, 0, self._size, self._size)

        # Chữ cái đầu
        letter = self._speaker_id[0].upper() if self._speaker_id else "?"
        font = QFont("Segoe UI", int(self._size * 0.38), QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QPen(QColor("#FFFFFF")))
        p.drawText(
            self.rect(),
            Qt.AlignmentFlag.AlignCenter,
            letter,
        )


# ---------------------------------------------------------------------------
# SpeakerAvatar — hình tròn + tên speaker
# ---------------------------------------------------------------------------

class SpeakerAvatar(QWidget):
    """Widget tổng hợp: avatar tròn bên trái + label tên bên phải.

    Usage:
        avatar = SpeakerAvatar("A", display_name="Speaker A")
        avatar = SpeakerAvatar("B", display_name="Narrator", size=40)
    """

    def __init__(
        self,
        speaker_id: str = "A",
        display_name: Optional[str] = None,
        size: int = 32,
        show_name: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._speaker_id = speaker_id
        self._size = size

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._circle = AvatarCircle(speaker_id, size)
        layout.addWidget(self._circle)

        if show_name:
            self._lbl = QLabel(display_name or f"Speaker {speaker_id}")
            self._lbl.setStyleSheet("font-size: 13px; color: #1C1C1C;")
            layout.addWidget(self._lbl)
            layout.addStretch()

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(size + 8)

    def set_speaker(self, speaker_id: str, display_name: Optional[str] = None) -> None:
        self._speaker_id = speaker_id
        self._circle.set_speaker(speaker_id)
        if hasattr(self, "_lbl"):
            self._lbl.setText(display_name or f"Speaker {speaker_id}")
