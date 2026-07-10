"""
workers/tts_worker.py — Worker bước Voice/TTS

Chạy trong QThread, gọi core/tts.py để sinh audio TTS từng segment.
Implement TTS idempotency: chỉ sinh lại segment có text_vi thay đổi.

Signals:
    started_signal()             → project.on_voice_started()
    progress(current, total)     → overlay update
    step_log(str)                → AI console
    segment_done(int, str)       → segment_id, voice_path — update table ngay
    segment_error(int, str)      → segment_id, error_message
    finished()                   → project.on_voice_completed()
    error(str)                   → lỗi nghiêm trọng
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from PyQt6.QtCore import pyqtSignal

from msdubstudio.core.models import ProjectSettings, Segment, Speaker
from msdubstudio.core.tts import (
    DEFAULT_FEMALE_VOICE,
    DEFAULT_MALE_VOICE,
    TTSEngineNotFoundError,
    TTSError,
    synthesize_segments,
)
from msdubstudio.workers.base_worker import BaseWorker

logger = logging.getLogger(__name__)


class TTSWorker(BaseWorker):
    """Worker sinh audio TTS cho các segment cần tạo/tạo lại.

    Chỉ sinh TTS cho segment có needs_tts_regeneration=True (idempotency).
    Emit segment_done sau mỗi segment xong để UI update ngay.

    Signals:
        started_signal(): Emit ngay khi thread bắt đầu.
        progress(current, total): Tiến độ theo segment.
        step_log(str): Log realtime cho AI console.
        segment_done(int, str): segment_id, voice_path — TTS thành công.
        segment_error(int, str): segment_id, error_message — TTS thất bại.
        finished(): Emit khi tất cả segment được xử lý.
        error(str): Inherited — lỗi engine nghiêm trọng.
    """

    started_signal = pyqtSignal()
    progress = pyqtSignal(int, int)
    step_log = pyqtSignal(str)
    segment_done = pyqtSignal(int, str)   # segment_id, voice_path
    segment_error = pyqtSignal(int, str)  # segment_id, error_message
    finished = pyqtSignal()

    def __init__(
        self,
        segments: list[Segment],
        speakers: dict[str, Speaker],
        voice_dir: str,
        settings: ProjectSettings,
        parent=None,
    ):
        """
        Args:
            segments: Toàn bộ segments. Worker tự lọc cần TTS.
            speakers: Dict speaker_id → Speaker (chứa voice_id, gender, etc.)
            voice_dir: Thư mục lưu file audio TTS.
            settings: ProjectSettings (chứa tts_engine).
        """
        super().__init__(parent)
        self.segments = segments
        self.speakers = speakers
        self.voice_dir = voice_dir
        self.settings = settings

    def run(self) -> None:
        start_time = time.time()

        try:
            self.started_signal.emit()

            # Filter: chỉ segment cần TTS (idempotency)
            to_tts = [s for s in self.segments if s.needs_tts_regeneration and s.text_vi]

            if not to_tts:
                self.step_log.emit("ℹ️ Không có segment nào cần sinh TTS.")
                self.finished.emit()
                return

            self.step_log.emit(
                f"🔊 Bắt đầu sinh TTS cho {len(to_tts)} segment "
                f"(engine: {self.settings.tts_engine})"
            )

            # Chuyển Segment → dict cho synthesize_segments()
            seg_dicts = [
                {"id": s.id, "text_vi": s.text_vi, "speaker": s.speaker}
                for s in to_tts
            ]

            success_count = 0
            error_count = 0

            def on_progress(current: int, total: int):
                self.progress.emit(current, total)

            try:
                results = synthesize_segments(
                    segments=seg_dicts,
                    voice_dir=self.voice_dir,
                    get_voice_id=self._get_voice_id,
                    get_rate=self._get_rate,
                    get_pitch=self._get_pitch,
                    get_volume=self._get_volume,
                    engine=self.settings.tts_engine,
                    progress_callback=on_progress,
                    cancel_check=lambda: self.is_cancelled,
                )
            except TTSEngineNotFoundError as e:
                self.error.emit(str(e))
                return

            for result in results:
                if result["success"]:
                    success_count += 1
                    self.segment_done.emit(result["segment_id"], result["voice_path"])
                    self.step_log.emit(
                        f"✅ Segment {result['segment_id']}: audio ok"
                    )
                else:
                    error_count += 1
                    self.segment_error.emit(
                        result["segment_id"], result["error_message"] or "TTS error"
                    )
                    self.step_log.emit(
                        f"❌ Segment {result['segment_id']}: {result['error_message']}"
                    )

            elapsed = time.time() - start_time
            self.step_log.emit(
                f"🎉 TTS hoàn thành: {success_count} thành công, "
                f"{error_count} lỗi ({elapsed:.1f}s)"
            )

            if not self.is_cancelled:
                self.finished.emit()

        except Exception as e:
            logger.exception(f"TTSWorker lỗi không mong đợi: {e}")
            self.error.emit(f"Lỗi không mong đợi khi sinh TTS: {e}")

    # ------------------------------------------------------------------
    # Speaker voice lookup helpers
    # ------------------------------------------------------------------

    def _get_voice_id(self, speaker_id: str) -> str:
        """Lấy voice_id của speaker, fallback về default."""
        speaker = self.speakers.get(speaker_id)
        if speaker and speaker.voice_id:
            return speaker.voice_id
        # Fallback theo gender
        if speaker:
            if speaker.gender == "male":
                return DEFAULT_MALE_VOICE
            elif speaker.gender == "female":
                return DEFAULT_FEMALE_VOICE
        return DEFAULT_FEMALE_VOICE

    def _get_rate(self, speaker_id: str) -> str:
        """Tốc độ đọc cho speaker (mặc định +0%)."""
        return "+0%"

    def _get_pitch(self, speaker_id: str) -> str:
        """Cao độ giọng cho speaker (mặc định +0Hz)."""
        return "+0Hz"

    def _get_volume(self, speaker_id: str) -> str:
        """Âm lượng cho speaker (mặc định +0%)."""
        return "+0%"
