"""
core/project.py — Project class: điều phối, lưu/load project.json

Đây là "trung gian" giữa UI/Worker layer và core logic. Project:
- Giữ ProjectData (nguồn sự thật duy nhất)
- Load/save project.json
- Cung cấp hooks callback để UI lắng nghe sự kiện (step_started, etc.)
- Tạo và start các Worker qua factory method

Không import bất cứ thứ gì từ PyQt6.
Callbacks là plain Python callables — MainWindow sẽ kết nối chúng
vào Qt signals bên ngoài.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from pydantic import ValidationError

from msdubstudio.core.models import (
    PipelineStatus,
    ProjectData,
    ProjectSettings,
    Segment,
    SegmentStatus,
    Speaker,
    StepStatus,
    VideoMetadata,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ProjectError(Exception):
    """Lỗi liên quan đến project (load/save, state không hợp lệ)."""


class ProjectFileNotFoundError(ProjectError):
    """project.json không tồn tại."""


class ProjectFileCorruptedError(ProjectError):
    """project.json tồn tại nhưng không parse được."""


class ProjectStateError(ProjectError):
    """Hành động không hợp lệ với state hiện tại của project."""


# ---------------------------------------------------------------------------
# Project class
# ---------------------------------------------------------------------------


class Project:
    """Quản lý vòng đời của một project dịch thuật.

    Chịu trách nhiệm:
    1. Load/save project.json (serialize/deserialize ProjectData)
    2. Tạo thư mục dự án (source/, audio/, frames/, voice/, output/, logs/)
    3. Thông báo sự kiện cho UI qua callback (step_started/progress/completed/error)
    4. Cung cấp helper methods để Workers gọi sau khi hoàn thành một bước

    Không phụ thuộc PyQt6. Callbacks là plain Python callables.
    """

    # Tên file project chuẩn — không thay đổi
    PROJECT_FILENAME = "project.json"

    # Thư mục con chuẩn trong mỗi project
    SUBDIRS = ["source", "audio", "frames", "voice", "output", "logs"]

    def __init__(self, data: ProjectData):
        self._data = data

        # Callback lists — UI đăng ký vào đây
        self._on_step_started: list[Callable[[str], None]] = []
        self._on_step_progress: list[Callable[[str, int, int, float], None]] = []
        self._on_step_completed: list[Callable[[str], None]] = []
        self._on_step_error: list[Callable[[str, str], None]] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def data(self) -> ProjectData:
        """Truy cập ProjectData (nguồn sự thật duy nhất)."""
        return self._data

    @property
    def project_dir(self) -> Path:
        return Path(self._data.project_dir)

    @property
    def project_file(self) -> Path:
        return self.project_dir / self.PROJECT_FILENAME

    @property
    def audio_dir(self) -> Path:
        return self.project_dir / "audio"

    @property
    def frames_dir(self) -> Path:
        return self.project_dir / "frames"

    @property
    def voice_dir(self) -> Path:
        return self.project_dir / "voice"

    @property
    def output_dir(self) -> Path:
        return self.project_dir / "output"

    @property
    def logs_dir(self) -> Path:
        return self.project_dir / "logs"

    @property
    def source_dir(self) -> Path:
        return self.project_dir / "source"

    @property
    def audio_path(self) -> Path:
        return self.audio_dir / "audio.wav"

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def new(
        cls,
        name: str,
        video_path: str,
        projects_base_dir: str,
        settings: Optional[ProjectSettings] = None,
    ) -> "Project":
        """Tạo project mới, tạo cấu trúc thư mục, lưu project.json lần đầu.

        Args:
            name: Tên project do người dùng đặt.
            video_path: Đường dẫn tuyệt đối tới video nguồn.
            projects_base_dir: Thư mục gốc chứa tất cả projects
                               (ví dụ: ~/MS DubStudio Projects).
            settings: ProjectSettings tuỳ chỉnh, dùng default nếu None.

        Returns:
            Project instance đã được tạo và lưu.

        Raises:
            ProjectError: Nếu không tạo được thư mục.
        """
        project_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        project_dir = Path(projects_base_dir) / _sanitize_dirname(name)

        # Tạo thư mục — raise nếu thất bại (lỗi nghiêm trọng tầng 3)
        try:
            project_dir.mkdir(parents=True, exist_ok=True)
            for subdir in cls.SUBDIRS:
                (project_dir / subdir).mkdir(exist_ok=True)
        except OSError as e:
            raise ProjectError(f"Không thể tạo thư mục project: {e}") from e

        data = ProjectData(
            project_id=project_id,
            project_name=name,
            video_path=video_path,
            project_dir=str(project_dir),
            created_at=now,
            updated_at=now,
            settings=settings or ProjectSettings(),
        )

        project = cls(data)
        project.save()
        logger.info(f"Đã tạo project mới: {name} ({project_id})")
        return project

    @classmethod
    def load(cls, project_dir: str) -> "Project":
        """Load project từ thư mục có sẵn.

        Args:
            project_dir: Đường dẫn tới thư mục project.

        Returns:
            Project instance đã load.

        Raises:
            ProjectFileNotFoundError: project.json không tồn tại.
            ProjectFileCorruptedError: project.json bị hỏng.
        """
        project_file = Path(project_dir) / cls.PROJECT_FILENAME

        if not project_file.exists():
            raise ProjectFileNotFoundError(
                f"Không tìm thấy project.json tại: {project_file}"
            )

        try:
            raw = project_file.read_text(encoding="utf-8")
        except OSError as e:
            raise ProjectFileCorruptedError(
                f"Không đọc được project.json: {e}"
            ) from e

        try:
            data = ProjectData.model_validate_json(raw)
        except (ValidationError, json.JSONDecodeError, ValueError) as e:
            raise ProjectFileCorruptedError(
                f"project.json bị hỏng hoặc sai định dạng: {e}"
            ) from e

        # Update project_dir nếu project được di chuyển sang thư mục khác
        if data.project_dir != str(Path(project_dir)):
            data = data.model_copy(update={"project_dir": str(Path(project_dir))})

        logger.info(f"Đã load project: {data.project_name} ({data.project_id})")
        return cls(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Ghi ProjectData hiện tại vào project.json.

        Cập nhật updated_at trước khi ghi.

        Raises:
            ProjectError: Nếu không ghi được file.
        """
        self._data = self._data.model_copy(
            update={"updated_at": datetime.now(timezone.utc)}
        )

        try:
            self.project_file.write_text(
                self._data.model_dump_json(indent=2, by_alias=True),
                encoding="utf-8",
            )
        except OSError as e:
            raise ProjectError(f"Không thể lưu project.json: {e}") from e

        logger.debug(f"Đã lưu project: {self._data.project_name}")

    # ------------------------------------------------------------------
    # Callback registration (UI layer đăng ký vào đây)
    # ------------------------------------------------------------------

    def add_on_step_started(self, fn: Callable[[str], None]) -> None:
        """Đăng ký callback: gọi khi một bước bắt đầu xử lý."""
        self._on_step_started.append(fn)

    def add_on_step_progress(
        self, fn: Callable[[str, int, int, float], None]
    ) -> None:
        """Đăng ký callback: gọi khi có tiến độ (step, current, total, elapsed_s)."""
        self._on_step_progress.append(fn)

    def add_on_step_completed(self, fn: Callable[[str], None]) -> None:
        """Đăng ký callback: gọi khi một bước hoàn thành."""
        self._on_step_completed.append(fn)

    def add_on_step_error(self, fn: Callable[[str, str], None]) -> None:
        """Đăng ký callback: gọi khi một bước gặp lỗi (step, error_message)."""
        self._on_step_error.append(fn)

    def clear_callbacks(self) -> None:
        """Xóa tất cả callbacks — dùng khi đóng project."""
        self._on_step_started.clear()
        self._on_step_progress.clear()
        self._on_step_completed.clear()
        self._on_step_error.clear()

    # ------------------------------------------------------------------
    # Internal event emitters (gọi bởi Worker callbacks)
    # ------------------------------------------------------------------

    def _emit_step_started(self, step: str) -> None:
        self._set_step_status(step, StepStatus.PROCESSING)
        self.save()
        for fn in self._on_step_started:
            fn(step)

    def _emit_step_progress(
        self, step: str, current: int, total: int, elapsed: float
    ) -> None:
        for fn in self._on_step_progress:
            fn(step, current, total, elapsed)

    def _emit_step_completed(self, step: str) -> None:
        self._set_step_status(step, StepStatus.COMPLETED)
        self.save()
        for fn in self._on_step_completed:
            fn(step)

    def _emit_step_error(self, step: str, message: str) -> None:
        self._set_step_status(step, StepStatus.ERROR)
        self.save()
        for fn in self._on_step_error:
            fn(step, message)

    def _set_step_status(self, step: str, status: StepStatus) -> None:
        """Cập nhật trạng thái một bước trong PipelineStatus."""
        current = self._data.pipeline_status.model_dump(by_alias=True)
        # PipelineStatus dùng alias "import" cho field import_
        field_key = "import" if step == "import" else step
        if field_key in current:
            current[field_key] = status.value
            self._data = self._data.model_copy(
                update={"pipeline_status": PipelineStatus.model_validate(current)}
            )

    # ------------------------------------------------------------------
    # Segment update API (gọi bởi Workers sau khi hoàn thành xử lý)
    # ------------------------------------------------------------------

    def update_segments_from_stt(
        self,
        raw_segments: list[dict],
        speakers: Optional[dict[str, Speaker]] = None,
    ) -> None:
        """Cập nhật segments từ kết quả Whisper STT.

        Args:
            raw_segments: List dict từ Whisper, mỗi dict có keys:
                          id, start, end, text, speaker, confidence, scene_frame.
            speakers: Dict speaker mới (nếu detect speaker), None để giữ nguyên.
        """
        segments = []
        for i, raw in enumerate(raw_segments):
            seg = Segment(
                id=raw.get("id", i + 1),
                start=float(raw["start"]),
                end=float(raw["end"]),
                speaker=raw.get("speaker", "A"),
                text_zh=raw.get("text", "").strip(),
                confidence=float(raw.get("confidence", 0.0)),
                scene_frame=raw.get("scene_frame"),
                status=SegmentStatus.PENDING,
            )
            segments.append(seg)

        update: dict = {"segments": segments}
        if speakers is not None:
            update["speakers"] = speakers
        self._data = self._data.model_copy(update=update)

    def update_translated_segments(self, translated: list[Segment]) -> None:
        """Cập nhật bản dịch cho các segment đã dịch.

        Merge bằng segment.id — chỉ update segment có trong `translated`,
        giữ nguyên các segment khác.
        """
        translated_map = {s.id: s for s in translated}
        updated_segments = []
        for seg in self._data.segments:
            if seg.id in translated_map:
                updated_segments.append(translated_map[seg.id])
            else:
                updated_segments.append(seg)
        self._data = self._data.model_copy(update={"segments": updated_segments})

    def update_segment_translation(
        self,
        segment_id: int,
        text_vi: str,
        status: SegmentStatus = SegmentStatus.TRANSLATED,
    ) -> None:
        """Cập nhật bản dịch của một segment cụ thể (dùng ở Review tab).

        Args:
            segment_id: ID của segment cần update.
            text_vi: Văn bản tiếng Việt mới.
            status: SegmentStatus sau khi update (mặc định TRANSLATED).
        """
        now = datetime.now(timezone.utc)
        updated = []
        for seg in self._data.segments:
            if seg.id == segment_id:
                seg = seg.model_copy(update={
                    "text_vi": text_vi,
                    "status": status,
                    "updated_at": now,
                    "error_message": None,
                })
            updated.append(seg)
        self._data = self._data.model_copy(update={"segments": updated})

    def mark_segment_error(self, segment_id: int, error_message: str) -> None:
        """Đánh dấu một segment là ERROR với thông báo lỗi."""
        updated = []
        for seg in self._data.segments:
            if seg.id == segment_id:
                seg = seg.model_copy(update={
                    "status": SegmentStatus.ERROR,
                    "error_message": error_message,
                })
            updated.append(seg)
        self._data = self._data.model_copy(update={"segments": updated})

    def mark_segment_reviewed(self, segment_id: int) -> None:
        """Đánh dấu segment đã được review và approve."""
        updated = []
        for seg in self._data.segments:
            if seg.id == segment_id:
                seg = seg.model_copy(update={"status": SegmentStatus.REVIEWED})
            updated.append(seg)
        self._data = self._data.model_copy(update={"segments": updated})

    def update_voice_path(self, segment_id: int, voice_path: str) -> None:
        """Cập nhật voice_path và text_vi_hash sau khi sinh TTS thành công.

        Lưu hash của text_vi tại thời điểm TTS để detect thay đổi sau này.
        """
        updated = []
        for seg in self._data.segments:
            if seg.id == segment_id:
                seg = seg.model_copy(update={
                    "voice_path": voice_path,
                    "text_vi_hash": seg.compute_text_vi_hash(),
                })
            updated.append(seg)
        self._data = self._data.model_copy(update={"segments": updated})

    def update_video_metadata(self, metadata: VideoMetadata) -> None:
        """Cập nhật metadata video sau khi import."""
        self._data = self._data.model_copy(update={"video_metadata": metadata})

    def update_settings(self, settings: ProjectSettings) -> None:
        """Cập nhật settings của project."""
        self._data = self._data.model_copy(update={"settings": settings})

    def update_speaker(self, speaker: Speaker) -> None:
        """Thêm hoặc cập nhật thông tin speaker."""
        speakers = dict(self._data.speakers)
        speakers[speaker.id] = speaker
        self._data = self._data.model_copy(update={"speakers": speakers})

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_segments_to_translate(self) -> list[Segment]:
        """Danh sách segment cần dịch (chưa TRANSLATED và chưa REVIEWED)."""
        return self._data.get_segments_to_translate()

    def get_segments_for_tts(self) -> list[Segment]:
        """Danh sách segment cần sinh TTS (text_vi thay đổi hoặc chưa TTS)."""
        return self._data.get_segments_for_tts()

    def is_step_unlocked(self, step: str) -> bool:
        """Kiểm tra xem bước này có thể chạy không (dependencies đã xong)."""
        return self._data.pipeline_status.is_step_unlocked(step)

    # ------------------------------------------------------------------
    # Convenience: pipeline event methods (gọi từ Worker callbacks)
    # ------------------------------------------------------------------

    def on_import_started(self) -> None:
        self._emit_step_started("import")

    def on_import_progress(self, current: int, total: int, elapsed: float) -> None:
        self._emit_step_progress("import", current, total, elapsed)

    def on_import_completed(self, metadata: VideoMetadata) -> None:
        self.update_video_metadata(metadata)
        self._emit_step_completed("import")

    def on_import_error(self, message: str) -> None:
        self._emit_step_error("import", message)

    def on_stt_started(self) -> None:
        self._emit_step_started("stt")

    def on_stt_progress(self, current: int, total: int, elapsed: float) -> None:
        self._emit_step_progress("stt", current, total, elapsed)

    def on_stt_completed(self, raw_segments: list[dict]) -> None:
        self.update_segments_from_stt(raw_segments)
        self._emit_step_completed("stt")

    def on_stt_error(self, message: str) -> None:
        self._emit_step_error("stt", message)

    def on_translate_started(self) -> None:
        self._emit_step_started("translate")

    def on_translate_progress(self, current: int, total: int, elapsed: float) -> None:
        self._emit_step_progress("translate", current, total, elapsed)

    def on_translate_batch_done(self, segments: list[Segment]) -> None:
        """Gọi sau mỗi batch translate xong — cập nhật + save ngay."""
        self.update_translated_segments(segments)
        self.save()

    def on_translate_completed(self) -> None:
        self._emit_step_completed("translate")

    def on_translate_error(self, message: str) -> None:
        """Lỗi toàn cục translate (không phải lỗi từng segment)."""
        self._emit_step_error("translate", message)

    def on_voice_started(self) -> None:
        self._emit_step_started("voice")

    def on_voice_progress(self, current: int, total: int, elapsed: float) -> None:
        self._emit_step_progress("voice", current, total, elapsed)

    def on_voice_segment_done(self, segment_id: int, voice_path: str) -> None:
        self.update_voice_path(segment_id, voice_path)
        self.save()

    def on_voice_completed(self) -> None:
        self._emit_step_completed("voice")

    def on_voice_error(self, message: str) -> None:
        self._emit_step_error("voice", message)

    def on_export_started(self) -> None:
        self._emit_step_started("export")

    def on_export_progress(self, current: int, total: int, elapsed: float) -> None:
        self._emit_step_progress("export", current, total, elapsed)

    def on_export_completed(self) -> None:
        self._emit_step_completed("export")

    def on_export_error(self, message: str) -> None:
        self._emit_step_error("export", message)

    def __repr__(self) -> str:
        return (
            f"Project(name={self._data.project_name!r}, "
            f"id={self._data.project_id!r}, "
            f"segments={self._data.total_segments})"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize_dirname(name: str) -> str:
    """Chuyển tên project thành tên thư mục an toàn.

    - Thay thế ký tự đặc biệt không hợp lệ trong tên thư mục
    - Giữ nguyên ký tự Unicode (tiếng Việt/Trung OK)
    - Giới hạn 100 ký tự
    """
    # Ký tự không được phép trong tên thư mục Windows/Unix
    invalid_chars = r'\/:*?"<>|'
    result = name
    for ch in invalid_chars:
        result = result.replace(ch, "_")
    result = result.strip(". ")
    return result[:100] or "Untitled Project"
