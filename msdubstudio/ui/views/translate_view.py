"""
ui/views/translate_view.py — Translate Workspace

Theo mockup 03-translate-workspace.png:
- Bên trái: Translation Settings panel + Translate All button
- Giữa: Bảng segment (# / Start / End / Chinese / Vietnamese / Confidence / Status)
  + Error panel dưới (Segment #X Error → Retry / Change Model / Skip)
  + Context Frame (ảnh scene)
- Bên phải: AI Console
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from msdubstudio.ui.main_window import MainWindow

from msdubstudio.core.models import Segment, SegmentStatus
from msdubstudio.ui.widgets.ai_console import AIConsole
from msdubstudio.ui.widgets.segment_table import COLUMNS_TRANSLATE, SegmentTableView


class _ErrorPanel(QWidget):
    """Panel hiện lỗi của 1 segment với 3 action buttons."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "background: #FDE7E9; border-radius: 8px; border: 1px solid #F1B4B6;"
        )
        self.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Error title
        title_row = QHBoxLayout()
        lbl_icon = QLabel("⊘")
        lbl_icon.setStyleSheet("font-size: 16px; color: #D13438;")
        self._lbl_title = QLabel("Error: —")
        self._lbl_title.setStyleSheet("color: #D13438; font-weight: 600;")
        title_row.addWidget(lbl_icon)
        title_row.addWidget(self._lbl_title, stretch=1)
        layout.addLayout(title_row)

        # Hint
        self._lbl_hint = QLabel("Try again with lower temperature or switch model.")
        self._lbl_hint.setStyleSheet("color: #5A5A5A; font-size: 12px;")
        layout.addWidget(self._lbl_hint)

        # Action buttons
        btn_row = QHBoxLayout()
        self.btn_retry  = QPushButton("Retry")
        self.btn_model  = QPushButton("Change Model")
        self.btn_skip   = QPushButton("Skip")
        for btn in (self.btn_retry, self.btn_model, self.btn_skip):
            btn.setFixedHeight(28)
            btn.setStyleSheet(
                "QPushButton { background: white; border: 1px solid #CCCCCC;"
                "border-radius: 6px; padding: 0 12px; }"
                "QPushButton:hover { background: #F0F0F0; }"
            )
        btn_row.addWidget(self.btn_retry)
        btn_row.addWidget(self.btn_model)
        btn_row.addWidget(self.btn_skip)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def show_error(self, seg_id: int, error_msg: str) -> None:
        self._lbl_title.setText(f"Segment #{seg_id} Error: {error_msg}")
        self.show()

    def hide_error(self) -> None:
        self.hide()


class TranslateView(QWidget):
    """Translate Workspace."""

    def __init__(self, main_window: "MainWindow") -> None:
        super().__init__()
        self._mw = main_window
        self._selected_segment: Optional[Segment] = None
        self._error_segment_id: Optional[int] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        # ---- Left: Translation Settings ----
        left = QWidget()
        left.setFixedWidth(220)
        left.setStyleSheet("background: #F9F9F9; border-right: 1px solid #E0E0E0;")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(12)

        grp = QGroupBox("Translation Settings")
        form = QFormLayout(grp)
        form.setSpacing(8)

        self._cmb_provider = QComboBox()
        self._cmb_provider.addItems(["Gemini 1.5 Pro", "Gemini 1.5 Flash", "Gemini 2.0 Flash"])

        self._cmb_src_lang = QComboBox()
        self._cmb_src_lang.addItems(["Chinese", "Japanese", "Korean", "English"])
        self._cmb_src_lang.setCurrentText("Chinese")

        self._cmb_tgt_lang = QComboBox()
        self._cmb_tgt_lang.addItems(["Vietnamese", "English", "Japanese"])
        self._cmb_tgt_lang.setCurrentText("Vietnamese")

        self._spn_temp = QDoubleSpinBox()
        self._spn_temp.setRange(0.0, 2.0)
        self._spn_temp.setSingleStep(0.1)
        self._spn_temp.setValue(0.3)
        self._spn_temp.setDecimals(1)

        from PyQt6.QtWidgets import QCheckBox
        self._chk_context = QCheckBox("Use context (scene + frame)")
        self._chk_context.setChecked(True)

        form.addRow("Provider:", self._cmb_provider)
        form.addRow("Source:", self._cmb_src_lang)
        form.addRow("Target:", self._cmb_tgt_lang)
        form.addRow("Temperature:", self._spn_temp)
        form.addRow(self._chk_context)
        left_layout.addWidget(grp)
        left_layout.addStretch()

        self._btn_translate = QPushButton("Translate All")
        self._btn_translate.setFixedHeight(40)
        self._btn_translate.setEnabled(False)
        self._btn_translate.setStyleSheet(
            "QPushButton { background: #0078D4; color: white; border-radius: 6px;"
            "font-size: 14px; font-weight: 600; border: none; }"
            "QPushButton:disabled { background: #B3D4EF; }"
            "QPushButton:hover { background: #106EBE; }"
        )
        self._btn_translate.clicked.connect(self._on_translate_all)
        left_layout.addWidget(self._btn_translate)

        splitter.addWidget(left)

        # ---- Center: Table + Error Panel + Context Frame ----
        center = QWidget()
        center.setStyleSheet("background: #FFFFFF;")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(16, 16, 16, 16)
        center_layout.setSpacing(12)

        self._table = SegmentTableView(columns=COLUMNS_TRANSLATE, show_search=False)
        self._table.segment_selected.connect(self._on_segment_selected)
        center_layout.addWidget(self._table, stretch=1)

        # Error panel
        self._error_panel = _ErrorPanel()
        self._error_panel.btn_retry.clicked.connect(self._on_retry)
        self._error_panel.btn_skip.clicked.connect(self._on_skip)
        center_layout.addWidget(self._error_panel)

        # Context frame
        self._grp_context = QGroupBox("Context (Scene Frame)")
        ctx_layout = QVBoxLayout(self._grp_context)
        self._lbl_context_img = QLabel("No scene frame")
        self._lbl_context_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_context_img.setFixedHeight(100)
        self._lbl_context_img.setStyleSheet(
            "background: #F0F0F0; border-radius: 6px; color: #ABABAB;"
        )
        self._lbl_context_scene = QLabel("")
        self._lbl_context_scene.setStyleSheet("font-size: 11px; color: #5A5A5A;")
        ctx_layout.addWidget(self._lbl_context_img)
        ctx_layout.addWidget(self._lbl_context_scene)
        center_layout.addWidget(self._grp_context)

        splitter.addWidget(center)

        # ---- Right: AI Console ----
        right = QWidget()
        right.setFixedWidth(280)
        right.setStyleSheet("background: #F9F9F9; border-left: 1px solid #E0E0E0;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 16, 12, 16)

        self._console = AIConsole(title="AI Console")
        right_layout.addWidget(self._console)

        splitter.addWidget(right)
        splitter.setSizes([220, 640, 280])

        root.addWidget(splitter)

    # ------------------------------------------------------------------
    # on_activated
    # ------------------------------------------------------------------

    def on_activated(self) -> None:
        project = self._mw.project
        if not project:
            return
        segs = project.data.segments
        self._table.set_segments(segs)
        # Enable nếu STT đã completed
        from msdubstudio.core.models import StepStatus
        stt_ok = project.data.pipeline_status.stt == StepStatus.COMPLETED
        self._btn_translate.setEnabled(stt_ok and bool(segs))

    # ------------------------------------------------------------------
    # Translate
    # ------------------------------------------------------------------

    def _on_translate_all(self) -> None:
        project = self._mw.project
        if not project:
            return

        api_key = project.data.settings.gemini_api_key
        if not api_key:
            from msdubstudio.config import AppConfig
            api_key = AppConfig.get().gemini_api_key
        if not api_key:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "API Key Missing",
                                "Please set your Gemini API key in Settings.")
            return

        from msdubstudio.workers.translate_worker import TranslateWorker

        settings = project.data.settings
        settings.gemini_model = self._cmb_provider.currentText().lower().replace(" ", "-")
        settings.gemini_temperature = self._spn_temp.value()

        # Chỉ translate pending segments
        pending = [s for s in project.data.segments
                   if s.status != SegmentStatus.TRANSLATED]

        if not pending:
            self._console.log_success("All segments already translated.")
            return

        worker = TranslateWorker(
            segments=pending,
            settings=settings,
            api_key=api_key,
        )
        self._mw.set_active_worker(worker)

        worker.batch_done.connect(self._on_batch_done)
        worker.batch_error.connect(self._on_batch_error)
        worker.step_log.connect(self._console.log)
        worker.finished_all.connect(self._on_translate_finished)
        worker.progress.connect(self._on_progress)

        total = len(pending)
        self._console.log(f"Start translating ({total} segments)…")
        self._console.log_dim(f"Sending to {self._cmb_provider.currentText()}")

        project.on_translate_started()
        worker.start()

    def _on_progress(self, current: int, total: int) -> None:
        self._mw._overlay.update_progress(current, total)

    def _on_batch_done(self, batch_segments: list) -> None:
        project = self._mw.project
        if not project:
            return
        from msdubstudio.core.models import Segment as Seg
        segs = [Seg(**s) if isinstance(s, dict) else s for s in batch_segments]
        project.update_translated_segments(segs)
        for seg in segs:
            self._table.update_segment(seg)
        n = len(segs)
        self._console.log_batch(f"✓ Batch done ({n} segments)")

    def _on_batch_error(self, batch_idx: int, error_msg: str) -> None:
        self._console.log_error(f"Batch {batch_idx} error: {error_msg}")
        # Highlight dòng lỗi nếu có thể xác định segment
        segs = self._mw.project.data.segments if self._mw.project else []
        for seg in segs:
            if seg.status == SegmentStatus.ERROR and self._error_segment_id is None:
                self._error_segment_id = seg.id
                self._error_panel.show_error(seg.id, error_msg)
                break

    def _on_translate_finished(self) -> None:
        if self._mw.project:
            self._mw.project.on_translate_completed()
        self._console.log_success(f"Completed all segments")
        self._error_panel.hide_error()

    # ------------------------------------------------------------------
    # Error actions
    # ------------------------------------------------------------------

    def _on_retry(self) -> None:
        if self._error_segment_id is not None:
            self._console.log(f"Retrying segment #{self._error_segment_id}…")
            self._error_panel.hide_error()
            # TODO: retry single segment

    def _on_skip(self) -> None:
        if self._error_segment_id is not None:
            self._console.log_dim(f"Skipping segment #{self._error_segment_id}")
            self._error_segment_id = None
            self._error_panel.hide_error()

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_segment_selected(self, seg: Segment) -> None:
        self._selected_segment = seg
        # Hiện scene frame nếu có
        if seg.scene_frame_path:
            from PyQt6.QtGui import QPixmap
            pix = QPixmap(seg.scene_frame_path)
            if not pix.isNull():
                self._lbl_context_img.setPixmap(
                    pix.scaled(
                        self._lbl_context_img.width(),
                        self._lbl_context_img.height(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self._lbl_context_scene.setText(
                    f"Scene {seg.scene_id or '?'}  "
                    f"{seg.start:.2f}s – {seg.end:.2f}s"
                )
