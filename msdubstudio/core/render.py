"""
core/render.py — FFmpeg video rendering cho MS DubStudio

Chịu trách nhiệm:
- Ghép audio TTS đã sinh thành 1 audio track liên tục
- Mix với nhạc nền (nếu giữ lại)
- Ghép lại với video gốc → file video cuối cùng

Pipeline render:
1. Tạo "silent timeline" = file audio im lặng cùng thời lượng video
2. Overlay từng segment TTS đúng vị trí start time
3. Mix với nhạc nền gốc (giảm volume) nếu keep_bgm=True
4. Ghép audio track mới vào video gốc
5. Xuất file video cuối

Không import PyQt6.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class RenderError(Exception):
    """Lỗi khi render video."""


class FFmpegRenderError(RenderError):
    """ffmpeg thất bại khi render."""


# ---------------------------------------------------------------------------
# Export settings
# ---------------------------------------------------------------------------


class ExportSettings:
    """Cài đặt xuất video cuối."""

    def __init__(
        self,
        output_path: str,
        video_codec: str = "libx264",
        audio_codec: str = "aac",
        video_bitrate: str = "4000k",
        audio_bitrate: str = "192k",
        crf: int = 18,
        resolution: Optional[str] = None,  # None = giữ nguyên, '1920x1080', '1280x720'
        fps: Optional[float] = None,       # None = giữ nguyên
        keep_bgm: bool = True,
        bgm_volume: float = 0.3,           # 0.0 – 1.0, volume nhạc nền gốc
        dub_volume: float = 1.0,           # Volume giọng đọc mới
        normalize_audio: bool = True,
        burn_subtitles: bool = False,
        subtitle_path: Optional[str] = None,
    ):
        self.output_path = output_path
        self.video_codec = video_codec
        self.audio_codec = audio_codec
        self.video_bitrate = video_bitrate
        self.audio_bitrate = audio_bitrate
        self.crf = crf
        self.resolution = resolution
        self.fps = fps
        self.keep_bgm = keep_bgm
        self.bgm_volume = bgm_volume
        self.dub_volume = dub_volume
        self.normalize_audio = normalize_audio
        self.burn_subtitles = burn_subtitles
        self.subtitle_path = subtitle_path


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------


def render_video(
    video_path: str,
    segments: list[dict],
    voice_dir: str,
    export_settings: ExportSettings,
    ffmpeg_bin: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> str:
    """Render video đã lồng tiếng.

    Args:
        video_path: Video gốc.
        segments: List dict {id, start, end, voice_path}. Chỉ segment
                  có voice_path mới được ghép vào output.
        voice_dir: Thư mục chứa file audio TTS.
        export_settings: Cài đặt xuất.
        ffmpeg_bin: Đường dẫn ffmpeg (None = tìm trong PATH).
        progress_callback: Callable(current_frame, total_frames).
        cancel_check: Callable → True nếu Cancel.

    Returns:
        Đường dẫn tuyệt đối của video đã render.

    Raises:
        RenderError: Lỗi chung khi render.
        FFmpegRenderError: ffmpeg thất bại.
    """
    ffmpeg = _get_ffmpeg(ffmpeg_bin)
    output_path = Path(export_settings.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Lọc segment có voice_path hợp lệ
    voiced_segments = [
        s for s in segments
        if s.get("voice_path") and Path(s["voice_path"]).exists()
    ]

    if not voiced_segments:
        raise RenderError(
            "Không có segment nào có audio TTS — hãy chạy bước Voice trước."
        )

    logger.info(
        f"Render: {len(voiced_segments)}/{len(segments)} segment có audio"
    )

    with tempfile.TemporaryDirectory(prefix="msdubstudio_render_") as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Bước 1: Tạo timeline audio im lặng
        if cancel_check and cancel_check():
            raise RenderError("Render bị hủy")

        logger.info("Bước 1/4: Tạo silent audio timeline...")
        silent_audio = str(tmp_path / "silent.wav")
        _create_silent_audio(video_path, silent_audio, ffmpeg)

        # Bước 2: Overlay TTS segments lên timeline
        if cancel_check and cancel_check():
            raise RenderError("Render bị hủy")

        logger.info("Bước 2/4: Overlay TTS segments...")
        dubbed_audio = str(tmp_path / "dubbed.wav")
        _overlay_segments(
            silent_audio, voiced_segments, dubbed_audio, ffmpeg
        )

        # Bước 3: Mix với nhạc nền (nếu cần)
        if cancel_check and cancel_check():
            raise RenderError("Render bị hủy")

        if export_settings.keep_bgm:
            logger.info("Bước 3/4: Mix với nhạc nền gốc...")
            mixed_audio = str(tmp_path / "mixed.wav")
            original_audio = str(tmp_path / "original_audio.wav")
            _extract_original_audio(video_path, original_audio, ffmpeg)
            _mix_audio(
                dubbed_audio,
                original_audio,
                mixed_audio,
                dub_volume=export_settings.dub_volume,
                bgm_volume=export_settings.bgm_volume,
                ffmpeg=ffmpeg,
            )
            final_audio = mixed_audio
        else:
            final_audio = dubbed_audio

        # Bước 4: Ghép video + audio → output
        if cancel_check and cancel_check():
            raise RenderError("Render bị hủy")

        logger.info("Bước 4/4: Ghép video + audio...")
        _mux_video_audio(
            video_path=video_path,
            audio_path=final_audio,
            output_path=str(output_path),
            export_settings=export_settings,
            ffmpeg=ffmpeg,
        )

    logger.info(f"Render hoàn thành: {output_path}")
    return str(output_path.resolve())


# ---------------------------------------------------------------------------
# Internal ffmpeg helpers
# ---------------------------------------------------------------------------


def _get_ffmpeg(ffmpeg_bin: Optional[str] = None) -> str:
    if ffmpeg_bin:
        return ffmpeg_bin
    return os.environ.get("FFMPEG_PATH", "ffmpeg")


def _run_ffmpeg(cmd: list[str], timeout: int = 3600) -> None:
    """Chạy lệnh ffmpeg, raise FFmpegRenderError nếu thất bại."""
    logger.debug(f"ffmpeg: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise FFmpegRenderError(
            f"ffmpeg không tìm thấy: {cmd[0]}. "
            "Cài ffmpeg vào PATH hoặc cấu hình FFMPEG_PATH."
        )
    except subprocess.TimeoutExpired:
        raise FFmpegRenderError(f"ffmpeg timeout sau {timeout}s")

    if result.returncode != 0:
        raise FFmpegRenderError(
            f"ffmpeg thất bại (code {result.returncode}): {result.stderr[-500:]}"
        )


def _create_silent_audio(
    video_path: str,
    output_path: str,
    ffmpeg: str,
) -> None:
    """Tạo file audio im lặng cùng thời lượng với video."""
    cmd = [
        ffmpeg, "-y",
        "-i", video_path,
        "-vn",
        "-af", "volume=0",
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        output_path,
    ]
    _run_ffmpeg(cmd)


def _extract_original_audio(
    video_path: str,
    output_path: str,
    ffmpeg: str,
) -> None:
    """Tách audio gốc từ video."""
    cmd = [
        ffmpeg, "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        output_path,
    ]
    _run_ffmpeg(cmd)


def _overlay_segments(
    base_audio: str,
    segments: list[dict],
    output_path: str,
    ffmpeg: str,
) -> None:
    """Overlay từng segment TTS lên base audio timeline.

    Dùng ffmpeg amix với adelay để đặt mỗi segment đúng vị trí thời gian.
    """
    if not segments:
        import shutil
        shutil.copy2(base_audio, output_path)
        return

    # Xây dựng filter_complex: mix base + từng segment với delay
    inputs = ["-i", base_audio]
    filter_parts = []
    stream_labels = ["[0:a]"]  # base audio là stream 0

    for i, seg in enumerate(segments):
        delay_ms = int(seg["start"] * 1000)
        inputs += ["-i", seg["voice_path"]]
        stream_idx = i + 1
        label = f"[delayed_{i}]"
        filter_parts.append(
            f"[{stream_idx}:a]adelay={delay_ms}|{delay_ms}{label}"
        )
        stream_labels.append(label)

    # Mix tất cả streams
    mix_input = "".join(stream_labels)
    n_streams = len(stream_labels)
    filter_parts.append(
        f"{mix_input}amix=inputs={n_streams}:normalize=0[out]"
    )

    filter_complex = ";".join(filter_parts)

    cmd = [
        ffmpeg, "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        output_path,
    ]
    _run_ffmpeg(cmd)


def _mix_audio(
    dub_audio: str,
    original_audio: str,
    output_path: str,
    dub_volume: float,
    bgm_volume: float,
    ffmpeg: str,
) -> None:
    """Mix giọng đọc mới với nhạc nền gốc."""
    filter_complex = (
        f"[0:a]volume={dub_volume}[dub];"
        f"[1:a]volume={bgm_volume}[bgm];"
        f"[dub][bgm]amix=inputs=2:normalize=0[out]"
    )
    cmd = [
        ffmpeg, "-y",
        "-i", dub_audio,
        "-i", original_audio,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        output_path,
    ]
    _run_ffmpeg(cmd)


def _mux_video_audio(
    video_path: str,
    audio_path: str,
    output_path: str,
    export_settings: ExportSettings,
    ffmpeg: str,
) -> None:
    """Ghép video (không audio) + audio mới → file output cuối."""
    cmd = [ffmpeg, "-y"]
    cmd += ["-i", video_path]
    cmd += ["-i", audio_path]

    # Video filter
    vf_parts = []
    if export_settings.resolution:
        w, h = export_settings.resolution.split("x")
        vf_parts.append(f"scale={w}:{h}")
    if export_settings.fps:
        vf_parts.append(f"fps={export_settings.fps}")
    if vf_parts:
        cmd += ["-vf", ",".join(vf_parts)]

    # Streams
    cmd += ["-map", "0:v", "-map", "1:a"]

    # Video codec
    cmd += ["-c:v", export_settings.video_codec]
    cmd += ["-crf", str(export_settings.crf)]
    if export_settings.video_bitrate:
        cmd += ["-b:v", export_settings.video_bitrate]

    # Audio codec
    cmd += ["-c:a", export_settings.audio_codec]
    if export_settings.audio_bitrate:
        cmd += ["-b:a", export_settings.audio_bitrate]

    # Normalize audio
    if export_settings.normalize_audio:
        cmd += ["-af", "loudnorm"]

    cmd += [output_path]
    _run_ffmpeg(cmd, timeout=7200)  # 2 giờ tối đa cho video dài
