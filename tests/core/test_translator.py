"""
tests/core/test_translator.py — Unit tests for core/translator.py

Đây là nhóm test ưu tiên cao nhất vì translator.py là module dễ bug nhất:
- Retry logic (đúng số lần, đúng backoff)
- Batch isolation (batch lỗi không chặn batch khác)
- Idempotency (segment đã dịch không bị gửi lại)
- Structured Output parsing (response đúng/sai format)
- translate_in_batches Generator behavior

KHÔNG gọi Gemini API thật — dùng mock hoàn toàn.
"""

from __future__ import annotations

import json
import time
from typing import Generator
from unittest.mock import MagicMock, call, patch

import pytest

from msdubstudio.core.models import (
    BatchResult,
    ProjectSettings,
    Segment,
    SegmentStatus,
)
from msdubstudio.core.translator import (
    ContentBlockedError,
    FatalApiError,
    RetriableError,
    StructuredOutputError,
    TranslatorError,
    _handle_gemini_exception,
    _parse_translate_response,
    build_translate_prompt,
    call_with_retry,
    make_batches,
    translate_in_batches,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_segment(
    id: int,
    start: float = 0.0,
    end: float = 2.0,
    text_zh: str = "你好",
    text_vi: str | None = None,
    status: SegmentStatus = SegmentStatus.PENDING,
    confidence: float = 0.9,
) -> Segment:
    return Segment(
        id=id,
        start=start + id * 0.01,  # tránh trùng start/end
        end=end + id * 0.01,
        speaker="A",
        text_zh=text_zh,
        text_vi=text_vi,
        confidence=confidence,
        status=status,
    )


def make_mock_response(translations: list[dict]) -> MagicMock:
    """Tạo mock Gemini response với JSON text."""
    mock_resp = MagicMock()
    mock_resp.text = json.dumps(translations, ensure_ascii=False)
    return mock_resp


# ---------------------------------------------------------------------------
# Tests: call_with_retry
# ---------------------------------------------------------------------------


class TestCallWithRetry:
    def test_success_on_first_try(self):
        fn = MagicMock(return_value="ok")
        result = call_with_retry(fn, max_retries=3)
        assert result == "ok"
        fn.assert_called_once()

    def test_retry_on_retriable_error_then_success(self):
        """Lần đầu raise RetriableError, lần sau thành công → retry đúng."""
        call_count = [0]

        def fn():
            call_count[0] += 1
            if call_count[0] == 1:
                raise RetriableError("429 Rate Limit")
            return "success"

        with patch("msdubstudio.core.translator.time.sleep") as mock_sleep:
            result = call_with_retry(fn, max_retries=3, base_delay=1.0)

        assert result == "success"
        assert call_count[0] == 2
        mock_sleep.assert_called_once_with(1.0)  # 1.0 * 2^0 = 1.0

    def test_retry_exponential_backoff(self):
        """Backoff phải là 1s, 2s, 4s cho 3 lần retry."""
        call_count = [0]

        def fn():
            call_count[0] += 1
            raise RetriableError("429")

        with patch("msdubstudio.core.translator.time.sleep") as mock_sleep:
            with pytest.raises(RetriableError):
                call_with_retry(fn, max_retries=3, base_delay=1.0)

        # 3 retry = 3 sleep calls: 1.0, 2.0, 4.0
        sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert sleep_calls == [1.0, 2.0, 4.0]
        assert call_count[0] == 4  # 1 lần đầu + 3 retry

    def test_max_retries_exceeded_raises(self):
        fn = MagicMock(side_effect=RetriableError("always fails"))

        with patch("msdubstudio.core.translator.time.sleep"):
            with pytest.raises(RetriableError):
                call_with_retry(fn, max_retries=3)

        assert fn.call_count == 4  # 1 + 3 retry

    def test_non_retriable_error_not_retried(self):
        """FatalApiError không nên bị retry."""
        call_count = [0]

        def fn():
            call_count[0] += 1
            raise FatalApiError("API key sai")

        with pytest.raises(FatalApiError):
            call_with_retry(fn, max_retries=3, retry_on=(RetriableError,))

        assert call_count[0] == 1  # không retry

    def test_zero_retries_raises_immediately(self):
        fn = MagicMock(side_effect=RetriableError("fail"))

        with pytest.raises(RetriableError):
            call_with_retry(fn, max_retries=0)

        fn.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: make_batches
# ---------------------------------------------------------------------------


class TestMakeBatches:
    def test_even_split(self):
        segments = [make_segment(i) for i in range(1, 7)]
        batches = make_batches(segments, batch_size=3)
        assert len(batches) == 2
        assert [s.id for s in batches[0]] == [1, 2, 3]
        assert [s.id for s in batches[1]] == [4, 5, 6]

    def test_uneven_split(self):
        segments = [make_segment(i) for i in range(1, 8)]  # 7 segments
        batches = make_batches(segments, batch_size=3)
        assert len(batches) == 3
        assert len(batches[0]) == 3
        assert len(batches[1]) == 3
        assert len(batches[2]) == 1

    def test_batch_size_larger_than_segments(self):
        segments = [make_segment(i) for i in range(1, 4)]
        batches = make_batches(segments, batch_size=10)
        assert len(batches) == 1
        assert len(batches[0]) == 3

    def test_single_segment(self):
        batches = make_batches([make_segment(1)], batch_size=15)
        assert len(batches) == 1

    def test_empty_segments(self):
        batches = make_batches([], batch_size=15)
        assert batches == []

    def test_batch_size_zero_raises(self):
        with pytest.raises(ValueError):
            make_batches([make_segment(1)], batch_size=0)

    def test_order_preserved(self):
        """Thứ tự segment phải được giữ nguyên trong mỗi batch."""
        segments = [make_segment(i) for i in range(1, 16)]
        batches = make_batches(segments, batch_size=15)
        flat = [s.id for batch in batches for s in batch]
        assert flat == list(range(1, 16))


# ---------------------------------------------------------------------------
# Tests: build_translate_prompt
# ---------------------------------------------------------------------------


class TestBuildTranslatePrompt:
    def test_returns_list_with_text(self):
        batch = [make_segment(1, text_zh="你好")]
        parts = build_translate_prompt(batch)
        assert isinstance(parts, list)
        assert len(parts) >= 1
        assert "text" in parts[0]
        assert "你好" in parts[0]["text"]

    def test_includes_segment_ids(self):
        batch = [make_segment(1), make_segment(2)]
        parts = build_translate_prompt(batch)
        text_content = parts[0]["text"]
        assert '"id": 1' in text_content
        assert '"id": 2' in text_content

    def test_no_image_when_no_frame(self):
        batch = [make_segment(1)]
        parts = build_translate_prompt(batch, scene_frame_path=None)
        # Không có inline_data part
        assert not any("inline_data" in p for p in parts)

    def test_adds_image_when_frame_exists(self, tmp_path):
        """Đính kèm ảnh khi scene_frame_path tồn tại và là file hợp lệ."""
        frame = tmp_path / "scene.jpg"
        frame.write_bytes(b"fake jpeg data")

        batch = [make_segment(1)]
        parts = build_translate_prompt(batch, scene_frame_path=str(frame))
        # Phải có ít nhất 1 part với inline_data
        assert any("inline_data" in p for p in parts)

    def test_skips_image_if_frame_not_exists(self):
        batch = [make_segment(1)]
        parts = build_translate_prompt(batch, scene_frame_path="/nonexistent/frame.jpg")
        assert not any("inline_data" in p for p in parts)


# ---------------------------------------------------------------------------
# Tests: _handle_gemini_exception
# ---------------------------------------------------------------------------


class TestHandleGeminiException:
    def test_429_becomes_retriable(self):
        exc = Exception("429 Resource has been exhausted")
        with pytest.raises(RetriableError):
            _handle_gemini_exception(exc)

    def test_quota_becomes_retriable(self):
        exc = Exception("quota exceeded for this project")
        with pytest.raises(RetriableError):
            _handle_gemini_exception(exc)

    def test_503_becomes_retriable(self):
        exc = Exception("503 Service Unavailable")
        with pytest.raises(RetriableError):
            _handle_gemini_exception(exc)

    def test_timeout_becomes_retriable(self):
        exc = Exception("Request timeout after 30s")
        with pytest.raises(RetriableError):
            _handle_gemini_exception(exc)

    def test_safety_becomes_content_blocked(self):
        exc = Exception("Response was blocked due to safety settings")
        with pytest.raises(ContentBlockedError):
            _handle_gemini_exception(exc)

    def test_api_key_becomes_fatal(self):
        exc = Exception("Invalid API key provided (401)")
        with pytest.raises(FatalApiError):
            _handle_gemini_exception(exc)

    def test_model_not_found_becomes_fatal(self):
        exc = Exception("Model not found: gemini-99 (404)")
        with pytest.raises(FatalApiError):
            _handle_gemini_exception(exc)


# ---------------------------------------------------------------------------
# Tests: _parse_translate_response
# ---------------------------------------------------------------------------


class TestParseTranslateResponse:
    def test_parses_valid_response(self):
        batch = [make_segment(1, text_zh="你好"), make_segment(2, text_zh="谢谢")]
        response = make_mock_response([
            {"id": 1, "text_vi": "Xin chào"},
            {"id": 2, "text_vi": "Cảm ơn"},
        ])
        result = _parse_translate_response(response, batch)
        assert len(result) == 2
        assert result[0].text_vi == "Xin chào"
        assert result[0].status == SegmentStatus.TRANSLATED
        assert result[1].text_vi == "Cảm ơn"
        assert result[1].status == SegmentStatus.TRANSLATED

    def test_segment_missing_from_response_becomes_error(self):
        """Nếu Gemini không trả về một segment → đánh dấu ERROR."""
        batch = [make_segment(1), make_segment(2)]
        response = make_mock_response([
            {"id": 1, "text_vi": "Xin chào"},
            # id=2 bị thiếu trong response
        ])
        result = _parse_translate_response(response, batch)
        seg2 = next(s for s in result if s.id == 2)
        assert seg2.status == SegmentStatus.ERROR
        assert seg2.error_message is not None

    def test_empty_response_text_raises(self):
        batch = [make_segment(1)]
        response = MagicMock()
        response.text = ""
        with pytest.raises(StructuredOutputError):
            _parse_translate_response(response, batch)

    def test_invalid_json_raises(self):
        batch = [make_segment(1)]
        response = MagicMock()
        response.text = "This is not JSON"
        with pytest.raises(StructuredOutputError):
            _parse_translate_response(response, batch)

    def test_wrong_type_raises(self):
        """Gemini trả về object thay vì array → raise StructuredOutputError."""
        batch = [make_segment(1)]
        response = MagicMock()
        response.text = json.dumps({"id": 1, "text_vi": "xin chào"})  # object, không phải array
        with pytest.raises(StructuredOutputError):
            _parse_translate_response(response, batch)

    def test_strips_whitespace_from_translation(self):
        batch = [make_segment(1)]
        response = make_mock_response([{"id": 1, "text_vi": "  Xin chào  "}])
        result = _parse_translate_response(response, batch)
        assert result[0].text_vi == "Xin chào"

    def test_clears_error_message_on_success(self):
        """Segment có error_message cũ phải được clear khi translate thành công."""
        seg = Segment(
            id=1, start=0.0, end=2.0, speaker="A", text_zh="你好",
            status=SegmentStatus.ERROR, error_message="Lỗi cũ"
        )
        response = make_mock_response([{"id": 1, "text_vi": "Xin chào"}])
        result = _parse_translate_response(response, [seg])
        assert result[0].status == SegmentStatus.TRANSLATED
        assert result[0].error_message is None


# ---------------------------------------------------------------------------
# Tests: translate_in_batches — idempotency (ưu tiên cao nhất)
# ---------------------------------------------------------------------------


class TestTranslateInBatchesIdempotency:
    """Test resume/idempotency — đây là logic dễ bug nhất."""

    def _make_mock_genai(self, responses: list[list[dict]]):
        """Helper tạo mock google.generativeai cho nhiều batch."""
        call_count = [0]
        mock_model = MagicMock()

        def generate_content_side_effect(*args, **kwargs):
            response_data = responses[call_count[0] % len(responses)]
            call_count[0] += 1
            return make_mock_response(response_data)

        mock_model.generate_content.side_effect = generate_content_side_effect
        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        return mock_genai, mock_model, call_count

    def test_skips_already_translated_segments(self):
        """Segment có status=TRANSLATED không được gửi lại."""
        segments = [
            make_segment(1, status=SegmentStatus.TRANSLATED, text_vi="đã dịch"),
            make_segment(2, status=SegmentStatus.PENDING),
        ]
        settings = ProjectSettings(batch_size=15)

        mock_genai, mock_model, call_count = self._make_mock_genai([
            [{"id": 2, "text_vi": "Xin chào"}]
        ])

        with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
            results = list(translate_in_batches(segments, settings, api_key="fake"))

        assert len(results) == 1
        # Chỉ 1 batch được gửi (chỉ có segment id=2)
        assert mock_model.generate_content.call_count == 1
        # Kiểm tra prompt chỉ chứa id=2, không có id=1
        call_args = mock_model.generate_content.call_args
        prompt_text = call_args[0][0][0]["text"]  # parts[0]["text"]
        assert '"id": 2' in prompt_text
        assert '"id": 1' not in prompt_text

    def test_skips_reviewed_segments(self):
        """Segment REVIEWED không được dịch lại."""
        segments = [
            make_segment(1, status=SegmentStatus.REVIEWED, text_vi="đã review"),
            make_segment(2, status=SegmentStatus.PENDING),
        ]
        settings = ProjectSettings(batch_size=15)

        mock_genai, mock_model, call_count = self._make_mock_genai([
            [{"id": 2, "text_vi": "Xin chào"}]
        ])

        with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
            results = list(translate_in_batches(segments, settings, api_key="fake"))

        assert mock_model.generate_content.call_count == 1
        prompt_text = mock_model.generate_content.call_args[0][0][0]["text"]
        assert '"id": 1' not in prompt_text

    def test_all_translated_yields_nothing(self):
        """Khi tất cả đã TRANSLATED → generator không yield gì cả."""
        segments = [
            make_segment(i, status=SegmentStatus.TRANSLATED, text_vi="đã dịch")
            for i in range(1, 4)
        ]
        settings = ProjectSettings()

        mock_genai = MagicMock()
        with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
            results = list(translate_in_batches(segments, settings, api_key="fake"))

        assert results == []
        mock_genai.GenerativeModel.assert_not_called()

    def test_error_segments_included_for_retry(self):
        """Segment có status=ERROR phải được gửi lại."""
        segments = [
            make_segment(1, status=SegmentStatus.ERROR),
            make_segment(2, status=SegmentStatus.PENDING),
        ]
        settings = ProjectSettings(batch_size=15)

        mock_genai, mock_model, _ = self._make_mock_genai([
            [{"id": 1, "text_vi": "Xin chào"}, {"id": 2, "text_vi": "Cảm ơn"}]
        ])

        with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
            results = list(translate_in_batches(segments, settings, api_key="fake"))

        # Cả 2 segment phải được gửi
        prompt_text = mock_model.generate_content.call_args[0][0][0]["text"]
        assert '"id": 1' in prompt_text
        assert '"id": 2' in prompt_text


# ---------------------------------------------------------------------------
# Tests: translate_in_batches — batch isolation
# ---------------------------------------------------------------------------


class TestTranslateInBatchesBatchIsolation:
    def test_batch_error_does_not_block_other_batches(self):
        """Batch fail không chặn các batch khác — mix of success/error results."""
        # Use 2 batches: batch 0 succeeds, batch 1 always fails
        # Use max_concurrent_batches=1 (serial) to avoid thread-ordering issues
        segments = [
            make_segment(i, start=float(i), end=float(i) + 0.9)
            for i in range(1, 7)  # 6 segments → 2 batches of 3
        ]
        settings = ProjectSettings(batch_size=3)

        call_count = [0]
        import threading
        lock = threading.Lock()
        mock_model = MagicMock()

        def gen_content(*args, **kwargs):
            with lock:
                call_count[0] += 1
                n = call_count[0]

            if n == 1:
                # First batch: success
                import re
                text = args[0][0]["text"]
                ids = [int(m) for m in re.findall(r'"id":\s*(\d+)', text)]
                return make_mock_response([{"id": sid, "text_vi": f"câu {sid}"} for sid in ids])
            else:
                # All subsequent batches fail (simulates batch 2 quota error)
                raise Exception("429 quota exceeded")

        mock_model.generate_content.side_effect = gen_content
        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        with patch("msdubstudio.core.translator.time.sleep"):
            with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
                results = list(
                    translate_in_batches(
                        segments, settings, api_key="fake",
                        max_concurrent_batches=1,  # serial to ensure determinism
                    )
                )

        assert len(results) == 2

        error_results = [r for r in results if r.is_error]
        success_results = [r for r in results if not r.is_error]
        # One batch succeeded, one failed
        assert len(error_results) == 1
        assert len(success_results) == 1
        assert error_results[0].error_message is not None


# ---------------------------------------------------------------------------
# Tests: translate_in_batches — retry behavior
# ---------------------------------------------------------------------------


class TestTranslateInBatchesRetry:
    def test_retries_on_rate_limit_then_succeeds(self):
        """429 lần đầu → retry → thành công → BatchResult không phải error."""
        segments = [make_segment(1)]
        settings = ProjectSettings(batch_size=15)

        call_count = [0]
        mock_model = MagicMock()

        def gen_content(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("429 Rate Limit Exceeded")
            return make_mock_response([{"id": 1, "text_vi": "Xin chào"}])

        mock_model.generate_content.side_effect = gen_content
        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        with patch("msdubstudio.core.translator.time.sleep"):
            with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
                results = list(translate_in_batches(segments, settings, api_key="fake"))

        assert len(results) == 1
        assert results[0].is_error is False
        assert results[0].segments[0].text_vi == "Xin chào"
        # Phải được gọi ít nhất 2 lần (1 fail + 1 success)
        assert mock_model.generate_content.call_count >= 2

    def test_exhausted_retries_yields_error_result(self):
        """Sau khi hết retry → BatchResult.is_error = True."""
        segments = [make_segment(1)]
        settings = ProjectSettings(batch_size=15)

        mock_model = MagicMock()
        mock_model.generate_content.side_effect = Exception("429 always")
        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        with patch("msdubstudio.core.translator.time.sleep"):
            with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
                results = list(translate_in_batches(segments, settings, api_key="fake"))

        assert len(results) == 1
        assert results[0].is_error is True
        assert results[0].error_message is not None

    def test_fatal_error_yields_error_result_immediately(self):
        """FatalApiError (API key sai) không retry — yield error ngay."""
        segments = [make_segment(1)]
        settings = ProjectSettings(batch_size=15)

        mock_model = MagicMock()
        mock_model.generate_content.side_effect = Exception("401 Invalid API key")
        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
            results = list(translate_in_batches(segments, settings, api_key="fake"))

        assert len(results) == 1
        assert results[0].is_error is True


# ---------------------------------------------------------------------------
# Tests: translate_in_batches — cancel
# ---------------------------------------------------------------------------


class TestTranslateInBatchesCancel:
    def test_cancel_stops_yielding(self):
        """Khi cancel_check() → True, không yield thêm kết quả nào."""
        # 30 segment → 2 batch (batch_size=15)
        segments = [
            make_segment(i, start=float(i), end=float(i) + 0.9)
            for i in range(1, 31)
        ]
        settings = ProjectSettings(batch_size=15)

        mock_model = MagicMock()
        mock_model.generate_content.return_value = make_mock_response(
            [{"id": i, "text_vi": f"câu {i}"} for i in range(1, 16)]
        )
        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        # Cancel ngay từ đầu
        cancelled = True

        with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
            results = list(
                translate_in_batches(
                    segments, settings, api_key="fake",
                    cancel_check=lambda: cancelled,
                )
            )

        # Không có kết quả nào được yield
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Tests: BatchResult từ translate_in_batches
# ---------------------------------------------------------------------------


class TestBatchResultFromGenerator:
    def test_progress_tracking(self):
        """current và total phải theo dõi đúng tiến độ."""
        # 2 batch × 3 segment mỗi batch = 6 segment tổng
        segments = [make_segment(i, start=float(i), end=float(i) + 0.9) for i in range(1, 7)]
        settings = ProjectSettings(batch_size=3)

        mock_model = MagicMock()
        call_count = [0]

        def gen_content(*args, **kwargs):
            text = args[0][0]["text"]
            import re
            ids = [int(m) for m in re.findall(r'"id":\s*(\d+)', text)]
            call_count[0] += 1
            return make_mock_response([{"id": sid, "text_vi": f"v{sid}"} for sid in ids])

        mock_model.generate_content.side_effect = gen_content
        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
            results = list(translate_in_batches(
                segments, settings, api_key="fake", max_concurrent_batches=1
            ))

        assert len(results) == 2
        # total phải là 6 (tổng số cần dịch)
        for r in results:
            assert r.total == 6

        # Sau tất cả batch, tổng current phải đúng
        total_current = max(r.current for r in results)
        assert total_current == 6
