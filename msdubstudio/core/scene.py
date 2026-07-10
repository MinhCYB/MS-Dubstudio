"""
core/scene.py — PySceneDetect wrapper cho MS DubStudio

Chịu trách nhiệm:
- Phát hiện scene boundaries trong video
- Trích xuất frame đại diện cho mỗi scene
- Trả về list SceneInfo để gán vào segment.scene_frame

Không import PyQt6. Được thiết kế để mock dễ dàng trong test.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SceneDetectError(Exception):
    """Lỗi khi phát hiện scene."""


class SceneDetectLibraryError(SceneDetectError):
    """PySceneDetect không được cài đặt."""


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class SceneInfo:
    """Thông tin về một scene."""

    def __init__(
        self,
        index: int,
        start: float,
        end: float,
        frame_path: Optional[str] = None,
    ):
        self.index = index
        self.start = start  # giây
        self.end = end      # giây
        self.frame_path = frame_path

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "frame_path": self.frame_path,
        }

    def __repr__(self) -> str:
        return f"SceneInfo(index={self.index}, start={self.start:.2f}, end={self.end:.2f})"


# ---------------------------------------------------------------------------
# Main detect function
# ---------------------------------------------------------------------------


def detect_scenes(
    video_path: str,
    frames_dir: str,
    threshold: float = 27.0,
    min_scene_len: int = 15,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> list[SceneInfo]:
    """Phát hiện scene boundaries trong video.

    Args:
        video_path: Đường dẫn tới video.
        frames_dir: Thư mục để lưu frame ảnh đại diện.
        threshold: Ngưỡng phát hiện scene (Content Detector).
                   Thấp → nhạy hơn, nhiều scene hơn.
        min_scene_len: Số frame tối thiểu cho một scene.
        progress_callback: Callable(current_frame, total_frames).
        cancel_check: Callable trả về True nếu user đã Cancel.

    Returns:
        List[SceneInfo] đã có frame_path.

    Raises:
        SceneDetectLibraryError: PySceneDetect chưa cài.
        SceneDetectError: Lỗi runtime.
    """
    if not Path(video_path).exists():
        raise SceneDetectError(f"File video không tồn tại: {video_path}")

    frames_dir_path = Path(frames_dir)
    frames_dir_path.mkdir(parents=True, exist_ok=True)

    try:
        return _detect_with_pyscenedetect(
            video_path, str(frames_dir_path), threshold, min_scene_len,
            progress_callback, cancel_check
        )
    except ImportError:
        raise SceneDetectLibraryError(
            "PySceneDetect chưa được cài. Chạy: pip install scenedetect[opencv]"
        )


def _detect_with_pyscenedetect(
    video_path: str,
    frames_dir: str,
    threshold: float,
    min_scene_len: int,
    progress_callback: Optional[Callable[[int, int], None]],
    cancel_check: Optional[Callable[[], bool]],
) -> list[SceneInfo]:
    """Thực tế detect dùng PySceneDetect."""
    from scenedetect import SceneManager, open_video  # type: ignore
    from scenedetect.detectors import ContentDetector  # type: ignore
    from scenedetect.scene_manager import save_images  # type: ignore

    logger.info(f"Bắt đầu scene detect: {video_path}")

    try:
        video = open_video(video_path)
    except Exception as e:
        raise SceneDetectError(f"Không mở được video: {e}") from e

    scene_manager = SceneManager()
    scene_manager.add_detector(
        ContentDetector(threshold=threshold, min_scene_len=min_scene_len)
    )

    # Detect với progress callback
    try:
        scene_manager.detect_scenes(
            video,
            show_progress=False,
        )
    except Exception as e:
        raise SceneDetectError(f"Scene detect thất bại: {e}") from e

    scene_list = scene_manager.get_scene_list()
    logger.info(f"Tìm thấy {len(scene_list)} scene")

    if not scene_list:
        # Không tìm thấy scene nào — coi toàn bộ video là 1 scene
        duration = video.duration.get_seconds()
        return [SceneInfo(index=1, start=0.0, end=duration, frame_path=None)]

    # Lưu frame đại diện cho mỗi scene (frame ở giữa scene)
    try:
        save_images(
            scene_list,
            video,
            num_images=1,
            output_dir=frames_dir,
            image_name_template="scene_$SCENE_NUMBER",
        )
    except Exception as e:
        logger.warning(f"Không lưu được frame: {e}")

    # Tạo SceneInfo list
    scenes: list[SceneInfo] = []
    for i, (start_time, end_time) in enumerate(scene_list):
        if cancel_check and cancel_check():
            break

        start_s = start_time.get_seconds()
        end_s = end_time.get_seconds()

        # Tìm frame file tương ứng
        frame_path = _find_scene_frame_file(frames_dir, i + 1)

        scenes.append(SceneInfo(
            index=i + 1,
            start=start_s,
            end=end_s,
            frame_path=frame_path,
        ))

        if progress_callback:
            progress_callback(i + 1, len(scene_list))

    return scenes


def _find_scene_frame_file(frames_dir: str, scene_number: int) -> Optional[str]:
    """Tìm file frame ảnh cho scene number đã cho."""
    frames_dir_path = Path(frames_dir)
    # PySceneDetect tạo file dạng scene_001-01.jpg hoặc scene_1.jpg
    patterns = [
        f"scene_{scene_number:03d}-01.jpg",
        f"scene_{scene_number}-01.jpg",
        f"scene_{scene_number:03d}.jpg",
        f"scene_{scene_number}.jpg",
    ]
    for pattern in patterns:
        candidate = frames_dir_path / pattern
        if candidate.exists():
            return str(candidate)
    return None


# ---------------------------------------------------------------------------
# Scene assignment
# ---------------------------------------------------------------------------


def assign_scenes_to_segments(
    raw_segments: list[dict],
    scenes: list[SceneInfo],
) -> list[dict]:
    """Gán scene_frame cho mỗi segment theo thời gian midpoint.

    Args:
        raw_segments: List dict segment từ stt.py.
        scenes: List SceneInfo từ detect_scenes().

    Returns:
        List segment đã có scene_frame field.
    """
    scene_dicts = [s.to_dict() for s in scenes]

    updated = []
    for seg in raw_segments:
        midpoint = (seg["start"] + seg["end"]) / 2
        frame_path = _find_frame_for_time(midpoint, scene_dicts)
        updated.append({**seg, "scene_frame": frame_path})
    return updated


def _find_frame_for_time(time_s: float, scenes: list[dict]) -> Optional[str]:
    """Tìm frame_path cho thời điểm time_s."""
    # Tìm scene chứa time_s
    for scene in scenes:
        if scene["start"] <= time_s <= scene["end"]:
            return scene.get("frame_path")
    # Fallback: scene có start gần nhất
    if scenes:
        closest = min(scenes, key=lambda s: abs(s["start"] - time_s))
        return closest.get("frame_path")
    return None
