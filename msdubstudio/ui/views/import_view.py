"""
ui/views/import_view.py — Import Workspace

Theo mockup 01-import.png:
- Bên trái: Project Files tree (cây thư mục project)
- Giữa: Video Preview (VideoPlayer) + Video Information table
- Bên phải: Import Options (checkboxes) + Detected Language + Start Import button
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from msdubstudio.ui.main_window import MainWindow

from msdubstudio.ui.widgets.video_player import VideoPlayer


def _fmt_duration(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class ImportView(QWidget):
    """Import workspace — video selection, metadata display, start import."""

    def __init__(self, main_window: "MainWindow") -> None:
        super().__init__()
        self._mw = main_window
        self._video_path: Optional[str] = None
        self._setup_ui()
        self.setAcceptDrops(True)

    def _setup_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)

        # --- Left: Project Files ---
        left = QWidget()
        left.setFixedWidth(200)
        left.setStyleSheet("background: #F9F9F9; border-right: 1px solid #E0E0E0;")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 16, 12, 16)
        left_layout.setSpacing(8)

        lbl_files = QLabel("Project Files")
        lbl_files.setStyleSheet("font-size: 13px; font-weight: 600; color: #5A5A5A;")
        left_layout.addWidget(lbl_files)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setStyleSheet(
            "QTreeWidget { background: transparent; border: none; }"
            "QTreeWidget::item { padding: 3px; }"
            "QTreeWidget::item:selected { background: #DCEEFB; color: #0078D4; }"
        )
        left_layout.addWidget(self._tree)

        self._lbl_status = QLabel("Ready to import…")
        self._lbl_status.setStyleSheet("font-size: 11px; color: #5A5A5A;")
        left_layout.addWidget(self._lbl_status)

        splitter.addWidget(left)

        # --- Center: Video Preview + Info ---
        center = QWidget()
        center.setStyleSheet("background: #FFFFFF;")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(20, 20, 20, 20)
        center_layout.setSpacing(16)

        lbl_preview = QLabel("Video Preview")
        lbl_preview.setStyleSheet("font-size: 15px; font-weight: 600;")
        center_layout.addWidget(lbl_preview)

        # Drop zone + VideoPlayer
        self._drop_zone = QWidget()
        self._drop_zone.setObjectName("drop_zone")
        self._drop_zone.setMinimumHeight(200)
        self._drop_zone.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._drop_zone.setStyleSheet(
            "#drop_zone { background: #F9FBFF; border: 2px dashed #B3D4EF; border-radius: 12px; }"
        )
        drop_layout = QVBoxLayout(self._drop_zone)
        drop_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._lbl_drop = QLabel("🎬\n\nDrop video file here\nor click to browse")
        self._lbl_drop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_drop.setStyleSheet("color: #5A5A5A; font-size: 14px; line-height: 2;")
        drop_layout.addWidget(self._lbl_drop)

        btn_browse = QPushButton("Browse File…")
        btn_browse.setFixedWidth(120)
        btn_browse.clicked.connect(self._on_browse)
        drop_layout.addWidget(btn_browse, alignment=Qt.AlignmentFlag.AlignCenter)

        self._player = VideoPlayer()
        self._player.hide()

        center_layout.addWidget(self._drop_zone, stretch=3)
        center_layout.addWidget(self._player, stretch=3)

        # Video Information
        self._grp_info = QGroupBox("Video Information")
        self._grp_info.hide()
        info_form = QFormLayout(self._grp_info)
        info_form.setSpacing(6)

        self._lbl_filename   = QLabel("—")
        self._lbl_duration   = QLabel("—")
        self._lbl_resolution = QLabel("—")
        self._lbl_fps        = QLabel("—")
        self._lbl_audio      = QLabel("—")

        info_form.addRow("File Name:",  self._lbl_filename)
        info_form.addRow("Duration:",   self._lbl_duration)
        info_form.addRow("Resolution:", self._lbl_resolution)
        info_form.addRow("Frame Rate:", self._lbl_fps)
        info_form.addRow("Audio:",      self._lbl_audio)
        center_layout.addWidget(self._grp_info, stretch=2)

        splitter.addWidget(center)

        # --- Right: Options ---
        right = QWidget()
        right.setFixedWidth(220)
        right.setStyleSheet("background: #F9F9F9; border-left: 1px solid #E0E0E0;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 20, 16, 20)
        right_layout.setSpacing(16)

        grp_opts = QGroupBox("Import Options")
        opts_layout = QVBoxLayout(grp_opts)
        opts_layout.setSpacing(8)
        self._chk_audio  = QCheckBox("Extract Audio")
        self._chk_scenes = QCheckBox("Detect Scenes")
        self._chk_lang   = QCheckBox("Detect Language")
        self._chk_audio.setChecked(True)
        self._chk_scenes.setChecked(True)
        self._chk_lang.setChecked(True)
        for chk in (self._chk_audio, self._chk_scenes, self._chk_lang):
            opts_layout.addWidget(chk)
        right_layout.addWidget(grp_opts)

        grp_lang = QGroupBox("Detected Language")
        grp_lang.setObjectName("grp_lang")
        lang_layout = QVBoxLayout(grp_lang)
        self._lbl_lang = QLabel("—")
        self._lbl_lang_conf = QLabel("")
        self._lbl_lang_conf.setStyleSheet("color: #107C10; font-weight: 600;")
        lang_layout.addWidget(self._lbl_lang)
        lang_layout.addWidget(self._lbl_lang_conf)
        right_layout.addWidget(grp_lang)

        right_layout.addStretch()

        self._btn_import = QPushButton("Start Import")
        self._btn_import.setObjectName("btn_primary")
        self._btn_import.setFixedHeight(40)
        self._btn_import.setEnabled(False)
        self._btn_import.setStyleSheet(
            "QPushButton { background: #0078D4; color: white; border-radius: 6px;"
            "font-size: 14px; font-weight: 600; border: none; }"
            "QPushButton:disabled { background: #B3D4EF; }"
            "QPushButton:hover { background: #106EBE; }"
        )
        self._btn_import.clicked.connect(self._on_start_import)
        right_layout.addWidget(self._btn_import)

        splitter.addWidget(right)
        splitter.setSizes([200, 600, 220])

        root.addWidget(splitter)

    # ------------------------------------------------------------------
    # Drag-Drop
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(
                url.toLocalFile().lower().endswith(
                    (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv")
                )
                for url in urls
            ):
                event.acceptProposedAction()
                self._drop_zone.setStyleSheet(
                    "#drop_zone { background: #DCEEFB; border: 2px dashed #0078D4;"
                    "border-radius: 12px; }"
                )

    def dragLeaveEvent(self, event) -> None:  # type: ignore[override]
        self._drop_zone.setStyleSheet(
            "#drop_zone { background: #F9FBFF; border: 2px dashed #B3D4EF;"
            "border-radius: 12px; }"
        )

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        self._drop_zone.setStyleSheet(
            "#drop_zone { background: #F9FBFF; border: 2px dashed #B3D4EF;"
            "border-radius: 12px; }"
        )
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            self._load_video(path)

    # ------------------------------------------------------------------
    # Video loading
    # ------------------------------------------------------------------

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video File",
            str(Path.home()),
            "Video Files (*.mp4 *.mkv *.avi *.mov *.wmv *.flv);;All Files (*)",
        )
        if path:
            self._load_video(path)

    def _load_video(self, path: str) -> None:
        """Load video vào player và lấy metadata (sync, nhanh)."""
        self._video_path = path
        p = Path(path)

        # Show player, hide drop zone
        self._drop_zone.hide()
        self._player.show()
        self._player.load_video(path)

        # Metadata (dùng ffprobe sync vì tác vụ nhanh)
        self._populate_metadata(path)

        # Update project files tree nếu project đã load
        if self._mw.project:
            self._refresh_tree()

        self._btn_import.setEnabled(True)
        self._lbl_status.setText("Ready to import…")

    def _populate_metadata(self, path: str) -> None:
        """Lấy metadata và hiện bảng Video Information."""
        try:
            from msdubstudio.core.media_io import get_video_metadata
            meta = get_video_metadata(path)
            self._lbl_filename.setText(Path(path).name)
            self._lbl_duration.setText(_fmt_duration(meta.duration_s))
            self._lbl_resolution.setText(
                f"{meta.width} × {meta.height}" if meta.width else "Unknown"
            )
            self._lbl_fps.setText(f"{meta.fps:.2f} fps" if meta.fps else "Unknown")
            codec = meta.audio_codec or "Unknown"
            ch = meta.audio_channels or 0
            sr = (meta.audio_sample_rate or 0) // 1000
            self._lbl_audio.setText(f"{codec}, {ch} ch, {sr} kHz")

            # Language detection
            lang = meta.detected_language or "—"
            conf = meta.language_confidence
            self._lbl_lang.setText(f"{lang}")
            if conf is not None:
                self._lbl_lang_conf.setText(f"Confidence: {conf:.2f}")

        except Exception:
            self._lbl_filename.setText(Path(path).name)

        self._grp_info.show()

    def _refresh_tree(self) -> None:
        """Cập nhật Project Files tree từ project directory."""
        if not self._mw.project:
            return
        self._tree.clear()
        project_dir = self._mw.project.project_dir
        root_item = QTreeWidgetItem([project_dir.name])
        self._tree.addTopLevelItem(root_item)
        self._build_tree(root_item, project_dir)
        root_item.setExpanded(True)

    def _build_tree(self, parent: QTreeWidgetItem, path: Path, depth: int = 0) -> None:
        if depth > 2:
            return
        try:
            for item in sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name)):
                child = QTreeWidgetItem([item.name])
                parent.addChild(child)
                if item.is_dir():
                    self._build_tree(child, item, depth + 1)
        except PermissionError:
            pass

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def _on_start_import(self) -> None:
        if not self._video_path or not self._mw.project:
            return

        from msdubstudio.workers.import_worker import ImportWorker

        self._mw.project.settings.extract_audio = self._chk_audio.isChecked()
        self._mw.project.settings.detect_scenes = self._chk_scenes.isChecked()
        self._mw.project.settings.detect_language = self._chk_lang.isChecked()

        worker = ImportWorker(
            video_path=self._video_path,
            audio_output_path=str(self._mw.project.audio_path),
            frames_dir=str(self._mw.project.frames_dir),
            settings=self._mw.project.settings,
        )
        self._mw.set_active_worker(worker)

        worker.step_log.connect(self._on_step_log)
        worker.finished.connect(self._on_import_finished)
        worker.error.connect(self._on_import_error)
        worker.progress.connect(self._on_progress)

        self._mw.project.on_import_started()
        worker.start()

    def _on_step_log(self, msg: str) -> None:
        self._lbl_status.setText(msg)

    def _on_progress(self, current: int, total: int) -> None:
        self._mw._overlay.update_progress(current, total)

    def _on_import_finished(self, metadata, scenes) -> None:
        self._mw.project.on_import_completed(metadata, scenes)
        self._refresh_tree()
        self._lbl_status.setText(f"✓ Import complete — {len(scenes)} scenes detected")

    def _on_import_error(self, msg: str) -> None:
        self._mw.project.on_import_failed(msg)
        self._lbl_status.setText(f"✕ {msg}")

    # ------------------------------------------------------------------
    # on_activated
    # ------------------------------------------------------------------

    def on_activated(self) -> None:
        if self._mw.project:
            self._refresh_tree()
