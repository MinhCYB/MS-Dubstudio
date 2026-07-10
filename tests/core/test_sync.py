"""
tests/core/test_sync.py — Tests cho core/sync.py

Kiểm tra:
- compute_stretch_ratio: tính toán đúng ratio
- needs_stretch: phát hiện cần stretch không
- _build_atempo_filter: tạo filter chain đúng cho ffmpeg
- stretch_audio: mock ffmpeg + mock rubberband
- get_audio_duration: mock ffprobe
- Edge cases: ratio clamp, threshold
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from msdubstudio.core.sync import (
    MIN_STRETCH_RATIO,
    MAX_STRETCH_RATIO,
    SKIP_THRESHOLD,
    SyncBackendNotFoundError,
    SyncError,
    _build_atempo_filter,
    compute_stretch_ratio,
    get_audio_duration,
    needs_stretch,
    stretch_audio,
    stretch_audio_to_duration,
)


# ---------------------------------------------------------------------------
# TestComputeStretchRatio
# ---------------------------------------------------------------------------


class TestComputeStretchRatio:
    """Test tính toán stretch ratio."""

    def test_equal_duration_returns_one(self):
        """TTS và gốc cùng độ dài → ratio = 1.0."""
        assert compute_stretch_ratio(3.0, 3.0) == pytest.approx(1.0)

    def test_tts_longer_than_original(self):
        """TTS 4s, gốc 2s → ratio = 2.0 (cần nén lại)."""
        assert compute_stretch_ratio(4.0, 2.0) == pytest.approx(2.0)

    def test_tts_shorter_than_original(self):
        """TTS 1s, gốc 2s → ratio = 0.5 (cần giãn ra)."""
        assert compute_stretch_ratio(1.0, 2.0) == pytest.approx(0.5)

    def test_zero_tts_duration(self):
        """TTS 0s → ratio = 1.0 (an toàn)."""
        assert compute_stretch_ratio(0.0, 2.0) == pytest.approx(1.0)

    def test_zero_original_duration(self):
        """Original 0s → ratio = 1.0 (an toàn)."""
        assert compute_stretch_ratio(3.0, 0.0) == pytest.approx(1.0)

    def test_both_zero(self):
        assert compute_stretch_ratio(0.0, 0.0) == pytest.approx(1.0)

    def test_typical_scenario(self):
        """TTS 2.5s, target 2.0s → ratio ≈ 1.25."""
        ratio = compute_stretch_ratio(2.5, 2.0)
        assert ratio == pytest.approx(1.25)


# ---------------------------------------------------------------------------
# TestNeedsStretch
# ---------------------------------------------------------------------------


class TestNeedsStretch:
    """Test kiểm tra cần stretch không."""

    def test_equal_durations_no_stretch(self):
        assert not needs_stretch(2.0, 2.0)

    def test_within_tolerance_no_stretch(self):
        """3% deviation, ngưỡng 5% → không cần stretch."""
        assert not needs_stretch(2.06, 2.0)  # 3% diff

    def test_outside_tolerance_needs_stretch(self):
        """6% deviation > 5% threshold → cần stretch."""
        assert needs_stretch(2.12, 2.0)  # 6% diff

    def test_tts_much_longer(self):
        assert needs_stretch(4.0, 2.0)

    def test_tts_much_shorter(self):
        assert needs_stretch(1.0, 2.0)

    def test_zero_original_no_stretch(self):
        """Original 0s → không stretch (an toàn)."""
        assert not needs_stretch(2.0, 0.0)

    def test_custom_tolerance(self):
        """Dùng tolerance cao hơn → bỏ qua deviation nhỏ hơn."""
        assert not needs_stretch(2.2, 2.0, tolerance=0.15)
        assert needs_stretch(2.4, 2.0, tolerance=0.15)


# ---------------------------------------------------------------------------
# TestBuildAtempoFilter
# ---------------------------------------------------------------------------


class TestBuildAtempoFilter:
    """Test xây dựng ffmpeg atempo filter chain."""

    def test_normal_ratio_single_filter(self):
        """Ratio trong [0.5, 2.0] → 1 filter duy nhất."""
        result = _build_atempo_filter(1.5)
        assert result == "atempo=1.5000"

    def test_ratio_one_single_filter(self):
        """Ratio = 1.0 → 1 filter."""
        result = _build_atempo_filter(1.0)
        assert "atempo=1.0000" in result

    def test_ratio_two_single_filter(self):
        """Ratio = 2.0 (biên trên) → 1 filter."""
        result = _build_atempo_filter(2.0)
        assert result == "atempo=2.0000"

    def test_ratio_half_single_filter(self):
        """Ratio = 0.5 (biên dưới) → 1 filter."""
        result = _build_atempo_filter(0.5)
        assert result == "atempo=0.5000"

    def test_ratio_above_two_cascades(self):
        """Ratio = 4.0 > 2.0 → cascade 2 filter."""
        result = _build_atempo_filter(4.0)
        # atempo=2.0, atempo=2.0
        parts = result.split(",")
        assert len(parts) == 2
        assert "atempo=2.0" in parts[0]

    def test_ratio_below_half_cascades(self):
        """Ratio = 0.25 < 0.5 → cascade 2 filter."""
        result = _build_atempo_filter(0.25)
        parts = result.split(",")
        assert len(parts) == 2
        assert "atempo=0.5" in parts[0]

    def test_filter_chain_valid_format(self):
        """Filter chain có format đúng (no spaces, comma-separated)."""
        result = _build_atempo_filter(1.2)
        assert " " not in result
        assert "atempo=" in result


# ---------------------------------------------------------------------------
# TestGetAudioDuration
# ---------------------------------------------------------------------------


class TestGetAudioDuration:
    """Test lấy thời lượng audio qua ffprobe."""

    def test_returns_duration_on_success(self, tmp_path):
        """ffprobe trả về duration hợp lệ → trả về float."""
        fake_audio = tmp_path / "test.wav"
        fake_audio.write_bytes(b"fake")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "3.450\n"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            duration = get_audio_duration(str(fake_audio))

        assert duration == pytest.approx(3.45)

    def test_raises_if_ffprobe_not_found(self, tmp_path):
        """ffprobe không tìm thấy → SyncBackendNotFoundError."""
        fake_audio = tmp_path / "test.wav"
        fake_audio.write_bytes(b"fake")

        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(SyncBackendNotFoundError, match="ffprobe"):
                get_audio_duration(str(fake_audio))

    def test_raises_if_ffprobe_fails(self, tmp_path):
        """ffprobe returncode != 0 → SyncError."""
        fake_audio = tmp_path / "test.wav"
        fake_audio.write_bytes(b"fake")

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(SyncError):
                get_audio_duration(str(fake_audio))

    def test_raises_on_invalid_output(self, tmp_path):
        """ffprobe trả về output không phải số → SyncError."""
        fake_audio = tmp_path / "test.wav"
        fake_audio.write_bytes(b"fake")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not_a_number\n"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(SyncError):
                get_audio_duration(str(fake_audio))


# ---------------------------------------------------------------------------
# TestStretchAudio
# ---------------------------------------------------------------------------


class TestStretchAudio:
    """Test stretch_audio với mock backends."""

    def test_raises_if_input_not_found(self, tmp_path):
        """File input không tồn tại → SyncError."""
        with pytest.raises(SyncError, match="không tồn tại"):
            stretch_audio(
                "/nonexistent/audio.wav",
                str(tmp_path / "out.wav"),
                stretch_ratio=1.2,
            )

    def test_copies_directly_if_ratio_near_one(self, tmp_path):
        """Ratio ≈ 1.0 (trong SKIP_THRESHOLD) → copy thẳng, không gọi ffmpeg."""
        input_file = tmp_path / "input.wav"
        input_file.write_bytes(b"fake wav content")
        output_file = tmp_path / "output.wav"

        with patch("subprocess.run") as mock_run:
            result = stretch_audio(
                str(input_file),
                str(output_file),
                stretch_ratio=1.02,  # 2% < 5% threshold
            )

        # subprocess.run không được gọi
        mock_run.assert_not_called()
        # Output phải tồn tại (copy thẳng)
        assert output_file.exists()
        assert output_file.read_bytes() == b"fake wav content"

    def test_uses_ffmpeg_backend_when_specified(self, tmp_path):
        """backend='ffmpeg' → gọi ffmpeg atempo."""
        input_file = tmp_path / "input.wav"
        input_file.write_bytes(b"fake wav content")
        output_file = tmp_path / "output.wav"

        # Mock ffmpeg thành công: tạo file output
        def mock_ffmpeg_run(cmd, **kwargs):
            # Tìm output_path từ args (argument cuối)
            output_path = cmd[-1]
            Path(output_path).write_bytes(b"stretched audio")
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch("subprocess.run", side_effect=mock_ffmpeg_run):
            result = stretch_audio(
                str(input_file),
                str(output_file),
                stretch_ratio=1.5,
                backend="ffmpeg",
            )

        assert output_file.exists()

    def test_raises_if_ffmpeg_not_found(self, tmp_path):
        """ffmpeg không tìm thấy → SyncBackendNotFoundError."""
        input_file = tmp_path / "input.wav"
        input_file.write_bytes(b"fake wav")

        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(SyncBackendNotFoundError):
                stretch_audio(
                    str(input_file),
                    str(tmp_path / "out.wav"),
                    stretch_ratio=1.5,
                    backend="ffmpeg",
                )

    def test_raises_if_ffmpeg_fails(self, tmp_path):
        """ffmpeg returncode != 0 → SyncError."""
        input_file = tmp_path / "input.wav"
        input_file.write_bytes(b"fake wav")

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "ffmpeg error"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(SyncError):
                stretch_audio(
                    str(input_file),
                    str(tmp_path / "out.wav"),
                    stretch_ratio=1.5,
                    backend="ffmpeg",
                )

    def test_clamped_ratio_does_not_crash(self, tmp_path):
        """Ratio ngoài [MIN, MAX] → bị clamp, vẫn chạy được."""
        input_file = tmp_path / "input.wav"
        input_file.write_bytes(b"fake wav")
        output_file = tmp_path / "output.wav"

        def mock_ffmpeg_run(cmd, **kwargs):
            Path(cmd[-1]).write_bytes(b"out")
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch("subprocess.run", side_effect=mock_ffmpeg_run):
            # ratio = 10.0 → bị clamp về MAX_STRETCH_RATIO = 2.0
            result = stretch_audio(
                str(input_file),
                str(output_file),
                stretch_ratio=10.0,
                backend="ffmpeg",
            )

        assert output_file.exists()

    def test_rubberband_backend_not_installed_falls_back(self, tmp_path):
        """rubberband không cài → auto fallback sang ffmpeg."""
        input_file = tmp_path / "input.wav"
        input_file.write_bytes(b"fake wav")
        output_file = tmp_path / "output.wav"

        def mock_ffmpeg_run(cmd, **kwargs):
            Path(cmd[-1]).write_bytes(b"out")
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        # Giả lập pyrubberband chưa cài
        with patch.dict("sys.modules", {
            "pyrubberband": None,
            "soundfile": None,
        }):
            with patch("subprocess.run", side_effect=mock_ffmpeg_run):
                result = stretch_audio(
                    str(input_file),
                    str(output_file),
                    stretch_ratio=1.5,
                    backend="auto",
                )

        assert output_file.exists()


# ---------------------------------------------------------------------------
# TestStretchAudioToDuration
# ---------------------------------------------------------------------------


class TestStretchAudioToDuration:
    """Test convenience wrapper stretch_audio_to_duration."""

    def test_calls_get_audio_duration_and_stretch(self, tmp_path):
        """Convenience: lấy duration rồi stretch đúng ratio."""
        input_file = tmp_path / "input.wav"
        input_file.write_bytes(b"fake wav")
        output_file = tmp_path / "output.wav"

        # Mock get_audio_duration → 4.0s, target → 2.0s → ratio = 2.0
        with patch("msdubstudio.core.sync.get_audio_duration", return_value=4.0):
            with patch("msdubstudio.core.sync.stretch_audio") as mock_stretch:
                mock_stretch.return_value = str(output_file)
                stretch_audio_to_duration(
                    str(input_file),
                    str(output_file),
                    target_duration_s=2.0,
                )

        mock_stretch.assert_called_once()
        # Kiểm tra ratio được tính đúng: 4.0 / 2.0 = 2.0
        call_args = mock_stretch.call_args
        assert call_args[0][2] == pytest.approx(2.0)  # stretch_ratio
