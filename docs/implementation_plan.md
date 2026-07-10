# MS DubStudio — Implementation Plan

## Tổng quan

Desktop PyQt6 app tự động dịch + lồng tiếng video Trung → Việt. Kiến trúc 3 lớp:
- `core/` — business logic thuần Python, không import PyQt6
- `workers/` — QThread bridge giữa UI và core
- `ui/` — PyQt6 views/widgets, không gọi `core/` trực tiếp

**Tài liệu tham chiếu:**
- [`docs/ms-dubstudio-design-doc.md`](ms-dubstudio-design-doc.md) — core logic, data model, error handling, batch strategy, testing
- [`docs/ms-dubstudio-ui-design-doc.md`](ms-dubstudio-ui-design-doc.md) — UI structure, overlay, widget design, view details

---

## Trạng thái tổng thể (2026-07-10)

| Phase | Nội dung | Trạng thái | Tests |
|-------|----------|-----------|-------|
| 1 | Core Foundation (models + project) | ✅ Done | 118/118 |
| 2 | Media Processing (media_io + stt + scene) | ✅ Done | 64/64 |
| 3 | Translator (Gemini batch + retry) | ✅ Done | 61/61 |
| 4 | Workers (QThread bridge) | ✅ Done | 14/14 |
| 5 | TTS + Sync + Render Core | ✅ Done | 54/54 |
| 6 | UI Layer | ⬜ Not started | — |
| 7 | Fixtures & Config | ✅ Done | — |

**Tổng pytest:** `292 passed` (verified 2026-07-10)

---

## Phase 1: Core Foundation ✅

### `msdubstudio/core/models.py`
Pydantic v2 models. Đã implement đầy đủ:
- `SegmentStatus`, `StepStatus` enums
- `Segment` — với `needs_tts_regeneration` property (hash-based idempotency), `confidence_level`
- `Speaker`, `ProjectSettings`, `PipelineStatus` (alias `import_` → `"import"`), `VideoMetadata`, `ProjectData`, `BatchResult`

### `msdubstudio/core/project.py`
- Factory: `Project.new()`, `Project.load()`
- Persistence: `save()` — write `project.json` (Pydantic JSON)
- Callbacks: `add_on_step_started/progress/completed/error`, `clear_callbacks()`
- Segment API: `update_segments_from_stt()`, `update_translated_segments()`, `update_segment_translation()`, `mark_segment_error()`, `mark_segment_reviewed()`, `update_voice_path()` (lưu `text_vi_hash`)
- Pipeline events: `on_import_*/on_stt_*/on_translate_*/on_voice_*/on_export_*`

---

## Phase 2: Media Processing Core ✅

### `msdubstudio/core/media_io.py`
- `get_video_metadata(path)` → `VideoMetadata` (qua ffprobe JSON)
- `extract_audio(video_path, output_path, sample_rate, channels)`
- `check_ffmpeg_available()`, `format_duration()`, `format_file_size()`
- Exceptions: `FFmpegNotFoundError`, `VideoFileError`, `AudioExtractionError`

### `msdubstudio/core/stt.py`
- `transcribe(audio_path, settings, progress_callback, cancel_check)` → `list[RawSegment]`
- Backend: faster-whisper (primary) → openai-whisper (fallback) → `WhisperModelNotFoundError`
- `_normalize_logprob(avg_logprob)` → confidence 0–1
- `assign_scene_frames(raw_segments, scenes)` — gán scene context

### `msdubstudio/core/scene.py`
- `SceneInfo` dataclass
- `detect_scenes(video_path, frames_dir, cancel_check, progress_callback)` → `list[SceneInfo]`
- `assign_scenes_to_segments(raw_segments, scenes)` → segments với `scene_frame` field
- Fallback: nếu PySceneDetect chưa cài → `SceneDetectNotInstalledError`

---

## Phase 3: Translator ✅

### `msdubstudio/core/translator.py`

**Exceptions:** `RetriableError`, `FatalApiError`, `ContentBlockedError`, `StructuredOutputError`

**Functions:**
- `call_with_retry(fn, max_retries=3, base_delay=1.0)` — exponential backoff
- `make_batches(segments, batch_size)` → `list[list[Segment]]`
- `build_translate_prompt(batch, source_lang, target_lang, scene_frame_path)` → Gemini multipart content (text + optional image)
- `translate_batch_with_gemini(batch, settings, api_key)` — Structured Output JSON Schema `[{id, text_vi}]`
- `translate_in_batches(segments, settings, api_key, cancel_check, max_concurrent_batches)` → `Generator[BatchResult]` — ThreadPoolExecutor, batch isolation, idempotency
- `refine_segment(segment, action, settings, api_key)` — Quick Actions (shorten/expand/formalize/simplify/fix_punctuation/improve_fluency)

---

## Phase 4: Workers ✅

### `msdubstudio/workers/base_worker.py`
`BaseWorker(QThread)` — `cancel()`, `is_cancelled` (threading.Event), `reset_cancel()`, `error = pyqtSignal(str)`

### `msdubstudio/workers/import_worker.py`
Signals: `started_signal()`, `progress(int, int)`, `step_log(str)`, `finished(object, list)`, `error(str)`
3 steps: metadata → audio extract → scene detect (scene lỗi = warning, không dừng)

### `msdubstudio/workers/stt_worker.py`
Signals: `started_signal()`, `progress(int, int)`, `step_log(str)`, `segment_done(dict)`, `finished(list)`, `error(str)`
Emit `segment_done` per-segment để UI update bảng ngay.

### `msdubstudio/workers/translate_worker.py`
Signals: `started_signal()`, `progress(int, int)`, `batch_done(list)`, `batch_error(int, str)`, `step_log(str)`, `finished_all()`, `error(str)`
Iterate Generator `translate_in_batches()`, emit per BatchResult.

### `msdubstudio/workers/tts_worker.py`
Signals: `started_signal()`, `progress(int, int)`, `step_log(str)`, `segment_done(int, str)`, `segment_error(int, str)`, `finished()`, `error(str)`
Filter `needs_tts_regeneration=True` (idempotency). `_get_voice_id()` với gender fallback.

### `msdubstudio/workers/render_worker.py`
Signals: `started_signal()`, `progress(int, int)`, `step_log(str)`, `finished(str)`, `error(str)`
Convert `Segment` → dict, count voiced segments, call `render_video()`.

---

## Phase 5: TTS + Sync + Render Core ✅

### `msdubstudio/core/tts.py`
- `synthesize(text, output_path, voice_id, rate, pitch, volume, engine)` — edge-tts via `asyncio.run()`
- `synthesize_segments(segments, voice_dir, get_voice_id, ..., cancel_check)` → `list[dict]` — idempotency ready
- `list_voices(engine, language)` — edge-tts live list + built-in fallback
- `format_rate(pct)`, `format_pitch(hz)` — format helpers
- Constants: `DEFAULT_MALE_VOICE = "vi-VN-NamMinhNeural"`, `DEFAULT_FEMALE_VOICE = "vi-VN-HoaiMyNeural"`

### `msdubstudio/core/sync.py`
- `compute_stretch_ratio(tts_duration, original_duration)` → float
- `needs_stretch(tts_duration, original_duration, tolerance=0.05)` → bool
- `stretch_audio(input, output, ratio, ffmpeg_bin, backend)` — auto: rubberband → ffmpeg atempo
- `stretch_audio_to_duration(input, output, target_duration_s)` — convenience wrapper
- `get_audio_duration(audio_path)` — via ffprobe
- `_build_atempo_filter(ratio)` — cascade filter chain cho ratio ngoài [0.5, 2.0]
- Constants: `MIN_STRETCH_RATIO=0.5`, `MAX_STRETCH_RATIO=2.0`, `SKIP_THRESHOLD=0.05`

### `msdubstudio/core/render.py`
- `ExportSettings` dataclass — codec, bitrate, CRF, resolution, fps, keep_bgm, bgm_volume, burn_subtitles
- `render_video(video_path, segments, voice_dir, export_settings, ...)` — 4-step pipeline:
  1. Silent audio timeline (ffmpeg `volume=0`)
  2. Overlay TTS segments (`adelay` + `amix`)
  3. Mix với BGM gốc (nếu `keep_bgm=True`)
  4. Mux video + audio (`-map 0:v -map 1:a`)
- Internal: `_run_ffmpeg()`, `_create_silent_audio()`, `_overlay_segments()`, `_mix_audio()`, `_mux_video_audio()`

---

## Phase 6: UI Layer ⬜ NEXT

**Thứ tự implement** (theo `ms-dubstudio-ui-design-doc.md` mục 8):

### 6.1 Foundation
- [ ] `msdubstudio/resources/styles.qss` — Fluent Design stylesheet: font Segoe UI, accent #0078D4, border-radius 6px, hover/pressed states
- [ ] `msdubstudio/ui/overlay.py` — `ProcessingOverlay(QWidget)`: full-screen semi-transparent, spinner animation, progress bar, elapsed time, Cancel button

### 6.2 Core Widgets (dùng lại ở nhiều views)
- [ ] `msdubstudio/ui/widgets/confidence_badge.py` — `ConfidenceBadge` + `ConfidenceDelegate(QStyledItemDelegate)`: ≥0.80 → `#107C10` | 0.50–0.79 → `#FFC83D` | <0.50 → `#D13438`
- [ ] `msdubstudio/ui/widgets/segment_table.py` — `SegmentTableModel(QAbstractTableModel)` + `SegmentTableView(QTableView)`: 500+ rows, search/filter, inline edit
- [ ] `msdubstudio/ui/widgets/ai_console.py` — log list, timestamp prefix, auto-scroll, Clear button
- [ ] `msdubstudio/ui/widgets/waveform_widget.py` — numpy PCM decode + QPainter render, playhead line, segment highlight, click-to-seek
- [ ] `msdubstudio/ui/widgets/speaker_avatar.py` — circular icon + speaker name label
- [ ] `msdubstudio/ui/widgets/video_player.py` — `QMediaPlayer` + `QVideoWidget` wrapper

### 6.3 Main Window
- [ ] `msdubstudio/ui/main_window.py` — `QMainWindow` + `QStackedWidget` nav (6 tabs + settings). Connect `Project` callbacks → show/hide overlay, enable/disable tabs, update tab badges (waiting/processing/completed/error)

### 6.4 Views
- [ ] `msdubstudio/ui/views/home_view.py` — Recent Projects list (thumbnail, name, date), New/Open Project buttons
- [ ] `msdubstudio/ui/views/import_view.py` — drag-drop zone, instant metadata display (sync ffprobe), Import Options checkboxes, Start Import → `ImportWorker`
- [ ] `msdubstudio/ui/views/stt_view.py` — WaveformWidget, SegmentTable (transcript), STTWorker
- [ ] `msdubstudio/ui/views/translate_view.py` — Translation Settings panel, SegmentTable (Chinese+Vietnamese+Status), AIConsole, Context Frame panel, error inline (Retry/Change Model/Skip), TranslateWorker
- [ ] `msdubstudio/ui/views/review_view.py` — 3-col layout: segment list | text editor (zh/vi + notes) + Quick Actions + char counter | Video/WaveformWidget
- [ ] `msdubstudio/ui/views/voice_view.py` — Speaker list, Voice Settings (engine/voice/speed/pitch/volume/emotion), Voice Preview, Speaker Mapping table, TTSWorker
- [ ] `msdubstudio/ui/views/export_view.py` — Export Settings, Video Preview, RenderWorker
- [ ] `msdubstudio/ui/views/settings_view.py` — sidebar: General / Whisper / Gemini / TTS / FFmpeg / Shortcuts / Advanced

### 6.5 Entry Point
- [ ] `msdubstudio/main.py` — `QApplication`, load `styles.qss`, create `MainWindow`, `sys.exit(app.exec())`
- [ ] `msdubstudio/config.py` — app-level settings: default project dir, API key storage (keyring hoặc config file)

---

## Verification Plan

### Automated Tests (đã pass)
```bash
pytest tests/ -q
# 292 passed in 1.15s
```

### Sau Phase 6 — Manual Verification Checklist
- [ ] Khởi chạy app: `python -m msdubstudio.main`
- [ ] Kéo thả video → metadata hiện đúng (duration, resolution, fps)
- [ ] STT xong → confidence badge tô đúng màu theo ngưỡng
- [ ] Translate: ngắt mạng → hiện lỗi + nút Retry đúng segment lỗi
- [ ] Sửa 1 câu Review → Translate All → log chỉ gửi lại segment đó (idempotency)
- [ ] Đóng app giữa Voice → mở lại → audio đã TTS trước không mất
- [ ] Export video dài → estimated time hiển thị

---

## Design Decisions & Notes

1. **`core/` không import PyQt6** — tái sử dụng headless, test không cần display
2. **Callbacks thay vì PyQt signal trong `core/project.py`** — plain Python callable, `MainWindow` wrap vào Qt signal ngoài
3. **Idempotency qua SHA-256 hash** — `Segment.text_vi_hash` lưu hash lần TTS cuối; `needs_tts_regeneration` so sánh để skip
4. **Batch isolation** — batch lỗi không chặn batch khác (ThreadPoolExecutor + `as_completed`)
5. **Cancel thread-safe** — `threading.Event` thay vì `bool` flag để tránh race condition
6. **sync.py atempo cascade** — ffmpeg atempo giới hạn [0.5, 2.0]; ratio ngoài khoảng → cascade nhiều filter
7. **ImportWorker**: scene detect lỗi = warning (emit `step_log`), không dừng import
8. **UI không gọi `core/` trực tiếp** — mọi thứ đi qua `project.py` hoặc worker tương ứng
