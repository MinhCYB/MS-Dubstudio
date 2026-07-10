"""
tests/core/test_models.py — Unit tests for core/models.py

Kiểm tra:
- Validate Pydantic models (đúng field, sai type, thiếu field bắt buộc)
- Edge cases (confidence boundary, duration, hash)
- Enum behavior
- PipelineStatus.is_step_unlocked logic
- ProjectData helper properties (translation_progress, get_segments_to_translate...)
- BatchResult.progress_pct
- Serialization roundtrip (model_dump → model_validate)
"""

import hashlib
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from msdubstudio.core.models import (
    BatchResult,
    PipelineStatus,
    ProjectData,
    ProjectSettings,
    Segment,
    SegmentStatus,
    Speaker,
    StepStatus,
    VideoMetadata,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_segment(
    id: int = 1,
    start: float = 0.0,
    end: float = 2.0,
    speaker: str = "A",
    text_zh: str = "你好世界",
    text_vi: str | None = None,
    confidence: float = 0.9,
    status: SegmentStatus = SegmentStatus.PENDING,
    voice_path: str | None = None,
    text_vi_hash: str | None = None,
) -> Segment:
    return Segment(
        id=id,
        start=start,
        end=end,
        speaker=speaker,
        text_zh=text_zh,
        text_vi=text_vi,
        confidence=confidence,
        status=status,
        voice_path=voice_path,
        text_vi_hash=text_vi_hash,
    )


def make_project_data(**kwargs) -> ProjectData:
    defaults = dict(
        project_id="test-uuid-1234",
        project_name="Test Project",
        video_path="/fake/path/video.mp4",
        project_dir="/fake/path",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return ProjectData(**defaults)


# ---------------------------------------------------------------------------
# Tests: SegmentStatus enum
# ---------------------------------------------------------------------------


class TestSegmentStatus:
    def test_values_are_strings(self):
        assert SegmentStatus.PENDING == "pending"
        assert SegmentStatus.TRANSLATED == "translated"
        assert SegmentStatus.ERROR == "error"
        assert SegmentStatus.REVIEWED == "reviewed"

    def test_is_str_enum(self):
        assert isinstance(SegmentStatus.PENDING, str)


# ---------------------------------------------------------------------------
# Tests: StepStatus enum
# ---------------------------------------------------------------------------


class TestStepStatus:
    def test_all_values(self):
        assert StepStatus.WAITING == "waiting"
        assert StepStatus.PROCESSING == "processing"
        assert StepStatus.COMPLETED == "completed"
        assert StepStatus.ERROR == "error"


# ---------------------------------------------------------------------------
# Tests: Segment model
# ---------------------------------------------------------------------------


class TestSegment:
    def test_create_minimal_segment(self):
        seg = make_segment()
        assert seg.id == 1
        assert seg.start == 0.0
        assert seg.end == 2.0
        assert seg.status == SegmentStatus.PENDING
        assert seg.text_vi is None
        assert seg.voice_path is None

    def test_duration_property(self):
        seg = make_segment(start=1.5, end=4.5)
        assert seg.duration == pytest.approx(3.0)

    def test_end_must_be_after_start(self):
        with pytest.raises(ValidationError) as exc_info:
            make_segment(start=5.0, end=3.0)
        assert "end" in str(exc_info.value).lower() or "start" in str(exc_info.value).lower()

    def test_end_equal_start_raises(self):
        with pytest.raises(ValidationError):
            make_segment(start=2.0, end=2.0)

    def test_confidence_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            make_segment(confidence=1.5)
        with pytest.raises(ValidationError):
            make_segment(confidence=-0.1)

    def test_confidence_boundary_values(self):
        seg_low = make_segment(confidence=0.0)
        seg_high = make_segment(confidence=1.0)
        assert seg_low.confidence == 0.0
        assert seg_high.confidence == 1.0

    # Confidence level classification
    def test_confidence_level_high(self):
        seg = make_segment(confidence=0.80)
        assert seg.confidence_level == "high"

    def test_confidence_level_high_boundary(self):
        seg = make_segment(confidence=1.0)
        assert seg.confidence_level == "high"

    def test_confidence_level_medium(self):
        seg = make_segment(confidence=0.65)
        assert seg.confidence_level == "medium"

    def test_confidence_level_medium_lower_boundary(self):
        seg = make_segment(confidence=0.50)
        assert seg.confidence_level == "medium"

    def test_confidence_level_low(self):
        seg = make_segment(confidence=0.49)
        assert seg.confidence_level == "low"

    def test_confidence_level_zero(self):
        seg = make_segment(confidence=0.0)
        assert seg.confidence_level == "low"

    # TTS hash / idempotency
    def test_needs_tts_no_voice_path(self):
        seg = make_segment(voice_path=None, text_vi="xin chào")
        assert seg.needs_tts_regeneration is True

    def test_needs_tts_no_text_vi(self):
        seg = make_segment(voice_path="/path/seg.wav", text_vi=None)
        assert seg.needs_tts_regeneration is False

    def test_needs_tts_text_unchanged(self):
        text = "xin chào thế giới"
        expected_hash = hashlib.sha256(text.encode()).hexdigest()
        seg = make_segment(
            voice_path="/path/seg.wav",
            text_vi=text,
            text_vi_hash=expected_hash,
        )
        assert seg.needs_tts_regeneration is False

    def test_needs_tts_text_changed(self):
        old_text = "xin chào"
        new_text = "tạm biệt"
        old_hash = hashlib.sha256(old_text.encode()).hexdigest()
        seg = make_segment(
            voice_path="/path/seg.wav",
            text_vi=new_text,
            text_vi_hash=old_hash,  # lưu hash của text cũ
        )
        assert seg.needs_tts_regeneration is True

    def test_compute_text_vi_hash_none_text(self):
        seg = make_segment(text_vi=None)
        assert seg.compute_text_vi_hash() is None

    def test_compute_text_vi_hash_consistent(self):
        text = "tiếng Việt"
        seg = make_segment(text_vi=text)
        h1 = seg.compute_text_vi_hash()
        h2 = hashlib.sha256(text.encode()).hexdigest()
        assert h1 == h2

    # Serialization roundtrip
    def test_segment_roundtrip(self):
        seg = make_segment(text_vi="xin chào", status=SegmentStatus.TRANSLATED)
        data = seg.model_dump()
        restored = Segment.model_validate(data)
        assert restored == seg

    def test_segment_json_roundtrip(self):
        seg = make_segment(text_vi="xin chào")
        json_str = seg.model_dump_json()
        restored = Segment.model_validate_json(json_str)
        assert restored.id == seg.id
        assert restored.text_vi == seg.text_vi


# ---------------------------------------------------------------------------
# Tests: Speaker model
# ---------------------------------------------------------------------------


class TestSpeaker:
    def test_create_speaker(self):
        sp = Speaker(id="A", gender="male", voice_id="vi-VN-NamMinhNeural")
        assert sp.id == "A"
        assert sp.gender == "male"

    def test_name_property_with_display_name(self):
        sp = Speaker(id="A", display_name="Nhân vật A")
        assert sp.name == "Nhân vật A"

    def test_name_property_fallback(self):
        sp = Speaker(id="B")
        assert sp.name == "Speaker B"

    def test_default_values(self):
        sp = Speaker(id="C")
        assert sp.gender == "unknown"
        assert sp.voice_id == ""
        assert sp.emotion == "neutral"


# ---------------------------------------------------------------------------
# Tests: ProjectSettings
# ---------------------------------------------------------------------------


class TestProjectSettings:
    def test_default_values(self):
        s = ProjectSettings()
        assert s.source_lang == "zh"
        assert s.target_lang == "vi"
        assert s.whisper_model == "large-v3"
        assert s.batch_size == 15
        assert s.translate_temperature == pytest.approx(0.3)
        assert s.use_context_frame is True
        assert s.tts_engine == "edge-tts"

    def test_custom_values(self):
        s = ProjectSettings(batch_size=20, translate_temperature=0.7)
        assert s.batch_size == 20
        assert s.translate_temperature == pytest.approx(0.7)

    def test_batch_size_min(self):
        with pytest.raises(ValidationError):
            ProjectSettings(batch_size=0)

    def test_batch_size_max(self):
        with pytest.raises(ValidationError):
            ProjectSettings(batch_size=101)

    def test_temperature_out_of_range(self):
        with pytest.raises(ValidationError):
            ProjectSettings(translate_temperature=-0.1)
        with pytest.raises(ValidationError):
            ProjectSettings(translate_temperature=2.1)

    def test_whisper_beam_size_range(self):
        with pytest.raises(ValidationError):
            ProjectSettings(whisper_beam_size=0)
        with pytest.raises(ValidationError):
            ProjectSettings(whisper_beam_size=21)


# ---------------------------------------------------------------------------
# Tests: PipelineStatus
# ---------------------------------------------------------------------------


class TestPipelineStatus:
    def test_default_all_waiting(self):
        ps = PipelineStatus()
        assert ps.import_ == StepStatus.WAITING
        assert ps.stt == StepStatus.WAITING
        assert ps.translate == StepStatus.WAITING

    def test_alias_import(self):
        """PipelineStatus dùng alias 'import' vì 'import' là keyword Python."""
        ps = PipelineStatus.model_validate({"import": "completed", "stt": "waiting"})
        assert ps.import_ == StepStatus.COMPLETED

    def test_is_step_unlocked_import_always(self):
        ps = PipelineStatus()  # tất cả waiting
        assert ps.is_step_unlocked("import") is True

    def test_is_step_unlocked_stt_requires_import_completed(self):
        ps = PipelineStatus()
        assert ps.is_step_unlocked("stt") is False
        ps.import_ = StepStatus.COMPLETED
        assert ps.is_step_unlocked("stt") is True

    def test_is_step_unlocked_translate_requires_stt(self):
        ps = PipelineStatus(stt=StepStatus.COMPLETED)
        assert ps.is_step_unlocked("translate") is True

    def test_is_step_unlocked_translate_blocked_if_stt_waiting(self):
        ps = PipelineStatus()
        assert ps.is_step_unlocked("translate") is False

    def test_is_step_unlocked_review_allows_error(self):
        """Review có thể được phép ngay cả khi translate có ERROR."""
        ps = PipelineStatus(translate=StepStatus.ERROR)
        assert ps.is_step_unlocked("review") is True

    def test_is_step_unlocked_voice_requires_translate_completed(self):
        ps = PipelineStatus(translate=StepStatus.COMPLETED)
        assert ps.is_step_unlocked("voice") is True

    def test_is_step_unlocked_voice_blocked_if_translate_error(self):
        """Voice không được mở nếu translate có lỗi — phải fix lỗi trước."""
        ps = PipelineStatus(translate=StepStatus.ERROR)
        assert ps.is_step_unlocked("voice") is False

    def test_is_step_unlocked_export_requires_voice(self):
        ps = PipelineStatus(voice=StepStatus.COMPLETED)
        assert ps.is_step_unlocked("export") is True

    def test_is_step_unlocked_unknown_step(self):
        ps = PipelineStatus()
        assert ps.is_step_unlocked("unknown_step") is False

    def test_pipeline_roundtrip_with_alias(self):
        ps = PipelineStatus(stt=StepStatus.COMPLETED)
        data = ps.model_dump(by_alias=True)
        assert "import" in data
        restored = PipelineStatus.model_validate(data)
        assert restored.stt == StepStatus.COMPLETED


# ---------------------------------------------------------------------------
# Tests: VideoMetadata
# ---------------------------------------------------------------------------


class TestVideoMetadata:
    def test_create(self):
        vm = VideoMetadata(
            filename="video.mp4",
            duration=120.5,
            width=1920,
            height=1080,
            fps=30.0,
        )
        assert vm.filename == "video.mp4"
        assert vm.duration == pytest.approx(120.5)
        assert vm.detected_language is None


# ---------------------------------------------------------------------------
# Tests: ProjectData
# ---------------------------------------------------------------------------


class TestProjectData:
    def test_create_minimal(self):
        p = make_project_data()
        assert p.project_id == "test-uuid-1234"
        assert p.total_segments == 0
        assert p.translation_progress == 0.0

    def test_total_segments(self):
        segs = [make_segment(id=i, start=i * 2.0, end=i * 2.0 + 1.5) for i in range(1, 6)]
        p = make_project_data(segments=segs)
        assert p.total_segments == 5

    def test_translated_segments_count(self):
        segs = [
            make_segment(id=1, start=0, end=1, status=SegmentStatus.TRANSLATED),
            make_segment(id=2, start=1, end=2, status=SegmentStatus.REVIEWED),
            make_segment(id=3, start=2, end=3, status=SegmentStatus.PENDING),
            make_segment(id=4, start=3, end=4, status=SegmentStatus.ERROR),
        ]
        p = make_project_data(segments=segs)
        assert p.translated_segments == 2

    def test_error_segments_count(self):
        segs = [
            make_segment(id=1, start=0, end=1, status=SegmentStatus.ERROR),
            make_segment(id=2, start=1, end=2, status=SegmentStatus.ERROR),
            make_segment(id=3, start=2, end=3, status=SegmentStatus.TRANSLATED),
        ]
        p = make_project_data(segments=segs)
        assert p.error_segments == 2

    def test_pending_segments_count(self):
        segs = [
            make_segment(id=1, start=0, end=1, status=SegmentStatus.PENDING),
            make_segment(id=2, start=1, end=2, status=SegmentStatus.TRANSLATED),
        ]
        p = make_project_data(segments=segs)
        assert p.pending_segments_count == 1

    def test_translation_progress_all_pending(self):
        segs = [make_segment(id=i, start=i * 1.0, end=i * 1.0 + 0.9) for i in range(1, 4)]
        p = make_project_data(segments=segs)
        assert p.translation_progress == pytest.approx(0.0)

    def test_translation_progress_all_translated(self):
        segs = [
            make_segment(id=i, start=i * 1.0, end=i * 1.0 + 0.9, status=SegmentStatus.TRANSLATED)
            for i in range(1, 4)
        ]
        p = make_project_data(segments=segs)
        assert p.translation_progress == pytest.approx(1.0)

    def test_translation_progress_partial(self):
        segs = [
            make_segment(id=1, start=0, end=1, status=SegmentStatus.TRANSLATED),
            make_segment(id=2, start=1, end=2, status=SegmentStatus.PENDING),
            make_segment(id=3, start=2, end=3, status=SegmentStatus.PENDING),
            make_segment(id=4, start=3, end=4, status=SegmentStatus.REVIEWED),
        ]
        p = make_project_data(segments=segs)
        assert p.translation_progress == pytest.approx(0.5)

    def test_translation_progress_no_segments(self):
        p = make_project_data(segments=[])
        assert p.translation_progress == pytest.approx(0.0)

    # get_segments_to_translate — idempotency
    def test_get_segments_to_translate_skips_translated(self):
        segs = [
            make_segment(id=1, start=0, end=1, status=SegmentStatus.TRANSLATED, text_vi="đã dịch"),
            make_segment(id=2, start=1, end=2, status=SegmentStatus.PENDING),
            make_segment(id=3, start=2, end=3, status=SegmentStatus.ERROR),
            make_segment(id=4, start=3, end=4, status=SegmentStatus.REVIEWED, text_vi="đã review"),
        ]
        p = make_project_data(segments=segs)
        to_translate = p.get_segments_to_translate()
        ids = [s.id for s in to_translate]
        assert 1 not in ids, "TRANSLATED segment không được dịch lại"
        assert 4 not in ids, "REVIEWED segment không được dịch lại"
        assert 2 in ids, "PENDING phải được dịch"
        assert 3 in ids, "ERROR phải được retry"

    def test_get_segments_to_translate_all_translated(self):
        segs = [
            make_segment(id=i, start=i * 1.0, end=i * 1.0 + 0.9, status=SegmentStatus.TRANSLATED)
            for i in range(1, 4)
        ]
        p = make_project_data(segments=segs)
        assert p.get_segments_to_translate() == []

    # get_segments_for_tts — idempotency
    def test_get_segments_for_tts_no_text_vi(self):
        segs = [make_segment(id=1, start=0, end=1)]  # text_vi = None
        p = make_project_data(segments=segs)
        assert p.get_segments_for_tts() == []

    def test_get_segments_for_tts_needs_generation(self):
        text = "xin chào"
        seg = make_segment(
            id=1, start=0, end=1,
            text_vi=text,
            voice_path=None,  # chưa TTS
        )
        p = make_project_data(segments=[seg])
        result = p.get_segments_for_tts()
        assert len(result) == 1
        assert result[0].id == 1

    def test_get_segments_for_tts_unchanged_skips(self):
        text = "xin chào"
        expected_hash = hashlib.sha256(text.encode()).hexdigest()
        seg = make_segment(
            id=1, start=0, end=1,
            text_vi=text,
            voice_path="/path/seg.wav",
            text_vi_hash=expected_hash,  # hash khớp → không cần regenerate
        )
        p = make_project_data(segments=[seg])
        assert p.get_segments_for_tts() == []

    def test_get_segments_for_tts_changed_text_included(self):
        old_hash = hashlib.sha256("cũ".encode()).hexdigest()
        seg = make_segment(
            id=1, start=0, end=1,
            text_vi="mới",
            voice_path="/path/seg.wav",
            text_vi_hash=old_hash,  # hash cũ → khác text hiện tại
        )
        p = make_project_data(segments=[seg])
        result = p.get_segments_for_tts()
        assert len(result) == 1

    # Serialization roundtrip
    def test_project_data_roundtrip(self):
        segs = [
            make_segment(id=1, start=0, end=1, text_vi="xin chào", status=SegmentStatus.TRANSLATED)
        ]
        speakers = {"A": Speaker(id="A", gender="male", voice_id="vi-VN-NamMinhNeural")}
        p = make_project_data(segments=segs, speakers=speakers)

        data = p.model_dump()
        restored = ProjectData.model_validate(data)
        assert restored.project_id == p.project_id
        assert restored.total_segments == p.total_segments
        assert restored.segments[0].text_vi == "xin chào"
        assert restored.speakers["A"].voice_id == "vi-VN-NamMinhNeural"

    def test_project_data_json_roundtrip(self):
        p = make_project_data()
        json_str = p.model_dump_json()
        restored = ProjectData.model_validate_json(json_str)
        assert restored.project_name == p.project_name
        assert restored.created_at == p.created_at


# ---------------------------------------------------------------------------
# Tests: BatchResult
# ---------------------------------------------------------------------------


class TestBatchResult:
    def test_progress_pct_normal(self):
        br = BatchResult(batch_index=0, current=30, total=100)
        assert br.progress_pct == 30

    def test_progress_pct_zero_total(self):
        br = BatchResult(batch_index=0, current=0, total=0)
        assert br.progress_pct == 0

    def test_progress_pct_capped_at_100(self):
        br = BatchResult(batch_index=0, current=110, total=100)
        assert br.progress_pct == 100

    def test_error_batch(self):
        br = BatchResult(
            batch_index=1,
            current=15,
            total=30,
            is_error=True,
            error_message="HTTP 429 Rate Limit",
        )
        assert br.is_error is True
        assert "429" in br.error_message

    def test_success_batch(self):
        seg = make_segment(id=1, start=0, end=1, status=SegmentStatus.TRANSLATED)
        br = BatchResult(batch_index=0, current=15, total=30, segments=[seg])
        assert br.is_error is False
        assert len(br.segments) == 1
