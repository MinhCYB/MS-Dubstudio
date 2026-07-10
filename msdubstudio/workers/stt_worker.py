"""
workers/stt_worker.py — Worker bước STT (Speech-to-Text)

Chạy trong QThread, gọi core/stt.py và emit signals theo mỗi segment
được nhận dạng xong.

Signals:
    started_signal()            → project.on_stt_started()
    progress(current, total)    → overlay: "Segment X / Total"
    step_log(str)               → AI console
    segment_done(dict)          → update bảng segment ngay khi xong từng câu
    finished(list[dict])        → project.on_stt_completed(raw_segments)
    error(str)                  → project.on_stt_error()
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import pyqtSignal

from msdubstudio.core.models import ProjectSettings
from msdubstudio.core.scene import SceneInfo, assign_scenes_to_segments
from msdubstudio.core.stt import (
    AudioFileError,
    STTError,
    WhisperModelNotFoundError,
    transcribe,
)
from msdubstudio.workers.base_worker import BaseWorker

logger = logging.getLogger(__name__)


class STTWorker(BaseWorker):
    """Worker chạy Whisper STT trên file audio.

    Signals:
        started_signal(): Emit ngay khi thread bắt đầu.
        progress(current, total): current = số segment đã nhận dạng,
                                  total = ước tính (tổng giây audio).
        step_log(str): Log để hiện AI console.
        segment_done(dict): Raw segment dict — UI cập nhật bảng ngay.
        finished(list): Toàn bộ raw_segments khi hoàn thành.
        error(str): Inherited — emit khi có lỗi nghiêm trọng.
    """

    started_signal = pyqtSignal()
    progress = pyqtSignal(int, int)
    step_log = pyqtSignal(str)
    segment_done = pyqtSignal(dict)
    finished = pyqtSignal(list)

    def __init__(
        self,
        audio_path: str,
        settings: ProjectSettings,
        scenes: Optional[list[SceneInfo]] = None,
        parent=None,
    ):
        """
        Args:
            audio_path: Đường dẫn file WAV đã tách từ video.
            settings: ProjectSettings (chứa Whisper config).
            scenes: List SceneInfo để gán scene_frame cho mỗi segment.
                    None nếu bước Import không detect scene.
        """
        super().__init__(parent)
        self.audio_path = audio_path
        self.settings = settings
        self.scenes = scenes or []

        # Buffer segment — tích lũy trong quá trình chạy
        self._raw_segments: list[dict] = []

    def run(self) -> None:
        start_time = time.time()

        try:
            self.started_signal.emit()
            self.step_log.emit(
                f"🎙️ Đang load Whisper model '{self.settings.whisper_model}'..."
            )
            self.step_log.emit(
                f"   Device: {self.settings.whisper_device} | "
                f"Compute: {self.settings.whisper_compute_type}"
            )

            if self.is_cancelled:
                return

            def on_progress(current_segment: int, total_duration_s: int):
                """Gọi sau mỗi segment hoàn thành bởi Whisper."""
                if self._raw_segments:
                    latest = self._raw_segments[-1]
                    self.segment_done.emit(dict(latest))
                self.progress.emit(current_segment, total_duration_s)

            try:
                raw_segments = transcribe(
                    self.audio_path,
                    self.settings,
                    progress_callback=on_progress,
                    cancel_check=lambda: self.is_cancelled,
                )
            except AudioFileError as e:
                self.error.emit(f"File audio không đọc được: {e}")
                return
            except WhisperModelNotFoundError as e:
                self.error.emit(f"Không load được Whisper model: {e}")
                return
            except STTError as e:
                self.error.emit(f"STT thất bại: {e}")
                return

            if self.is_cancelled:
                self.step_log.emit("⚠️ STT bị hủy.")
                return

            self.step_log.emit(
                f"✅ Whisper hoàn thành: {len(raw_segments)} segment "
                f"({time.time() - start_time:.1f}s)"
            )

            # Gán scene_frame nếu có
            if self.scenes:
                self.step_log.emit("🎬 Đang gán scene frame cho segment...")
                raw_segments = assign_scenes_to_segments(raw_segments, self.scenes)

            self._raw_segments = raw_segments

            # Emit summary stats
            high = sum(1 for s in raw_segments if s["confidence"] >= 0.80)
            medium = sum(1 for s in raw_segments if 0.50 <= s["confidence"] < 0.80)
            low = sum(1 for s in raw_segments if s["confidence"] < 0.50)
            self.step_log.emit(
                f"📊 Confidence: {high} cao (≥0.80) | "
                f"{medium} trung bình | {low} thấp (<0.50)"
            )

            self.finished.emit(raw_segments)

        except Exception as e:
            logger.exception(f"STTWorker lỗi không mong đợi: {e}")
            self.error.emit(f"Lỗi không mong đợi khi chạy STT: {e}")
