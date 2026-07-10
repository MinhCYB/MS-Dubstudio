"""
core/tts.py — Text-to-Speech engine wrapper cho MS DubStudio

Engine chính: edge-tts (Microsoft Edge TTS, miễn phí, không cần API key)
Fallback: có thể mở rộng sau (Google TTS, Azure TTS...)

Chịu trách nhiệm:
- Sinh file audio WAV từ văn bản tiếng Việt
- Hỗ trợ nhiều giọng đọc (male/female, phong cách khác nhau)
- Điều chỉnh rate/pitch/volume
- List danh sách giọng có sẵn (để hiện trong Voice settings)

Không import PyQt6.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TTSError(Exception):
    """Lỗi khi sinh TTS."""


class TTSEngineNotFoundError(TTSError):
    """TTS engine chưa được cài."""


class TTSVoiceNotFoundError(TTSError):
    """Voice ID không hợp lệ hoặc không tìm thấy."""


# ---------------------------------------------------------------------------
# Default Vietnamese voices
# ---------------------------------------------------------------------------


# Danh sách giọng tiếng Việt mặc định (edge-tts)
# Format: (voice_id, display_name, gender)
EDGE_TTS_VI_VOICES: list[tuple[str, str, str]] = [
    ("vi-VN-NamMinhNeural", "Nam Minh (Nam)", "male"),
    ("vi-VN-HoaiMyNeural", "Hoài My (Nữ)", "female"),
]

# Giọng mặc định theo giới tính
DEFAULT_MALE_VOICE = "vi-VN-NamMinhNeural"
DEFAULT_FEMALE_VOICE = "vi-VN-HoaiMyNeural"
DEFAULT_VOICE = DEFAULT_FEMALE_VOICE


# ---------------------------------------------------------------------------
# Main TTS functions
# ---------------------------------------------------------------------------


def synthesize(
    text: str,
    output_path: str,
    voice_id: str = DEFAULT_VOICE,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    volume: str = "+0%",
    engine: str = "edge-tts",
) -> str:
    """Sinh file audio từ văn bản.

    Args:
        text: Văn bản tiếng Việt cần đọc.
        output_path: Đường dẫn lưu file audio đầu ra (WAV hoặc MP3).
        voice_id: ID giọng đọc (ví dụ: 'vi-VN-HoaiMyNeural').
        rate: Tốc độ đọc ('+10%' = nhanh hơn 10%, '-10%' = chậm hơn 10%).
        pitch: Cao độ giọng ('+10Hz', '-10Hz').
        volume: Âm lượng ('+10%', '-10%').
        engine: TTS engine ('edge-tts' — mặc định).

    Returns:
        Đường dẫn tuyệt đối của file audio đã tạo.

    Raises:
        TTSEngineNotFoundError: Engine chưa cài.
        TTSVoiceNotFoundError: Voice ID không hợp lệ.
        TTSError: Lỗi runtime khác.
    """
    if not text or not text.strip():
        raise TTSError("Văn bản rỗng — không thể sinh TTS")

    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    if engine == "edge-tts":
        return _synthesize_edge_tts(
            text.strip(), str(output_path_obj),
            voice_id, rate, pitch, volume
        )
    else:
        raise TTSEngineNotFoundError(
            f"Engine '{engine}' chưa được hỗ trợ. Chỉ hỗ trợ: edge-tts"
        )


def _synthesize_edge_tts(
    text: str,
    output_path: str,
    voice_id: str,
    rate: str,
    pitch: str,
    volume: str,
) -> str:
    """Sinh audio dùng edge-tts (async → chạy trong event loop)."""
    try:
        import edge_tts  # type: ignore
    except ImportError:
        raise TTSEngineNotFoundError(
            "edge-tts chưa được cài. Chạy: pip install edge-tts"
        )

    async def _run():
        communicate = edge_tts.Communicate(
            text=text,
            voice=voice_id,
            rate=rate,
            pitch=pitch,
            volume=volume,
        )
        await communicate.save(output_path)

    try:
        # Chạy coroutine trong event loop mới (thread-safe, không dùng loop của main thread)
        asyncio.run(_run())
    except Exception as e:
        exc_str = str(e).lower()
        if "voice" in exc_str or "not found" in exc_str or "invalid" in exc_str:
            raise TTSVoiceNotFoundError(
                f"Voice ID '{voice_id}' không hợp lệ hoặc không tìm thấy: {e}"
            ) from e
        raise TTSError(f"edge-tts thất bại: {e}") from e

    output_obj = Path(output_path)
    if not output_obj.exists() or output_obj.stat().st_size == 0:
        raise TTSError(
            f"edge-tts chạy xong nhưng file output không tồn tại hoặc rỗng: {output_path}"
        )

    logger.debug(f"TTS: '{text[:30]}...' → {output_path}")
    return str(output_obj.resolve())


# ---------------------------------------------------------------------------
# Batch synthesis (dùng bởi TTSWorker)
# ---------------------------------------------------------------------------


def synthesize_segments(
    segments: list[dict],
    voice_dir: str,
    get_voice_id: Callable[[str], str],
    get_rate: Callable[[str], str] = lambda _: "+0%",
    get_pitch: Callable[[str], str] = lambda _: "+0Hz",
    get_volume: Callable[[str], str] = lambda _: "+0%",
    engine: str = "edge-tts",
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> list[dict]:
    """Sinh TTS cho danh sách segment.

    Args:
        segments: List dict với keys: id, text_vi, speaker.
        voice_dir: Thư mục lưu file audio TTS.
        get_voice_id: Callable(speaker_id) → voice_id.
        get_rate: Callable(speaker_id) → rate string.
        get_pitch: Callable(speaker_id) → pitch string.
        get_volume: Callable(speaker_id) → volume string.
        engine: TTS engine.
        progress_callback: Callable(current, total).
        cancel_check: Callable → True nếu đã cancel.

    Yields... (thực ra trả về list):
        List dict: {segment_id, voice_path, success, error_message}.
    """
    results = []
    total = len(segments)
    voice_dir_path = Path(voice_dir)
    voice_dir_path.mkdir(parents=True, exist_ok=True)

    for i, seg in enumerate(segments):
        if cancel_check and cancel_check():
            break

        seg_id = seg["id"]
        text_vi = seg.get("text_vi", "").strip()
        speaker = seg.get("speaker", "A")

        if not text_vi:
            results.append({
                "segment_id": seg_id,
                "voice_path": None,
                "success": False,
                "error_message": "text_vi rỗng",
            })
            if progress_callback:
                progress_callback(i + 1, total)
            continue

        voice_id = get_voice_id(speaker)
        output_filename = f"segment_{seg_id:04d}.wav"
        output_path = str(voice_dir_path / output_filename)

        try:
            result_path = synthesize(
                text=text_vi,
                output_path=output_path,
                voice_id=voice_id,
                rate=get_rate(speaker),
                pitch=get_pitch(speaker),
                volume=get_volume(speaker),
                engine=engine,
            )
            results.append({
                "segment_id": seg_id,
                "voice_path": result_path,
                "success": True,
                "error_message": None,
            })
            logger.debug(f"TTS segment {seg_id}: OK")
        except TTSVoiceNotFoundError as e:
            results.append({
                "segment_id": seg_id,
                "voice_path": None,
                "success": False,
                "error_message": f"Voice không hợp lệ: {e}",
            })
        except TTSError as e:
            results.append({
                "segment_id": seg_id,
                "voice_path": None,
                "success": False,
                "error_message": str(e),
            })

        if progress_callback:
            progress_callback(i + 1, total)

    return results


# ---------------------------------------------------------------------------
# List available voices
# ---------------------------------------------------------------------------


def list_voices(
    engine: str = "edge-tts",
    language: str = "vi",
) -> list[dict]:
    """Lấy danh sách giọng đọc có sẵn.

    Args:
        engine: TTS engine.
        language: Mã ngôn ngữ để lọc (ví dụ: 'vi').

    Returns:
        List dict: {voice_id, display_name, gender, locale}.
    """
    if engine == "edge-tts":
        return _list_edge_tts_voices(language)
    return []


def _list_edge_tts_voices(language: str) -> list[dict]:
    """Lấy danh sách giọng edge-tts theo ngôn ngữ."""
    try:
        import edge_tts  # type: ignore

        async def _get_voices():
            return await edge_tts.list_voices()

        voices = asyncio.run(_get_voices())
        return [
            {
                "voice_id": v["Name"],
                "display_name": v.get("FriendlyName", v["Name"]),
                "gender": v.get("Gender", "Unknown"),
                "locale": v.get("Locale", ""),
            }
            for v in voices
            if v.get("Locale", "").startswith(language)
        ]
    except ImportError:
        # edge-tts chưa cài — trả về danh sách built-in
        return [
            {
                "voice_id": vid,
                "display_name": name,
                "gender": gender,
                "locale": "vi-VN",
            }
            for vid, name, gender in EDGE_TTS_VI_VOICES
        ]
    except Exception as e:
        logger.warning(f"Không lấy được danh sách voice từ edge-tts: {e}")
        return [
            {
                "voice_id": vid,
                "display_name": name,
                "gender": gender,
                "locale": "vi-VN",
            }
            for vid, name, gender in EDGE_TTS_VI_VOICES
        ]


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------


def format_rate(rate_pct: int) -> str:
    """Chuyển rate_pct (-50 đến +50) sang format edge-tts ('+10%').

    Args:
        rate_pct: Phần trăm thay đổi tốc độ. 0 = bình thường.

    Examples:
        >>> format_rate(10)
        '+10%'
        >>> format_rate(-20)
        '-20%'
        >>> format_rate(0)
        '+0%'
    """
    sign = "+" if rate_pct >= 0 else ""
    return f"{sign}{rate_pct}%"


def format_pitch(pitch_hz: int) -> str:
    """Chuyển pitch_hz sang format edge-tts ('+10Hz').

    Args:
        pitch_hz: Hz thay đổi (-50 đến +50). 0 = bình thường.
    """
    sign = "+" if pitch_hz >= 0 else ""
    return f"{sign}{pitch_hz}Hz"
