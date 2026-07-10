"""
core/translator.py — Gemini API batch translate + retry + idempotency

Đây là module phức tạp nhất và dễ bug nhất trong pipeline:
1. Batch strategy: chia segments thành batch size N, giữ context
2. Concurrent: chạy 2-3 batch song song, không phải tuần tự
3. Retry: exponential backoff cho lỗi tạm thời (429, 5xx, timeout)
4. Idempotency: chỉ dịch segment chưa TRANSLATED/REVIEWED
5. Structured Output: Gemini JSON Schema để tránh parse tự do
6. Batch isolation: batch lỗi không chặn batch khác

Không import PyQt6.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Generator, Iterator, Optional

from msdubstudio.core.models import (
    BatchResult,
    ProjectSettings,
    Segment,
    SegmentStatus,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TranslatorError(Exception):
    """Lỗi dịch thuật chung."""


class RetriableError(TranslatorError):
    """Lỗi tạm thời có thể retry: 429, 503, timeout mạng."""


class FatalApiError(TranslatorError):
    """Lỗi API không thể tự sửa: API key sai, model không tồn tại, quota hết."""


class ContentBlockedError(TranslatorError):
    """Nội dung bị Gemini block (safety filter)."""


class StructuredOutputError(TranslatorError):
    """Gemini trả về JSON không parse được hoặc thiếu field."""


# ---------------------------------------------------------------------------
# Retry logic (tầng 1 — bên trong translator)
# ---------------------------------------------------------------------------


def call_with_retry(
    fn: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    retry_on: tuple = (RetriableError,),
) -> any:
    """Gọi fn() với retry tự động khi gặp RetriableError.

    Chiến lược: exponential backoff — 1s, 2s, 4s
    User không thấy gì nếu retry thành công.

    Args:
        fn: Callable không có tham số.
        max_retries: Số lần retry tối đa (không tính lần đầu).
        base_delay: Thời gian chờ cơ bản (giây).
        retry_on: Tuple các exception class sẽ trigger retry.

    Returns:
        Kết quả từ fn() nếu thành công.

    Raises:
        Exception gốc nếu hết số lần retry.
    """
    last_exception: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except retry_on as e:
            last_exception = e
            if attempt == max_retries:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(
                f"Retry {attempt + 1}/{max_retries} sau {delay:.1f}s: {e}"
            )
            time.sleep(delay)
    raise last_exception  # unreachable nhưng type checker cần


# ---------------------------------------------------------------------------
# Batch creation
# ---------------------------------------------------------------------------


def make_batches(
    segments: list[Segment],
    batch_size: int,
) -> list[list[Segment]]:
    """Chia danh sách segment thành các batch liên tiếp.

    Giữ thứ tự câu trong batch để Gemini có đủ context hội thoại.

    Args:
        segments: List segment cần dịch.
        batch_size: Số câu tối đa mỗi batch.

    Returns:
        List of lists, mỗi list là 1 batch.
    """
    if batch_size <= 0:
        raise ValueError(f"batch_size phải > 0, nhận: {batch_size}")
    return [segments[i:i + batch_size] for i in range(0, len(segments), batch_size)]


# ---------------------------------------------------------------------------
# Gemini prompt builder
# ---------------------------------------------------------------------------


def build_translate_prompt(
    batch: list[Segment],
    source_lang: str = "zh",
    target_lang: str = "vi",
    scene_frame_path: Optional[str] = None,
) -> list[dict]:
    """Tạo prompt cho Gemini theo cấu trúc multipart content.

    Trả về list parts để truyền vào Gemini API content.

    Args:
        batch: List Segment cần dịch trong batch này.
        source_lang: Mã ngôn ngữ nguồn (ví dụ: 'zh').
        target_lang: Mã ngôn ngữ đích (ví dụ: 'vi').
        scene_frame_path: Đường dẫn ảnh scene context (nếu có).

    Returns:
        List dict parts cho Gemini API.
    """
    lang_names = {
        "zh": "Chinese (Mandarin)",
        "vi": "Vietnamese",
        "en": "English",
        "ja": "Japanese",
        "ko": "Korean",
    }

    source_name = lang_names.get(source_lang, source_lang)
    target_name = lang_names.get(target_lang, target_lang)

    # Tạo text segments để đưa vào prompt
    segments_json = json.dumps(
        [{"id": s.id, "text": s.text_zh} for s in batch],
        ensure_ascii=False,
        indent=2,
    )

    system_text = (
        f"You are a professional translator specializing in {source_name} to {target_name} translation "
        f"for video dubbing. Your translations must:\n"
        f"1. Be natural and idiomatic in {target_name}\n"
        f"2. Maintain the original meaning and tone precisely\n"
        f"3. Be appropriate for spoken audio (not literal subtitles)\n"
        f"4. Consider the visual context if an image is provided\n"
        f"5. Keep translations concise — spoken audio must fit the original timing\n\n"
        f"Translate the following {source_name} segments to {target_name}.\n"
        f"Return a JSON array where each item has 'id' and 'text_vi' fields.\n"
        f"Do NOT include any explanation or extra text — ONLY the JSON array.\n\n"
        f"Segments to translate:\n{segments_json}"
    )

    parts = [{"text": system_text}]

    # Đính kèm scene frame nếu có
    if scene_frame_path and Path(scene_frame_path).exists():
        try:
            image_data = Path(scene_frame_path).read_bytes()
            image_b64 = base64.b64encode(image_data).decode()
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": image_b64,
                }
            })
            parts.append({
                "text": "Use the above image as visual context for translation."
            })
        except OSError as e:
            logger.warning(f"Không đọc được scene frame {scene_frame_path}: {e}")

    return parts


# ---------------------------------------------------------------------------
# Gemini API call
# ---------------------------------------------------------------------------


def translate_batch_with_gemini(
    batch: list[Segment],
    settings: ProjectSettings,
    api_key: str,
) -> list[Segment]:
    """Gọi Gemini API để dịch một batch segment.

    Args:
        batch: List Segment cần dịch.
        settings: ProjectSettings.
        api_key: Gemini API key.

    Returns:
        List Segment đã được cập nhật text_vi và status=TRANSLATED.

    Raises:
        RetriableError: Lỗi tạm thời (429, 503, timeout).
        FatalApiError: Lỗi API key, model, quota.
        ContentBlockedError: Nội dung bị safety filter.
        StructuredOutputError: Response không parse được.
    """
    try:
        import google.generativeai as genai  # type: ignore
    except ImportError:
        raise FatalApiError(
            "Thiếu thư viện google-generativeai. Chạy: pip install google-generativeai"
        )

    genai.configure(api_key=api_key)

    # Lấy scene frame từ segment đầu tiên trong batch (nếu có)
    scene_frame = None
    if settings.use_context_frame:
        for seg in batch:
            if seg.scene_frame and Path(seg.scene_frame).exists():
                scene_frame = seg.scene_frame
                break

    parts = build_translate_prompt(
        batch,
        source_lang=settings.source_lang,
        target_lang=settings.target_lang,
        scene_frame_path=scene_frame,
    )

    # JSON Schema cho Structured Output
    response_schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "text_vi": {"type": "string"},
            },
            "required": ["id", "text_vi"],
        },
    }

    generation_config = {
        "temperature": settings.translate_temperature,
        "response_mime_type": "application/json",
        "response_schema": response_schema,
    }

    model = genai.GenerativeModel(settings.gemini_model)

    def _call():
        try:
            response = model.generate_content(
                parts,
                generation_config=generation_config,
            )
            return response
        except Exception as e:
            _handle_gemini_exception(e)

    response = _call()

    # Parse Structured Output
    return _parse_translate_response(response, batch)


def _handle_gemini_exception(exc: Exception) -> None:
    """Phân loại exception từ Gemini và raise exception chuẩn của chúng ta."""
    exc_str = str(exc).lower()
    exc_type = type(exc).__name__

    # 429 Rate Limit
    if "429" in str(exc) or "quota" in exc_str or "rate" in exc_str:
        raise RetriableError(f"Gemini rate limit / quota: {exc}") from exc

    # 503 Service Unavailable
    if "503" in str(exc) or "unavailable" in exc_str or "internal" in exc_str:
        raise RetriableError(f"Gemini service unavailable: {exc}") from exc

    # Timeout
    if "timeout" in exc_str or "deadline" in exc_str:
        raise RetriableError(f"Gemini request timeout: {exc}") from exc

    # Safety / content blocked
    if "safety" in exc_str or "blocked" in exc_str or "finish_reason" in exc_str:
        raise ContentBlockedError(f"Nội dung bị Gemini block: {exc}") from exc

    # API key / auth
    if "api_key" in exc_str or "auth" in exc_str or "401" in str(exc) or "403" in str(exc):
        raise FatalApiError(f"Lỗi xác thực Gemini API: {exc}") from exc

    # Model not found
    if "model" in exc_str and ("not found" in exc_str or "404" in str(exc)):
        raise FatalApiError(f"Model Gemini không tồn tại: {exc}") from exc

    # Default: treat as retriable (unknown errors might be transient)
    raise RetriableError(f"Lỗi Gemini không xác định: {exc}") from exc


def _parse_translate_response(response, batch: list[Segment]) -> list[Segment]:
    """Parse Gemini response và update batch segments.

    Args:
        response: Gemini response object.
        batch: List Segment gốc.

    Returns:
        List Segment đã update text_vi.

    Raises:
        StructuredOutputError: Không parse được JSON.
    """
    try:
        text = response.text
        if not text:
            raise StructuredOutputError("Gemini trả về response rỗng")

        translations = json.loads(text)
        if not isinstance(translations, list):
            raise StructuredOutputError(
                f"Gemini trả về type sai: {type(translations).__name__}, mong đợi list"
            )
    except json.JSONDecodeError as e:
        raise StructuredOutputError(
            f"Gemini response không phải JSON hợp lệ: {e}\nResponse: {getattr(response, 'text', '')[:200]}"
        ) from e
    except AttributeError as e:
        raise StructuredOutputError(f"Gemini response không có .text: {e}") from e

    # Tạo map id → text_vi
    translation_map: dict[int, str] = {}
    for item in translations:
        if not isinstance(item, dict):
            continue
        seg_id = item.get("id")
        text_vi = item.get("text_vi")
        if seg_id is not None and text_vi is not None:
            translation_map[int(seg_id)] = str(text_vi).strip()

    # Update segments
    updated = []
    for seg in batch:
        if seg.id in translation_map:
            seg = seg.model_copy(update={
                "text_vi": translation_map[seg.id],
                "status": SegmentStatus.TRANSLATED,
                "error_message": None,
            })
        else:
            # Segment không có trong response → đánh dấu lỗi
            logger.warning(f"Segment {seg.id} không có trong Gemini response")
            seg = seg.model_copy(update={
                "status": SegmentStatus.ERROR,
                "error_message": "Segment không có trong Gemini response",
            })
        updated.append(seg)

    return updated


# ---------------------------------------------------------------------------
# Main: translate_in_batches (Generator — dùng bởi TranslateWorker)
# ---------------------------------------------------------------------------


def translate_in_batches(
    segments: list[Segment],
    settings: ProjectSettings,
    api_key: str,
    cancel_check: Optional[Callable[[], bool]] = None,
    max_concurrent_batches: int = 2,
) -> Generator[BatchResult, None, None]:
    """Dịch danh sách segment theo batch, yield từng BatchResult.

    Đây là Generator — TranslateWorker iterate qua và emit signal cho mỗi result.

    Chiến lược:
    - Chỉ gửi segment có status != TRANSLATED và != REVIEWED (idempotency)
    - Chia thành batch_size câu/batch
    - Chạy max_concurrent_batches batch đồng thời (ThreadPoolExecutor)
    - Batch lỗi không chặn batch khác — emit BatchResult với is_error=True
    - Retry tự động tầng 1 bên trong translate_batch_with_gemini
    - Yield BatchResult theo thứ tự hoàn thành (không nhất thiết theo thứ tự gửi)

    Args:
        segments: Toàn bộ segments (kể cả đã dịch — sẽ bị bỏ qua).
        settings: ProjectSettings.
        api_key: Gemini API key.
        cancel_check: Callable trả về True nếu user Cancel.
        max_concurrent_batches: Số batch chạy đồng thời tối đa.

    Yields:
        BatchResult cho mỗi batch (thành công hoặc thất bại).
    """
    # Idempotency: chỉ lấy segment cần dịch
    to_translate = [
        s for s in segments
        if s.status not in (SegmentStatus.TRANSLATED, SegmentStatus.REVIEWED)
    ]

    if not to_translate:
        logger.info("Không có segment nào cần dịch (tất cả đã TRANSLATED/REVIEWED)")
        return

    batches = make_batches(to_translate, settings.batch_size)
    total_segments = len(to_translate)
    processed_segments = 0

    logger.info(
        f"Bắt đầu dịch: {total_segments} segment, "
        f"{len(batches)} batch (size={settings.batch_size}), "
        f"max_concurrent={max_concurrent_batches}"
    )

    with ThreadPoolExecutor(max_workers=max_concurrent_batches) as executor:
        # Submit tất cả batch
        future_to_batch = {}
        for batch_idx, batch in enumerate(batches):
            if cancel_check and cancel_check():
                logger.info(f"Translate bị cancel trước khi submit batch {batch_idx}")
                break

            future = executor.submit(
                _translate_single_batch_with_retry,
                batch_idx=batch_idx,
                batch=batch,
                settings=settings,
                api_key=api_key,
            )
            future_to_batch[future] = (batch_idx, batch)

        # Thu kết quả theo thứ tự hoàn thành
        for future in as_completed(future_to_batch):
            if cancel_check and cancel_check():
                logger.info("Translate bị cancel — dừng xử lý kết quả")
                # Không cancel future đang chạy (safe), chỉ dừng yield
                break

            batch_idx, batch = future_to_batch[future]
            processed_segments += len(batch)

            try:
                updated_segments = future.result()
                yield BatchResult(
                    batch_index=batch_idx,
                    current=processed_segments,
                    total=total_segments,
                    segments=updated_segments,
                    is_error=False,
                )
                logger.debug(
                    f"Batch {batch_idx} xong: {len(updated_segments)} segment"
                )
            except (FatalApiError, ContentBlockedError) as e:
                # Lỗi nghiêm trọng không retry — vẫn yield để UI biết
                yield BatchResult(
                    batch_index=batch_idx,
                    current=processed_segments,
                    total=total_segments,
                    is_error=True,
                    error_message=str(e),
                )
                logger.error(f"Batch {batch_idx} lỗi nghiêm trọng: {e}")
            except RetriableError as e:
                # Đã retry hết lần trong _translate_single_batch_with_retry
                yield BatchResult(
                    batch_index=batch_idx,
                    current=processed_segments,
                    total=total_segments,
                    is_error=True,
                    error_message=f"Retry thất bại: {e}",
                )
                logger.error(f"Batch {batch_idx} lỗi sau retry: {e}")
            except Exception as e:
                yield BatchResult(
                    batch_index=batch_idx,
                    current=processed_segments,
                    total=total_segments,
                    is_error=True,
                    error_message=str(e),
                )
                logger.exception(f"Batch {batch_idx} lỗi không mong đợi: {e}")


def _translate_single_batch_with_retry(
    batch_idx: int,
    batch: list[Segment],
    settings: ProjectSettings,
    api_key: str,
) -> list[Segment]:
    """Wrap translate_batch_with_gemini với retry cho một batch.

    Được gọi trong ThreadPoolExecutor — không emit signal.
    """
    logger.debug(f"Bắt đầu batch {batch_idx}: {len(batch)} segment")

    def call():
        return translate_batch_with_gemini(batch, settings, api_key)

    # Chỉ retry RetriableError, không retry FatalApiError/ContentBlockedError
    return call_with_retry(
        call,
        max_retries=3,
        base_delay=1.0,
        retry_on=(RetriableError,),
    )


# ---------------------------------------------------------------------------
# Quick Actions (dùng cho Review tab)
# ---------------------------------------------------------------------------


QUICK_ACTION_PROMPTS = {
    "shorten": "Rút gọn câu dịch sau (giữ ý chính, ngắn hơn 30%): {text_vi}\nChỉ trả về câu đã rút gọn, không giải thích.",
    "expand": "Mở rộng câu dịch sau thêm chi tiết tự nhiên: {text_vi}\nChỉ trả về câu đã mở rộng.",
    "formalize": "Chuyển câu dịch sau sang văn phong trang trọng hơn: {text_vi}\nChỉ trả về câu đã chuyển đổi.",
    "simplify": "Đơn giản hóa câu dịch sau cho người nghe dễ hiểu hơn: {text_vi}\nChỉ trả về câu đã đơn giản hóa.",
    "fix_punctuation": "Sửa lỗi chính tả và dấu câu trong câu dịch sau: {text_vi}\nChỉ trả về câu đã sửa.",
    "improve_fluency": "Cải thiện sự tự nhiên và trôi chảy của câu dịch sau: {text_vi}\nChỉ trả về câu đã cải thiện.",
}


def refine_segment(
    segment: Segment,
    action: str,
    settings: ProjectSettings,
    api_key: str,
) -> str:
    """Dùng Gemini để refine một câu theo action cụ thể (Quick Actions).

    Args:
        segment: Segment cần refine. Phải có text_vi.
        action: Tên action: 'shorten', 'expand', 'formalize', etc.
        settings: ProjectSettings.
        api_key: Gemini API key.

    Returns:
        Văn bản tiếng Việt đã được refine.

    Raises:
        ValueError: action không hợp lệ hoặc text_vi là None.
        RetriableError, FatalApiError: Lỗi API.
    """
    if segment.text_vi is None:
        raise ValueError(f"Segment {segment.id} chưa có text_vi để refine")

    if action not in QUICK_ACTION_PROMPTS:
        raise ValueError(
            f"Action không hợp lệ: {action!r}. "
            f"Các action hợp lệ: {list(QUICK_ACTION_PROMPTS)}"
        )

    try:
        import google.generativeai as genai  # type: ignore
    except ImportError:
        raise FatalApiError("Thiếu thư viện google-generativeai")

    genai.configure(api_key=api_key)

    prompt = QUICK_ACTION_PROMPTS[action].format(text_vi=segment.text_vi)
    model = genai.GenerativeModel(settings.gemini_model)

    def _call():
        try:
            response = model.generate_content(
                prompt,
                generation_config={"temperature": 0.5},
            )
            return response.text.strip()
        except Exception as e:
            _handle_gemini_exception(e)

    return call_with_retry(_call, max_retries=2, base_delay=1.0)
