"""
tests/core/test_tts.py — Unit tests for core/tts.py

Mock edge-tts hoàn toàn — không gọi TTS thật.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from msdubstudio.core.tts import (
    DEFAULT_FEMALE_VOICE,
    DEFAULT_MALE_VOICE,
    TTSEngineNotFoundError,
    TTSError,
    TTSVoiceNotFoundError,
    format_pitch,
    format_rate,
    synthesize,
    synthesize_segments,
)


# ---------------------------------------------------------------------------
# Tests: format helpers
# ---------------------------------------------------------------------------


class TestFormatRate:
    def test_positive(self):
        assert format_rate(10) == "+10%"

    def test_zero(self):
        assert format_rate(0) == "+0%"

    def test_negative(self):
        assert format_rate(-20) == "-20%"


class TestFormatPitch:
    def test_positive(self):
        assert format_pitch(10) == "+10Hz"

    def test_zero(self):
        assert format_pitch(0) == "+0Hz"

    def test_negative(self):
        assert format_pitch(-15) == "-15Hz"


# ---------------------------------------------------------------------------
# Tests: synthesize()
# ---------------------------------------------------------------------------


class TestSynthesize:
    def test_raises_if_empty_text(self, tmp_path: Path):
        with pytest.raises(TTSError):
            synthesize("", str(tmp_path / "out.wav"))

    def test_raises_if_whitespace_only(self, tmp_path: Path):
        with pytest.raises(TTSError):
            synthesize("   ", str(tmp_path / "out.wav"))

    def test_raises_if_unknown_engine(self, tmp_path: Path):
        with pytest.raises(TTSEngineNotFoundError):
            synthesize("Xin chào", str(tmp_path / "out.wav"), engine="unknown_engine")

    def test_raises_if_edge_tts_not_installed(self, tmp_path: Path):
        with patch.dict("sys.modules", {"edge_tts": None}):
            with pytest.raises(TTSEngineNotFoundError) as exc_info:
                synthesize("Xin chào", str(tmp_path / "out.wav"))
            assert "pip install" in str(exc_info.value)

    def test_success_with_mock_edge_tts(self, tmp_path: Path):
        """Mock edge-tts để test happy path."""
        output_path = str(tmp_path / "seg_001.wav")

        mock_communicate = MagicMock()
        # Simulate save() tạo file thật
        async def fake_save(path):
            Path(path).write_bytes(b"fake wav data")
        mock_communicate.save = fake_save

        mock_edge_tts = MagicMock()
        mock_edge_tts.Communicate.return_value = mock_communicate

        with patch.dict("sys.modules", {"edge_tts": mock_edge_tts}):
            result = synthesize("Xin chào thế giới", output_path)

        assert result == str(Path(output_path).resolve())
        assert Path(output_path).exists()

        # Kiểm tra Communicate được tạo với đúng args
        mock_edge_tts.Communicate.assert_called_once_with(
            text="Xin chào thế giới",
            voice=DEFAULT_FEMALE_VOICE,
            rate="+0%",
            pitch="+0Hz",
            volume="+0%",
        )

    def test_creates_parent_directory(self, tmp_path: Path):
        """Parent dir được tạo tự động nếu chưa có."""
        output_path = str(tmp_path / "new_dir" / "seg.wav")

        async def fake_save(path):
            Path(path).write_bytes(b"fake wav")

        mock_communicate = MagicMock()
        mock_communicate.save = fake_save
        mock_edge_tts = MagicMock()
        mock_edge_tts.Communicate.return_value = mock_communicate

        with patch.dict("sys.modules", {"edge_tts": mock_edge_tts}):
            synthesize("Xin chào", output_path)

        assert (tmp_path / "new_dir").is_dir()

    def test_raises_if_output_file_empty_after_synthesis(self, tmp_path: Path):
        """File tồn tại nhưng rỗng → raise TTSError."""
        output_path = str(tmp_path / "seg.wav")

        async def fake_save(path):
            Path(path).write_bytes(b"")  # file rỗng

        mock_communicate = MagicMock()
        mock_communicate.save = fake_save
        mock_edge_tts = MagicMock()
        mock_edge_tts.Communicate.return_value = mock_communicate

        with patch.dict("sys.modules", {"edge_tts": mock_edge_tts}):
            with pytest.raises(TTSError) as exc_info:
                synthesize("Xin chào", output_path)
            assert "rỗng" in str(exc_info.value)

    def test_uses_custom_voice_id(self, tmp_path: Path):
        output_path = str(tmp_path / "seg.wav")

        async def fake_save(path):
            Path(path).write_bytes(b"fake wav")

        mock_communicate = MagicMock()
        mock_communicate.save = fake_save
        mock_edge_tts = MagicMock()
        mock_edge_tts.Communicate.return_value = mock_communicate

        with patch.dict("sys.modules", {"edge_tts": mock_edge_tts}):
            synthesize("Xin chào", output_path, voice_id="vi-VN-NamMinhNeural")

        call_kwargs = mock_edge_tts.Communicate.call_args.kwargs
        assert call_kwargs["voice"] == "vi-VN-NamMinhNeural"

    def test_uses_custom_rate_and_pitch(self, tmp_path: Path):
        output_path = str(tmp_path / "seg.wav")

        async def fake_save(path):
            Path(path).write_bytes(b"fake wav")

        mock_communicate = MagicMock()
        mock_communicate.save = fake_save
        mock_edge_tts = MagicMock()
        mock_edge_tts.Communicate.return_value = mock_communicate

        with patch.dict("sys.modules", {"edge_tts": mock_edge_tts}):
            synthesize(
                "Xin chào", output_path,
                rate="+15%", pitch="-5Hz"
            )

        call_kwargs = mock_edge_tts.Communicate.call_args.kwargs
        assert call_kwargs["rate"] == "+15%"
        assert call_kwargs["pitch"] == "-5Hz"


# ---------------------------------------------------------------------------
# Tests: synthesize_segments() — batch
# ---------------------------------------------------------------------------


class TestSynthesizeSegments:
    def _make_mock_edge_tts(self, tmp_path: Path):
        """Tạo mock edge-tts tạo file thật cho mỗi segment."""
        mock_communicate = MagicMock()

        async def fake_save(path):
            Path(path).write_bytes(b"fake wav data for " + path.encode())

        mock_communicate.save = fake_save
        mock_et = MagicMock()
        mock_et.Communicate.return_value = mock_communicate
        return mock_et

    def test_synthesizes_all_segments(self, tmp_path: Path):
        segments = [
            {"id": 1, "text_vi": "Xin chào", "speaker": "A"},
            {"id": 2, "text_vi": "Cảm ơn bạn", "speaker": "B"},
        ]
        voice_dir = str(tmp_path / "voice")
        mock_et = self._make_mock_edge_tts(tmp_path)

        with patch.dict("sys.modules", {"edge_tts": mock_et}):
            results = synthesize_segments(
                segments=segments,
                voice_dir=voice_dir,
                get_voice_id=lambda s: DEFAULT_FEMALE_VOICE,
            )

        assert len(results) == 2
        assert all(r["success"] for r in results)
        assert all(r["voice_path"] is not None for r in results)

    def test_skips_empty_text_vi(self, tmp_path: Path):
        segments = [
            {"id": 1, "text_vi": "", "speaker": "A"},
            {"id": 2, "text_vi": "Xin chào", "speaker": "A"},
        ]
        voice_dir = str(tmp_path / "voice")
        mock_et = self._make_mock_edge_tts(tmp_path)

        with patch.dict("sys.modules", {"edge_tts": mock_et}):
            results = synthesize_segments(
                segments=segments,
                voice_dir=voice_dir,
                get_voice_id=lambda s: DEFAULT_FEMALE_VOICE,
            )

        seg1 = next(r for r in results if r["segment_id"] == 1)
        assert seg1["success"] is False
        assert "rỗng" in seg1["error_message"]

    def test_progress_callback_called(self, tmp_path: Path):
        segments = [
            {"id": i, "text_vi": f"Câu {i}", "speaker": "A"}
            for i in range(1, 4)
        ]
        voice_dir = str(tmp_path / "voice")
        mock_et = self._make_mock_edge_tts(tmp_path)
        progress_calls = []

        with patch.dict("sys.modules", {"edge_tts": mock_et}):
            synthesize_segments(
                segments=segments,
                voice_dir=voice_dir,
                get_voice_id=lambda s: DEFAULT_FEMALE_VOICE,
                progress_callback=lambda c, t: progress_calls.append((c, t)),
            )

        assert len(progress_calls) == 3
        assert progress_calls[-1] == (3, 3)

    def test_cancel_stops_processing(self, tmp_path: Path):
        segments = [
            {"id": i, "text_vi": f"Câu {i}", "speaker": "A"}
            for i in range(1, 6)
        ]
        voice_dir = str(tmp_path / "voice")
        mock_et = self._make_mock_edge_tts(tmp_path)

        with patch.dict("sys.modules", {"edge_tts": mock_et}):
            results = synthesize_segments(
                segments=segments,
                voice_dir=voice_dir,
                get_voice_id=lambda s: DEFAULT_FEMALE_VOICE,
                cancel_check=lambda: True,  # cancel ngay
            )

        assert len(results) == 0

    def test_voice_id_called_with_correct_speaker(self, tmp_path: Path):
        segments = [
            {"id": 1, "text_vi": "Xin chào", "speaker": "A"},
            {"id": 2, "text_vi": "Tạm biệt", "speaker": "B"},
        ]
        voice_dir = str(tmp_path / "voice")
        mock_et = self._make_mock_edge_tts(tmp_path)
        seen_speakers = []

        def get_voice_id(speaker):
            seen_speakers.append(speaker)
            return DEFAULT_FEMALE_VOICE if speaker == "A" else DEFAULT_MALE_VOICE

        with patch.dict("sys.modules", {"edge_tts": mock_et}):
            synthesize_segments(
                segments=segments,
                voice_dir=voice_dir,
                get_voice_id=get_voice_id,
            )

        assert "A" in seen_speakers
        assert "B" in seen_speakers

    def test_output_filenames_include_segment_id(self, tmp_path: Path):
        segments = [
            {"id": 42, "text_vi": "Test", "speaker": "A"},
        ]
        voice_dir = str(tmp_path / "voice")
        mock_et = self._make_mock_edge_tts(tmp_path)

        with patch.dict("sys.modules", {"edge_tts": mock_et}):
            results = synthesize_segments(
                segments=segments,
                voice_dir=voice_dir,
                get_voice_id=lambda s: DEFAULT_FEMALE_VOICE,
            )

        assert results[0]["success"]
        assert "0042" in results[0]["voice_path"]
