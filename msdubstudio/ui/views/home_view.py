"""
ui/views/home_view.py — Home Screen

Màn hình chào: Recent Projects, New Project, Open Project, Workflow guide.
Không chứa logic xử lý — chỉ điều hướng qua main_window.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from msdubstudio.ui.main_window import MainWindow

from msdubstudio.config import AppConfig


class _WorkflowStep(QWidget):
    """Một bước trong DubFlow Workflow guide (bên phải Home)."""

    def __init__(self, icon: str, title: str, subtitle: str, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(12)

        lbl_icon = QLabel(icon)
        lbl_icon.setFixedWidth(28)
        lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_icon.setStyleSheet("font-size: 18px;")
        layout.addWidget(lbl_icon)

        col = QVBoxLayout()
        col.setSpacing(1)
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-size: 13px; font-weight: 600; color: #1C1C1C;")
        lbl_sub = QLabel(subtitle)
        lbl_sub.setStyleSheet("font-size: 11px; color: #5A5A5A;")
        col.addWidget(lbl_title)
        col.addWidget(lbl_sub)
        layout.addLayout(col)


class _RecentProjectRow(QWidget):
    """Một dòng trong danh sách Recent Projects."""

    def __init__(
        self,
        project_dir: str,
        on_open,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("project_card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._project_dir = project_dir
        self._on_open = on_open
        self.setFixedHeight(56)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        # Thumbnail placeholder (file icon)
        lbl_thumb = QLabel("🎬")
        lbl_thumb.setFixedSize(36, 36)
        lbl_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_thumb.setStyleSheet(
            "background: #DCEEFB; border-radius: 6px; font-size: 18px;"
        )
        layout.addWidget(lbl_thumb)

        col = QVBoxLayout()
        col.setSpacing(2)
        name = Path(project_dir).name.replace("_", " ")
        lbl_name = QLabel(name)
        lbl_name.setStyleSheet("font-size: 13px; font-weight: 600; color: #1C1C1C;")
        lbl_path = QLabel(project_dir)
        lbl_path.setStyleSheet("font-size: 11px; color: #5A5A5A;")
        lbl_path.setWordWrap(False)
        lbl_path.setTextFormat(Qt.TextFormat.PlainText)
        col.addWidget(lbl_name)
        col.addWidget(lbl_path)
        layout.addLayout(col, stretch=1)

        lbl_arrow = QLabel("›")
        lbl_arrow.setStyleSheet("font-size: 18px; color: #ABABAB;")
        layout.addWidget(lbl_arrow)

        self.setStyleSheet(
            "#project_card { background: #FFFFFF; border: 1px solid #E8E8E8;"
            "border-radius: 8px; }"
            "#project_card:hover { border-color: #0078D4; background: #F5F9FF; }"
        )

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_open(self._project_dir)


class HomeView(QWidget):
    """Home screen — Welcome, Recent Projects, Workflow guide."""

    def __init__(self, main_window: "MainWindow") -> None:
        super().__init__()
        self._mw = main_window
        self._cfg = AppConfig.get()
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Left panel: main content ---
        left = QWidget()
        left.setStyleSheet("background-color: #FFFFFF;")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(40, 40, 40, 40)
        left_layout.setSpacing(24)

        # Welcome text
        lbl_welcome = QLabel("Welcome to MS DubStudio")
        lbl_welcome.setStyleSheet(
            "font-size: 24px; font-weight: 700; color: #1C1C1C;"
        )
        lbl_sub = QLabel("AI Video Translation, Simplified.")
        lbl_sub.setStyleSheet("font-size: 14px; color: #5A5A5A;")

        left_layout.addWidget(lbl_welcome)
        left_layout.addWidget(lbl_sub)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self._btn_new = QPushButton("＋  New Project")
        self._btn_new.setObjectName("btn_primary")
        self._btn_new.setFixedHeight(56)
        self._btn_new.setFixedWidth(200)
        self._btn_new.setStyleSheet(
            "QPushButton { background: #0078D4; color: white; border-radius: 8px;"
            "font-size: 14px; font-weight: 600; border: none; }"
            "QPushButton:hover { background: #106EBE; }"
        )
        self._btn_new.clicked.connect(self._on_new_project)

        self._btn_open = QPushButton("📂  Open Project")
        self._btn_open.setFixedHeight(56)
        self._btn_open.setFixedWidth(200)
        self._btn_open.setStyleSheet(
            "QPushButton { background: white; color: #1C1C1C; border-radius: 8px;"
            "font-size: 14px; border: 1px solid #CCCCCC; }"
            "QPushButton:hover { background: #F0F0F0; }"
        )
        self._btn_open.clicked.connect(self._on_open_project)

        btn_row.addWidget(self._btn_new)
        btn_row.addWidget(self._btn_open)
        btn_row.addStretch()
        left_layout.addLayout(btn_row)

        # Recent Projects
        hdr_row = QHBoxLayout()
        lbl_recent = QLabel("Recent Projects")
        lbl_recent.setStyleSheet("font-size: 15px; font-weight: 600; color: #1C1C1C;")
        hdr_row.addWidget(lbl_recent)
        hdr_row.addStretch()
        btn_see_all = QPushButton("See all")
        btn_see_all.setFlat(True)
        btn_see_all.setStyleSheet("color: #0078D4; font-size: 12px; border: none;")
        hdr_row.addWidget(btn_see_all)
        left_layout.addLayout(hdr_row)

        self._recent_list = QVBoxLayout()
        self._recent_list.setSpacing(6)
        left_layout.addLayout(self._recent_list)

        left_layout.addStretch()
        root.addWidget(left, stretch=3)

        # --- Separator ---
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #E0E0E0;")
        root.addWidget(sep)

        # --- Right panel: workflow guide ---
        right = QWidget()
        right.setFixedWidth(240)
        right.setStyleSheet("background-color: #F9F9F9;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(24, 40, 24, 40)
        right_layout.setSpacing(16)

        lbl_guide = QLabel("DubStudio Workflow")
        lbl_guide.setStyleSheet("font-size: 14px; font-weight: 700; color: #1C1C1C;")
        right_layout.addWidget(lbl_guide)

        steps = [
            ("📥", "Import",          "Load your video and assets"),
            ("🎙️", "Speech to Text",  "Extract accurate transcripts"),
            ("🌐", "Translate",       "Translate with AI (Gemini)"),
            ("✏️", "Review",          "Edit and refine translations"),
            ("🔊", "Voice",           "Generate natural AI voices"),
            ("🎬", "Export",          "Render and export final video"),
        ]
        for icon, title, sub in steps:
            step_w = _WorkflowStep(icon, title, sub)
            right_layout.addWidget(step_w)

        right_layout.addStretch()
        root.addWidget(right)

    def on_activated(self) -> None:
        """Gọi mỗi khi tab Home được chọn — refresh danh sách recent."""
        self._refresh_recent()

    def _refresh_recent(self) -> None:
        """Xóa và vẽ lại danh sách recent projects."""
        # Xóa cũ
        while self._recent_list.count():
            item = self._recent_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        recent = self._cfg.recent_projects
        if not recent:
            lbl = QLabel("No recent projects")
            lbl.setStyleSheet("color: #ABABAB; font-size: 13px;")
            self._recent_list.addWidget(lbl)
            return

        for path in recent[:5]:
            if Path(path).exists():
                row = _RecentProjectRow(path, self._mw.open_project)
                self._recent_list.addWidget(row)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_new_project(self) -> None:
        """Chọn video file → tạo project mới."""
        video_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video File",
            str(Path.home()),
            "Video Files (*.mp4 *.mkv *.avi *.mov *.wmv *.flv);;All Files (*)",
        )
        if not video_path:
            return

        name, ok = QInputDialog.getText(
            self,
            "New Project",
            "Project name:",
            text=Path(video_path).stem,
        )
        if not ok or not name.strip():
            return

        self._mw.create_project(name.strip(), video_path)

    def _on_open_project(self) -> None:
        """Chọn thư mục project."""
        project_dir = QFileDialog.getExistingDirectory(
            self,
            "Open Project Folder",
            str(self._cfg.projects_dir),
        )
        if project_dir and Path(project_dir).exists():
            self._mw.open_project(project_dir)
