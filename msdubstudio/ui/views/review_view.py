"""
ui/views/review_view.py — Review Workspace

Theo mockup 05-review-workspace.png:
- Bên trái: Segment list (click để chọn) + search
- Giữa: Quick Actions row + Text editor (Chinese | Vietnamese) + Notes + Video Preview
- Bên phải: Segment Inspector + History
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from msdubstudio.ui.main_window import MainWindow

from msdubstudio.core.models import Segment
from msdubstudio.ui.widgets.confidence_badge import ConfidenceBadge
from msdubstudio.ui.widgets.segment_table import (
    COLUMNS_REVIEW,
    SegmentTableView,
)
from msdubstudio.ui.widgets.video_player import VideoPlayer


_QUICK_ACTIONS = [
    ("✏️  Improve Fluency", "improve_fluency"),
    ("✂️  Shorten",          "shorten"),
    ("➕  Expand",           "expand"),
    ("👔  Formalize",       "formalize"),
    ("👍  Simplify",        "simplify"),
]


class ReviewView(QWidget):
    """Review Workspace — 3-column editor, quick actions, segment inspector."""

    def __init__(self, main_window: "MainWindow") -> None:
        super().__init__()
        self._mw = main_window
        self._selected_segment: Optional[Segment] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        # ---- Left: Segment list ----
        left = QWidget()
        left.setFixedWidth(220)
        left.setStyleSheet("background: #F9F9F9; border-right: 1px solid #E0E0E0;")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 12, 8, 12)
        left_layout.setSpacing(8)

        self._seg_list = SegmentTableView(
            columns=COLUMNS_REVIEW,
            show_search=True,
        )
        self._seg_list.segment_selected.connect(self._on_segment_selected)
        left_layout.addWidget(self._seg_list)

        splitter.addWidget(left)

        # ---- Center: Editor + Preview ----
        center = QWidget()
        center.setStyleSheet("background: #FFFFFF;")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(16, 12, 16, 16)
        center_layout.setSpacing(10)

        # Quick Actions row
        qa_row = QHBoxLayout()
        qa_row.setSpacing(6)
        lbl_qa = QLabel("Quick Actions")
        lbl_qa.setStyleSheet("font-size: 12px; color: #5A5A5A; font-weight: 600;")
        qa_row.addWidget(lbl_qa)
        for label, action_id in _QUICK_ACTIONS:
            btn = QPushButton(label)
            btn.setFixedHeight(26)
            btn.setStyleSheet(
                "QPushButton { background: #F0F0F0; border: 1px solid #DCDCDC;"
                "border-radius: 4px; font-size: 11px; padding: 0 8px; }"
                "QPushButton:hover { background: #E0E0E0; }"
            )
            btn.clicked.connect(lambda _, a=action_id: self._on_quick_action(a))
            qa_row.addWidget(btn)
        qa_row.addStretch()
        center_layout.addLayout(qa_row)

        # Editor: Chinese | Vietnamese side by side
        editor_row = QHBoxLayout()
        editor_row.setSpacing(12)

        # Chinese (read-only)
        zh_col = QVBoxLayout()
        lbl_zh = QLabel("Chinese (Original)")
        lbl_zh.setStyleSheet("font-size: 12px; color: #5A5A5A; font-weight: 600;")
        zh_col.addWidget(lbl_zh)
        self._txt_zh = QPlainTextEdit()
        self._txt_zh.setReadOnly(True)
        self._txt_zh.setPlaceholderText("Chinese text…")
        self._txt_zh.setStyleSheet(
            "background: #F9F9F9; border: 1px solid #E0E0E0;"
            "border-radius: 6px; padding: 8px; font-size: 13px;"
        )
        zh_col.addWidget(self._txt_zh)
        self._lbl_zh_count = QLabel("0 / 200")
        self._lbl_zh_count.setStyleSheet("font-size: 11px; color: #ABABAB;")
        self._lbl_zh_count.setAlignment(Qt.AlignmentFlag.AlignRight)
        zh_col.addWidget(self._lbl_zh_count)
        editor_row.addLayout(zh_col, stretch=1)

        # Separator
        sep = QWidget()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background: #E0E0E0;")
        editor_row.addWidget(sep)

        # Vietnamese (editable)
        vi_col = QVBoxLayout()
        lbl_vi = QLabel("Vietnamese (Translation)")
        lbl_vi.setStyleSheet("font-size: 12px; color: #5A5A5A; font-weight: 600;")
        vi_col.addWidget(lbl_vi)
        self._txt_vi = QPlainTextEdit()
        self._txt_vi.setPlaceholderText("Vietnamese translation…")
        self._txt_vi.setStyleSheet(
            "background: #FFFFFF; border: 1.5px solid #0078D4;"
            "border-radius: 6px; padding: 8px; font-size: 13px;"
        )
        self._txt_vi.textChanged.connect(self._on_vi_text_changed)
        vi_col.addWidget(self._txt_vi)
        self._lbl_vi_count = QLabel("0 / 200")
        self._lbl_vi_count.setStyleSheet("font-size: 11px; color: #ABABAB;")
        self._lbl_vi_count.setAlignment(Qt.AlignmentFlag.AlignRight)
        vi_col.addWidget(self._lbl_vi_count)
        editor_row.addLayout(vi_col, stretch=1)

        center_layout.addLayout(editor_row, stretch=2)

        # Notes
        lbl_notes = QLabel("Notes")
        lbl_notes.setStyleSheet("font-size: 12px; color: #5A5A5A; font-weight: 600;")
        self._txt_notes = QPlainTextEdit()
        self._txt_notes.setPlaceholderText("Add notes for this line…")
        self._txt_notes.setFixedHeight(56)
        self._txt_notes.setStyleSheet(
            "background: #F9F9F9; border: 1px solid #E0E0E0;"
            "border-radius: 6px; padding: 6px; font-size: 12px;"
        )
        center_layout.addWidget(lbl_notes)
        center_layout.addWidget(self._txt_notes)

        # Save button
        save_row = QHBoxLayout()
        save_row.addStretch()
        self._btn_save = QPushButton("Save Changes")
        self._btn_save.setFixedHeight(32)
        self._btn_save.setStyleSheet(
            "background: #0078D4; color: white; border-radius: 6px;"
            "font-size: 13px; font-weight: 600; border: none; padding: 0 16px;"
        )
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._on_save)
        save_row.addWidget(self._btn_save)
        center_layout.addLayout(save_row)

        # Video Preview
        lbl_video = QLabel("Video Preview")
        lbl_video.setStyleSheet("font-size: 12px; color: #5A5A5A; font-weight: 600;")
        center_layout.addWidget(lbl_video)
        self._player = VideoPlayer()
        self._player.setFixedHeight(160)
        center_layout.addWidget(self._player)

        splitter.addWidget(center)

        # ---- Right: Inspector + History ----
        right = QWidget()
        right.setFixedWidth(240)
        right.setStyleSheet("background: #F9F9F9; border-left: 1px solid #E0E0E0;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 16, 12, 16)
        right_layout.setSpacing(12)

        # Segment Inspector
        from PyQt6.QtWidgets import QGroupBox, QFormLayout
        inspector = QGroupBox("Segment Inspector")
        ins_form = QFormLayout(inspector)
        ins_form.setSpacing(6)
        self._ins_id    = QLabel("—")
        self._ins_start = QLabel("—")
        self._ins_end   = QLabel("—")
        self._ins_dur   = QLabel("—")
        self._ins_spk   = QLabel("—")
        self._ins_conf  = ConfidenceBadge(0.0)
        ins_form.addRow("Segment #:", self._ins_id)
        ins_form.addRow("Start:", self._ins_start)
        ins_form.addRow("End:", self._ins_end)
        ins_form.addRow("Duration:", self._ins_dur)
        ins_form.addRow("Speaker:", self._ins_spk)
        ins_form.addRow("Confidence:", self._ins_conf)
        right_layout.addWidget(inspector)

        # History
        hist = QGroupBox("History")
        hist_layout = QVBoxLayout(hist)
        self._lbl_auto = QLabel("—")
        self._lbl_auto.setStyleSheet("font-size: 11px; color: #5A5A5A;")
        self._lbl_edit = QLabel("—")
        self._lbl_edit.setStyleSheet("font-size: 11px; color: #5A5A5A;")
        hist_layout.addWidget(QLabel("Auto (Gemini):"))
        hist_layout.addWidget(self._lbl_auto)
        hist_layout.addWidget(QLabel("Current Edit:"))
        hist_layout.addWidget(self._lbl_edit)
        right_layout.addWidget(hist)

        right_layout.addStretch()
        splitter.addWidget(right)

        splitter.setSizes([220, 600, 240])
        root.addWidget(splitter)

    # ------------------------------------------------------------------
    # on_activated
    # ------------------------------------------------------------------

    def on_activated(self) -> None:
        project = self._mw.project
        if not project:
            return
        self._seg_list.set_segments(project.data.segments)

        # Load video if available
        video_path = project.data.video_path
        if video_path and __import__("pathlib").Path(video_path).exists():
            self._player.load_video(video_path)

    # ------------------------------------------------------------------
    # Segment selection
    # ------------------------------------------------------------------

    def _on_segment_selected(self, seg: Segment) -> None:
        self._selected_segment = seg

        # Cập nhật inspector
        self._ins_id.setText(str(seg.id))
        self._ins_start.setText(f"{seg.start:.3f}s")
        self._ins_end.setText(f"{seg.end:.3f}s")
        self._ins_dur.setText(f"{seg.end - seg.start:.2f}s")
        self._ins_spk.setText(seg.speaker)
        self._ins_conf.set_score(seg.confidence)

        # Nạp text
        self._txt_zh.setPlainText(seg.text_zh or "")
        self._txt_vi.setPlainText(seg.text_vi or "")
        self._txt_notes.setPlainText(seg.notes or "")

        # Count
        self._update_counts()

        # History
        from datetime import datetime
        self._lbl_auto.setText(seg.updated_at.strftime("%H:%M:%S") if seg.updated_at else "—")
        self._lbl_edit.setText(datetime.now().strftime("%H:%M:%S"))

        # Seek video
        self._player.seek(seg.start)

        self._btn_save.setEnabled(True)

    # ------------------------------------------------------------------
    # Edit
    # ------------------------------------------------------------------

    def _on_vi_text_changed(self) -> None:
        self._update_counts()
        if self._selected_segment:
            self._btn_save.setEnabled(True)

    def _update_counts(self) -> None:
        zh_len = len(self._txt_zh.toPlainText())
        vi_len = len(self._txt_vi.toPlainText())
        self._lbl_zh_count.setText(f"{zh_len} / 200")
        self._lbl_vi_count.setText(f"{vi_len} / 200")

    def _on_save(self) -> None:
        if not self._selected_segment or not self._mw.project:
            return
        new_vi = self._txt_vi.toPlainText()
        notes = self._txt_notes.toPlainText()
        self._mw.project.update_segment_translation(
            self._selected_segment.id,
            new_vi,
        )
        # Refresh table
        updated = next(
            (s for s in self._mw.project.data.segments
             if s.id == self._selected_segment.id),
            None,
        )
        if updated:
            self._seg_list.update_segment(updated)
            self._selected_segment = updated
        self._btn_save.setEnabled(False)

    def _on_quick_action(self, action: str) -> None:
        """Gọi Gemini refine_segment cho action."""
        seg = self._selected_segment
        if not seg or not self._mw.project:
            return

        project = self._mw.project
        api_key = project.data.settings.gemini_api_key
        settings = project.data.settings

        # Chạy trong QThread nhỏ để không block UI
        from PyQt6.QtCore import QThread, pyqtSignal as Signal

        class _RefineThread(QThread):
            done = Signal(str)
            failed = Signal(str)

            def __init__(self, segment, action, settings, api_key):
                super().__init__()
                self.segment = segment
                self.action = action
                self.settings = settings
                self.api_key = api_key

            def run(self):
                try:
                    from msdubstudio.core.translator import refine_segment
                    result = refine_segment(self.segment, self.action, self.settings, self.api_key)
                    self.done.emit(result)
                except Exception as e:
                    self.failed.emit(str(e))

        thread = _RefineThread(seg, action, settings, api_key)
        thread.done.connect(lambda text: self._txt_vi.setPlainText(text))
        thread.failed.connect(lambda e: print(f"Refine error: {e}"))
        thread.start()
        self._refine_thread = thread  # prevent GC
