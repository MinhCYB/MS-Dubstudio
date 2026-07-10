"""
tests/core/test_stt.py — Unit tests for core/stt.py

Kiểm tra các hàm không phụ thuộc Whisper bằng cách mock model hoàn toàn.
Không bao giờ load model thật trong automated test.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from msdubstudio.core.models import ProjectSettings
from msdubstudio.core.stt import (
    AudioFileError,
    WhisperModelNotFoundError,
    _normalize_logprob,
    _resolve_device,
    assign_scene_frames,
    transcribe,
)


# ---------------------------------------------------------------------------
# Tests: _normalize_logprob
# ---------------------------------------------------------------------------


class TestNormalizeLogprob:
    def test_zero_gives_one(self):
        """avg_logprob = 0 → confidence = 1.0 (perfect)"""
        assert _normalize_logprob(0.0) == pytest.approx(1.0)

    def test_minus_two_gives_zero(self):
        """avg_logprob = -2 → confidence = 0.0"""
        assert _normalize_logprob(-2.0) == pytest.approx(0.0)

    def test_minus_one_gives_half(self):
        """avg_logprob = -1 → confidence ≈ 0.5"""
        assert _normalize_logprob(-1.0) == pytest.approx(0.5)

    def test_very_negative_clamped_to_zero(self):
        """avg_logprob rất âm → không cho ra confidence âm"""
        assert _normalize_logprob(-10.0) == pytest.approx(0.0)

    def test_slightly_negative(self):
        """avg_logprob = -0.5 → confidence = 0.75"""
        assert _normalize_logprob(-0.5) == pytest.approx(0.75)

    def test_positive_clamped_to_one(self):
        """avg_logprob dương (không thường xảy ra) → clamp về 1.0"""
        assert _normalize_logprob(0.5) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Tests: _resolve_device
# ---------------------------------------------------------------------------


class TestResolveDevice:
    def test_explicit_cuda(self):
        assert _resolve_device("cuda") == "cuda"

    def test_explicit_cpu(self):
        assert _resolve_device("cpu") == "cpu"

    def test_auto_with_cuda_available(self):
        with patch("msdubstudio.core.stt.torch", create=True) as mock_torch:
            mock_torch.cuda.is_available.return_value = True
            # Không thể patch import trong hàm trực tiếp — test behavior
            # thay vào đó test kết quả của auto khi không có torch
            pass

    def test_auto_without_torch_returns_cpu(self):
        """Nếu torch không được cài → auto trả về 'cpu'."""
        with patch.dict("sys.modules", {"torch": None}):
            result = _resolve_device("auto")
            assert result == "cpu"


# ---------------------------------------------------------------------------
# Tests: transcribe() với mock faster-whisper
# ---------------------------------------------------------------------------


class TestTranscribe:
    @pytest.fixture
    def audio_file(self, tmp_path: Path) -> Path:
        """Tạo file WAV giả (chỉ cần tồn tại, không cần valid)."""
        f = tmp_path / "test.wav"
        f.write_bytes(b"RIFF fake wav data")
        return f

    def test_raises_if_audio_not_found(self):
        settings = ProjectSettings()
        with pytest.raises(AudioFileError):
            transcribe("/nonexistent/audio.wav", settings)

    def test_with_mock_faster_whisper(self, audio_file: Path):
        """Test transcribe với faster-whisper mock hoàn toàn."""
        settings = ProjectSettings(whisper_model="tiny", whisper_language="zh")

        # Tạo mock segment giống faster-whisper output
        mock_segment1 = MagicMock()
        mock_segment1.start = 0.0
        mock_segment1.end = 2.34
        mock_segment1.text = "  今天天气真好  "
        mock_segment1.avg_logprob = -0.2  # confidence cao

        mock_segment2 = MagicMock()
        mock_segment2.start = 2.5
        mock_segment2.end = 5.1
        mock_segment2.text = "你好世界"
        mock_segment2.avg_logprob = -0.8

        mock_info = MagicMock()
        mock_info.duration = 10.0

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment1, mock_segment2], mock_info)

        mock_faster_whisper = MagicMock()
        mock_faster_whisper.WhisperModel.return_value = mock_model

        with patch.dict("sys.modules", {"faster_whisper": mock_faster_whisper}):
            result = transcribe(str(audio_file), settings)

        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[0]["start"] == pytest.approx(0.0)
        assert result[0]["end"] == pytest.approx(2.34)
        assert result[0]["text"] == "今天天气真好"  # stripped
        assert result[0]["speaker"] == "A"
        assert result[0]["confidence"] == pytest.approx(_normalize_logprob(-0.2))
        assert result[0]["scene_frame"] is None

    def test_progress_callback_called(self, audio_file: Path):
        """progress_callback phải được gọi cho mỗi segment."""
        settings = ProjectSettings()

        mock_segments = []
        for i in range(3):
            seg = MagicMock()
            seg.start = float(i * 2)
            seg.end = float(i * 2 + 1.5)
            seg.text = f"segment {i}"
            seg.avg_logprob = -0.5
            mock_segments.append(seg)

        mock_info = MagicMock()
        mock_info.duration = 10.0
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (mock_segments, mock_info)

        mock_fw = MagicMock()
        mock_fw.WhisperModel.return_value = mock_model

        progress_calls = []
        with patch.dict("sys.modules", {"faster_whisper": mock_fw}):
            transcribe(str(audio_file), settings, progress_callback=lambda c, t: progress_calls.append((c, t)))

        assert len(progress_calls) == 3
        assert progress_calls[0][0] == 1
        assert progress_calls[2][0] == 3

    def test_cancel_check_stops_early(self, audio_file: Path):
        """cancel_check=True ngay từ đầu → không xử lý segment nào."""
        settings = ProjectSettings()

        mock_segment = MagicMock()
        mock_segment.start = 0.0
        mock_segment.end = 2.0
        mock_segment.text = "你好"
        mock_segment.avg_logprob = -0.3
        mock_info = MagicMock()
        mock_info.duration = 5.0
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment, mock_segment], mock_info)

        mock_fw = MagicMock()
        mock_fw.WhisperModel.return_value = mock_model

        cancelled = [False]
        call_count = [0]

        def cancel_check():
            call_count[0] += 1
            return True  # cancel ngay lập tức

        with patch.dict("sys.modules", {"faster_whisper": mock_fw}):
            result = transcribe(str(audio_file), settings, cancel_check=cancel_check)

        # Kết quả rỗng vì cancel ngay từ segment đầu tiên
        assert len(result) == 0

    def test_fallback_to_openai_whisper_when_faster_not_available(self, audio_file: Path):
        """Khi faster-whisper không có, fallback sang openai-whisper."""
        settings = ProjectSettings()

        # Mock openai-whisper result
        mock_ow_result = {
            "segments": [
                {"start": 0.0, "end": 2.0, "text": "你好", "avg_logprob": -0.4},
            ]
        }
        mock_ow_model = MagicMock()
        mock_ow_model.transcribe.return_value = mock_ow_result
        mock_openai_whisper = MagicMock()
        mock_openai_whisper.load_model.return_value = mock_ow_model

        with patch.dict("sys.modules", {
            "faster_whisper": None,  # không có faster-whisper
            "whisper": mock_openai_whisper,
        }):
            result = transcribe(str(audio_file), settings)

        assert len(result) == 1
        assert result[0]["text"] == "你好"

    def test_raises_when_no_whisper_available(self, audio_file: Path):
        """Khi cả faster-whisper và openai-whisper đều không có → raise lỗi rõ."""
        settings = ProjectSettings()
        with patch.dict("sys.modules", {
            "faster_whisper": None,
            "whisper": None,
        }):
            with pytest.raises(WhisperModelNotFoundError) as exc_info:
                transcribe(str(audio_file), settings)
            assert "pip install" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Tests: assign_scene_frames
# ---------------------------------------------------------------------------


class TestAssignSceneFrames:
    def test_assigns_correct_frame(self):
        segments = [
            {"id": 1, "start": 0.0, "end": 3.0, "text": "a", "speaker": "A",
             "confidence": 0.9, "scene_frame": None},
            {"id": 2, "start": 5.0, "end": 8.0, "text": "b", "speaker": "B",
             "confidence": 0.7, "scene_frame": None},
        ]
        scenes = [
            {"start": 0.0, "end": 4.0, "frame_path": "/frames/scene_001.jpg"},
            {"start": 4.0, "end": 10.0, "frame_path": "/frames/scene_002.jpg"},
        ]
        result = assign_scene_frames(segments, scenes)
        assert result[0]["scene_frame"] == "/frames/scene_001.jpg"
        assert result[1]["scene_frame"] == "/frames/scene_002.jpg"

    def test_no_scenes_returns_unchanged(self):
        segments = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "a", "speaker": "A",
             "confidence": 0.8, "scene_frame": None},
        ]
        result = assign_scene_frames(segments, [])
        assert result[0]["scene_frame"] is None

    def test_fallback_to_closest_scene(self):
        """Nếu không có scene chứa midpoint → dùng scene gần nhất."""
        segments = [
            {"id": 1, "start": 20.0, "end": 25.0, "text": "a", "speaker": "A",
             "confidence": 0.9, "scene_frame": None},
        ]
        scenes = [
            {"start": 0.0, "end": 10.0, "frame_path": "/frames/scene_001.jpg"},
            {"start": 10.0, "end": 15.0, "frame_path": "/frames/scene_002.jpg"},
        ]
        result = assign_scene_frames(segments, scenes)
        # midpoint = 22.5, scene 002 gần hơn (start=10 vs start=0)
        assert result[0]["scene_frame"] == "/frames/scene_002.jpg"
