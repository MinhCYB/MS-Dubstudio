"""
core/media_io.py — ffmpeg/ffprobe wrapper cho MS DubStudio

Chịu trách nhiệm:
- Lấy metadata video (duration, resolution, fps, codec...)
- Tách audio từ video → WAV 16kHz mono (tối ưu cho Whisper)
- Auto-detect ngôn ngữ (dùng Whisper detect_language, không phải ffmpeg)

Không import PyQt6. Lỗi nghiêm trọng (ffmpeg không tìm thấy, file hỏng)
sẽ raise FatalError — UI layer bắt và hiển thị thông báo.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from msdubstudio.core.models import VideoMetadata

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MediaIOError(Exception):
    """Lỗi liên quan đến xử lý media (ffmpeg/ffprobe)."""


class FFmpegNotFoundError(MediaIOError):
    """ffmpeg/ffprobe không tìm thấy trong PATH hoặc đường dẫn đã cấu hình."""


class VideoFileError(MediaIOError):
    """File video không tồn tại hoặc không đọc được."""


class AudioExtractionError(MediaIOError):
    """Lỗi khi tách audio từ video."""


# ---------------------------------------------------------------------------
# ffmpeg/ffprobe discovery
# ---------------------------------------------------------------------------


def _get_ffmpeg_path(ffmpeg_bin: Optional[str] = None) -> str:
    """Tìm đường dẫn tới ffmpeg executable.

    Ưu tiên theo thứ tự:
    1. ffmpeg_bin được truyền vào
    2. Biến môi trường FFMPEG_PATH
    3. 'ffmpeg' trong PATH hệ thống
    """
    if ffmpeg_bin:
        return ffmpeg_bin
    env_path = os.environ.get("FFMPEG_PATH")
    if env_path:
        return env_path
    return "ffmpeg"


def _get_ffprobe_path(ffprobe_bin: Optional[str] = None) -> str:
    if ffprobe_bin:
        return ffprobe_bin
    env_path = os.environ.get("FFPROBE_PATH")
    if env_path:
        return env_path
    return "ffprobe"


def check_ffmpeg_available(ffmpeg_bin: Optional[str] = None) -> bool:
    """Kiểm tra ffmpeg có tồn tại và chạy được không.

    Returns:
        True nếu ffmpeg hoạt động, False nếu không tìm thấy.
    """
    try:
        result = subprocess.run(
            [_get_ffmpeg_path(ffmpeg_bin), "-version"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


# ---------------------------------------------------------------------------
# Video metadata
# ---------------------------------------------------------------------------


def get_video_metadata(
    video_path: str,
    ffprobe_bin: Optional[str] = None,
) -> VideoMetadata:
    """Lấy metadata của video bằng ffprobe.

    Args:
        video_path: Đường dẫn tuyệt đối tới video.
        ffprobe_bin: Đường dẫn tới ffprobe (None = tìm trong PATH).

    Returns:
        VideoMetadata object.

    Raises:
        VideoFileError: File không tồn tại.
        FFmpegNotFoundError: ffprobe không tìm thấy.
        MediaIOError: ffprobe chạy thất bại.
    """
    video_path_obj = Path(video_path)
    if not video_path_obj.exists():
        raise VideoFileError(f"File video không tồn tại: {video_path}")

    ffprobe = _get_ffprobe_path(ffprobe_bin)

    cmd = [
        ffprobe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(video_path_obj),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        raise FFmpegNotFoundError(
            f"ffprobe không tìm thấy. Cài ffmpeg vào PATH hoặc cấu hình FFPROBE_PATH. "
            f"Đã tìm: {ffprobe}"
        )
    except subprocess.TimeoutExpired:
        raise MediaIOError("ffprobe timeout sau 30 giây")

    if result.returncode != 0:
        raise MediaIOError(
            f"ffprobe thất bại (code {result.returncode}): {result.stderr[:500]}"
        )

    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise MediaIOError(f"Không parse được output ffprobe: {e}") from e

    return _parse_ffprobe_output(video_path_obj.name, info)


def _parse_ffprobe_output(filename: str, info: dict) -> VideoMetadata:
    """Parse dict từ ffprobe JSON thành VideoMetadata."""
    streams = info.get("streams", [])
    fmt = info.get("format", {})

    # Lấy thông tin từng stream
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

    # Duration: ưu tiên format-level, fallback sang stream-level
    duration_str = fmt.get("duration") or video_stream.get("duration", "0")
    try:
        duration = float(duration_str)
    except (ValueError, TypeError):
        duration = 0.0

    # FPS từ avg_frame_rate (ví dụ "30/1" hoặc "29.97")
    fps = _parse_fps(video_stream.get("avg_frame_rate", "0/1"))

    # File size
    try:
        file_size = int(fmt.get("size", 0))
    except (ValueError, TypeError):
        file_size = 0

    return VideoMetadata(
        filename=filename,
        duration=duration,
        width=int(video_stream.get("width", 0)),
        height=int(video_stream.get("height", 0)),
        fps=fps,
        video_codec=video_stream.get("codec_name", ""),
        audio_codec=audio_stream.get("codec_name", ""),
        audio_channels=int(audio_stream.get("channels", 2)),
        audio_sample_rate=int(audio_stream.get("sample_rate", 44100)),
        file_size_bytes=file_size,
    )


def _parse_fps(fps_str: str) -> float:
    """Parse fps string như '30/1' hoặc '29.97' → float."""
    if "/" in fps_str:
        parts = fps_str.split("/")
        try:
            num, den = float(parts[0]), float(parts[1])
            return num / den if den != 0 else 0.0
        except (ValueError, IndexError):
            return 0.0
    try:
        return float(fps_str)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# Audio extraction
# ---------------------------------------------------------------------------


def extract_audio(
    video_path: str,
    output_path: str,
    sample_rate: int = 16000,
    channels: int = 1,
    ffmpeg_bin: Optional[str] = None,
    progress_callback: Optional[callable] = None,
) -> str:
    """Tách audio từ video và lưu thành WAV.

    Mặc định xuất 16kHz mono — định dạng tối ưu cho Whisper STT.

    Args:
        video_path: Đường dẫn tới video nguồn.
        output_path: Đường dẫn lưu file WAV đầu ra.
        sample_rate: Sample rate (Hz). Mặc định 16000 cho Whisper.
        channels: Số kênh audio. 1 = mono, 2 = stereo.
        ffmpeg_bin: Đường dẫn ffmpeg (None = tìm trong PATH).
        progress_callback: Callable(seconds_processed: float) để report tiến độ.

    Returns:
        Đường dẫn tuyệt đối của file WAV đã tạo.

    Raises:
        VideoFileError: File video không tồn tại.
        FFmpegNotFoundError: ffmpeg không tìm thấy.
        AudioExtractionError: ffmpeg chạy thất bại.
    """
    if not Path(video_path).exists():
        raise VideoFileError(f"File video không tồn tại: {video_path}")

    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = _get_ffmpeg_path(ffmpeg_bin)

    cmd = [
        ffmpeg,
        "-y",                        # overwrite output
        "-i", str(video_path),
        "-vn",                        # không lấy video stream
        "-acodec", "pcm_s16le",      # PCM 16-bit little-endian
        "-ar", str(sample_rate),
        "-ac", str(channels),
        str(output_path_obj),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 phút tối đa cho video dài
        )
    except FileNotFoundError:
        raise FFmpegNotFoundError(
            f"ffmpeg không tìm thấy. Cài ffmpeg vào PATH hoặc cấu hình FFMPEG_PATH. "
            f"Đã tìm: {ffmpeg}"
        )
    except subprocess.TimeoutExpired:
        raise AudioExtractionError("ffmpeg timeout (>10 phút) khi tách audio")

    if result.returncode != 0:
        raise AudioExtractionError(
            f"ffmpeg thất bại (code {result.returncode}): {result.stderr[-500:]}"
        )

    if not output_path_obj.exists():
        raise AudioExtractionError(
            f"ffmpeg chạy thành công nhưng file output không tồn tại: {output_path}"
        )

    logger.info(f"Đã tách audio: {video_path} → {output_path}")
    return str(output_path_obj.resolve())


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------


def format_duration(seconds: float) -> str:
    """Chuyển số giây sang định dạng HH:MM:SS.ss.

    Examples:
        >>> format_duration(3661.5)
        '01:01:01.50'
        >>> format_duration(90.0)
        '00:01:30.00'
    """
    total_seconds = int(seconds)
    centiseconds = int((seconds - total_seconds) * 100)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def format_file_size(bytes: int) -> str:
    """Chuyển bytes sang string dễ đọc (KB, MB, GB).

    Examples:
        >>> format_file_size(1500)
        '1.46 KB'
        >>> format_file_size(2_000_000)
        '1.91 MB'
    """
    if bytes < 1024:
        return f"{bytes} B"
    elif bytes < 1024 ** 2:
        return f"{bytes / 1024:.2f} KB"
    elif bytes < 1024 ** 3:
        return f"{bytes / 1024 ** 2:.2f} MB"
    else:
        return f"{bytes / 1024 ** 3:.2f} GB"
