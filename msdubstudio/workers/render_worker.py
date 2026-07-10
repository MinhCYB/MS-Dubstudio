"""
workers/render_worker.py — Worker bước Export/Render

Chạy trong QThread, gọi core/render.py để render video cuối.

Signals:
    started_signal()             → project.on_export_started()
    progress(current, total)     → overlay update (frame-level)
    step_log(str)                → AI console
    finished(str)                → output_path — render thành công
    error(str)                   → lỗi nghiêm trọng
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PyQt6.QtCore import pyqtSignal

from msdubstudio.core.models import Segment
from msdubstudio.core.render import (
    ExportSettings,
    FFmpegRenderError,
    RenderError,
    render_video,
)
from msdubstudio.workers.base_worker import BaseWorker

logger = logging.getLogger(__name__)


class RenderWorker(BaseWorker):
    """Worker render video đã lồng tiếng.

    Signals:
        started_signal(): Emit ngay khi thread bắt đầu.
        progress(current, total): Tiến độ theo frame (tương lai).
        step_log(str): Log cho AI console.
        finished(str): output_path khi render thành công.
        error(str): Inherited — lỗi ffmpeg nghiêm trọng.
    """

    started_signal = pyqtSignal()
    progress = pyqtSignal(int, int)
    step_log = pyqtSignal(str)
    finished = pyqtSignal(str)  # output_path

    def __init__(
        self,
        video_path: str,
        segments: list[Segment],
        export_settings: ExportSettings,
        parent=None,
    ):
        """
        Args:
            video_path: Đường dẫn video gốc.
            segments: Toàn bộ segments (worker lọc có voice_path).
            export_settings: Cài đặt xuất video.
        """
        super().__init__(parent)
        self.video_path = video_path
        self.segments = segments
        self.export_settings = export_settings

    def run(self) -> None:
        start_time = time.time()

        try:
            self.started_signal.emit()

            # Chuyển Segment → dict để render.py dùng
            seg_dicts = [
                {
                    "id": s.id,
                    "start": s.start,
                    "end": s.end,
                    "speaker": s.speaker,
                    "voice_path": s.voice_path,
                }
                for s in self.segments
            ]

            voiced_count = sum(
                1 for s in seg_dicts
                if s.get("voice_path") and Path(s["voice_path"]).exists()
            )

            self.step_log.emit(
                f"🎬 Bắt đầu render: {voiced_count}/{len(seg_dicts)} segment có audio"
            )
            self.step_log.emit(
                f"   Output: {self.export_settings.output_path}"
            )

            if voiced_count == 0:
                self.error.emit(
                    "Không có segment nào có audio TTS. "
                    "Hãy chạy bước Voice trước khi Export."
                )
                return

            def on_progress(current: int, total: int):
                self.progress.emit(current, total)

            try:
                output_path = render_video(
                    video_path=self.video_path,
                    segments=seg_dicts,
                    voice_dir="",  # voice_path đã được gán trong seg_dicts
                    export_settings=self.export_settings,
                    progress_callback=on_progress,
                    cancel_check=lambda: self.is_cancelled,
                )
            except RenderError as e:
                self.error.emit(str(e))
                return
            except FFmpegRenderError as e:
                self.error.emit(f"ffmpeg thất bại: {e}")
                return

            elapsed = time.time() - start_time
            self.step_log.emit(
                f"🎉 Render hoàn thành ({elapsed:.1f}s): {output_path}"
            )

            if not self.is_cancelled:
                self.finished.emit(output_path)

        except Exception as e:
            logger.exception(f"RenderWorker lỗi không mong đợi: {e}")
            self.error.emit(f"Lỗi không mong đợi khi render: {e}")
