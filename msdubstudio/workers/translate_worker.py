"""
workers/translate_worker.py — Worker bước Translate (Gemini API)

Đây là worker phức tạp nhất vì translate_in_batches() là Generator —
worker iterate qua và emit từng BatchResult.

Signals:
    started_signal()            → project.on_translate_started()
    progress(current, total)    → overlay update
    batch_done(list)            → list[Segment] đã dịch — update bảng ngay
    batch_error(int, str)       → batch_index, error_message — tô đỏ dòng lỗi
    step_log(str)               → AI console
    finished_all()              → project.on_translate_completed()
    error(str)                  → lỗi nghiêm trọng (FatalApiError)
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from PyQt6.QtCore import pyqtSignal

from msdubstudio.core.models import ProjectSettings, Segment
from msdubstudio.core.translator import (
    FatalApiError,
    translate_in_batches,
)
from msdubstudio.workers.base_worker import BaseWorker

logger = logging.getLogger(__name__)


class TranslateWorker(BaseWorker):
    """Worker gọi Gemini API dịch segment theo batch.

    Iterate qua Generator translate_in_batches() và emit signal
    cho từng BatchResult (thành công hoặc thất bại).

    Thiết kế theo đúng thiết kế trong UI doc:
        progress = pyqtSignal(int, int)      # current, total
        batch_done = pyqtSignal(list)        # list[Segment]
        batch_error = pyqtSignal(int, str)   # batch_index, error_message
        finished_all = pyqtSignal()

    Signals:
        started_signal(): Emit ngay khi thread bắt đầu.
        progress(current, total): Tiến độ theo số segment.
        batch_done(list): List Segment đã dịch thành công trong batch này.
        batch_error(int, str): Batch thất bại — index và error message.
        step_log(str): Log realtime cho AI console.
        finished_all(): Emit khi tất cả batch hoàn thành (kể cả có lỗi).
        error(str): Lỗi nghiêm trọng dừng toàn bộ pipeline.
    """

    started_signal = pyqtSignal()
    progress = pyqtSignal(int, int)
    batch_done = pyqtSignal(list)
    batch_error = pyqtSignal(int, str)
    step_log = pyqtSignal(str)
    finished_all = pyqtSignal()

    def __init__(
        self,
        segments: list[Segment],
        settings: ProjectSettings,
        api_key: str,
        max_concurrent_batches: int = 2,
        parent=None,
    ):
        """
        Args:
            segments: Toàn bộ segments (kể cả đã dịch — sẽ bị bỏ qua).
            settings: ProjectSettings.
            api_key: Gemini API key.
            max_concurrent_batches: Số batch chạy đồng thời tối đa.
        """
        super().__init__(parent)
        self.segments = segments
        self.settings = settings
        self.api_key = api_key
        self.max_concurrent_batches = max_concurrent_batches

    def run(self) -> None:
        start_time = time.time()
        total_to_translate = sum(
            1 for s in self.segments
            if s.status.value not in ("translated", "reviewed")
        )

        try:
            self.started_signal.emit()

            if total_to_translate == 0:
                self.step_log.emit(
                    "ℹ️ Tất cả segment đã được dịch — không có gì để làm."
                )
                self.finished_all.emit()
                return

            self.step_log.emit(
                f"🌐 Bắt đầu dịch {total_to_translate} segment "
                f"(model: {self.settings.gemini_model}, "
                f"batch size: {self.settings.batch_size})"
            )

            success_count = 0
            error_count = 0

            for result in translate_in_batches(
                self.segments,
                self.settings,
                self.api_key,
                cancel_check=lambda: self.is_cancelled,
                max_concurrent_batches=self.max_concurrent_batches,
            ):
                if self.is_cancelled:
                    self.step_log.emit("⚠️ Dịch bị hủy.")
                    break

                self.progress.emit(result.current, result.total)

                if result.is_error:
                    error_count += 1
                    self.batch_error.emit(
                        result.batch_index,
                        result.error_message or "Unknown error",
                    )
                    self.step_log.emit(
                        f"❌ Batch {result.batch_index + 1} lỗi: "
                        f"{result.error_message}"
                    )
                else:
                    success_count += len(result.segments)
                    self.batch_done.emit(result.segments)
                    self.step_log.emit(
                        f"✅ Batch {result.batch_index + 1}: "
                        f"{len(result.segments)} câu ({result.progress_pct}%)"
                    )

            elapsed = time.time() - start_time
            self.step_log.emit(
                f"🎉 Dịch hoàn thành: {success_count} câu thành công, "
                f"{error_count} batch lỗi ({elapsed:.1f}s)"
            )

            self.finished_all.emit()

        except FatalApiError as e:
            # FatalApiError: API key sai, model không tồn tại — dừng toàn bộ
            logger.error(f"TranslateWorker FatalApiError: {e}")
            self.error.emit(str(e))
        except Exception as e:
            logger.exception(f"TranslateWorker lỗi không mong đợi: {e}")
            self.error.emit(f"Lỗi không mong đợi khi dịch: {e}")
