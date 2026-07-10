# MS DubStudio — Bản thiết kế giao diện (UI Design Doc cho Claude CLI)

> Đọc kèm với `ms-dubstudio-design-doc.md` (core logic). File này chỉ mô tả phần `ui/` và `workers/`.

## 0. Định hướng phong cách

- **Fluent Design** (giống Windows 11) — bo góc nhẹ, shadow mềm, hiệu ứng hover/press rõ ràng
- **Theme sáng**: nền trắng/xám nhạt, accent xanh lam
- **Font**: Segoe UI (Windows) / San Francisco hoặc hệ thống mặc định trên macOS — fallback về font hệ thống nếu không có sẵn
- **Icon**: bộ icon dạng outline nhất quán (Fluent Icons hoặc tương đương), không trộn nhiều style icon khác nhau
- Giao diện phải có cảm giác **native desktop app**, không mang dáng dấp web app (tránh flat-design kiểu Material quá đơn giản, tránh border-radius quá lớn kiểu mobile)

---

## 1. Cấu trúc thư mục `ui/`

```
ui/
├── main_window.py           # QMainWindow — khung chính, quản lý chuyển tab, chứa sidebar
├── views/
│   ├── home_view.py          # Recent Projects, New/Open Project
│   ├── import_view.py        # Kéo thả video, metadata, import options
│   ├── stt_view.py           # Whisper settings, waveform, transcript segments
│   ├── translate_view.py     # Translation settings, bảng dịch, AI console, context frame
│   ├── review_view.py        # Editor 2 cột, quick actions, segment inspector
│   ├── voice_view.py         # Speaker mapping, voice settings, preview
│   ├── export_view.py        # Export settings, preview, render progress
│   └── settings_view.py      # General / Whisper / Gemini / TTS / FFmpeg settings
├── widgets/
│   ├── waveform_widget.py     # Vẽ waveform + playhead, click để seek
│   ├── segment_table.py        # Bảng segment tái sử dụng (STT/Translate/Review đều dùng)
│   ├── confidence_badge.py     # Badge màu theo mức confidence (xanh/vàng/đỏ)
│   ├── speaker_avatar.py        # Icon tròn + tên speaker
│   ├── ai_console.py             # Log panel dùng chung (Translate, có thể tái dùng ở Render)
│   └── video_player.py            # Video preview widget (dùng QMediaPlayer)
├── overlay.py                # ProcessingOverlay — dùng chung cho STT/Translate/Voice/Export
└── styles.qss                 # Stylesheet toàn app
```

**Nguyên tắc:** `views/` không tự gọi `core/`. Mọi thao tác nặng đi qua `project.py` (được gọi từ `main_window.py` hoặc trực tiếp trong view thông qua 1 reference `self.project` được truyền vào lúc khởi tạo).

---

## 2. `main_window.py` — khung điều phối

Trách nhiệm:
- Giữ đối tượng `Project` hiện tại (từ `core/project.py`)
- Quản lý chuyển đổi giữa các tab (dùng `QStackedWidget` hoặc `QTabWidget` tùy phong cách — mockup cho thấy dạng thanh tab ngang trên cùng, nên ưu tiên `QTabWidget` custom style hoặc `QStackedWidget` + thanh nav tự vẽ để kiểm soát style tốt hơn)
- Lắng nghe signal từ `Project` (`step_started`, `step_progress`, `step_completed`, `step_error`) để:
  - Hiện/ẩn `ProcessingOverlay`
  - Enable/disable các tab khác khi đang xử lý
  - Cập nhật badge trạng thái trên từng tab (waiting/processing/completed/error)

```python
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project: Project | None = None
        self._setup_tabs()
        self._setup_overlay()

    def open_project(self, path: str):
        self.project = Project.load(path)
        self.project.step_started.connect(self._on_step_started)
        self.project.step_progress.connect(self._on_step_progress)
        self.project.step_completed.connect(self._on_step_completed)
        self.project.step_error.connect(self._on_step_error)
        self._refresh_all_views()

    def _on_step_started(self, step_name: str):
        self._set_tabs_enabled(False, except_current=False)
        self.overlay.show_for(step_name)

    def _on_step_completed(self, step_name: str):
        self.overlay.hide()
        self._set_tabs_enabled(True)
        self._refresh_all_views()
```

---

## 3. `overlay.py` — Processing Overlay (widget dùng chung, quan trọng nhất)

Đây là widget xuất hiện đè lên toàn bộ cửa sổ khi STT/Translate/Voice/Export đang chạy. Theo mockup: card ở giữa/góc, có icon động (spinner hoặc icon theo bước), % progress bar, elapsed/remaining time, nút Cancel.

**Yêu cầu chức năng:**
- `show_for(step_name: str)` — hiện overlay với label đúng bước (VD: "Running Speech to Text (Whisper)")
- `update_progress(current: int, total: int, elapsed: float)` — cập nhật % và thời gian
- `hide()` — ẩn overlay, trả lại quyền thao tác
- Nút **Cancel** → gọi `worker.cancel()` (worker tương ứng phải hỗ trợ cờ `_is_cancelled` như đã thiết kế ở core doc)
- Overlay phải chặn click-through xuống các widget bên dưới (dùng `QWidget` full-size, đặt `raise_()` lên trên cùng, hoặc dùng `QGraphicsOpacityEffect` cho nền mờ + `setEnabled(False)` cho các widget khác)

```python
class ProcessingOverlay(QWidget):
    cancelled = pyqtSignal()

    def show_for(self, step_name: str):
        self.label.setText(step_name)
        self.progress_bar.setValue(0)
        self.show()
        self.raise_()

    def update_progress(self, current: int, total: int, elapsed: float):
        pct = int(current / total * 100) if total else 0
        self.progress_bar.setValue(pct)
        self.time_label.setText(f"Elapsed {format_time(elapsed)}")
```

---

## 4. `workers/` — cầu nối UI ↔ core

Mỗi worker là 1 `QThread` mỏng, chỉ gọi hàm `core/` tương ứng và emit signal. **Không chứa business logic** — logic thật nằm trong `core/`.

```python
# workers/translate_worker.py
class TranslateWorker(QThread):
    progress = pyqtSignal(int, int)          # current, total
    batch_done = pyqtSignal(list)             # list[Segment] đã dịch
    batch_error = pyqtSignal(int, str)        # batch_index, error_message
    finished_all = pyqtSignal()

    def __init__(self, segments, settings, api_key):
        super().__init__()
        self.segments = segments
        self.settings = settings
        self.api_key = api_key
        self._is_cancelled = False

    def run(self):
        from core.translator import translate_in_batches
        for result in translate_in_batches(
            self.segments, self.settings, self.api_key,
            cancel_check=lambda: self._is_cancelled
        ):
            if result.is_error:
                self.batch_error.emit(result.batch_index, result.error_message)
            else:
                self.batch_done.emit(result.segments)
            self.progress.emit(result.current, result.total)
        self.finished_all.emit()

    def cancel(self):
        self._is_cancelled = True
```

Mỗi view kết nối worker signal → cập nhật UI trực tiếp (VD: `translate_view.py` nhận `batch_done` → cập nhật bảng, nhận `batch_error` → highlight đỏ dòng lỗi + hiện Retry/Change Model/Skip).

---

## 5. Chi tiết từng view

### 5.1 `home_view.py`
- Danh sách Recent Projects (thumbnail, tên, ngày cập nhật) — click để mở
- Nút "New Project" / "Open Project"
- Không có logic xử lý gì ở đây, chỉ điều hướng

### 5.2 `import_view.py`
- Khu kéo thả video (`QWidget` với `dragEnterEvent`/`dropEvent`) hoặc nút chọn file
- Hiện metadata ngay khi chọn xong (dùng `core/media_io.py` lấy thông tin, KHÔNG cần Worker vì đây là tác vụ đọc metadata rất nhanh, có thể chạy sync)
- Checkbox Import Options: Extract Audio / Detect Scenes / Detect Language
- Nút "Start Import" → **đây mới cần Worker** (tách audio + scene detect có thể mất vài giây tới vài chục giây tùy video dài)

### 5.3 `stt_view.py`
- `WaveformWidget` hiển thị audio, đồng bộ playhead với `VideoPlayer`
- Bảng `SegmentTable` hiện transcript: #, Start, End, Speaker, Confidence (dùng `ConfidenceBadge`), Text
- Click vào 1 dòng → waveform scroll/highlight tới đúng đoạn, video preview nhảy tới đó
- Nút "Start STT" → mở `STTWorker`, hiện overlay

### 5.4 `translate_view.py`
- Panel trái: Translation Settings (Provider, Source/Target Lang, Temperature, checkbox Use Context)
- Bảng chính: #, Start, End, Chinese, Vietnamese, Confidence, Status, Actions
- Dòng lỗi (status = ERROR) tô nền đỏ nhạt, click vào hiện panel "Segment #X Error" bên dưới với 3 nút Retry/Change Model/Skip
- Panel phải: `AIConsole` (log theo thời gian thực) + Context Frame (ảnh scene liên quan tới dòng đang chọn)
- Nút "Translate All" — chỉ enable nếu STT đã completed; chỉ gửi các segment `status != TRANSLATED` (theo nguyên tắc resume ở core doc)

### 5.5 `review_view.py`
- Layout 3 cột: danh sách segment bên trái | text editor (Chinese/Vietnamese + Notes) ở giữa | Video/Audio Preview + waveform bên phải
- Quick Actions (Fix Punctuation, Improve Fluency, Shorten, Expand, Formalize, Simplify) — mỗi action gọi 1 lần Gemini riêng cho câu đang chọn (không phải Worker riêng, có thể tái dùng `translator.py` với 1 hàm `refine_segment()` chạy trong thread ngắn hoặc đồng bộ nếu đủ nhanh)
- Character counter dưới ô Vietnamese Translation (VD "30 / 200")
- Segment Inspector hiện Grammar/Fluency/Consistency nếu có (optional, có thể để version sau)

### 5.6 `voice_view.py`
- Danh sách Speakers bên trái (Add Speaker)
- Voice Settings cho speaker đang chọn: Voice Engine, Voice, Speed, Pitch, Volume, Emotion
- Voice Preview: nghe thử câu hiện tại
- Speaker Mapping: bảng map Speaker → voice_id cụ thể
- Nút "Generate TTS" → mở `TTSWorker`, chỉ generate lại segment có thay đổi (resume logic)

### 5.7 `export_view.py`
- Export Settings: Output path, Format, Resolution, Frame rate, Audio codec, checkbox Burn subtitles / Keep background music / Normalize audio
- Preview video
- Export Progress: %, elapsed, estimated time, frame counter
- Nút "Start Export" → mở `RenderWorker`

### 5.8 `settings_view.py`
- Sidebar con: General / Whisper / Gemini (Translate) / TTS / FFmpeg (Render) / Shortcuts / Advanced
- Whisper: Model, Language, Task, Compute Type, Device, Beam Size, Best Of + panel Model Info (size, VRAM, speed, accuracy) + nút "Run Benchmark"
- Gemini: API key, model, temperature mặc định, batch size mặc định

---

## 6. Widget dùng chung — chi tiết cần lưu ý

### `waveform_widget.py`
- Vẽ waveform từ file audio (dùng `numpy` + đọc PCM data, hoặc thư viện có sẵn) lên `QPainter`/`QGraphicsView`
- Playhead là 1 đường dọc, đồng bộ với vị trí phát của `VideoPlayer`
- Click vào waveform → seek video tới đúng vị trí
- Highlight vùng segment đang chọn (tô màu nhạt lên đoạn tương ứng)

### `segment_table.py`
- Dùng `QTableView` + custom `QAbstractTableModel` (không dùng `QTableWidget` thô, vì dữ liệu 500+ dòng cần model hiệu năng tốt hơn)
- Cột Confidence dùng `ConfidenceBadge` (delegate riêng) để tô màu theo ngưỡng: ≥0.80 xanh (High), 0.50–0.79 vàng (Medium), <0.50 đỏ (Low — cần sửa)
- Hỗ trợ search/filter theo text

### `ai_console.py`
- List log dạng `timestamp - message`, auto-scroll xuống dòng mới nhất
- Có nút "Clear"
- Chỉ log cho project/video hiện tại (không multi-job, theo đúng quyết định đã chốt)

---

## 7. Trạng thái tab (Tab Status Indicator)

Mỗi tab trên thanh nav nên có 1 badge nhỏ phản ánh `pipeline_status` tương ứng:
- ⚪ Waiting — chưa chạy
- 🔵 Processing — đang chạy (đồng thời toàn bộ tab khác bị disable)
- ✅ Completed — xong
- 🔴 Error — có lỗi cần xử lý (VD segment nào đó translate failed)

Cập nhật badge này thông qua signal `step_completed`/`step_error` từ `Project`, không tự suy luận riêng trong từng view.

---

## 8. Việc cần Claude CLI làm theo thứ tự (phần UI)

1. `styles.qss` — định nghĩa màu sắc, font, style chung trước (để mọi widget sau này áp dụng nhất quán)
2. `overlay.py` — vì mọi view đều cần dùng
3. `widgets/segment_table.py`, `widgets/confidence_badge.py`, `widgets/waveform_widget.py` — 3 widget lõi dùng lại nhiều nơi
4. `main_window.py` — khung chính, nav, kết nối signal với `Project`
5. `views/home_view.py`, `views/import_view.py` — 2 màn đơn giản nhất, làm trước để có luồng end-to-end sớm
6. `views/stt_view.py`, `views/translate_view.py` — 2 màn phức tạp nhất, cần `waveform_widget` và `ai_console` đã xong trước đó
7. `views/review_view.py`, `views/voice_view.py`, `views/export_view.py`
8. `views/settings_view.py` — làm cuối vì không chặn luồng chính
