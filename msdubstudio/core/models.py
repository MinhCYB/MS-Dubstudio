"""
core/models.py — MS DubStudio Data Models

Nguồn sự thật duy nhất cho tất cả cấu trúc dữ liệu trong app.
Dùng Pydantic để validate + serialize/deserialize project.json.

Không import bất cứ thứ gì từ PyQt6. Module này phải chạy được
hoàn toàn trong môi trường headless (test, CLI...).
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SegmentStatus(str, Enum):
    """Trạng thái của một segment dịch thuật."""

    PENDING = "pending"
    """Chưa được dịch."""

    TRANSLATED = "translated"
    """Đã dịch thành công (bởi AI hoặc người dùng chỉnh sửa + confirm)."""

    ERROR = "error"
    """Dịch thất bại — có lỗi trong `error_message`."""

    REVIEWED = "reviewed"
    """Người dùng đã review + approve bản dịch."""


class StepStatus(str, Enum):
    """Trạng thái của từng bước trong pipeline."""

    WAITING = "waiting"
    """Chưa chạy — các bước trước chưa hoàn thành."""

    PROCESSING = "processing"
    """Đang chạy — UI hiển thị Processing Overlay."""

    COMPLETED = "completed"
    """Đã hoàn thành thành công."""

    ERROR = "error"
    """Có lỗi — cần user can thiệp."""


# ---------------------------------------------------------------------------
# Core domain models
# ---------------------------------------------------------------------------


class Segment(BaseModel):
    """Một câu thoại đã được nhận dạng từ audio.

    Đây là đơn vị cơ bản của pipeline dịch thuật. Mỗi Segment tương ứng
    với một đoạn lời nói liên tục của một speaker trong video.
    """

    id: int
    """ID tuần tự, bắt đầu từ 1. Dùng trong prompt Gemini để map kết quả."""

    start: float
    """Thời điểm bắt đầu tính bằng giây (ví dụ: 1.42)."""

    end: float
    """Thời điểm kết thúc tính bằng giây."""

    speaker: str
    """Mã speaker: 'A', 'B', 'C'... Được gán bởi diarization hoặc user chỉnh."""

    text_zh: str
    """Văn bản tiếng Trung gốc từ Whisper STT."""

    text_vi: Optional[str] = None
    """Văn bản tiếng Việt đã dịch. None nếu chưa dịch."""

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    """Độ tin cậy từ Whisper (0.0–1.0).
    ≥0.80 → High (xanh), 0.50–0.79 → Medium (vàng), <0.50 → Low (đỏ).
    """

    scene_frame: Optional[str] = None
    """Đường dẫn tuyệt đối tới frame ảnh đại diện cho scene chứa segment này.
    Được đính kèm vào prompt Gemini nếu use_context_frame=True.
    """

    status: SegmentStatus = SegmentStatus.PENDING
    """Trạng thái dịch thuật hiện tại của segment."""

    error_message: Optional[str] = None
    """Thông báo lỗi nếu status == ERROR. None nếu không có lỗi."""

    voice_path: Optional[str] = None
    """Đường dẫn tuyệt đối tới file audio TTS đã sinh.
    None nếu chưa sinh TTS. Được dùng trong bước render.
    """

    text_vi_hash: Optional[str] = None
    """SHA-256 hash của text_vi lần TTS cuối cùng.
    Dùng để detect thay đổi: nếu hash khác → cần regenerate TTS.
    None nếu chưa từng sinh TTS.
    """

    notes: Optional[str] = None
    """Ghi chú của người dùng về segment này (không ảnh hưởng đến TTS)."""

    updated_at: Optional[datetime] = None
    """Thời điểm segment được chỉnh sửa lần cuối."""

    @field_validator("end")
    @classmethod
    def end_must_be_after_start(cls, v: float, info) -> float:
        """Validate end > start."""
        start = info.data.get("start")
        if start is not None and v <= start:
            raise ValueError(
                f"end ({v}) phải lớn hơn start ({start})"
            )
        return v

    @property
    def duration(self) -> float:
        """Thời lượng của segment tính bằng giây."""
        return self.end - self.start

    @property
    def needs_tts_regeneration(self) -> bool:
        """True nếu text_vi đã thay đổi kể từ lần TTS cuối, hoặc chưa TTS lần nào.

        So sánh hash của text_vi hiện tại với text_vi_hash được lưu.
        Trả về True nếu:
        - Chưa có voice_path (chưa TTS lần nào)
        - Hash của text_vi hiện tại khác text_vi_hash
        """
        if self.voice_path is None:
            return True
        if self.text_vi is None:
            return False
        current_hash = hashlib.sha256(self.text_vi.encode("utf-8")).hexdigest()
        return current_hash != self.text_vi_hash

    def compute_text_vi_hash(self) -> Optional[str]:
        """Tính SHA-256 hash của text_vi hiện tại. None nếu text_vi là None."""
        if self.text_vi is None:
            return None
        return hashlib.sha256(self.text_vi.encode("utf-8")).hexdigest()

    @property
    def confidence_level(self) -> str:
        """Phân loại confidence thành 3 mức: 'high', 'medium', 'low'."""
        if self.confidence >= 0.80:
            return "high"
        elif self.confidence >= 0.50:
            return "medium"
        else:
            return "low"


class Speaker(BaseModel):
    """Thông tin về một nhân vật nói trong video."""

    id: str
    """Mã speaker: 'A', 'B', 'C'..."""

    gender: str = "unknown"
    """Giới tính: 'male', 'female', 'unknown'."""

    voice_id: str = ""
    """ID giọng đọc TTS (ví dụ: 'vi-VN-NamMinhNeural').
    Rỗng nếu chưa được cấu hình.
    """

    emotion: str = "neutral"
    """Cảm xúc mặc định: 'neutral', 'happy', 'sad', 'angry', 'fearful'."""

    display_name: Optional[str] = None
    """Tên hiển thị thân thiện (ví dụ: 'Speaker A'). Tự động tạo nếu None."""

    @property
    def name(self) -> str:
        """Tên hiển thị, fallback về 'Speaker {id}'."""
        return self.display_name or f"Speaker {self.id}"


class ProjectSettings(BaseModel):
    """Cài đặt xử lý cho project.

    Lưu vào project.json để đảm bảo reproducibility —
    mở lại project trên máy khác vẫn biết dùng settings gì.
    """

    source_lang: str = "zh"
    """Ngôn ngữ nguồn (ISO 639-1). Mặc định tiếng Trung."""

    target_lang: str = "vi"
    """Ngôn ngữ đích (ISO 639-1). Mặc định tiếng Việt."""

    whisper_model: str = "large-v3"
    """Tên model Whisper: tiny/base/small/medium/large-v2/large-v3."""

    whisper_language: Optional[str] = None
    """Gợi ý ngôn ngữ cho Whisper. None = auto-detect."""

    whisper_task: str = "transcribe"
    """'transcribe' hoặc 'translate' (translate sang tiếng Anh)."""

    whisper_compute_type: str = "float16"
    """Kiểu tính toán: 'float16', 'float32', 'int8' (để giảm VRAM)."""

    whisper_device: str = "auto"
    """'cuda', 'cpu', 'auto'. Auto sẽ dùng CUDA nếu có."""

    whisper_beam_size: int = Field(default=5, ge=1, le=20)
    """Beam search size. Cao hơn → chính xác hơn nhưng chậm hơn."""

    whisper_best_of: int = Field(default=5, ge=1, le=20)
    """Number of best candidates. Dùng khi temperature > 0."""

    gemini_model: str = "gemini-1.5-pro"
    """Model Gemini dùng để dịch."""

    translate_temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    """Temperature cho Gemini. Thấp hơn → ổn định hơn, ít sáng tạo hơn."""

    batch_size: int = Field(default=15, ge=1, le=100)
    """Số câu mỗi batch gửi Gemini. Quá lớn → context window overflow."""

    use_context_frame: bool = True
    """Đính kèm scene frame vào prompt Gemini để dịch có ngữ cảnh hình ảnh."""

    tts_engine: str = "edge-tts"
    """TTS engine: 'edge-tts' (mặc định, free), có thể mở rộng sau."""

    extract_audio: bool = True
    """Tách audio từ video khi import."""

    detect_scenes: bool = True
    """Phát hiện cảnh (scenes) từ video khi import."""

    detect_language: bool = True
    """Auto-detect ngôn ngữ video khi import."""


class PipelineStatus(BaseModel):
    """Trạng thái tổng thể của pipeline xử lý.

    Được update sau mỗi bước. UI dùng để hiển thị badge trên tab bar
    và để quyết định tab nào được enable.
    """

    import_: StepStatus = Field(default=StepStatus.WAITING, alias="import")
    """Bước Import (tách audio, detect scene)."""

    stt: StepStatus = StepStatus.WAITING
    """Bước Speech-to-Text (Whisper)."""

    translate: StepStatus = StepStatus.WAITING
    """Bước Translate (Gemini)."""

    review: StepStatus = StepStatus.WAITING
    """Bước Review (người dùng kiểm tra, không có processing nặng)."""

    voice: StepStatus = StepStatus.WAITING
    """Bước Voice/TTS (edge-tts)."""

    export: StepStatus = StepStatus.WAITING
    """Bước Export (ffmpeg render)."""

    model_config = {"populate_by_name": True}

    def is_step_unlocked(self, step: str) -> bool:
        """Kiểm tra xem một bước có được phép chạy không.

        Quy tắc unlock:
        - import: luôn được phép
        - stt: import phải COMPLETED
        - translate: stt phải COMPLETED
        - review: translate phải COMPLETED hoặc ERROR (cho phép review kể cả có lỗi)
        - voice: translate phải COMPLETED
        - export: voice phải COMPLETED
        """
        rules: dict[str, bool] = {
            "import": True,
            "stt": self.import_ == StepStatus.COMPLETED,
            "translate": self.stt == StepStatus.COMPLETED,
            "review": self.translate in (StepStatus.COMPLETED, StepStatus.ERROR),
            "voice": self.translate == StepStatus.COMPLETED,
            "export": self.voice == StepStatus.COMPLETED,
        }
        return rules.get(step, False)


class VideoMetadata(BaseModel):
    """Metadata của video nguồn, lấy từ ffprobe."""

    filename: str
    """Tên file video (không kèm đường dẫn)."""

    duration: float
    """Thời lượng video tính bằng giây."""

    width: int
    height: int
    fps: float

    video_codec: str = ""
    audio_codec: str = ""
    audio_channels: int = 2
    audio_sample_rate: int = 44100
    file_size_bytes: int = 0

    detected_language: Optional[str] = None
    """Ngôn ngữ được auto-detect, None nếu chưa detect."""

    detected_language_confidence: float = 0.0
    """Confidence của language detection (0.0–1.0)."""


class ProjectData(BaseModel):
    """Nguồn sự thật duy nhất — toàn bộ state của project được lưu trong đây.

    File `project.json` là serialized form của ProjectData.
    Không có state nào quan trọng tồn tại ngoài file này.
    """

    project_id: str
    """UUID v4 duy nhất cho project này."""

    project_name: str
    """Tên project do người dùng đặt."""

    video_path: str
    """Đường dẫn tuyệt đối tới video gốc (trong thư mục source/)."""

    project_dir: str
    """Đường dẫn tuyệt đối tới thư mục gốc của project."""

    created_at: datetime
    """Thời điểm tạo project."""

    updated_at: datetime
    """Thời điểm lưu project lần cuối."""

    settings: ProjectSettings = Field(default_factory=ProjectSettings)
    """Cài đặt xử lý."""

    pipeline_status: PipelineStatus = Field(default_factory=PipelineStatus)
    """Trạng thái pipeline."""

    segments: list[Segment] = Field(default_factory=list)
    """Danh sách tất cả segment đã nhận dạng."""

    speakers: dict[str, Speaker] = Field(default_factory=dict)
    """Map từ speaker_id ('A', 'B'...) sang Speaker object."""

    video_metadata: Optional[VideoMetadata] = None
    """Metadata video, được điền sau khi import."""

    @property
    def total_segments(self) -> int:
        """Tổng số segment trong project."""
        return len(self.segments)

    @property
    def translated_segments(self) -> int:
        """Số segment đã dịch thành công (TRANSLATED hoặc REVIEWED)."""
        return sum(
            1 for s in self.segments
            if s.status in (SegmentStatus.TRANSLATED, SegmentStatus.REVIEWED)
        )

    @property
    def error_segments(self) -> int:
        """Số segment có lỗi dịch."""
        return sum(1 for s in self.segments if s.status == SegmentStatus.ERROR)

    @property
    def pending_segments_count(self) -> int:
        """Số segment chưa dịch."""
        return sum(1 for s in self.segments if s.status == SegmentStatus.PENDING)

    @property
    def translation_progress(self) -> float:
        """Tỉ lệ dịch hoàn thành (0.0–1.0). 0 nếu chưa có segment."""
        if not self.segments:
            return 0.0
        return self.translated_segments / len(self.segments)

    def get_segments_to_translate(self) -> list[Segment]:
        """Trả về các segment cần dịch (resume/idempotency logic).

        Chỉ trả về segment có status != TRANSLATED và != REVIEWED.
        Segment đã REVIEWED không bị dịch lại trừ khi user yêu cầu.
        """
        return [
            s for s in self.segments
            if s.status not in (SegmentStatus.TRANSLATED, SegmentStatus.REVIEWED)
        ]

    def get_segments_for_tts(self) -> list[Segment]:
        """Trả về các segment cần sinh TTS (resume/idempotency logic).

        Chỉ trả về segment có text_vi và cần regenerate TTS
        (text_vi đã thay đổi hoặc chưa từng sinh TTS).
        """
        return [
            s for s in self.segments
            if s.text_vi is not None and s.needs_tts_regeneration
        ]

    model_config = {
        "json_encoders": {datetime: lambda v: v.isoformat()},
    }


# ---------------------------------------------------------------------------
# Batch processing types (dùng trong core/translator.py và workers)
# ---------------------------------------------------------------------------


class BatchResult(BaseModel):
    """Kết quả của một batch translate — thành công hoặc thất bại.

    TranslateWorker emit kết quả này qua signal để UI cập nhật.
    """

    batch_index: int
    """Index của batch (0-based)."""

    current: int
    """Số segment đã xử lý tính đến batch này."""

    total: int
    """Tổng số segment cần dịch."""

    segments: list[Segment] = Field(default_factory=list)
    """Danh sách segment đã dịch thành công trong batch này."""

    is_error: bool = False
    """True nếu batch này thất bại."""

    error_message: Optional[str] = None
    """Thông báo lỗi nếu is_error = True."""

    @property
    def progress_pct(self) -> int:
        """Tiến độ tính bằng % (0–100)."""
        if self.total == 0:
            return 0
        return min(100, int(self.current / self.total * 100))
