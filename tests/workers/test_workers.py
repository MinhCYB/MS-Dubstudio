"""
tests/workers/test_workers.py — pytest-qt tests cho toàn bộ Workers

Dùng qtbot.waitSignal() để verify signals được emit đúng.
Mock toàn bộ external dependencies (google-generativeai, faster-whisper, edge-tts).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from msdubstudio.core.models import ProjectSettings, Segment, SegmentStatus
from msdubstudio.workers.translate_worker import TranslateWorker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_segment(
    id: int,
    text_zh: str = "你好",
    status: SegmentStatus = SegmentStatus.PENDING,
    text_vi: str | None = None,
    start: float | None = None,
    end: float | None = None,
) -> Segment:
    """Helper tạo Segment cho test. start/end mặc định từ id nếu không cung cấp."""
    _start = start if start is not None else float(id - 1) * 2.0
    _end = end if end is not None else _start + 1.8
    return Segment(
        id=id,
        start=_start,
        end=_end,
        speaker="A",
        text_zh=text_zh,
        text_vi=text_vi,
        confidence=0.9,
        status=status,
    )


def make_mock_genai(responses: list[list[dict]]) -> MagicMock:
    """Tạo mock google.generativeai với các response tuần tự."""
    call_count = [0]
    mock_model = MagicMock()

    def gen_content(*args, **kwargs):
        data = responses[call_count[0] % len(responses)]
        call_count[0] += 1
        mock_resp = MagicMock()
        mock_resp.text = json.dumps(data, ensure_ascii=False)
        return mock_resp

    mock_model.generate_content.side_effect = gen_content
    mock_genai = MagicMock()
    mock_genai.GenerativeModel.return_value = mock_model
    return mock_genai


# ---------------------------------------------------------------------------
# Tests: TranslateWorker signals
# ---------------------------------------------------------------------------


class TestTranslateWorkerSignals:
    """Test signals bằng pytest-qt qtbot."""

    def test_finished_all_emitted_on_success(self, qtbot):
        """finished_all phải emit sau khi tất cả batch hoàn thành."""
        segments = [
            make_segment(1, "今天天气真好"),
            make_segment(2, "你好世界"),
        ]
        settings = ProjectSettings(batch_size=15)

        mock_genai = make_mock_genai([
            [{"id": 1, "text_vi": "Hôm nay trời đẹp"},
             {"id": 2, "text_vi": "Xin chào thế giới"}]
        ])

        worker = TranslateWorker(segments, settings, api_key="fake")

        with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
            with qtbot.waitSignal(worker.finished_all, timeout=5000):
                worker.start()

        assert not worker.isRunning()

    def test_batch_done_emitted_with_segments(self, qtbot):
        """batch_done phải emit với list Segment đã dịch."""
        segments = [make_segment(1, "你好")]
        settings = ProjectSettings(batch_size=15)

        mock_genai = make_mock_genai([
            [{"id": 1, "text_vi": "Xin chào"}]
        ])

        worker = TranslateWorker(segments, settings, api_key="fake")
        received_segments = []

        worker.batch_done.connect(lambda segs: received_segments.extend(segs))

        with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
            with qtbot.waitSignal(worker.finished_all, timeout=5000):
                worker.start()

        assert len(received_segments) == 1
        assert received_segments[0].text_vi == "Xin chào"
        assert received_segments[0].status == SegmentStatus.TRANSLATED

    def test_progress_emitted(self, qtbot):
        """progress signal phải emit ít nhất 1 lần."""
        segments = [make_segment(1, "你好"), make_segment(2, "谢谢")]
        settings = ProjectSettings(batch_size=15)

        mock_genai = make_mock_genai([
            [{"id": 1, "text_vi": "Xin chào"}, {"id": 2, "text_vi": "Cảm ơn"}]
        ])

        worker = TranslateWorker(segments, settings, api_key="fake")
        progress_calls = []
        worker.progress.connect(lambda c, t: progress_calls.append((c, t)))

        with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
            with qtbot.waitSignal(worker.finished_all, timeout=5000):
                worker.start()

        assert len(progress_calls) >= 1
        last_current, last_total = progress_calls[-1]
        assert last_total == 2

    def test_step_log_emitted(self, qtbot):
        """step_log phải emit message logs."""
        segments = [make_segment(1)]
        settings = ProjectSettings(batch_size=15)

        mock_genai = make_mock_genai([
            [{"id": 1, "text_vi": "Xin chào"}]
        ])

        worker = TranslateWorker(segments, settings, api_key="fake")
        logs = []
        worker.step_log.connect(lambda msg: logs.append(msg))

        with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
            with qtbot.waitSignal(worker.finished_all, timeout=5000):
                worker.start()

        assert len(logs) > 0
        # Phải có log bắt đầu và kết thúc
        all_logs = " ".join(logs)
        assert any(word in all_logs for word in ["Bắt đầu", "dịch", "segment"])

    def test_batch_error_emitted_on_api_failure(self, qtbot):
        """batch_error phải emit khi Gemini trả về lỗi."""
        segments = [make_segment(1)]
        settings = ProjectSettings(batch_size=15)

        # Mock Gemini luôn trả về lỗi 429
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = Exception("429 Rate Limit")
        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        worker = TranslateWorker(segments, settings, api_key="fake")
        batch_errors = []
        worker.batch_error.connect(lambda idx, msg: batch_errors.append((idx, msg)))

        with patch("msdubstudio.core.translator.time.sleep"):
            with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
                with qtbot.waitSignal(worker.finished_all, timeout=10000):
                    worker.start()

        # Phải có ít nhất 1 batch error
        assert len(batch_errors) >= 1
        _, error_msg = batch_errors[0]
        assert error_msg  # không rỗng

    def test_no_action_when_all_translated(self, qtbot):
        """Khi tất cả đã TRANSLATED → finished_all emit ngay, không gọi API."""
        segments = [
            make_segment(1, status=SegmentStatus.TRANSLATED, text_vi="đã dịch"),
            make_segment(2, status=SegmentStatus.REVIEWED, text_vi="đã review"),
        ]
        settings = ProjectSettings()

        mock_genai = MagicMock()
        worker = TranslateWorker(segments, settings, api_key="fake")

        with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
            with qtbot.waitSignal(worker.finished_all, timeout=3000):
                worker.start()

        # GenerativeModel không được tạo ra
        mock_genai.GenerativeModel.assert_not_called()

    def test_cancel_stops_worker(self, qtbot):
        """Sau khi gọi cancel(), worker phải dừng sớm."""
        # 30 segments để đảm bảo cancel có thể kịp xảy ra
        segments = [
            make_segment(i, start=float(i), end=float(i) + 0.9)
            for i in range(1, 31)
        ]
        settings = ProjectSettings(batch_size=5)

        # Mock với delay nhỏ để cancel kịp xảy ra
        call_count = [0]
        mock_model = MagicMock()

        def gen_content(*args, **kwargs):
            call_count[0] += 1
            time.sleep(0.01)  # delay nhỏ
            import re
            text = args[0][0]["text"]
            ids = [int(m) for m in re.findall(r'"id":\s*(\d+)', text)]
            mock_resp = MagicMock()
            mock_resp.text = json.dumps(
                [{"id": i, "text_vi": f"câu {i}"} for i in ids]
            )
            return mock_resp

        mock_model.generate_content.side_effect = gen_content
        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        worker = TranslateWorker(segments, settings, api_key="fake", max_concurrent_batches=1)

        with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
            worker.start()
            time.sleep(0.05)  # cho worker chạy 1-2 batch
            worker.cancel()
            worker.wait(3000)  # đợi tối đa 3s

        assert not worker.isRunning()


# ---------------------------------------------------------------------------
# Tests: STTWorker signals
# ---------------------------------------------------------------------------


class TestSTTWorkerSignals:
    """Test STTWorker signals với mock Whisper."""

    def test_finished_emitted_with_segments(self, qtbot, tmp_path):
        """finished phải emit với list raw_segments."""
        from msdubstudio.workers.stt_worker import STTWorker

        # Tạo fake WAV file
        audio_file = tmp_path / "audio.wav"
        audio_file.write_bytes(b"RIFF fake wav")

        settings = ProjectSettings(whisper_model="tiny")

        # Mock faster-whisper
        mock_seg1 = MagicMock()
        mock_seg1.start = 0.0
        mock_seg1.end = 2.5
        mock_seg1.text = "今天天气真好"
        mock_seg1.avg_logprob = -0.2

        mock_info = MagicMock()
        mock_info.duration = 10.0
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_seg1], mock_info)
        mock_fw = MagicMock()
        mock_fw.WhisperModel.return_value = mock_model

        worker = STTWorker(str(audio_file), settings)
        received = []
        worker.finished.connect(lambda segs: received.extend(segs))

        with patch.dict("sys.modules", {"faster_whisper": mock_fw}):
            with qtbot.waitSignal(worker.finished, timeout=5000):
                worker.start()

        assert len(received) == 1
        assert received[0]["text"] == "今天天气真好"
        assert received[0]["id"] == 1

    def test_error_emitted_on_file_not_found(self, qtbot):
        """error phải emit khi audio file không tồn tại."""
        from msdubstudio.workers.stt_worker import STTWorker

        settings = ProjectSettings()
        worker = STTWorker("/nonexistent/audio.wav", settings)
        errors = []
        worker.error.connect(lambda msg: errors.append(msg))

        with qtbot.waitSignal(worker.error, timeout=3000):
            worker.start()

        assert len(errors) == 1
        assert "audio" in errors[0].lower() or "tồn tại" in errors[0].lower()


# ---------------------------------------------------------------------------
# Tests: TTSWorker signals
# ---------------------------------------------------------------------------


class TestTTSWorkerSignals:
    """Test TTSWorker với mock edge-tts."""

    def test_segment_done_emitted_per_segment(self, qtbot, tmp_path):
        """segment_done phải emit 1 lần cho mỗi segment thành công."""
        from msdubstudio.core.models import Speaker
        from msdubstudio.workers.tts_worker import TTSWorker

        # Tạo segments cần TTS (needs_tts_regeneration = True)
        segs = [
            Segment(
                id=i, start=float(i - 1), end=float(i - 1) + 0.9,
                speaker="A", text_zh=f"câu {i}", text_vi=f"câu {i} tiếng Việt",
                confidence=0.9,
                # voice_path=None → needs_tts_regeneration=True
            )
            for i in range(1, 4)
        ]

        speakers = {"A": Speaker(id="A", gender="female", voice_id="vi-VN-HoaiMyNeural")}
        voice_dir = str(tmp_path / "voice")

        settings = ProjectSettings()

        # Mock edge-tts: Communicate().save() phải là AsyncMock để asyncio.run() await đúng.
        # Dùng side_effect để ghi file thật (để tts.py pass kiểm tra file tồn tại).
        def make_fake_communicate(*args, **kwargs):
            comm = MagicMock()
            # Lấy output_path từ save call — ghi file giả
            async def fake_save_impl(path):
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_bytes(b"fake wav data")
            comm.save = AsyncMock(side_effect=fake_save_impl)
            return comm

        mock_et = MagicMock()
        mock_et.Communicate.side_effect = make_fake_communicate

        worker = TTSWorker(segs, speakers, voice_dir, settings)
        done_events = []
        worker.segment_done.connect(lambda sid, vp: done_events.append((sid, vp)))

        with patch.dict("sys.modules", {"edge_tts": mock_et}):
            with qtbot.waitSignal(worker.finished, timeout=10000):
                worker.start()

        assert len(done_events) == 3
        assert all(Path(vp).exists() for _, vp in done_events)

    def test_finished_emitted_when_no_segments_need_tts(self, qtbot, tmp_path):
        """Khi không có segment cần TTS → finished emit ngay."""
        from msdubstudio.core.models import Speaker
        from msdubstudio.workers.tts_worker import TTSWorker
        import hashlib

        # Segment đã có voice_path + hash khớp → không cần TTS
        text = "xin chào"
        hash_ = hashlib.sha256(text.encode()).hexdigest()
        segs = [
            Segment(
                id=1, start=0.0, end=2.0, speaker="A",
                text_zh="你好", text_vi=text,
                confidence=0.9,
                voice_path=str(tmp_path / "seg.wav"),
                text_vi_hash=hash_,
            )
        ]
        speakers = {"A": Speaker(id="A")}
        worker = TTSWorker(segs, speakers, str(tmp_path / "voice"), ProjectSettings())

        with qtbot.waitSignal(worker.finished, timeout=3000):
            worker.start()

        assert not worker.isRunning()


# ---------------------------------------------------------------------------
# Tests: BaseWorker
# ---------------------------------------------------------------------------


class TestBaseWorker:
    """Test BaseWorker cancel mechanism."""

    def test_cancel_sets_flag(self):
        """cancel() phải set is_cancelled = True."""
        from msdubstudio.workers.base_worker import BaseWorker

        # Tạo concrete subclass đơn giản để test
        class DummyWorker(BaseWorker):
            def run(self):
                pass

        w = DummyWorker()
        assert not w.is_cancelled
        w.cancel()
        assert w.is_cancelled

    def test_reset_cancel_clears_flag(self):
        from msdubstudio.workers.base_worker import BaseWorker

        class DummyWorker(BaseWorker):
            def run(self):
                pass

        w = DummyWorker()
        w.cancel()
        assert w.is_cancelled
        w.reset_cancel()
        assert not w.is_cancelled

    def test_cancel_is_thread_safe(self, qtbot):
        """cancel() từ main thread trong khi worker đang chạy."""
        from msdubstudio.workers.base_worker import BaseWorker

        class SlowWorker(BaseWorker):
            finished = __import__("PyQt6.QtCore", fromlist=["pyqtSignal"]).pyqtSignal()

            def run(self):
                import time
                start = time.time()
                while not self.is_cancelled and time.time() - start < 5:
                    time.sleep(0.01)
                self.finished.emit()

        from PyQt6.QtCore import pyqtSignal
        SlowWorker.finished = pyqtSignal()

        worker = SlowWorker()
        with qtbot.waitSignal(worker.finished, timeout=3000):
            worker.start()
            time.sleep(0.05)
            worker.cancel()

        assert worker.is_cancelled
