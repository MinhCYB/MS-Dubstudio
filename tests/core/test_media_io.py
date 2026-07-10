"""
tests/core/test_media_io.py — Unit tests for core/media_io.py

Mock subprocess.run để test mà không cần ffmpeg thật.
Chỉ test với ffmpeg thật trong integration tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from msdubstudio.core.media_io import (
    AudioExtractionError,
    FFmpegNotFoundError,
    MediaIOError,
    VideoFileError,
    _parse_fps,
    _parse_ffprobe_output,
    check_ffmpeg_available,
    extract_audio,
    format_duration,
    format_file_size,
    get_video_metadata,
)


# ---------------------------------------------------------------------------
# Tests: _parse_fps
# ---------------------------------------------------------------------------


class TestParseFps:
    def test_fraction_format(self):
        assert _parse_fps("30/1") == pytest.approx(30.0)

    def test_decimal_format(self):
        assert _parse_fps("29.97") == pytest.approx(29.97)

    def test_zero_denominator(self):
        assert _parse_fps("30/0") == pytest.approx(0.0)

    def test_ntsc_fraction(self):
        assert _parse_fps("30000/1001") == pytest.approx(29.97, rel=1e-3)

    def test_invalid_string(self):
        assert _parse_fps("not_a_fps") == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Tests: _parse_ffprobe_output
# ---------------------------------------------------------------------------


class TestParseFFprobeOutput:
    def test_parses_standard_video(self):
        info = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30/1",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "channels": 2,
                    "sample_rate": "44100",
                },
            ],
            "format": {
                "duration": "120.5",
                "size": "50000000",
            },
        }
        meta = _parse_ffprobe_output("video.mp4", info)
        assert meta.filename == "video.mp4"
        assert meta.duration == pytest.approx(120.5)
        assert meta.width == 1920
        assert meta.height == 1080
        assert meta.fps == pytest.approx(30.0)
        assert meta.video_codec == "h264"
        assert meta.audio_codec == "aac"
        assert meta.audio_channels == 2
        assert meta.audio_sample_rate == 44100
        assert meta.file_size_bytes == 50000000

    def test_handles_missing_audio_stream(self):
        info = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264",
                 "width": 1280, "height": 720, "avg_frame_rate": "25/1"},
            ],
            "format": {"duration": "60.0"},
        }
        meta = _parse_ffprobe_output("video.mp4", info)
        assert meta.audio_codec == ""
        assert meta.audio_channels == 2  # default

    def test_handles_empty_streams(self):
        info = {"streams": [], "format": {"duration": "0"}}
        meta = _parse_ffprobe_output("empty.mp4", info)
        assert meta.duration == pytest.approx(0.0)
        assert meta.width == 0


# ---------------------------------------------------------------------------
# Tests: check_ffmpeg_available
# ---------------------------------------------------------------------------


class TestCheckFFmpegAvailable:
    def test_returns_true_when_ffmpeg_works(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            assert check_ffmpeg_available() is True

    def test_returns_false_when_ffmpeg_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert check_ffmpeg_available() is False

    def test_returns_false_when_ffmpeg_returns_nonzero(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            assert check_ffmpeg_available() is False


# ---------------------------------------------------------------------------
# Tests: get_video_metadata
# ---------------------------------------------------------------------------


class TestGetVideoMetadata:
    @pytest.fixture
    def video_file(self, tmp_path: Path) -> Path:
        f = tmp_path / "video.mp4"
        f.write_bytes(b"fake mp4")
        return f

    def test_raises_if_file_not_found(self):
        with pytest.raises(VideoFileError):
            get_video_metadata("/nonexistent/video.mp4")

    def test_raises_if_ffprobe_not_found(self, video_file: Path):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(FFmpegNotFoundError) as exc_info:
                get_video_metadata(str(video_file))
            assert "ffprobe" in str(exc_info.value).lower() or "ffmpeg" in str(exc_info.value).lower()

    def test_raises_on_ffprobe_failure(self, video_file: Path):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Error reading file"
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(MediaIOError):
                get_video_metadata(str(video_file))

    def test_returns_metadata_on_success(self, video_file: Path):
        ffprobe_output = json.dumps({
            "streams": [
                {"codec_type": "video", "codec_name": "h264",
                 "width": 1920, "height": 1080, "avg_frame_rate": "30/1"},
                {"codec_type": "audio", "codec_name": "aac",
                 "channels": 2, "sample_rate": "44100"},
            ],
            "format": {"duration": "90.0", "size": "30000000"},
        })
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ffprobe_output

        with patch("subprocess.run", return_value=mock_result):
            meta = get_video_metadata(str(video_file))

        assert meta.filename == "video.mp4"
        assert meta.duration == pytest.approx(90.0)
        assert meta.width == 1920
        assert meta.fps == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# Tests: extract_audio
# ---------------------------------------------------------------------------


class TestExtractAudio:
    @pytest.fixture
    def video_file(self, tmp_path: Path) -> Path:
        f = tmp_path / "video.mp4"
        f.write_bytes(b"fake mp4")
        return f

    @pytest.fixture
    def output_path(self, tmp_path: Path) -> Path:
        return tmp_path / "audio" / "audio.wav"

    def test_raises_if_video_not_found(self, output_path: Path):
        with pytest.raises(VideoFileError):
            extract_audio("/nonexistent/video.mp4", str(output_path))

    def test_raises_if_ffmpeg_not_found(self, video_file: Path, output_path: Path):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(FFmpegNotFoundError):
                extract_audio(str(video_file), str(output_path))

    def test_raises_on_ffmpeg_failure(self, video_file: Path, output_path: Path):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Conversion failed"
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(AudioExtractionError):
                extract_audio(str(video_file), str(output_path))

    def test_success_returns_path(self, video_file: Path, output_path: Path):
        mock_result = MagicMock()
        mock_result.returncode = 0

        def create_output(*args, **kwargs):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"fake wav data")
            return mock_result

        with patch("subprocess.run", side_effect=create_output):
            result = extract_audio(str(video_file), str(output_path))

        assert result == str(output_path.resolve())
        assert output_path.exists()

    def test_creates_output_directory(self, video_file: Path, tmp_path: Path):
        nested_output = tmp_path / "new_dir" / "nested" / "audio.wav"
        mock_result = MagicMock()
        mock_result.returncode = 0

        def create_output(*args, **kwargs):
            nested_output.parent.mkdir(parents=True, exist_ok=True)
            nested_output.write_bytes(b"fake wav")
            return mock_result

        with patch("subprocess.run", side_effect=create_output):
            extract_audio(str(video_file), str(nested_output))

        assert nested_output.parent.exists()

    def test_uses_correct_ffmpeg_args(self, video_file: Path, output_path: Path):
        """Kiểm tra ffmpeg được gọi với các tham số đúng."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        called_args = []

        def capture_args(*args, **kwargs):
            called_args.extend(args[0])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"fake wav")
            return mock_result

        with patch("subprocess.run", side_effect=capture_args):
            extract_audio(str(video_file), str(output_path), sample_rate=16000, channels=1)

        assert "-ar" in called_args
        sr_idx = called_args.index("-ar")
        assert called_args[sr_idx + 1] == "16000"

        assert "-ac" in called_args
        ac_idx = called_args.index("-ac")
        assert called_args[ac_idx + 1] == "1"

        assert "-vn" in called_args  # no video stream
        assert "pcm_s16le" in called_args  # PCM 16-bit


# ---------------------------------------------------------------------------
# Tests: format helpers
# ---------------------------------------------------------------------------


class TestFormatDuration:
    def test_hours_minutes_seconds(self):
        assert format_duration(3661.5) == "01:01:01.50"

    def test_minutes_seconds(self):
        assert format_duration(90.0) == "00:01:30.00"

    def test_zero(self):
        assert format_duration(0.0) == "00:00:00.00"

    def test_centiseconds(self):
        assert format_duration(1.25) == "00:00:01.25"


class TestFormatFileSize:
    def test_bytes(self):
        assert format_file_size(500) == "500 B"

    def test_kilobytes(self):
        result = format_file_size(1500)
        assert "KB" in result

    def test_megabytes(self):
        result = format_file_size(2_000_000)
        assert "MB" in result

    def test_gigabytes(self):
        result = format_file_size(2_000_000_000)
        assert "GB" in result
