"""
workers/import_worker.py — Worker xử lý bước Import

Chạy trong QThread:
1. Lấy metadata video (ffprobe — nhanh, nhưng vẫn I/O)
2. Tách audio → audio/audio.wav (có thể mất vài giây với video dài)
3. Detect scenes (PySceneDetect — có thể mất 30-60s tùy video)

Emit signals:
    started()           → project.on_import_started()
    progress(int, int)  → overlay update
    step_log(str)       → AI console log từng bước con
    finished(VideoMetadata, list[SceneInfo])  → project.on_import_completed()
    error(str)          → project.on_import_error()
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import pyqtSignal

from msdubstudio.core.media_io import (
    AudioExtractionError,
    FFmpegNotFoundError,
    VideoFileError,
    extract_audio,
    get_video_metadata,
)
from msdubstudio.core.models import ProjectSettings, VideoMetadata
from msdubstudio.core.scene import SceneInfo, detect_scenes
from msdubstudio.workers.base_worker import BaseWorker

logger = logging.getLogger(__name__)


class ImportWorker(BaseWorker):
    """Worker bước Import: metadata + audio extraction + scene detect.

    Signals:
        started(): Emit ngay khi thread bắt đầu chạy.
        progress(current, total): Tiến độ tổng (0/3, 1/3, 2/3, 3/3).
        step_log(message): Log từng bước con để hiện AI console.
        finished(VideoMetadata, list): Emit khi tất cả xong thành công.
        error(str): Inherited từ BaseWorker — emit khi có lỗi nghiêm trọng.
    """

    started_signal = pyqtSignal()
    progress = pyqtSignal(int, int)  # current_step (0-3), total_steps (3)
    step_log = pyqtSignal(str)       # message để hiện trong AI console
    finished = pyqtSignal(object, list)  # (VideoMetadata, list[SceneInfo])

    def __init__(
        self,
        video_path: str,
        audio_output_path: str,
        frames_dir: str,
        settings: ProjectSettings,
        parent=None,
    ):
        """
        Args:
            video_path: Đường dẫn video nguồn.
            audio_output_path: Đường dẫn lưu audio.wav.
            frames_dir: Thư mục lưu frame ảnh scene.
            settings: ProjectSettings (chứa detect_scenes, detect_language flag).
        """
        super().__init__(parent)
        self.video_path = video_path
        self.audio_output_path = audio_output_path
        self.frames_dir = frames_dir
        self.settings = settings

    def run(self) -> None:
        start_time = time.time()
        total_steps = 3  # metadata + audio + scenes

        try:
            self.started_signal.emit()

            # --- Bước 1: Lấy metadata ---
            self.step_log.emit("📋 Đang đọc thông tin video...")
            self.progress.emit(0, total_steps)

            if self.is_cancelled:
                return

            try:
                metadata = get_video_metadata(self.video_path)
            except (VideoFileError, FFmpegNotFoundError) as e:
                self.error.emit(str(e))
                return

            self.step_log.emit(
                f"✅ Video: {metadata.width}×{metadata.height} "
                f"@ {metadata.fps:.2f}fps, {metadata.duration:.1f}s"
            )
            self.progress.emit(1, total_steps)

            # --- Bước 2: Tách audio ---
            if self.is_cancelled:
                return

            self.step_log.emit("🎵 Đang tách audio (16kHz mono)...")

            try:
                extract_audio(
                    self.video_path,
                    self.audio_output_path,
                    sample_rate=16000,
                    channels=1,
                )
            except (FFmpegNotFoundError, AudioExtractionError) as e:
                self.error.emit(str(e))
                return

            elapsed = time.time() - start_time
            self.step_log.emit(
                f"✅ Audio: {Path(self.audio_output_path).name} "
                f"({elapsed:.1f}s)"
            )
            self.progress.emit(2, total_steps)

            # --- Bước 3: Detect scenes ---
            scenes: list[SceneInfo] = []
            if self.settings.detect_scenes and not self.is_cancelled:
                self.step_log.emit("🎬 Đang phát hiện cảnh (PySceneDetect)...")
                try:
                    scenes = detect_scenes(
                        self.video_path,
                        self.frames_dir,
                        cancel_check=lambda: self.is_cancelled,
                        progress_callback=lambda c, t: None,  # tương lai: finer progress
                    )
                    self.step_log.emit(f"✅ Phát hiện {len(scenes)} cảnh.")
                except Exception as e:
                    # Scene detect lỗi không dừng import — warning thay vì error
                    self.step_log.emit(f"⚠️ Scene detect thất bại: {e}. Bỏ qua.")
                    logger.warning(f"Scene detect failed: {e}")

            self.progress.emit(3, total_steps)

            if not self.is_cancelled:
                self.finished.emit(metadata, scenes)
                self.step_log.emit(
                    f"🎉 Import hoàn thành ({time.time() - start_time:.1f}s)"
                )

        except Exception as e:
            logger.exception(f"ImportWorker lỗi không mong đợi: {e}")
            self.error.emit(f"Lỗi không mong đợi khi import: {e}")
