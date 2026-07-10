# MS DubStudio — Bản thiết kế hệ thống (Design Doc cho Claude CLI)

## 0. Tổng quan

**Tên sản phẩm:** MS DubStudio
**Loại:** Desktop app (PyQt6), chạy local trên máy người dùng
**Mục đích:** Tự động hóa quy trình dịch + lồng tiếng video Trung → Việt cho nội dung người dùng có quyền sử dụng hợp pháp (video tự sản xuất, licensed, hoặc có thỏa thuận phân phối).

**Nguyên tắc thiết kế cốt lõi:**
- Xử lý **1 video / 1 project tại một thời điểm** — không hỗ trợ batch nhiều video song song, không có job queue.
- **Block UI khi đang xử lý** (Processing Overlay che toàn màn hình, disable các tab khác) — không chạy nền để user làm việc khác trong lúc chờ.
- Chỉ hỗ trợ **Gemini API** cho bước dịch trong bản MVP. Không thiết kế abstraction đa provider.
- `core/` (business logic) hoàn toàn **không phụ thuộc PyQt6** — tái sử dụng được nếu sau này đổi UI framework.
- Idempotent theo segment: sửa 1 câu không cần chạy lại toàn bộ pipeline từ đầu.

---

## 1. Cấu trúc source code

```
msdubstudio/
├── main.py                    # Entry point, khởi tạo QApplication
├── config.py                  # App-level settings (API key, default paths)
│
├── ui/                         # PyQt6 — chỉ lo hiển thị + bắt sự kiện
│   ├── main_window.py          # Cửa sổ chính, quản lý chuyển tab
│   ├── views/
│   │   ├── home_view.py
│   │   ├── import_view.py
│   │   ├── stt_view.py
│   │   ├── translate_view.py
│   │   ├── review_view.py
│   │   ├── voice_view.py
│   │   └── export_view.py
│   ├── widgets/                 # Component tái sử dụng (waveform, segment table...)
│   └── overlay.py               # Processing overlay dùng chung cho STT/Translate/Voice/Export
│
├── core/                        # Logic thuần Python, KHÔNG import PyQt6
│   ├── models.py                 # Segment, Speaker, ProjectData (Pydantic)
│   ├── project.py                 # Class Project — điều phối, lưu/load project.json
│   ├── media_io.py                # ffmpeg wrapper: tách audio, lấy metadata
│   ├── stt.py                     # Whisper wrapper
│   ├── scene.py                   # PySceneDetect wrapper
│   ├── translator.py              # Gemini API + batch + retry
│   ├── tts.py                     # TTS engine wrapper
│   ├── sync.py                    # Time-stretch
│   └── render.py                  # Ghép final video
│
├── workers/                     # QThread — cầu nối giữa ui/ và core/
│   ├── stt_worker.py
│   ├── translate_worker.py
│   ├── tts_worker.py
│   └── render_worker.py
│
└── resources/
    ├── icons/
    └── styles.qss                # Stylesheet (Fluent Design, theme sáng trắng-xanh lam)
```

**Nguyên tắc bắt buộc:**
- `ui/` gọi `workers/`. `workers/` gọi `core/`. `ui/` KHÔNG được gọi thẳng `core/`.
- `core/` không import bất cứ thứ gì từ PyQt6.
- Mọi tác vụ nặng (STT, gọi API, TTS, render) PHẢI chạy trong `QThread`, không chạy trên main/GUI thread.

---

## 2. Cấu trúc thư mục dữ liệu (mỗi project của người dùng)

```
~/MS DubStudio Projects/
└── <Tên Project>/
    ├── project.json           # Nguồn sự thật duy nhất — mọi state ở đây
    ├── source/
    │   └── video.mp4            # Video gốc, không đụng vào
    ├── audio/
    │   └── audio.wav             # Audio tách ra từ video
    ├── frames/
    │   ├── scene_001.jpg
    │   └── ...
    ├── voice/
    │   ├── segment_001.wav       # Audio TTS từng câu (trước khi ghép)
    │   └── ...
    ├── output/
    │   └── video_dubbed.mp4     # Kết quả cuối
    └── logs/
        └── session.log           # Log lỗi để debug
```

Không tách `stt.json` / `translation.json` / `speakers.json` riêng — gộp hết vào **1 file `project.json`** để tránh nhiều file bị lệch trạng thái.

---

## 3. Data Model (dùng Pydantic)

```python
from enum import Enum
from pydantic import BaseModel
from datetime import datetime

class SegmentStatus(str, Enum):
    PENDING = "pending"
    TRANSLATED = "translated"
    ERROR = "error"
    REVIEWED = "reviewed"

class StepStatus(str, Enum):
    WAITING = "waiting"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"

class Segment(BaseModel):
    id: int
    start: float                    # giây
    end: float
    speaker: str                    # "A", "B", "C"...
    text_zh: str
    text_vi: str | None = None
    confidence: float               # 0.0 - 1.0, từ Whisper
    scene_frame: str | None = None  # path tới frame đại diện
    status: SegmentStatus = SegmentStatus.PENDING
    error_message: str | None = None
    voice_path: str | None = None   # path audio TTS đã sinh, nếu có
    notes: str | None = None        # ghi chú người dùng

class Speaker(BaseModel):
    id: str                         # "A", "B", "C"
    gender: str
    voice_id: str                   # map sang voice TTS cụ thể
    emotion: str = "neutral"

class ProjectSettings(BaseModel):
    source_lang: str = "zh"
    target_lang: str = "vi"
    whisper_model: str = "large-v3"
    gemini_model: str = "gemini-1.5-pro"
    tts_engine: str = "edge-tts"
    use_context_frame: bool = True
    translate_temperature: float = 0.3
    batch_size: int = 15            # số câu/batch khi gửi Gemini

class PipelineStatus(BaseModel):
    import_: StepStatus = StepStatus.WAITING
    stt: StepStatus = StepStatus.WAITING
    translate: StepStatus = StepStatus.WAITING
    review: StepStatus = StepStatus.WAITING
    voice: StepStatus = StepStatus.WAITING
    export: StepStatus = StepStatus.WAITING

class ProjectData(BaseModel):
    project_id: str
    project_name: str
    video_path: str
    created_at: datetime
    updated_at: datetime
    settings: ProjectSettings = ProjectSettings()
    pipeline_status: PipelineStatus = PipelineStatus()
    segments: list[Segment] = []
    speakers: dict[str, Speaker] = {}
```

---

## 4. Luồng điều phối (Orchestration)

```
UI Layer (PyQt6)
     │  gọi qua project.py, không gọi core/ trực tiếp
     ▼
Worker Layer (QThread)
     │  chạy nền, emit signal khi có tiến độ/kết quả
     ▼
Core Layer (business logic thuần)
     │  gọi service cụ thể
     ▼
External (Whisper local / Gemini API / TTS engine / ffmpeg)
```

**Khuôn mẫu chuẩn cho mỗi bước xử lý** (STT / Translate / TTS / Render):

1. UI: user bấm nút → gọi `project.start_stt()` (hoặc bước tương ứng)
2. `project.py`: tạo Worker tương ứng (`STTWorker(...)`), `.start()`
3. Worker chạy hàm trong `core/` ở background thread
4. Worker emit signal `progress(current, total)` → UI update % trên Processing Overlay
5. Worker xong → emit signal `result(data)` → `project.py` nhận, update `segments`, gọi `save()` ghi lại `project.json`
6. `project.py` emit `step_completed(step_name)` → UI tắt overlay, enable lại các tab khác
7. Nếu lỗi: Worker emit `error(message)` thay vì `result` → `project.py` set status = ERROR, UI hiện thông báo + hành động khắc phục (Retry/Change Model/Skip)

**Yêu cầu UI khi đang xử lý bất kỳ bước nào ở trên:**
- Hiện Processing Overlay full màn hình với: tên bước, % tiến độ, elapsed/remaining time, nút Cancel
- Disable toàn bộ tab khác (Import/STT/Translate/Review/Voice/Export) cho tới khi bước hiện tại xong hoặc bị Cancel

---

## 5. Xử lý lỗi — 3 tầng

**Tầng 1 — Retry tự động (bên trong `core/translator.py`, `core/tts.py`)**
Lỗi tạm thời (HTTP 429 rate limit, timeout mạng, lỗi 5xx) → tự động retry với exponential backoff (1s → 2s → 4s), tối đa 3 lần. User không cần thấy gì nếu retry thành công.

```python
def call_with_retry(fn, max_retries=3, base_delay=1):
    for attempt in range(max_retries):
        try:
            return fn()
        except RetriableError:
            if attempt == max_retries - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))
```

**Tầng 2 — Lỗi cần người dùng quyết định**
Sau khi retry tự động thất bại, hoặc lỗi rõ ràng không tự sửa được (API key sai, model không tồn tại, content bị block, quota hết) → dừng lại tại segment/batch đó, set `segment.status = ERROR`, `segment.error_message = "..."`. UI hiện rõ lỗi kèm 3 hành động: **Retry / Change Model / Skip**. Các segment khác không bị chặn — batch tiếp theo vẫn tiếp tục chạy.

**Tầng 3 — Lỗi nghiêm trọng (dừng toàn bộ pipeline)**
File video hỏng, ffmpeg không tồn tại/không chạy được, hết dung lượng ổ đĩa → không retry, dừng ngay, ghi log đầy đủ vào `logs/session.log`, hiện thông báo lỗi rõ ràng cho user thay vì để app treo im lặng.

---

## 6. Chiến lược batch cho Gemini Translate

- Chia `segments` thành các batch theo `settings.batch_size` (mặc định 15 câu/batch), giữ các câu liên tiếp trong cùng batch để giữ mạch hội thoại.
- Mỗi batch, nếu `use_context_frame = True`, đính kèm `scene_frame` liên quan của batch đó.
- Gửi request tới Gemini với **Structured Output** (JSON Schema) để nhận về đúng format `{id, text_vi}` cho từng segment trong batch — tránh phải tự parse text tự do.
- Giới hạn số batch chạy đồng thời tối đa 2-3 (không tuần tự 100%, cũng không bắn hết cùng lúc) để cân bằng tốc độ và tránh rate limit.
- Batch lỗi không chặn các batch khác — đánh dấu lỗi rồi tiếp tục batch kế tiếp.

**JSON Schema đề xuất cho response Gemini:**
```json
{
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "id": {"type": "integer"},
      "text_vi": {"type": "string"}
    },
    "required": ["id", "text_vi"]
  }
}
```

---

## 7. Resume / Idempotency

Nguyên tắc: **không xử lý lại những gì đã xong**, trừ khi user chủ động yêu cầu.

- Khi bấm "Translate All" lần 2 (sau khi đã sửa vài câu ở Review): chỉ gửi lại các segment có `status != TRANSLATED` hoặc bị người dùng đánh dấu "dịch lại" — không gửi lại toàn bộ.
- Khi bấm "Generate TTS": chỉ sinh lại audio cho segment có `text_vi` thay đổi kể từ lần TTS gần nhất (so sánh qua field theo dõi thay đổi, ví dụ lưu `updated_at` cấp segment hoặc hash nội dung).
- Khi Export: luôn dùng dữ liệu mới nhất trong `project.json`, không cần chạy lại STT/Translate/TTS nếu các bước đó đã hoàn tất và không có thay đổi.

---

## 8. Workflow người dùng (end-to-end)

1. **Home** → "New Project" hoặc "Open Project"
2. **New Project**: kéo thả video → tự tách audio + lấy metadata → chọn ngôn ngữ nguồn/đích, Whisper model → "Start Import" → tạo folder project + `project.json`
3. **Tab STT**: "Run Transcribe" → [Processing Overlay] → xem transcript + confidence, sửa tay câu sai nếu cần
4. **Tab Translate**: chỉnh settings (temperature, use_context_frame) → "Translate All" (chủ động bấm, không tự động) → [Processing Overlay] → nếu lỗi 429/etc → Retry/Change Model/Skip tại đúng chỗ lỗi
5. **Tab Review**: sửa câu tiếng Việt, dùng Quick Actions (Shorten/Formalize/...), đánh dấu segment cần chú ý (confidence thấp)
6. **Tab Voice**: map Speaker → giọng đọc, test thử, "Generate TTS" → [Processing Overlay]
7. **Tab Export**: chọn định dạng/giữ nhạc nền/burn sub → "Start Export" → [Processing Overlay] → ffmpeg render
8. Quay lại Home: project status "Completed", có thể mở lại để sửa/export version khác mà không cần chạy lại từ đầu (nhờ mục 7 — Resume/Idempotency)

---

## 9. Đóng gói & phân phối

- Dùng **PyInstaller** với `--onedir` (không dùng `--onefile`, tránh giải nén chậm mỗi lần mở)
- Cân nhắc bundle CPU-only build cho Whisper/torch để giảm size, hoặc để user tự cài GPU support riêng nếu cần
- Xác nhận sớm license PyQt6 (GPL) nếu có ý định đóng gói closed-source để chia sẻ/bán — cân nhắc PySide6 (LGPL) nếu cần thoáng hơn về sau

---

## 10. Testing Strategy

**Nguyên tắc:** vì `core/` không phụ thuộc PyQt6, toàn bộ business logic test được bằng `pytest` thuần, không cần mở UI. Đây là lợi ích trực tiếp của việc tách kiến trúc ở mục 1.

### 10.1 Cấu trúc thư mục test

```
tests/
├── core/
│   ├── test_models.py           # Validate Pydantic models, edge case (thiếu field, sai type)
│   ├── test_project.py           # Load/save project.json, roundtrip, file lỗi
│   ├── test_translator.py        # Batch logic, retry, Structured Output parsing
│   ├── test_stt.py                # Wrapper Whisper (mock output)
│   ├── test_scene.py              # Wrapper PySceneDetect (mock output)
│   ├── test_tts.py                 # Wrapper TTS (mock audio output)
│   └── test_sync.py                 # Time-stretch tính toán đúng tỉ lệ
├── workers/
│   └── test_translate_worker.py   # Dùng pytest-qt để test signal/slot
├── fixtures/
│   ├── sample_video.mp4            # Video mẫu 10-15s, 3-5 câu, 2 speaker
│   ├── sample_project.json          # Project mẫu ở nhiều trạng thái (mới, đang dịch, lỗi, hoàn tất)
│   └── mock_gemini_responses.json    # Response giả lập cho các case: thành công, 429, lỗi content block
└── conftest.py                      # Fixture dùng chung (tmp_path project, mock API client...)
```

### 10.2 Nguyên tắc mock

- **Không bao giờ gọi Gemini API thật trong automated test** — dùng `unittest.mock.patch` hoặc `responses`/`respx` để giả lập response, tránh tốn tiền + tránh test không ổn định do rate limit thật.
- Test thật với Gemini (để verify prompt/schema hoạt động đúng ngoài đời) chỉ chạy thủ công, giới hạn số lần, dùng `fixtures/sample_video.mp4` (video ngắn để giảm token).

### 10.3 Các nhóm test bắt buộc

**a. Retry & error handling**
```python
def test_translate_retry_on_rate_limit(mock_gemini_429_then_success):
    # lần đầu 429, lần 2 thành công → verify retry đúng số lần, backoff đúng
    ...

def test_batch_error_does_not_block_other_batches():
    # batch 2 lỗi, batch 1 và 3 vẫn phải trả kết quả bình thường
    ...
```

**b. Resume / Idempotency (nhóm dễ bug nhất, ưu tiên cao)**
```python
def test_translate_all_skips_already_translated():
    segments = [
        Segment(id=1, status=TRANSLATED, text_vi="đã dịch"),
        Segment(id=2, status=PENDING),
    ]
    result = translate_in_batches(segments, ...)
    # assert chỉ segment id=2 được gửi request, id=1 không bị gọi lại
```

**c. Project persistence**
```python
def test_project_save_load_roundtrip(tmp_path):
    project = Project.new(name="test", video_path="fake.mp4")
    project.save(tmp_path / "project.json")
    loaded = Project.load(tmp_path / "project.json")
    assert loaded.data == project.data

def test_project_load_handles_corrupted_file(tmp_path):
    # file json lỗi cú pháp → raise lỗi rõ ràng, KHÔNG crash im lặng
    ...
```

**d. Worker signal (dùng `pytest-qt`)**
```python
def test_translate_worker_emits_progress(qtbot, mock_translator):
    worker = TranslateWorker(segments, settings, api_key="fake")
    with qtbot.waitSignal(worker.finished_all, timeout=2000):
        worker.start()
    # assert progress đã emit đủ số lần, batch_done chứa đúng data
```

### 10.4 Checklist test thủ công (trước mỗi lần release, không cần automated UI test)

- [ ] Import video → metadata hiện đúng, checkbox options hoạt động
- [ ] STT xong → confidence badge tô đúng màu theo ngưỡng (≥0.80 xanh / 0.50-0.79 vàng / <0.50 đỏ)
- [ ] Translate: ngắt mạng giữa chừng → hiện lỗi + nút Retry, bấm Retry chạy lại đúng segment lỗi
- [ ] Sửa 1 câu ở Review → bấm "Translate All" lại → verify (qua AI Console log) chỉ segment vừa sửa được gửi lại
- [ ] Đóng app giữa chừng lúc đang ở bước Voice → mở lại project → audio đã TTS trước đó không bị mất
- [ ] Export video dài thử → thời gian ước tính hiển thị có sát thực tế không

### 10.5 Chi phí test có gọi API thật

- CI/automated test: luôn mock, không gọi API thật
- Test thật (verify prompt/schema với Gemini) chỉ chạy thủ công, dùng `fixtures/sample_video.mp4` (video ngắn), giới hạn tần suất chạy trong ngày

---

## 11. Việc cần Claude CLI làm theo thứ tự ưu tiên

1. Dựng `core/models.py` (Pydantic models ở mục 3) trước — mọi thứ khác phụ thuộc vào đây. Viết kèm `tests/core/test_models.py`.
2. Dựng `core/project.py` (load/save `project.json`, các hàm điều phối `start_stt()`, `start_translate()`, v.v.). Viết kèm `tests/core/test_project.py`.
3. Dựng `core/media_io.py` + `core/stt.py` (tách audio, chạy Whisper). Viết kèm test với mock output Whisper.
4. Dựng `core/scene.py` (PySceneDetect). Viết kèm test với mock output.
5. Dựng `core/translator.py` (Gemini batch + retry theo mục 5, 6). Viết kèm `tests/core/test_translator.py` — ưu tiên test retry và resume/idempotency vì đây là logic dễ bug nhất.
6. Dựng `workers/` tương ứng để nối `core/` với UI qua QThread + Signal. Viết kèm test bằng `pytest-qt`.
7. Dựng `ui/main_window.py` + các `views/` theo đúng 6 tab, tái sử dụng `overlay.py` cho Processing Overlay
8. Cuối cùng: `core/tts.py`, `core/sync.py`, `core/render.py`, `ui/views/voice_view.py`, `ui/views/export_view.py`

**Nguyên tắc chung:** mỗi module `core/` nên có test đi kèm ngay khi viết xong, không dồn hết viết test ở cuối — dễ phát hiện lỗi sớm và không bị "nợ test" chồng chất.
