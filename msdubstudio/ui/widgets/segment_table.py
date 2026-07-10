"""
ui/widgets/segment_table.py — Bảng segment tái sử dụng (STT / Translate / Review)

Dùng QTableView + QAbstractTableModel (không QTableWidget) để hỗ trợ 500+ dòng
với hiệu năng tốt.

Columns có thể cấu hình theo từng view:
- STT view:       #, Start, End, Speaker, Confidence, Text (Chinese)
- Translate view: #, Start, End, Chinese, Vietnamese, Confidence, Status
- Review view:    #, Start, End, Vietnamese, Status (click-to-edit)
"""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    pyqtSignal,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLineEdit,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from msdubstudio.core.models import Segment, SegmentStatus
from msdubstudio.ui.widgets.confidence_badge import ConfidenceDelegate


# ---------------------------------------------------------------------------
# Column Definitions
# ---------------------------------------------------------------------------

class Col:
    """Column ID constants."""
    IDX       = "idx"
    START     = "start"
    END       = "end"
    SPEAKER   = "speaker"
    CONFIDENCE = "confidence"
    TEXT_ZH   = "text_zh"
    TEXT_VI   = "text_vi"
    STATUS    = "status"


# Preset column sets
COLUMNS_STT = [Col.IDX, Col.START, Col.END, Col.SPEAKER, Col.CONFIDENCE, Col.TEXT_ZH]
COLUMNS_TRANSLATE = [Col.IDX, Col.START, Col.END, Col.TEXT_ZH, Col.TEXT_VI, Col.CONFIDENCE, Col.STATUS]
COLUMNS_REVIEW = [Col.IDX, Col.START, Col.END, Col.TEXT_VI, Col.STATUS]

_HEADERS = {
    Col.IDX:        "#",
    Col.START:      "Start",
    Col.END:        "End",
    Col.SPEAKER:    "Speaker",
    Col.CONFIDENCE: "Confidence",
    Col.TEXT_ZH:    "Chinese (Original)",
    Col.TEXT_VI:    "Vietnamese (Translation)",
    Col.STATUS:     "Status",
}

_COL_WIDTHS = {
    Col.IDX:        45,
    Col.START:      80,
    Col.END:        80,
    Col.SPEAKER:    65,
    Col.CONFIDENCE: 90,
    Col.TEXT_ZH:    260,
    Col.TEXT_VI:    260,
    Col.STATUS:     80,
}


def _format_time(seconds: float) -> str:
    """3.5 → '00:00:03.50'"""
    total_cs = int(seconds * 100)
    h = total_cs // 360000
    rem = total_cs % 360000
    m = rem // 6000
    rem %= 6000
    s = rem // 100
    cs = rem % 100
    return f"{h:02d}:{m:02d}:{s:02d}.{cs:02d}"


# ---------------------------------------------------------------------------
# SegmentTableModel
# ---------------------------------------------------------------------------

_STATUS_DISPLAY = {
    SegmentStatus.PENDING:    "Pending",
    SegmentStatus.TRANSLATED: "Translated",
    SegmentStatus.ERROR:      "Error",
    SegmentStatus.REVIEWED:   "Reviewed",
}

_STATUS_FG = {
    SegmentStatus.PENDING:    "#5A5A5A",
    SegmentStatus.TRANSLATED: "#107C10",
    SegmentStatus.ERROR:      "#D13438",
    SegmentStatus.REVIEWED:   "#0078D4",
}

_STATUS_BG = {
    SegmentStatus.ERROR: "#FDE7E9",
}


class SegmentTableModel(QAbstractTableModel):
    """Model nguồn sự thật cho bảng segment.

    Hỗ trợ:
    - Lazy update: `set_segments()` / `update_segment()` / `append_segment()`
    - Column preset bằng `columns` list
    - Error row highlight qua `data(BackgroundRole)`
    """

    def __init__(
        self,
        segments: list[Segment] | None = None,
        columns: list[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._segments: list[Segment] = segments or []
        self._columns: list[str] = columns or COLUMNS_STT

    # ------------------------------------------------------------------
    # QAbstractTableModel interface
    # ------------------------------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._segments)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._columns)

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole) -> Any:
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                col = self._columns[section]
                return _HEADERS.get(col, col)
            else:
                return str(section + 1)
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None

        seg = self._segments[index.row()]
        col = self._columns[index.column()]

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display_data(seg, col)

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == Col.STATUS:
                from PyQt6.QtGui import QBrush, QColor
                return QBrush(QColor(_STATUS_FG.get(seg.status, "#1C1C1C")))

        if role == Qt.ItemDataRole.BackgroundRole:
            from PyQt6.QtGui import QBrush, QColor
            if seg.status == SegmentStatus.ERROR:
                return QBrush(QColor("#FDE7E9"))

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (Col.IDX, Col.START, Col.END, Col.SPEAKER, Col.CONFIDENCE):
                return Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.UserRole:
            return seg  # Trả về Segment object để view xử lý

        return None

    def _display_data(self, seg: Segment, col: str) -> str:
        if col == Col.IDX:
            return str(seg.id)
        if col == Col.START:
            return _format_time(seg.start)
        if col == Col.END:
            return _format_time(seg.end)
        if col == Col.SPEAKER:
            return seg.speaker
        if col == Col.CONFIDENCE:
            return f"{seg.confidence:.2f}"
        if col == Col.TEXT_ZH:
            return seg.text_zh or ""
        if col == Col.TEXT_VI:
            return seg.text_vi or ""
        if col == Col.STATUS:
            return _STATUS_DISPLAY.get(seg.status, seg.status)
        return ""

    # ------------------------------------------------------------------
    # Mutation API
    # ------------------------------------------------------------------

    def set_segments(self, segments: list[Segment]) -> None:
        """Thay thế toàn bộ dữ liệu, reset model."""
        self.beginResetModel()
        self._segments = list(segments)
        self.endResetModel()

    def update_segment(self, segment: Segment) -> None:
        """Cập nhật 1 segment (tìm theo id)."""
        for row, s in enumerate(self._segments):
            if s.id == segment.id:
                self._segments[row] = segment
                top_left = self.index(row, 0)
                bottom_right = self.index(row, self.columnCount() - 1)
                self.dataChanged.emit(top_left, bottom_right)
                return
        # Không tìm thấy → append
        self.append_segment(segment)

    def append_segment(self, segment: Segment) -> None:
        """Thêm segment mới vào cuối (dùng khi STT emit từng segment)."""
        row = len(self._segments)
        self.beginInsertRows(QModelIndex(), row, row)
        self._segments.append(segment)
        self.endInsertRows()

    def get_segment_at_row(self, row: int) -> Optional[Segment]:
        if 0 <= row < len(self._segments):
            return self._segments[row]
        return None

    def get_all_segments(self) -> list[Segment]:
        return list(self._segments)

    def set_columns(self, columns: list[str]) -> None:
        self.beginResetModel()
        self._columns = columns
        self.endResetModel()


# ---------------------------------------------------------------------------
# SegmentTableView
# ---------------------------------------------------------------------------

class SegmentTableView(QWidget):
    """Widget tổng hợp: search bar + QTableView với SegmentTableModel.

    Signals:
        segment_selected(Segment): Emit khi user click vào 1 dòng.
        segment_double_clicked(Segment): Emit khi double-click (mở editor).
    """

    segment_selected = pyqtSignal(object)      # Segment
    segment_double_clicked = pyqtSignal(object)  # Segment

    def __init__(
        self,
        columns: list[str] | None = None,
        show_search: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._columns = columns or COLUMNS_STT
        self._show_search = show_search

        self._model = SegmentTableModel(columns=self._columns)
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)  # search tất cả columns

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        if self._show_search:
            search_row = QHBoxLayout()
            self._search = QLineEdit()
            self._search.setPlaceholderText("🔍  Search segments…")
            self._search.textChanged.connect(self._proxy.setFilterFixedString)
            search_row.addWidget(self._search)
            layout.addLayout(search_row)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setDefaultSectionSize(36)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setShowGrid(False)
        self._table.setSortingEnabled(False)

        # Confidence delegate
        conf_cols = [i for i, c in enumerate(self._columns) if c == Col.CONFIDENCE]
        for col_idx in conf_cols:
            self._table.setItemDelegateForColumn(col_idx, ConfidenceDelegate(self._table))

        # Column widths
        for i, col in enumerate(self._columns):
            w = _COL_WIDTHS.get(col, 100)
            self._table.setColumnWidth(i, w)

        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._table.doubleClicked.connect(self._on_double_clicked)

        layout.addWidget(self._table)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_segments(self, segments: list[Segment]) -> None:
        self._model.set_segments(segments)

    def update_segment(self, segment: Segment) -> None:
        self._model.update_segment(segment)

    def append_segment(self, segment: Segment) -> None:
        self._model.append_segment(segment)

    def get_selected_segment(self) -> Optional[Segment]:
        indexes = self._table.selectionModel().selectedRows()
        if not indexes:
            return None
        proxy_idx = indexes[0]
        source_idx = self._proxy.mapToSource(proxy_idx)
        return self._model.get_segment_at_row(source_idx.row())

    def select_segment_by_id(self, seg_id: int) -> None:
        """Select dòng có segment.id == seg_id."""
        for row in range(self._model.rowCount()):
            seg = self._model.get_segment_at_row(row)
            if seg and seg.id == seg_id:
                proxy_idx = self._proxy.mapFromSource(self._model.index(row, 0))
                self._table.selectRow(proxy_idx.row())
                self._table.scrollTo(proxy_idx)
                return

    def set_columns(self, columns: list[str]) -> None:
        self._columns = columns
        self._model.set_columns(columns)
        # Reapply column widths
        for i, col in enumerate(columns):
            self._table.setColumnWidth(i, _COL_WIDTHS.get(col, 100))
        # Reapply confidence delegate
        conf_cols = [i for i, c in enumerate(columns) if c == Col.CONFIDENCE]
        for col_idx in conf_cols:
            self._table.setItemDelegateForColumn(col_idx, ConfidenceDelegate(self._table))

    def clear_search(self) -> None:
        if hasattr(self, "_search"):
            self._search.clear()

    @property
    def model(self) -> SegmentTableModel:
        return self._model

    # ------------------------------------------------------------------
    # Private slots
    # ------------------------------------------------------------------

    def _on_selection_changed(self, selected, _deselected) -> None:
        indexes = selected.indexes()
        if indexes:
            proxy_idx = indexes[0]
            source_idx = self._proxy.mapToSource(proxy_idx)
            seg = self._model.get_segment_at_row(source_idx.row())
            if seg:
                self.segment_selected.emit(seg)

    def _on_double_clicked(self, proxy_idx: QModelIndex) -> None:
        source_idx = self._proxy.mapToSource(proxy_idx)
        seg = self._model.get_segment_at_row(source_idx.row())
        if seg:
            self.segment_double_clicked.emit(seg)
