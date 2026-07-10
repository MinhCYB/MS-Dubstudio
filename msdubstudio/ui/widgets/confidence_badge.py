"""
ui/widgets/confidence_badge.py — Badge hiển thị mức độ tin cậy (confidence score)

Theo mockup "status confidence guide.png":
- ≥ 0.80 → xanh lá (High)   #107C10 / bg #DFF6DD
- 0.50–0.79 → vàng (Medium) #835B00 / bg #FFF4CE
- < 0.50 → đỏ (Low)         #D13438 / bg #FDE7E9

Dùng như QStyledItemDelegate trong SegmentTable để render cột Confidence.
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QLabel, QStyledItemDelegate, QStyleOptionViewItem, QWidget


# ---------------------------------------------------------------------------
# Confidence thresholds
# ---------------------------------------------------------------------------

HIGH_THRESHOLD = 0.80
MED_THRESHOLD = 0.50

# (text_color, bg_color, label)
_HIGH = (QColor("#107C10"), QColor("#DFF6DD"), "High")
_MED  = (QColor("#835B00"), QColor("#FFF4CE"), "Medium")
_LOW  = (QColor("#D13438"), QColor("#FDE7E9"), "Low")


def confidence_colors(score: float) -> tuple[QColor, QColor, str]:
    """Trả về (text_color, bg_color, level_label) theo ngưỡng."""
    if score >= HIGH_THRESHOLD:
        return _HIGH
    if score >= MED_THRESHOLD:
        return _MED
    return _LOW


# ---------------------------------------------------------------------------
# ConfidenceBadge — standalone QLabel widget (dùng trong card/inspector)
# ---------------------------------------------------------------------------

class ConfidenceBadge(QLabel):
    """Pill-shaped badge hiển thị confidence score.

    Usage:
        badge = ConfidenceBadge(0.87)
        badge.set_score(0.42)  # update
    """

    def __init__(self, score: float = 0.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(22)
        self.set_score(score)

    def set_score(self, score: float) -> None:
        self._score = score
        text_col, bg_col, label = confidence_colors(score)
        self.setText(f"{score:.2f}  {label}")
        self.setStyleSheet(
            f"background-color: {bg_col.name()};"
            f"color: {text_col.name()};"
            "border-radius: 11px;"
            "padding: 0 10px;"
            "font-size: 11px;"
            "font-weight: 600;"
        )


# ---------------------------------------------------------------------------
# ConfidenceDelegate — QStyledItemDelegate cho QTableView
# ---------------------------------------------------------------------------

class ConfidenceDelegate(QStyledItemDelegate):
    """Render cột Confidence trong SegmentTableView.

    Item data cần là float (0.0 – 1.0) hoặc string.
    """

    _PADDING_H = 8
    _PADDING_V = 3
    _RADIUS = 10

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index,
    ) -> None:
        raw = index.data(Qt.ItemDataRole.DisplayRole)
        try:
            score = float(raw)
        except (TypeError, ValueError):
            super().paint(painter, option, index)
            return

        text_col, bg_col, label = confidence_colors(score)
        text = f"{score:.2f}"

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background of cell
        if option.state & 0x0001:  # QStyle.StateFlag.State_Selected
            painter.fillRect(option.rect, QColor("#DCEEFB"))
        else:
            painter.fillRect(option.rect, QColor("#FFFFFF"))

        # Badge pill — centered in cell
        font = QFont(painter.font())
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)

        fm = painter.fontMetrics()
        text_w = fm.horizontalAdvance(text)
        badge_w = text_w + self._PADDING_H * 2
        badge_h = fm.height() + self._PADDING_V * 2

        cx = option.rect.center().x()
        cy = option.rect.center().y()
        badge_rect = QRect(
            cx - badge_w // 2,
            cy - badge_h // 2,
            badge_w,
            badge_h,
        )

        # Draw pill
        painter.setBrush(QBrush(bg_col))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, self._RADIUS, self._RADIUS)

        # Draw text
        painter.setPen(QPen(text_col))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, text)

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(90, 36)
