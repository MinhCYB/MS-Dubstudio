"""
core/stt.py — Whisper Speech-to-Text wrapper cho MS DubStudio

Chịu trách nhiệm:
- Load Whisper model (faster-whisper hoặc openai-whisper)
- Transcribe audio file → list dict segment
- Format output thành cấu trúc chuẩn để Project.update_segments_from_stt() dùng

Thiết kế để có thể mock hoàn toàn trong test — interface rõ ràng,
không phụ thuộc state ngoài.

Không import PyQt6.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Iterator, Optional

from msdubstudio.core.models import ProjectSettings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class STTError(Exception):
    """Lỗi khi thực hiện Speech-to-Text."""


class WhisperModelNotFoundError(STTError):
    """Model Whisper không tồn tại hoặc không tải được."""


class AudioFileError(STTError):
    """File audio không tồn tại hoặc không đọc được."""


# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------


# Raw segment format từ Whisper/faster-whisper (sau khi normalize)
RawSegment = dict  # keys: id, start, end, text, speaker, confidence, scene_frame


# ---------------------------------------------------------------------------
# Main transcribe function
# ---------------------------------------------------------------------------


def transcribe(
    audio_path: str,
    settings: ProjectSettings,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> list[RawSegment]:
    """Chạy Whisper STT trên file audio.

    Args:
        audio_path: Đường dẫn tuyệt đối tới file WAV.
        settings: ProjectSettings chứa cấu hình Whisper.
        progress_callback: Callable(current_segment, total_duration_s) để report tiến độ.
        cancel_check: Callable trả về True nếu user đã bấm Cancel.

    Returns:
        List[RawSegment] — mỗi dict có keys:
            - id: int (1-based)
            - start: float (giây)
            - end: float (giây)
            - text: str (văn bản gốc)
            - speaker: str (mặc định 'A' — diarization riêng nếu cần)
            - confidence: float (avg_logprob normalized)
            - scene_frame: str | None (None ở bước này, gán sau ở scene.py)

    Raises:
        AudioFileError: File audio không tồn tại.
        WhisperModelNotFoundError: Không load được model.
        STTError: Lỗi runtime khác.
    """
    if not Path(audio_path).exists():
        raise AudioFileError(f"File audio không tồn tại: {audio_path}")

    # Thử faster-whisper trước (nhanh hơn, ít VRAM hơn)
    try:
        return _transcribe_with_faster_whisper(
            audio_path, settings, progress_callback, cancel_check
        )
    except ImportError:
        logger.info("faster-whisper không có, thử openai-whisper...")

    # Fallback sang openai-whisper
    try:
        return _transcribe_with_openai_whisper(
            audio_path, settings, progress_callback, cancel_check
        )
    except ImportError:
        raise WhisperModelNotFoundError(
            "Không tìm thấy thư viện Whisper. Cài đặt: pip install faster-whisper "
            "hoặc pip install openai-whisper"
        )


def _transcribe_with_faster_whisper(
    audio_path: str,
    settings: ProjectSettings,
    progress_callback: Optional[Callable[[int, int], None]],
    cancel_check: Optional[Callable[[], bool]],
) -> list[RawSegment]:
    """Transcribe dùng faster-whisper (CTranslate2 backend, nhanh hơn ~4x)."""
    from faster_whisper import WhisperModel  # type: ignore

    device = _resolve_device(settings.whisper_device)
    compute_type = settings.whisper_compute_type

    logger.info(
        f"Đang load Whisper model '{settings.whisper_model}' "
        f"trên {device} (compute_type={compute_type})"
    )

    try:
        model = WhisperModel(
            settings.whisper_model,
            device=device,
            compute_type=compute_type,
        )
    except Exception as e:
        raise WhisperModelNotFoundError(
            f"Không load được model '{settings.whisper_model}': {e}"
        ) from e

    transcribe_kwargs: dict = {
        "task": settings.whisper_task,
        "beam_size": settings.whisper_beam_size,
        "best_of": settings.whisper_best_of,
        "vad_filter": True,  # lọc khoảng im lặng
    }
    if settings.whisper_language:
        transcribe_kwargs["language"] = settings.whisper_language

    logger.info(f"Bắt đầu transcribe: {audio_path}")

    try:
        segments_iter, info = model.transcribe(audio_path, **transcribe_kwargs)
    except Exception as e:
        raise STTError(f"Whisper transcribe thất bại: {e}") from e

    raw_segments: list[RawSegment] = []
    total_duration = info.duration

    for i, seg in enumerate(segments_iter):
        if cancel_check and cancel_check():
            logger.info(f"STT bị cancel tại segment {i + 1}")
            break

        # avg_logprob từ faster-whisper, normalize về 0-1
        confidence = _normalize_logprob(seg.avg_logprob)

        raw_segments.append({
            "id": i + 1,
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
            "speaker": "A",  # diarization sẽ được gán riêng nếu cần
            "confidence": confidence,
            "scene_frame": None,  # gán sau ở scene.py
        })

        if progress_callback:
            progress_callback(i + 1, int(total_duration))

    logger.info(f"STT hoàn thành: {len(raw_segments)} segment")
    return raw_segments


def _transcribe_with_openai_whisper(
    audio_path: str,
    settings: ProjectSettings,
    progress_callback: Optional[Callable[[int, int], None]],
    cancel_check: Optional[Callable[[], bool]],
) -> list[RawSegment]:
    """Transcribe dùng openai-whisper (PyTorch backend, fallback)."""
    import whisper  # type: ignore

    device = _resolve_device(settings.whisper_device)

    logger.info(f"Đang load openai-whisper model '{settings.whisper_model}' trên {device}")

    try:
        model = whisper.load_model(settings.whisper_model, device=device)
    except Exception as e:
        raise WhisperModelNotFoundError(
            f"Không load được model '{settings.whisper_model}': {e}"
        ) from e

    transcribe_kwargs: dict = {
        "task": settings.whisper_task,
        "beam_size": settings.whisper_beam_size,
        "best_of": settings.whisper_best_of,
    }
    if settings.whisper_language:
        transcribe_kwargs["language"] = settings.whisper_language

    try:
        result = model.transcribe(audio_path, **transcribe_kwargs)
    except Exception as e:
        raise STTError(f"Whisper transcribe thất bại: {e}") from e

    raw_segments: list[RawSegment] = []
    for i, seg in enumerate(result.get("segments", [])):
        if cancel_check and cancel_check():
            break

        # avg_logprob từ openai-whisper
        confidence = _normalize_logprob(seg.get("avg_logprob", -1.0))

        raw_segments.append({
            "id": i + 1,
            "start": float(seg["start"]),
            "end": float(seg["end"]),
            "text": seg["text"].strip(),
            "speaker": "A",
            "confidence": confidence,
            "scene_frame": None,
        })

        if progress_callback:
            progress_callback(i + 1, len(result.get("segments", [])))

    return raw_segments


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_device(device: str) -> str:
    """Resolve 'auto' → 'cuda' nếu có GPU, ngược lại 'cpu'."""
    if device != "auto":
        return device
    try:
        import torch  # type: ignore
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _normalize_logprob(avg_logprob: float) -> float:
    """Chuyển avg_logprob (âm) sang confidence 0.0–1.0.

    avg_logprob thường trong khoảng [-2, 0]:
    - 0 = perfect confidence → 1.0
    - -1 → khoảng 0.5
    - <= -2 → gần 0

    Dùng hàm tuyến tính clamp: confidence = max(0, 1 + avg_logprob/2)
    """
    confidence = max(0.0, 1.0 + avg_logprob / 2.0)
    return min(1.0, confidence)


def assign_scene_frames(
    raw_segments: list[RawSegment],
    scenes: list[dict],
) -> list[RawSegment]:
    """Gán scene_frame cho mỗi segment dựa theo thời gian.

    Mỗi segment được gán frame của scene chứa thời điểm giữa segment (midpoint).
    Nếu không có scene nào chứa segment, dùng scene gần nhất.

    Args:
        raw_segments: List segment từ transcribe().
        scenes: List dict từ scene.py: [{start, end, frame_path}].

    Returns:
        List segment đã được gán scene_frame.
    """
    if not scenes:
        return raw_segments

    updated = []
    for seg in raw_segments:
        midpoint = (seg["start"] + seg["end"]) / 2
        frame_path = _find_scene_frame(midpoint, scenes)
        updated.append({**seg, "scene_frame": frame_path})
    return updated


def _find_scene_frame(time_s: float, scenes: list[dict]) -> Optional[str]:
    """Tìm scene_frame cho thời điểm time_s."""
    # Tìm scene chứa time_s
    for scene in scenes:
        if scene["start"] <= time_s <= scene["end"]:
            return scene.get("frame_path")
    # Fallback: scene có start gần nhất
    if scenes:
        closest = min(scenes, key=lambda s: abs(s["start"] - time_s))
        return closest.get("frame_path")
    return None
