"""
ui/widgets/ai_console.py — AI Console log panel

Hiển thị log theo thời gian thực (batch progress, API calls, errors).
Theo mockup: dark panel, monospace font, auto-scroll, Clear button.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Log level colors (trong dark console)
# ---------------------------------------------------------------------------

_COLORS = {
    "info":    "#CDD6F4",   # catppuccin text
    "success": "#A6E3A1",   # catppuccin green
    "warning": "#F9E2AF",   # catppuccin yellow
    "error":   "#F38BA8",   # catppuccin red
    "batch":   "#89DCEB",   # catppuccin sky
    "dim":     "#6C7086",   # catppuccin overlay0
}


class AIConsole(QWidget):
    """Dark log panel với auto-scroll và Clear button.

    Usage:
        console = AIConsole(title="AI Console")
        console.log("Starting translation…")
        console.log_success("Batch 1/5 done (15 segments)")
        console.log_error("Error: 429 Rate Limit")
        console.clear()
    """

    def __init__(
        self,
        title: str = "AI Console",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ai_console")
        self._setup_ui(title)

    def _setup_ui(self, title: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header bar
        header = QWidget()
        header.setObjectName("console_header")
        header.setFixedHeight(32)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 0, 8, 0)

        lbl = QLabel(title)
        lbl.setObjectName("console_header")
        lbl.setStyleSheet("color: #A6ADC8; font-size: 11px; font-weight: 600; background: transparent;")
        header_layout.addWidget(lbl)
        header_layout.addStretch()

        btn_clear = QPushButton("Clear")
        btn_clear.setFixedSize(48, 22)
        btn_clear.setStyleSheet(
            "background: #313244; border: none; border-radius: 4px;"
            "color: #A6ADC8; font-size: 11px;"
        )
        btn_clear.clicked.connect(self.clear)
        header_layout.addWidget(btn_clear)

        layout.addWidget(header)

        # Log area
        self._edit = QPlainTextEdit()
        self._edit.setReadOnly(True)
        self._edit.setObjectName("console_text")
        self._edit.setStyleSheet(
            "background-color: #1E1E2E; color: #CDD6F4; border: none;"
            "font-family: 'Cascadia Code', 'Consolas', 'JetBrains Mono', monospace;"
            "font-size: 12px; padding: 8px;"
        )
        self._edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self._edit)

        # Outer border
        self.setStyleSheet(
            "#ai_console { border: 1px solid #3A3A4A; border-radius: 8px; }"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log(self, message: str, level: str = "info") -> None:
        """Thêm 1 dòng log với timestamp.

        Args:
            message: Nội dung log.
            level: "info" | "success" | "warning" | "error" | "batch" | "dim"
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = _COLORS.get(level, _COLORS["info"])

        cursor = self._edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # Timestamp (dim)
        fmt_ts = QTextCharFormat()
        fmt_ts.setForeground(QColor(_COLORS["dim"]))
        cursor.insertText(f"{timestamp}  ", fmt_ts)

        # Message
        fmt_msg = QTextCharFormat()
        fmt_msg.setForeground(QColor(color))
        cursor.insertText(message + "\n", fmt_msg)

        # Auto-scroll
        self._edit.setTextCursor(cursor)
        self._edit.ensureCursorVisible()

    def log_success(self, message: str) -> None:
        self.log(message, "success")

    def log_warning(self, message: str) -> None:
        self.log(message, "warning")

    def log_error(self, message: str) -> None:
        self.log(message, "error")

    def log_batch(self, message: str) -> None:
        """Dùng cho progress từng batch (màu cyan)."""
        self.log(message, "batch")

    def log_dim(self, message: str) -> None:
        """Dùng cho thông tin phụ (mờ)."""
        self.log(message, "dim")

    def clear(self) -> None:
        self._edit.clear()

    def set_title(self, title: str) -> None:
        """Cập nhật tiêu đề header."""
        # Tìm label trong header
        for child in self.findChildren(QLabel):
            if child.objectName() == "console_header":
                child.setText(title)
                break
