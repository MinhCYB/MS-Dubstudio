"""
ui/main_window.py — Cửa sổ chính của MS DubStudio

Trách nhiệm:
- Giữ đối tượng Project hiện tại
- Quản lý QStackedWidget (7 views: Home/Import/STT/Translate/Review/Voice/Export)
- Thanh nav ngang (tab buttons) phản ánh pipeline_status
- Kết nối Project callbacks → show/hide overlay, enable/disable tabs, update badge
- Không gọi core/ trực tiếp — mọi thứ qua project.py hoặc workers
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from msdubstudio.config import APP_NAME, APP_VERSION, AppConfig
from msdubstudio.core.models import StepStatus
from msdubstudio.core.project import Project
from msdubstudio.ui.overlay import ProcessingOverlay

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tab definitions
# ---------------------------------------------------------------------------

_TABS = [
    ("home",      "🏠",  "Home",       None),
    ("import",    "📥",  "Import",     "import"),
    ("stt",       "🎙️",  "STT",        "stt"),
    ("translate", "🌐",  "Translate",  "translate"),
    ("review",    "✏️",  "Review",     "review"),
    ("voice",     "🔊",  "Voice",      "voice"),
    ("export",    "🎬",  "Export",     "export"),
]

# step → (icon_done, icon_processing, icon_error)
_STEP_BADGE = {
    StepStatus.WAITING:    "○",
    StepStatus.PROCESSING: "◉",
    StepStatus.COMPLETED:  "✓",
    StepStatus.ERROR:      "✕",
}
_STEP_BADGE_COLOR = {
    StepStatus.WAITING:    "#ABABAB",
    StepStatus.PROCESSING: "#0078D4",
    StepStatus.COMPLETED:  "#107C10",
    StepStatus.ERROR:      "#D13438",
}


class MainWindow(QMainWindow):
    """Cửa sổ chính — khung điều phối toàn bộ UI."""

    # Emit khi project được load/unload (dùng để refresh các view)
    project_changed = pyqtSignal(object)   # Project | None

    def __init__(self) -> None:
        super().__init__()
        self.project: Optional[Project] = None
        self._active_worker = None  # worker đang chạy (để cancel)
        self._cfg = AppConfig.get()

        self.imported_scenes: list = [] 

        self.setWindowTitle(APP_NAME)
        self.resize(self._cfg.window_width, self._cfg.window_height)
        self.setMinimumSize(900, 600)

        self._setup_ui()
        self._navigate_to("home")

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top nav bar
        self._nav = self._build_nav()
        root.addWidget(self._nav)

        # Content area (QStackedWidget)
        self._stack = QStackedWidget()
        root.addWidget(self._stack, stretch=1)

        # Overlay — đặt lên trên QStackedWidget
        self._overlay = ProcessingOverlay(parent=self)
        self._overlay.cancelled.connect(self._on_cancel_requested)

        # Status bar
        self._statusbar = QStatusBar()
        self._statusbar.setFixedHeight(24)
        self._lbl_status = QLabel("Ready")
        self._statusbar.addWidget(self._lbl_status)
        self.setStatusBar(self._statusbar)

        # Add views (lazy import để tránh circular)
        self._views: dict[str, QWidget] = {}
        self._add_views()

        # Tab buttons dict (key = tab_id)
        self._tab_btns: dict[str, QPushButton] = {}
        for tab_id, icon, label, _ in _TABS:
            btn = self._nav.findChild(QPushButton, f"tab_{tab_id}")
            if btn:
                self._tab_btns[tab_id] = btn

    def _build_nav(self) -> QWidget:
        """Thanh nav ngang trên cùng."""
        nav = QWidget()
        nav.setObjectName("tab_bar")
        nav.setFixedHeight(48)

        layout = QHBoxLayout(nav)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(0)

        # App logo + name (bên trái)
        lbl_logo = QLabel(f"<b style='color:#0078D4; font-size:15px;'>⬥ {APP_NAME}</b>")
        lbl_logo.setFixedWidth(160)
        layout.addWidget(lbl_logo)

        layout.addStretch()

        # Tab buttons
        for tab_id, icon, label, step in _TABS:
            btn = QPushButton(f"{icon}  {label}")
            btn.setObjectName(f"tab_{tab_id}")
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setFixedHeight(48)
            btn.setMinimumWidth(90)
            btn.clicked.connect(lambda checked, tid=tab_id: self._navigate_to(tid))
            layout.addWidget(btn)

        layout.addStretch()

        # Settings + About (bên phải)
        btn_settings = QPushButton("⚙")
        btn_settings.setObjectName("tab_settings")
        btn_settings.setFixedSize(36, 36)
        btn_settings.clicked.connect(lambda: self._navigate_to("settings"))
        layout.addWidget(btn_settings)

        btn_about = QPushButton("?")
        btn_about.setFixedSize(36, 36)
        btn_about.clicked.connect(self._show_about)
        layout.addWidget(btn_about)

        return nav

    def _add_views(self) -> None:
        """Khởi tạo và thêm tất cả views vào QStackedWidget."""
        # Import lazy để tránh circular ở top-level
        from msdubstudio.ui.views.home_view import HomeView
        from msdubstudio.ui.views.import_view import ImportView
        from msdubstudio.ui.views.stt_view import STTView
        from msdubstudio.ui.views.translate_view import TranslateView
        from msdubstudio.ui.views.review_view import ReviewView
        from msdubstudio.ui.views.voice_view import VoiceView
        from msdubstudio.ui.views.export_view import ExportView
        from msdubstudio.ui.views.settings_view import SettingsView

        view_classes = {
            "home":      HomeView,
            "import":    ImportView,
            "stt":       STTView,
            "translate": TranslateView,
            "review":    ReviewView,
            "voice":     VoiceView,
            "export":    ExportView,
            "settings":  SettingsView,
        }

        for view_id, ViewClass in view_classes.items():
            view = ViewClass(main_window=self)
            self._views[view_id] = view
            self._stack.addWidget(view)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _navigate_to(self, tab_id: str) -> None:
        """Chuyển sang view tương ứng và toggle tab button."""
        view = self._views.get(tab_id)
        if view is None:
            return

        self._stack.setCurrentWidget(view)

        # Update tab button active state
        for tid, btn in self._tab_btns.items():
            btn.setChecked(tid == tab_id)

        # Refresh view nếu cần
        if hasattr(view, "on_activated"):
            view.on_activated()

    def navigate_to(self, tab_id: str) -> None:
        """Public — gọi từ views để chuyển tab."""
        self._navigate_to(tab_id)

    # ------------------------------------------------------------------
    # Project lifecycle
    # ------------------------------------------------------------------

    def open_project(self, project_dir: str) -> None:
        """Load project từ thư mục và kết nối callbacks."""
        try:
            if self.project:
                self.project.clear_callbacks()

            self.project = Project.load(project_dir)
            self._connect_project_callbacks()
            self._cfg.add_recent_project(project_dir)
            self._cfg.save()

            self.project_changed.emit(self.project)
            self._refresh_tab_badges()
            self._navigate_to("import")
            self._lbl_status.setText(
                f"Project: {self.project.data.project_name}"
            )
            logger.info(f"Opened project: {project_dir}")

        except Exception as e:
            self._show_error("Open Project Error", str(e))

    def create_project(
        self,
        name: str,
        video_path: str,
        projects_base_dir: Optional[str] = None,
    ) -> None:
        """Tạo project mới."""
        try:
            base_dir = projects_base_dir or str(self._cfg.projects_dir)
            self._cfg.projects_dir.mkdir(parents=True, exist_ok=True)

            if self.project:
                self.project.clear_callbacks()

            self.project = Project.new(
                name=name,
                video_path=video_path,
                projects_base_dir=base_dir,
            )
            self._connect_project_callbacks()
            self._cfg.add_recent_project(str(self.project.project_dir))
            self._cfg.save()

            self.project_changed.emit(self.project)
            self._navigate_to("import")
            self._lbl_status.setText(f"Project: {name}")

        except Exception as e:
            self._show_error("Create Project Error", str(e))

    def _connect_project_callbacks(self) -> None:
        """Kết nối Project callbacks → UI."""
        if not self.project:
            return
        self.project.add_on_step_started(self._on_step_started)
        self.project.add_on_step_progress(self._on_step_progress)
        self.project.add_on_step_completed(self._on_step_completed)
        self.project.add_on_step_error(self._on_step_error)

    # ------------------------------------------------------------------
    # Project event handlers (gọi bởi Project callbacks)
    # ------------------------------------------------------------------

    def _on_step_started(self, step: str) -> None:
        self._set_tabs_enabled(False)
        self._overlay.show_for(step)
        self._overlay.resize(self.size())
        self._overlay.raise_()
        self._refresh_tab_badges()
        self._lbl_status.setText(f"Processing: {step}…")

    def _on_step_progress(
        self, step: str, current: int, total: int, elapsed: float
    ) -> None:
        self._overlay.update_progress(current, total, elapsed_s=elapsed)

    def _on_step_completed(self, step: str) -> None:
        self._overlay.hide()
        self._set_tabs_enabled(True)
        self._active_worker = None
        self._refresh_tab_badges()
        self._lbl_status.setText(f"✓ {step.title()} completed")
        self.project_changed.emit(self.project)

    def _on_step_error(self, step: str, message: str) -> None:
        self._overlay.hide()
        self._set_tabs_enabled(True)
        self._active_worker = None
        self._refresh_tab_badges()
        self._lbl_status.setText(f"✕ Error in {step}: {message[:60]}")
        self.project_changed.emit(self.project)

    # ------------------------------------------------------------------
    # Tab enable / badge update
    # ------------------------------------------------------------------

    def _set_tabs_enabled(self, enabled: bool) -> None:
        for tab_id, btn in self._tab_btns.items():
            if tab_id == "home":
                continue  # Home luôn accessible
            btn.setEnabled(enabled)

    def _refresh_tab_badges(self) -> None:
        """Cập nhật tooltip và badge màu cho mỗi tab theo pipeline_status."""
        if not self.project:
            return
        ps = self.project.data.pipeline_status
        step_map = {
            "import":    ps.import_,
            "stt":       ps.stt,
            "translate": ps.translate,
            "review":    ps.review,
            "voice":     ps.voice,
            "export":    ps.export,
        }
        for tab_id, icon, label, step in _TABS:
            if step and step in step_map:
                status = step_map[step]
                badge = _STEP_BADGE.get(status, "○")
                color = _STEP_BADGE_COLOR.get(status, "#ABABAB")
                btn = self._tab_btns.get(tab_id)
                if btn:
                    btn.setText(f"{icon}  {label}  {badge}")
                    # Tooltip hiện status
                    btn.setToolTip(f"{step.title()}: {status.value}")

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    def _on_cancel_requested(self) -> None:
        if self._active_worker and hasattr(self._active_worker, "cancel"):
            self._active_worker.cancel()
            self._lbl_status.setText("Cancelling…")

    def set_active_worker(self, worker) -> None:
        """Đăng ký worker đang chạy để overlay Cancel có thể gọi .cancel()."""
        self._active_worker = worker

    # ------------------------------------------------------------------
    # Window events
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._overlay.isVisible():
            self._overlay.resize(self.size())

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._cfg.save_window_state(self.width(), self.height())
        self._cfg.save()
        if self.project:
            self.project.clear_callbacks()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _show_error(self, title: str, message: str) -> None:
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(self, title, message)

    def _show_about(self) -> None:
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<b>{APP_NAME}</b> v{APP_VERSION}<br>"
            "AI-powered video dubbing (Chinese → Vietnamese)<br><br>"
            "Built with PyQt6 + Gemini + Whisper + edge-tts",
        )
