"""
tests/core/test_project.py — Unit tests for core/project.py

Kiểm tra:
- Project.new() tạo thư mục + project.json đúng
- Project.load() load thành công + roundtrip
- Project.load() raise lỗi rõ ràng khi file không tồn tại hoặc bị hỏng
- save() + load() roundtrip giữ nguyên toàn bộ data
- update_segments_from_stt() mapping đúng
- update_translated_segments() merge đúng (idempotency)
- update_segment_translation() chỉ thay đổi đúng segment
- Pipeline event methods cập nhật PipelineStatus đúng
- Callback system hoạt động (step_started, completed, error)
- _sanitize_dirname() xử lý ký tự đặc biệt
"""

from __future__ import annotations

import json
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
from msdubstudio.core.project import (
    Project,
    ProjectError,
    ProjectFileCorruptedError,
    ProjectFileNotFoundError,
    ProjectStateError,
    _sanitize_dirname,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_base_dir(tmp_path: Path) -> Path:
    """Thư mục gốc chứa tất cả projects — dùng tmp_path của pytest."""
    base = tmp_path / "MS DubStudio Projects"
    base.mkdir()
    return base


@pytest.fixture
def new_project(project_base_dir: Path) -> Project:
    """Project mới chưa có segments."""
    return Project.new(
        name="Test Project",
        video_path="/fake/video.mp4",
        projects_base_dir=str(project_base_dir),
    )


@pytest.fixture
def project_with_segments(new_project: Project) -> Project:
    """Project đã có segments từ STT."""
    raw_segments = [
        {"id": 1, "start": 0.0, "end": 2.34, "text": "今天天气真好", "speaker": "A", "confidence": 0.92},
        {"id": 2, "start": 2.50, "end": 5.10, "text": "你好世界", "speaker": "B", "confidence": 0.65},
        {"id": 3, "start": 5.20, "end": 8.00, "text": "谢谢", "speaker": "A", "confidence": 0.45},
    ]
    new_project.update_segments_from_stt(raw_segments)
    return new_project


# ---------------------------------------------------------------------------
# Tests: Project.new()
# ---------------------------------------------------------------------------


class TestProjectNew:
    def test_creates_project_dir(self, project_base_dir: Path):
        p = Project.new("My Project", "/fake/video.mp4", str(project_base_dir))
        assert (project_base_dir / "My Project").is_dir()

    def test_creates_project_json(self, project_base_dir: Path):
        p = Project.new("My Project", "/fake/video.mp4", str(project_base_dir))
        assert (Path(p.data.project_dir) / "project.json").exists()

    def test_creates_subdirectories(self, project_base_dir: Path):
        p = Project.new("My Project", "/fake/video.mp4", str(project_base_dir))
        project_dir = Path(p.data.project_dir)
        for subdir in Project.SUBDIRS:
            assert (project_dir / subdir).is_dir(), f"Thiếu thư mục: {subdir}"

    def test_project_data_populated(self, project_base_dir: Path):
        p = Project.new("My Project", "/fake/video.mp4", str(project_base_dir))
        assert p.data.project_name == "My Project"
        assert p.data.video_path == "/fake/video.mp4"
        assert p.data.project_id != ""
        assert p.data.total_segments == 0

    def test_custom_settings(self, project_base_dir: Path):
        settings = ProjectSettings(batch_size=20, whisper_model="medium")
        p = Project.new("Proj", "/fake/v.mp4", str(project_base_dir), settings=settings)
        assert p.data.settings.batch_size == 20
        assert p.data.settings.whisper_model == "medium"

    def test_sanitize_dirname_applied(self, project_base_dir: Path):
        """Tên có ký tự đặc biệt phải được sanitize khi tạo thư mục."""
        p = Project.new("Project: Test/2024", "/fake/v.mp4", str(project_base_dir))
        project_dir = Path(p.data.project_dir)
        assert project_dir.exists()
        # Ký tự : và / phải bị thay bằng _
        assert ":" not in project_dir.name
        assert "/" not in project_dir.name

    def test_pipeline_all_waiting_initially(self, new_project: Project):
        ps = new_project.data.pipeline_status
        assert ps.import_ == StepStatus.WAITING
        assert ps.stt == StepStatus.WAITING
        assert ps.translate == StepStatus.WAITING


# ---------------------------------------------------------------------------
# Tests: Project.load()
# ---------------------------------------------------------------------------


class TestProjectLoad:
    def test_load_existing_project(self, new_project: Project):
        loaded = Project.load(new_project.data.project_dir)
        assert loaded.data.project_id == new_project.data.project_id
        assert loaded.data.project_name == new_project.data.project_name

    def test_load_file_not_found(self, tmp_path: Path):
        with pytest.raises(ProjectFileNotFoundError):
            Project.load(str(tmp_path / "nonexistent_project"))

    def test_load_corrupted_json_syntax(self, tmp_path: Path):
        project_dir = tmp_path / "corrupted"
        project_dir.mkdir()
        (project_dir / "project.json").write_text("{invalid json!!!", encoding="utf-8")

        with pytest.raises(ProjectFileCorruptedError):
            Project.load(str(project_dir))

    def test_load_invalid_schema(self, tmp_path: Path):
        """JSON hợp lệ nhưng thiếu trường bắt buộc."""
        project_dir = tmp_path / "invalid_schema"
        project_dir.mkdir()
        (project_dir / "project.json").write_text(
            json.dumps({"name": "test", "missing_required_fields": True}),
            encoding="utf-8",
        )
        with pytest.raises(ProjectFileCorruptedError):
            Project.load(str(project_dir))

    def test_load_empty_file(self, tmp_path: Path):
        project_dir = tmp_path / "empty"
        project_dir.mkdir()
        (project_dir / "project.json").write_text("", encoding="utf-8")
        with pytest.raises(ProjectFileCorruptedError):
            Project.load(str(project_dir))


# ---------------------------------------------------------------------------
# Tests: Save/Load roundtrip
# ---------------------------------------------------------------------------


class TestProjectRoundtrip:
    def test_basic_roundtrip(self, new_project: Project):
        """Save rồi load lại phải cho kết quả giống nhau."""
        original_id = new_project.data.project_id
        original_name = new_project.data.project_name

        loaded = Project.load(new_project.data.project_dir)
        assert loaded.data.project_id == original_id
        assert loaded.data.project_name == original_name

    def test_roundtrip_with_segments(self, project_with_segments: Project):
        project_with_segments.save()
        loaded = Project.load(project_with_segments.data.project_dir)

        assert loaded.data.total_segments == 3
        seg1 = loaded.data.segments[0]
        assert seg1.text_zh == "今天天气真好"
        assert seg1.confidence == pytest.approx(0.92)
        assert seg1.speaker == "A"

    def test_roundtrip_with_translations(self, project_with_segments: Project):
        project_with_segments.update_segment_translation(1, "Hôm nay thời tiết thật tốt")
        project_with_segments.save()

        loaded = Project.load(project_with_segments.data.project_dir)
        seg = next(s for s in loaded.data.segments if s.id == 1)
        assert seg.text_vi == "Hôm nay thời tiết thật tốt"
        assert seg.status == SegmentStatus.TRANSLATED

    def test_roundtrip_preserves_pipeline_status(self, new_project: Project):
        new_project.on_stt_started()
        loaded = Project.load(new_project.data.project_dir)
        assert loaded.data.pipeline_status.stt == StepStatus.PROCESSING

    def test_roundtrip_preserves_settings(self, project_base_dir: Path):
        settings = ProjectSettings(batch_size=25, gemini_model="gemini-1.5-flash")
        p = Project.new("Roundtrip Test", "/fake/v.mp4", str(project_base_dir), settings=settings)
        loaded = Project.load(p.data.project_dir)
        assert loaded.data.settings.batch_size == 25
        assert loaded.data.settings.gemini_model == "gemini-1.5-flash"

    def test_roundtrip_preserves_speakers(self, new_project: Project):
        speaker = Speaker(id="A", gender="male", voice_id="vi-VN-NamMinhNeural")
        new_project.update_speaker(speaker)
        new_project.save()

        loaded = Project.load(new_project.data.project_dir)
        assert "A" in loaded.data.speakers
        assert loaded.data.speakers["A"].voice_id == "vi-VN-NamMinhNeural"


# ---------------------------------------------------------------------------
# Tests: Segment update API
# ---------------------------------------------------------------------------


class TestUpdateSegments:
    def test_update_from_stt_creates_segments(self, new_project: Project):
        raw = [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "你好", "speaker": "A", "confidence": 0.9},
        ]
        new_project.update_segments_from_stt(raw)
        assert new_project.data.total_segments == 1
        assert new_project.data.segments[0].text_zh == "你好"

    def test_update_from_stt_replaces_all_segments(self, project_with_segments: Project):
        """update_segments_from_stt nên thay thế hoàn toàn danh sách segment cũ."""
        new_raw = [
            {"id": 1, "start": 0.0, "end": 1.0, "text": "新内容", "speaker": "A", "confidence": 0.8},
        ]
        project_with_segments.update_segments_from_stt(new_raw)
        assert project_with_segments.data.total_segments == 1

    def test_update_translated_segments_merge(self, project_with_segments: Project):
        """Chỉ segment có trong translated_list bị update, các segment khác giữ nguyên."""
        segs = project_with_segments.data.segments
        translated = [
            segs[0].model_copy(update={
                "text_vi": "Hôm nay trời đẹp",
                "status": SegmentStatus.TRANSLATED,
            })
        ]
        project_with_segments.update_translated_segments(translated)

        updated_segs = project_with_segments.data.segments
        assert updated_segs[0].text_vi == "Hôm nay trời đẹp"
        assert updated_segs[0].status == SegmentStatus.TRANSLATED
        # Segment 1 và 2 (index 1, 2) không bị thay đổi
        assert updated_segs[1].text_vi is None
        assert updated_segs[2].text_vi is None

    def test_update_segment_translation_single(self, project_with_segments: Project):
        project_with_segments.update_segment_translation(2, "Xin chào thế giới")
        seg = next(s for s in project_with_segments.data.segments if s.id == 2)
        assert seg.text_vi == "Xin chào thế giới"
        assert seg.status == SegmentStatus.TRANSLATED
        assert seg.error_message is None

    def test_update_segment_translation_sets_updated_at(self, project_with_segments: Project):
        project_with_segments.update_segment_translation(1, "Cảm ơn")
        seg = next(s for s in project_with_segments.data.segments if s.id == 1)
        assert seg.updated_at is not None

    def test_mark_segment_error(self, project_with_segments: Project):
        project_with_segments.mark_segment_error(1, "HTTP 429 Rate Limit")
        seg = next(s for s in project_with_segments.data.segments if s.id == 1)
        assert seg.status == SegmentStatus.ERROR
        assert "429" in seg.error_message

    def test_mark_segment_reviewed(self, project_with_segments: Project):
        project_with_segments.update_segment_translation(1, "Hôm nay trời đẹp")
        project_with_segments.mark_segment_reviewed(1)
        seg = next(s for s in project_with_segments.data.segments if s.id == 1)
        assert seg.status == SegmentStatus.REVIEWED

    def test_update_voice_path_stores_hash(self, project_with_segments: Project):
        """update_voice_path phải lưu text_vi_hash để phục vụ TTS idempotency."""
        project_with_segments.update_segment_translation(1, "Hôm nay trời đẹp")
        project_with_segments.update_voice_path(1, "/path/to/seg_001.wav")

        seg = next(s for s in project_with_segments.data.segments if s.id == 1)
        assert seg.voice_path == "/path/to/seg_001.wav"
        assert seg.text_vi_hash is not None
        # Hash phải khớp với text_vi hiện tại → không cần regenerate
        assert not seg.needs_tts_regeneration


# ---------------------------------------------------------------------------
# Tests: Idempotency (resume logic)
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_get_segments_to_translate_skips_translated(self, project_with_segments: Project):
        """Chỉ PENDING và ERROR cần translate lại."""
        project_with_segments.update_segment_translation(1, "Hôm nay trời đẹp")  # → TRANSLATED
        to_translate = project_with_segments.get_segments_to_translate()
        ids = [s.id for s in to_translate]
        assert 1 not in ids
        assert 2 in ids
        assert 3 in ids

    def test_get_segments_to_translate_skips_reviewed(self, project_with_segments: Project):
        project_with_segments.update_segment_translation(2, "Xin chào")
        project_with_segments.mark_segment_reviewed(2)
        to_translate = project_with_segments.get_segments_to_translate()
        ids = [s.id for s in to_translate]
        assert 2 not in ids

    def test_get_segments_for_tts_no_text_vi(self, project_with_segments: Project):
        """Segment chưa có text_vi không vào hàng đợi TTS."""
        tts_segs = project_with_segments.get_segments_for_tts()
        assert len(tts_segs) == 0

    def test_get_segments_for_tts_after_translate(self, project_with_segments: Project):
        project_with_segments.update_segment_translation(1, "Hôm nay trời đẹp")
        tts_segs = project_with_segments.get_segments_for_tts()
        ids = [s.id for s in tts_segs]
        assert 1 in ids

    def test_get_segments_for_tts_skips_after_voice(self, project_with_segments: Project):
        project_with_segments.update_segment_translation(1, "Hôm nay trời đẹp")
        project_with_segments.update_voice_path(1, "/path/seg.wav")  # lưu hash
        tts_segs = project_with_segments.get_segments_for_tts()
        ids = [s.id for s in tts_segs]
        assert 1 not in ids  # đã TTS, text không đổi → bỏ qua


# ---------------------------------------------------------------------------
# Tests: Pipeline events & callbacks
# ---------------------------------------------------------------------------


class TestPipelineEvents:
    def test_stt_started_updates_status(self, new_project: Project):
        new_project.on_stt_started()
        assert new_project.data.pipeline_status.stt == StepStatus.PROCESSING

    def test_stt_completed_updates_status(self, new_project: Project):
        raw = [{"id": 1, "start": 0.0, "end": 2.0, "text": "你好", "speaker": "A", "confidence": 0.9}]
        new_project.on_stt_started()
        new_project.on_stt_completed(raw)
        assert new_project.data.pipeline_status.stt == StepStatus.COMPLETED
        assert new_project.data.total_segments == 1

    def test_stt_error_updates_status(self, new_project: Project):
        new_project.on_stt_started()
        new_project.on_stt_error("ffmpeg không tìm thấy")
        assert new_project.data.pipeline_status.stt == StepStatus.ERROR

    def test_translate_started_and_completed(self, project_with_segments: Project):
        project_with_segments.on_translate_started()
        assert project_with_segments.data.pipeline_status.translate == StepStatus.PROCESSING
        project_with_segments.on_translate_completed()
        assert project_with_segments.data.pipeline_status.translate == StepStatus.COMPLETED

    def test_import_completed_stores_metadata(self, new_project: Project):
        meta = VideoMetadata(
            filename="video.mp4",
            duration=120.0,
            width=1920,
            height=1080,
            fps=30.0,
        )
        new_project.on_import_completed(meta)
        assert new_project.data.video_metadata is not None
        assert new_project.data.video_metadata.filename == "video.mp4"

    def test_pipeline_status_saved_after_event(self, new_project: Project):
        new_project.on_stt_started()
        # Load lại từ disk để verify đã được save
        loaded = Project.load(new_project.data.project_dir)
        assert loaded.data.pipeline_status.stt == StepStatus.PROCESSING


class TestCallbackSystem:
    def test_step_started_callback_called(self, new_project: Project):
        calls = []
        new_project.add_on_step_started(lambda step: calls.append(step))
        new_project.on_stt_started()
        assert "stt" in calls

    def test_step_completed_callback_called(self, project_with_segments: Project):
        calls = []
        project_with_segments.add_on_step_completed(lambda step: calls.append(step))
        project_with_segments.on_translate_completed()
        assert "translate" in calls

    def test_step_error_callback_called(self, new_project: Project):
        errors = []
        new_project.add_on_step_error(lambda step, msg: errors.append((step, msg)))
        new_project.on_stt_error("Lỗi thử nghiệm")
        assert len(errors) == 1
        assert errors[0][0] == "stt"
        assert "Lỗi thử nghiệm" in errors[0][1]

    def test_multiple_callbacks_all_called(self, new_project: Project):
        calls1 = []
        calls2 = []
        new_project.add_on_step_started(lambda s: calls1.append(s))
        new_project.add_on_step_started(lambda s: calls2.append(s))
        new_project.on_stt_started()
        assert len(calls1) == 1
        assert len(calls2) == 1

    def test_clear_callbacks(self, new_project: Project):
        calls = []
        new_project.add_on_step_started(lambda s: calls.append(s))
        new_project.clear_callbacks()
        new_project.on_stt_started()
        assert len(calls) == 0


# ---------------------------------------------------------------------------
# Tests: _sanitize_dirname helper
# ---------------------------------------------------------------------------


class TestSanitizeDirname:
    def test_normal_name_unchanged(self):
        assert _sanitize_dirname("My Project") == "My Project"

    def test_special_chars_replaced(self):
        result = _sanitize_dirname("Project: Test/2024")
        assert ":" not in result
        assert "/" not in result

    def test_all_invalid_chars(self):
        result = _sanitize_dirname(r'a\b/c:d*e?f"g<h>i|j')
        for ch in r'\/:*?"<>|':
            assert ch not in result

    def test_unicode_preserved(self):
        name = "Dự án tiếng Việt"
        result = _sanitize_dirname(name)
        assert "Dự án tiếng Việt" in result

    def test_chinese_preserved(self):
        name = "项目名称"
        result = _sanitize_dirname(name)
        assert result == "项目名称"

    def test_length_limit(self):
        long_name = "a" * 200
        result = _sanitize_dirname(long_name)
        assert len(result) <= 100

    def test_empty_name_fallback(self):
        result = _sanitize_dirname("   ")
        assert result == "Untitled Project"

    def test_leading_dots_stripped(self):
        result = _sanitize_dirname("...project")
        assert not result.startswith(".")
