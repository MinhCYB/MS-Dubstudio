"""
tests/conftest.py — Fixtures dùng chung cho tất cả tests

Bao gồm:
- sample_segments: 5 segment ở các trạng thái khác nhau
- project_with_data: Project đã có segments, speakers, translations
- mock_api_key: fake API key cho test
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from msdubstudio.core.models import (
    ProjectSettings,
    Segment,
    SegmentStatus,
    Speaker,
    StepStatus,
    VideoMetadata,
)
from msdubstudio.core.project import Project


# ---------------------------------------------------------------------------
# API Key
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_api_key() -> str:
    """Fake API key cho test — không bao giờ gọi API thật."""
    return "AIzaFakeKeyForTestingOnly1234567890abcdef"


# ---------------------------------------------------------------------------
# Sample segments
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_segments_pending() -> list[Segment]:
    """5 segment tất cả đều PENDING — chưa dịch."""
    return [
        Segment(
            id=i,
            start=float(i - 1) * 3.0,
            end=float(i - 1) * 3.0 + 2.5,
            speaker="A" if i % 2 == 1 else "B",
            text_zh=f"这是第{i}句话",
            confidence=0.9 - i * 0.05,
        )
        for i in range(1, 6)
    ]


@pytest.fixture
def sample_segments_mixed() -> list[Segment]:
    """5 segment ở nhiều trạng thái khác nhau."""
    return [
        Segment(
            id=1, start=0.0, end=2.5, speaker="A",
            text_zh="今天天气真好", text_vi="Hôm nay thời tiết thật tốt",
            confidence=0.95, status=SegmentStatus.TRANSLATED,
        ),
        Segment(
            id=2, start=2.5, end=5.0, speaker="B",
            text_zh="你好世界", text_vi="Xin chào thế giới",
            confidence=0.88, status=SegmentStatus.REVIEWED,
        ),
        Segment(
            id=3, start=5.0, end=7.5, speaker="A",
            text_zh="可以吗", text_vi=None,
            confidence=0.42, status=SegmentStatus.PENDING,
        ),
        Segment(
            id=4, start=7.5, end=10.0, speaker="B",
            text_zh="当然可以", text_vi=None,
            confidence=0.72, status=SegmentStatus.ERROR,
            error_message="HTTP 429 Rate Limit",
        ),
        Segment(
            id=5, start=10.0, end=13.0, speaker="A",
            text_zh="谢谢你", text_vi=None,
            confidence=0.81, status=SegmentStatus.PENDING,
        ),
    ]


# ---------------------------------------------------------------------------
# Project fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def projects_base_dir(tmp_path: Path) -> Path:
    base = tmp_path / "MS DubStudio Projects"
    base.mkdir()
    return base


@pytest.fixture
def blank_project(projects_base_dir: Path) -> Project:
    """Project mới không có segments."""
    return Project.new(
        name="Blank Test Project",
        video_path="/fake/video.mp4",
        projects_base_dir=str(projects_base_dir),
    )


@pytest.fixture
def project_with_data(
    projects_base_dir: Path,
    sample_segments_mixed: list[Segment],
) -> Project:
    """Project đầy đủ: segments, speakers, video metadata."""
    settings = ProjectSettings(batch_size=5)
    project = Project.new(
        name="Full Test Project",
        video_path="/fake/video.mp4",
        projects_base_dir=str(projects_base_dir),
        settings=settings,
    )

    # Thêm segments
    raw_segs = [
        {
            "id": s.id,
            "start": s.start,
            "end": s.end,
            "text": s.text_zh,
            "speaker": s.speaker,
            "confidence": s.confidence,
        }
        for s in sample_segments_mixed
    ]
    project.update_segments_from_stt(raw_segs)

    # Update translations cho các segment đã dịch
    for seg in sample_segments_mixed:
        if seg.text_vi is not None:
            project.update_segment_translation(seg.id, seg.text_vi, seg.status)
        if seg.status == SegmentStatus.ERROR:
            project.mark_segment_error(seg.id, seg.error_message or "Unknown error")

    # Thêm speakers
    project.update_speaker(Speaker(id="A", gender="male", voice_id="vi-VN-NamMinhNeural"))
    project.update_speaker(Speaker(id="B", gender="female", voice_id="vi-VN-HoaiMyNeural"))

    # Video metadata
    project.update_video_metadata(VideoMetadata(
        filename="video.mp4",
        duration=13.0,
        width=1920,
        height=1080,
        fps=30.0,
        video_codec="h264",
        audio_codec="aac",
        detected_language="zh",
        detected_language_confidence=0.98,
    ))

    project.save()
    return project


# ---------------------------------------------------------------------------
# Sample project JSON (cho test load từ file)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_project_json_path(tmp_path: Path) -> Path:
    """Path tới sample project.json để test load."""
    import json
    from datetime import datetime, timezone

    project_dir = tmp_path / "sample_project"
    project_dir.mkdir()

    project_data = {
        "project_id": "sample-uuid-5678",
        "project_name": "Sample Project",
        "video_path": str(project_dir / "source" / "video.mp4"),
        "project_dir": str(project_dir),
        "created_at": "2024-01-01T00:00:00+00:00",
        "updated_at": "2024-01-02T12:00:00+00:00",
        "settings": {
            "source_lang": "zh",
            "target_lang": "vi",
            "whisper_model": "large-v3",
            "batch_size": 15,
            "translate_temperature": 0.3,
            "use_context_frame": True,
            "tts_engine": "edge-tts",
        },
        "pipeline_status": {
            "import": "completed",
            "stt": "completed",
            "translate": "completed",
            "review": "waiting",
            "voice": "waiting",
            "export": "waiting",
        },
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 2.5,
                "speaker": "A",
                "text_zh": "今天天气真好",
                "text_vi": "Hôm nay thời tiết thật tốt",
                "confidence": 0.95,
                "status": "translated",
                "scene_frame": None,
                "error_message": None,
                "voice_path": None,
                "text_vi_hash": None,
                "notes": None,
                "updated_at": None,
            }
        ],
        "speakers": {
            "A": {"id": "A", "gender": "male", "voice_id": "vi-VN-NamMinhNeural", "emotion": "neutral"}
        },
        "video_metadata": {
            "filename": "video.mp4",
            "duration": 120.0,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "video_codec": "h264",
            "audio_codec": "aac",
            "audio_channels": 2,
            "audio_sample_rate": 44100,
            "file_size_bytes": 50000000,
            "detected_language": "zh",
            "detected_language_confidence": 0.98,
        }
    }

    (project_dir / "project.json").write_text(
        json.dumps(project_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return project_dir
