"""
core/sync.py — Time-stretch TTS audio để khớp timing gốc của video

Chịu trách nhiệm:
- Tính toán tỉ lệ stretch cần thiết (tts_duration / original_duration)
- Áp dụng time-stretch lên file audio TTS đã sinh (không thay đổi pitch)
- Cắt bớt nếu TTS quá dài và không thể nén nữa
- Trả về đường dẫn file audio đã xử lý

Hỗ trợ 2 backend:
1. ffmpeg atempo filter (0.5×–2×, sẵn có nếu đã cài ffmpeg)
2. rubberband (chất lượng cao, cần cài thêm: pip install pyrubberband soundfile)

Không import PyQt6.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SyncError(Exception):
    """Lỗi khi time-stretch audio."""


class SyncBackendNotFoundError(SyncError):
    """Backend time-stretch không tìm thấy (ffmpeg / rubberband)."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Giới hạn stretch ratio để tránh âm thanh quá méo
MIN_STRETCH_RATIO = 0.5  # Nén tối đa 2× (nghe nhanh gấp đôi)
MAX_STRETCH_RATIO = 2.0  # Giãn tối đa 2× (nghe chậm gấp đôi)

# Ratio nào coi là "đủ gần" → không cần stretch (tiết kiệm CPU)
SKIP_THRESHOLD = 0.05  # 5% deviation — nếu nằm trong khoảng này thì bỏ qua


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------


def compute_stretch_ratio(
    tts_duration_s: float,
    original_duration_s: float,
) -> float:
    """Tính tỉ lệ stretch để TTS khớp với thời lượng gốc.

    Args:
        tts_duration_s: Thời lượng file audio TTS (giây).
        original_duration_s: Thời lượng segment gốc trong video (giây).

    Returns:
        Stretch ratio > 0. Ví dụ:
        - 1.0 = không cần stretch
        - 0.8 = cần đọc nhanh hơn 20% (compress)
        - 1.5 = cần đọc chậm hơn 50% (stretch)
    """
    if tts_duration_s <= 0 or original_duration_s <= 0:
        return 1.0
    return tts_duration_s / original_duration_s


def stretch_audio(
    input_path: str,
    output_path: str,
    stretch_ratio: float,
    ffmpeg_bin: Optional[str] = None,
    backend: str = "auto",
) -> str:
    """Time-stretch file audio theo tỉ lệ cho trước.

    Args:
        input_path: Đường dẫn file audio TTS đầu vào.
        output_path: Đường dẫn file audio đầu ra đã time-stretch.
        stretch_ratio: Tỉ lệ stretch (tts_duration / target_duration).
                       > 1.0 → nén (audio quá dài → đọc nhanh hơn)
                       < 1.0 → giãn (audio quá ngắn → đọc chậm hơn)
        ffmpeg_bin: Đường dẫn ffmpeg binary. None = tìm trong PATH.
        backend: "auto", "ffmpeg", hoặc "rubberband".

    Returns:
        Đường dẫn tuyệt đối của file output.

    Raises:
        SyncBackendNotFoundError: Không tìm thấy backend.
        SyncError: Lỗi khi xử lý.
    """
    if not Path(input_path).exists():
        raise SyncError(f"File audio không tồn tại: {input_path}")

    # Clamp ratio về phạm vi hợp lý
    clamped_ratio = max(MIN_STRETCH_RATIO, min(MAX_STRETCH_RATIO, stretch_ratio))
    if clamped_ratio != stretch_ratio:
        logger.warning(
            f"Stretch ratio {stretch_ratio:.2f} bị clamp về {clamped_ratio:.2f}"
        )

    # Nếu ratio gần 1.0 → copy thẳng, không cần stretch
    if abs(clamped_ratio - 1.0) < SKIP_THRESHOLD:
        import shutil
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_path, output_path)
        logger.debug(f"Sync: ratio {clamped_ratio:.3f} ≈ 1.0, copy thẳng")
        return str(Path(output_path).resolve())

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    if backend == "rubberband":
        return _stretch_with_rubberband(input_path, output_path, clamped_ratio)
    elif backend == "ffmpeg":
        return _stretch_with_ffmpeg(input_path, output_path, clamped_ratio, ffmpeg_bin)
    else:  # auto
        try:
            return _stretch_with_rubberband(input_path, output_path, clamped_ratio)
        except (SyncBackendNotFoundError, ImportError):
            logger.info("rubberband không có, fallback sang ffmpeg atempo")
            return _stretch_with_ffmpeg(input_path, output_path, clamped_ratio, ffmpeg_bin)


def stretch_audio_to_duration(
    input_path: str,
    output_path: str,
    target_duration_s: float,
    ffmpeg_bin: Optional[str] = None,
    backend: str = "auto",
) -> str:
    """Time-stretch audio để đạt đúng target_duration (convenience wrapper).

    Args:
        input_path: File audio TTS đầu vào.
        output_path: File audio đầu ra.
        target_duration_s: Thời lượng đích tính bằng giây.
        ffmpeg_bin: Đường dẫn ffmpeg.
        backend: Backend time-stretch.

    Returns:
        Đường dẫn tuyệt đối của file output.
    """
    tts_duration = get_audio_duration(input_path, ffmpeg_bin)
    ratio = compute_stretch_ratio(tts_duration, target_duration_s)
    return stretch_audio(input_path, output_path, ratio, ffmpeg_bin, backend)


# ---------------------------------------------------------------------------
# Audio duration helper
# ---------------------------------------------------------------------------


def get_audio_duration(
    audio_path: str,
    ffmpeg_bin: Optional[str] = None,
) -> float:
    """Lấy thời lượng file audio bằng ffprobe.

    Args:
        audio_path: Đường dẫn file audio.
        ffmpeg_bin: Đường dẫn ffmpeg binary (để suy ra ffprobe).

    Returns:
        Thời lượng tính bằng giây.

    Raises:
        SyncError: Không lấy được duration.
    """
    ffprobe = _get_ffprobe(ffmpeg_bin)

    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        raise SyncBackendNotFoundError(
            f"ffprobe không tìm thấy: {ffprobe}. Cài ffmpeg vào PATH."
        )
    except subprocess.TimeoutExpired:
        raise SyncError("ffprobe timeout khi lấy duration")

    if result.returncode != 0 or not result.stdout.strip():
        raise SyncError(
            f"Không lấy được duration của {audio_path}: {result.stderr}"
        )

    try:
        return float(result.stdout.strip())
    except ValueError as e:
        raise SyncError(f"Duration không hợp lệ: {result.stdout!r}") from e


# ---------------------------------------------------------------------------
# Internal backends
# ---------------------------------------------------------------------------


def _stretch_with_ffmpeg(
    input_path: str,
    output_path: str,
    stretch_ratio: float,
    ffmpeg_bin: Optional[str] = None,
) -> str:
    """Time-stretch dùng ffmpeg atempo filter.

    Giới hạn của atempo: phải trong khoảng [0.5, 2.0].
    Nếu ratio ngoài khoảng → cascade nhiều atempo filter.

    stretch_ratio > 1.0 → cần nén (đọc nhanh hơn) → atempo = 1/ratio ?? Không!
    Lưu ý: atempo trong ffmpeg làm thay đổi tốc độ phát lại.
    - atempo=2.0 → phát nhanh gấp đôi (duration giảm 50%)
    - atempo=0.5 → phát chậm gấp đôi (duration tăng gấp đôi)

    Nếu stretch_ratio > 1.0: audio TTS dài hơn target → cần đọc nhanh hơn:
        atempo = stretch_ratio (nếu ≤ 2.0)
    Nếu stretch_ratio < 1.0: audio TTS ngắn hơn target → cần đọc chậm hơn:
        atempo = stretch_ratio (nếu ≥ 0.5)
    """
    ffmpeg = _get_ffmpeg(ffmpeg_bin)

    # Xây dựng atempo filter chain (chỉ cascade khi cần vì atempo giới hạn 0.5-2.0)
    atempo_value = stretch_ratio  # ffmpeg atempo > 1.0 → nhanh hơn (ngắn hơn)

    # Cascade nếu cần
    filter_parts = _build_atempo_filter(atempo_value)

    cmd = [
        ffmpeg, "-y",
        "-i", input_path,
        "-filter:a", filter_parts,
        "-ar", "44100",
        "-ac", "2",
        output_path,
    ]

    logger.debug(f"ffmpeg atempo: ratio={stretch_ratio:.3f}, filter='{filter_parts}'")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        raise SyncBackendNotFoundError(
            f"ffmpeg không tìm thấy: {ffmpeg}. Cài ffmpeg vào PATH."
        )
    except subprocess.TimeoutExpired:
        raise SyncError("ffmpeg timeout khi time-stretch audio")

    if result.returncode != 0:
        raise SyncError(
            f"ffmpeg atempo thất bại: {result.stderr[-500:]}"
        )

    return str(Path(output_path).resolve())


def _build_atempo_filter(ratio: float) -> str:
    """Xây dựng atempo filter chain cho ffmpeg.

    atempo chỉ hỗ trợ [0.5, 2.0]. Nếu ratio ngoài khoảng, cascade:
    - ratio = 4.0 → atempo=2.0,atempo=2.0
    - ratio = 0.25 → atempo=0.5,atempo=0.5
    """
    filters = []
    remaining = ratio

    # Cascade các atempo filter
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0

    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5

    filters.append(f"atempo={remaining:.4f}")
    return ",".join(filters)


def _stretch_with_rubberband(
    input_path: str,
    output_path: str,
    stretch_ratio: float,
) -> str:
    """Time-stretch dùng pyrubberband (chất lượng cao hơn ffmpeg atempo).

    pyrubberband dùng Rubber Band Library — time-stretch + pitch-correct.
    Cài đặt: pip install pyrubberband soundfile

    stretch_ratio > 1.0 → audio TTS quá dài → cần nén → time_ratio = 1/stretch_ratio
    (trong rubberband: time_ratio < 1.0 → ngắn hơn)
    """
    try:
        import numpy as np  # type: ignore
        import pyrubberband as pyrb  # type: ignore
        import soundfile as sf  # type: ignore
    except ImportError as e:
        raise SyncBackendNotFoundError(
            f"pyrubberband/soundfile chưa cài: {e}. "
            "Chạy: pip install pyrubberband soundfile"
        ) from e

    try:
        # Đọc audio
        audio_data, sample_rate = sf.read(input_path)

        # rubberband time_ratio: < 1 → nhanh hơn, > 1 → chậm hơn
        # stretch_ratio = tts_duration / target
        # > 1 → tts quá dài → cần nhanh hơn → time_ratio = 1/stretch_ratio < 1
        time_ratio = 1.0 / stretch_ratio

        stretched = pyrb.time_stretch(audio_data, sample_rate, time_ratio)

        # Ghi output
        sf.write(output_path, stretched, sample_rate)
        logger.debug(
            f"rubberband: stretch_ratio={stretch_ratio:.3f}, "
            f"time_ratio={time_ratio:.3f}"
        )
        return str(Path(output_path).resolve())

    except Exception as e:
        raise SyncError(f"pyrubberband time-stretch thất bại: {e}") from e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_ffmpeg(ffmpeg_bin: Optional[str] = None) -> str:
    if ffmpeg_bin:
        return ffmpeg_bin
    return os.environ.get("FFMPEG_PATH", "ffmpeg")


def _get_ffprobe(ffmpeg_bin: Optional[str] = None) -> str:
    """Suy ra ffprobe từ ffmpeg_bin."""
    if ffmpeg_bin:
        ffmpeg_path = Path(ffmpeg_bin)
        # ffmpeg → ffprobe trong cùng thư mục
        ffprobe_path = ffmpeg_path.parent / ffmpeg_path.name.replace("ffmpeg", "ffprobe")
        if ffprobe_path.exists():
            return str(ffprobe_path)
    return os.environ.get("FFPROBE_PATH", "ffprobe")


# ---------------------------------------------------------------------------
# Convenience: check if stretch is needed at all
# ---------------------------------------------------------------------------


def needs_stretch(
    tts_duration_s: float,
    original_duration_s: float,
    tolerance: float = SKIP_THRESHOLD,
) -> bool:
    """Kiểm tra xem có cần time-stretch không.

    Args:
        tts_duration_s: Thời lượng TTS audio.
        original_duration_s: Thời lượng segment gốc.
        tolerance: Ngưỡng sai số cho phép (mặc định 5%).

    Returns:
        True nếu cần stretch.
    """
    if original_duration_s <= 0:
        return False
    ratio = compute_stretch_ratio(tts_duration_s, original_duration_s)
    return abs(ratio - 1.0) >= tolerance
