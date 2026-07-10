"""
tests/core/test_scene.py — Unit tests for core/scene.py

Kiểm tra scene detection và assignment với mock PySceneDetect.
Không chạy detection thật trong automated test.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from msdubstudio.core.scene import (
    SceneDetectError,
    SceneDetectLibraryError,
    SceneInfo,
    _find_frame_for_time,
    assign_scenes_to_segments,
    detect_scenes,
)


# ---------------------------------------------------------------------------
# Tests: SceneInfo
# ---------------------------------------------------------------------------


class TestSceneInfo:
    def test_create(self):
        scene = SceneInfo(index=1, start=0.0, end=5.3, frame_path="/frames/scene_001.jpg")
        assert scene.index == 1
        assert scene.duration == pytest.approx(5.3)
        assert scene.frame_path == "/frames/scene_001.jpg"

    def test_to_dict(self):
        scene = SceneInfo(index=2, start=5.3, end=12.1, frame_path="/frames/scene_002.jpg")
        d = scene.to_dict()
        assert d["index"] == 2
        assert d["start"] == pytest.approx(5.3)
        assert d["end"] == pytest.approx(12.1)
        assert d["frame_path"] == "/frames/scene_002.jpg"

    def test_to_dict_no_frame(self):
        scene = SceneInfo(index=1, start=0.0, end=10.0, frame_path=None)
        d = scene.to_dict()
        assert d["frame_path"] is None


# ---------------------------------------------------------------------------
# Tests: detect_scenes()
# ---------------------------------------------------------------------------


class TestDetectScenes:
    @pytest.fixture
    def video_file(self, tmp_path: Path) -> Path:
        f = tmp_path / "test.mp4"
        f.write_bytes(b"fake mp4 data")
        return f

    @pytest.fixture
    def frames_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "frames"
        d.mkdir()
        return d

    def test_raises_if_video_not_found(self, tmp_path: Path):
        with pytest.raises(SceneDetectError):
            detect_scenes("/nonexistent/video.mp4", str(tmp_path / "frames"))

    def test_raises_if_pyscenedetect_not_installed(
        self, video_file: Path, frames_dir: Path
    ):
        with patch.dict("sys.modules", {
            "scenedetect": None,
            "scenedetect.detectors": None,
            "scenedetect.scene_manager": None,
        }):
            with pytest.raises(SceneDetectLibraryError) as exc_info:
                detect_scenes(str(video_file), str(frames_dir))
            assert "pip install" in str(exc_info.value)

    def test_detect_returns_scene_infos(self, video_file: Path, frames_dir: Path):
        """Mock PySceneDetect để test return value shape."""
        # Mock scene time objects
        def make_time(seconds: float):
            t = MagicMock()
            t.get_seconds.return_value = seconds
            return t

        mock_scene_list = [
            (make_time(0.0), make_time(8.3)),
            (make_time(8.3), make_time(19.7)),
            (make_time(19.7), make_time(30.0)),
        ]

        mock_video = MagicMock()
        mock_video.duration.get_seconds.return_value = 30.0

        mock_scene_manager = MagicMock()
        mock_scene_manager.get_scene_list.return_value = mock_scene_list

        mock_scenedetect = MagicMock()
        mock_scenedetect.open_video.return_value = mock_video
        mock_scenedetect.SceneManager.return_value = mock_scene_manager

        mock_detector = MagicMock()
        mock_detectors = MagicMock()
        mock_detectors.ContentDetector.return_value = mock_detector

        mock_save_images = MagicMock()
        mock_scene_manager_module = MagicMock()
        mock_scene_manager_module.save_images = mock_save_images

        with patch.dict("sys.modules", {
            "scenedetect": mock_scenedetect,
            "scenedetect.detectors": mock_detectors,
            "scenedetect.scene_manager": mock_scene_manager_module,
        }):
            result = detect_scenes(str(video_file), str(frames_dir))

        assert len(result) == 3
        assert result[0].index == 1
        assert result[0].start == pytest.approx(0.0)
        assert result[0].end == pytest.approx(8.3)
        assert result[1].start == pytest.approx(8.3)
        assert result[2].end == pytest.approx(30.0)

    def test_no_scenes_returns_single_scene(self, video_file: Path, frames_dir: Path):
        """Khi không phát hiện scene nào → trả về 1 scene bao toàn bộ video."""
        mock_video = MagicMock()
        mock_video.duration.get_seconds.return_value = 60.0

        mock_scene_manager = MagicMock()
        mock_scene_manager.get_scene_list.return_value = []  # không có scene

        mock_scenedetect = MagicMock()
        mock_scenedetect.open_video.return_value = mock_video
        mock_scenedetect.SceneManager.return_value = mock_scene_manager

        mock_detectors = MagicMock()
        mock_detectors.ContentDetector.return_value = MagicMock()
        mock_scene_manager_module = MagicMock()

        with patch.dict("sys.modules", {
            "scenedetect": mock_scenedetect,
            "scenedetect.detectors": mock_detectors,
            "scenedetect.scene_manager": mock_scene_manager_module,
        }):
            result = detect_scenes(str(video_file), str(frames_dir))

        assert len(result) == 1
        assert result[0].start == pytest.approx(0.0)
        assert result[0].end == pytest.approx(60.0)

    def test_progress_callback_called(self, video_file: Path, frames_dir: Path):
        def make_time(seconds: float):
            t = MagicMock()
            t.get_seconds.return_value = seconds
            return t

        mock_scene_list = [
            (make_time(0.0), make_time(5.0)),
            (make_time(5.0), make_time(10.0)),
        ]

        mock_video = MagicMock()
        mock_scene_manager = MagicMock()
        mock_scene_manager.get_scene_list.return_value = mock_scene_list
        mock_scenedetect = MagicMock()
        mock_scenedetect.open_video.return_value = mock_video
        mock_scenedetect.SceneManager.return_value = mock_scene_manager
        mock_detectors = MagicMock()
        mock_detectors.ContentDetector.return_value = MagicMock()
        mock_sm_module = MagicMock()

        progress_calls = []
        with patch.dict("sys.modules", {
            "scenedetect": mock_scenedetect,
            "scenedetect.detectors": mock_detectors,
            "scenedetect.scene_manager": mock_sm_module,
        }):
            detect_scenes(
                str(video_file),
                str(frames_dir),
                progress_callback=lambda c, t: progress_calls.append((c, t))
            )

        assert len(progress_calls) == 2
        assert progress_calls[0] == (1, 2)
        assert progress_calls[1] == (2, 2)

    def test_cancel_stops_processing(self, video_file: Path, frames_dir: Path):
        def make_time(s: float):
            t = MagicMock()
            t.get_seconds.return_value = s
            return t

        mock_scene_list = [
            (make_time(0.0), make_time(5.0)),
            (make_time(5.0), make_time(10.0)),
            (make_time(10.0), make_time(15.0)),
        ]

        mock_video = MagicMock()
        mock_sm = MagicMock()
        mock_sm.get_scene_list.return_value = mock_scene_list
        mock_sd = MagicMock()
        mock_sd.open_video.return_value = mock_video
        mock_sd.SceneManager.return_value = mock_sm
        mock_det = MagicMock()
        mock_det.ContentDetector.return_value = MagicMock()
        mock_sm_mod = MagicMock()

        with patch.dict("sys.modules", {
            "scenedetect": mock_sd,
            "scenedetect.detectors": mock_det,
            "scenedetect.scene_manager": mock_sm_mod,
        }):
            result = detect_scenes(
                str(video_file), str(frames_dir),
                cancel_check=lambda: True  # cancel ngay lập tức
            )

        # Cancel ngay từ vòng đầu → không có scene nào được append
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Tests: _find_frame_for_time
# ---------------------------------------------------------------------------


class TestFindFrameForTime:
    def test_finds_exact_scene(self):
        scenes = [
            {"start": 0.0, "end": 10.0, "frame_path": "/frames/s1.jpg"},
            {"start": 10.0, "end": 20.0, "frame_path": "/frames/s2.jpg"},
        ]
        assert _find_frame_for_time(5.0, scenes) == "/frames/s1.jpg"
        assert _find_frame_for_time(15.0, scenes) == "/frames/s2.jpg"

    def test_fallback_to_closest(self):
        scenes = [
            {"start": 0.0, "end": 10.0, "frame_path": "/frames/s1.jpg"},
        ]
        # time=50 nằm ngoài scene duy nhất → fallback về scene đó
        assert _find_frame_for_time(50.0, scenes) == "/frames/s1.jpg"

    def test_empty_scenes_returns_none(self):
        assert _find_frame_for_time(5.0, []) is None

    def test_returns_none_if_frame_path_missing(self):
        scenes = [{"start": 0.0, "end": 10.0, "frame_path": None}]
        result = _find_frame_for_time(5.0, scenes)
        assert result is None


# ---------------------------------------------------------------------------
# Tests: assign_scenes_to_segments
# ---------------------------------------------------------------------------


class TestAssignScenesToSegments:
    def test_assigns_frames_by_midpoint(self):
        scenes = [
            SceneInfo(1, 0.0, 10.0, "/frames/s1.jpg"),
            SceneInfo(2, 10.0, 20.0, "/frames/s2.jpg"),
        ]
        segments = [
            {"id": 1, "start": 0.0, "end": 4.0, "text": "a", "speaker": "A",
             "confidence": 0.9, "scene_frame": None},
            {"id": 2, "start": 12.0, "end": 18.0, "text": "b", "speaker": "B",
             "confidence": 0.7, "scene_frame": None},
        ]
        result = assign_scenes_to_segments(segments, scenes)
        # midpoint seg1 = 2.0 → scene 1
        assert result[0]["scene_frame"] == "/frames/s1.jpg"
        # midpoint seg2 = 15.0 → scene 2
        assert result[1]["scene_frame"] == "/frames/s2.jpg"

    def test_empty_scenes_leaves_none(self):
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "a", "speaker": "A",
             "confidence": 0.8, "scene_frame": None},
        ]
        result = assign_scenes_to_segments(segments, [])
        assert result[0]["scene_frame"] is None

    def test_does_not_mutate_original(self):
        """assign_scenes_to_segments không được thay đổi list gốc."""
        scenes = [SceneInfo(1, 0.0, 10.0, "/frames/s1.jpg")]
        orig_seg = {"id": 1, "start": 0.0, "end": 5.0, "text": "a",
                    "speaker": "A", "confidence": 0.9, "scene_frame": None}
        segments = [orig_seg]
        _ = assign_scenes_to_segments(segments, scenes)
        # Original segment không bị thay đổi
        assert orig_seg["scene_frame"] is None
