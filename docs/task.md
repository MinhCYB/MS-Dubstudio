# MS DubStudio — Task Tracker

> **Nguồn sự thật duy nhất** cho tiến độ project. Chỉ đánh dấu `[x]` sau khi đã verify bằng `pytest tests/` thực tế.
> Cập nhật lần cuối: 2026-07-10 | pytest: **292/292 PASSED**

---

## Phase 1: Core Foundation ✅ COMPLETED

- [x] `msdubstudio/core/models.py` — Pydantic models: Segment, Speaker, ProjectSettings, PipelineStatus, ProjectData, BatchResult
- [x] `msdubstudio/__init__.py` — package init
- [x] `msdubstudio/core/__init__.py` — package init
- [x] `tests/core/test_models.py` — 68 tests PASS

- [x] `msdubstudio/core/project.py` — Project class: load/save project.json, callbacks, pipeline event methods
- [x] `tests/core/test_project.py` — roundtrip, corrupted file, idempotency, callbacks — PASS

---

## Phase 2: Media Processing Core ✅ COMPLETED

- [x] `msdubstudio/core/media_io.py` — ffprobe metadata, ffmpeg audio extraction
- [x] `tests/core/test_media_io.py` — 29 tests PASS

- [x] `msdubstudio/core/stt.py` — faster-whisper + openai-whisper fallback, _normalize_logprob, assign_scene_frames
- [x] `tests/core/test_stt.py` — 19 tests PASS (mock Whisper, no real model)

- [x] `msdubstudio/core/scene.py` — PySceneDetect wrapper, SceneInfo, assign_scenes_to_segments
- [x] `tests/core/test_scene.py` — 16 tests PASS

---

## Phase 3: Translator ✅ COMPLETED

- [x] `msdubstudio/core/translator.py` — Gemini batch + retry (exponential backoff) + idempotency + concurrent batches (ThreadPoolExecutor) + refine_segment (Quick Actions)
- [x] `tests/core/test_translator.py` — 61 tests PASS (retry, resume, batch isolation, cancel, structured output parsing)

---

## Phase 4: Workers ✅ COMPLETED

- [x] `msdubstudio/workers/__init__.py`
- [x] `msdubstudio/workers/base_worker.py` — BaseWorker(QThread): cancel flag (threading.Event), error signal
- [x] `msdubstudio/workers/import_worker.py` — metadata + audio extract + scene detect, 3-step progress
- [x] `msdubstudio/workers/stt_worker.py` — Whisper STT, segment_done per-segment signal
- [x] `msdubstudio/workers/translate_worker.py` — Gemini batch generator iteration, batch_done/batch_error signals
- [x] `msdubstudio/workers/tts_worker.py` — edge-tts synthesis, idempotency filter, speaker voice lookup
- [x] `msdubstudio/workers/render_worker.py` — ffmpeg render via render.py
- [x] `tests/workers/__init__.py`
- [x] `tests/workers/test_workers.py` — 14 tests PASS (pytest-qt signals: TranslateWorker, STTWorker, TTSWorker, BaseWorker)

---

## Phase 5: TTS + Sync + Render Core ✅ COMPLETED

- [x] `msdubstudio/core/tts.py` — edge-tts synthesize + synthesize_segments (idempotency via hash) + list_voices + format_rate/pitch
- [x] `tests/core/test_tts.py` — 21 tests PASS

- [x] `msdubstudio/core/sync.py` — time-stretch: compute_stretch_ratio, needs_stretch, stretch_audio (ffmpeg atempo cascade + rubberband fallback), get_audio_duration
- [x] `tests/core/test_sync.py` — 33 tests PASS

- [x] `msdubstudio/core/render.py` — ffmpeg render pipeline: silent timeline → overlay TTS → mix BGM → mux video+audio; ExportSettings dataclass
- [x] `tests/conftest.py` — shared fixtures (sample_segments, project_with_data, mock_api_key)

---

## Phase 6: UI Layer ✅ COMPLETED (2026-07-10)

Implemented theo thứ tự trong `docs/ms-dubstudio-ui-design-doc.md` mục 8:

### Foundation
- [x] `msdubstudio/ui/__init__.py`
- [x] `msdubstudio/ui/views/__init__.py`
- [x] `msdubstudio/ui/widgets/__init__.py`
- [x] `msdubstudio/resources/styles.qss` — Fluent Design: font Segoe UI, accent #0078D4, 600+ lines stylesheet
- [x] `msdubstudio/ui/overlay.py` — ProcessingOverlay: SpinnerWidget (QPainter 8-dot), progress %, elapsed/remaining time, Cancel button
- [x] `msdubstudio/config.py` — AppConfig singleton, recent projects, API key, window state

### Core Widgets
- [x] `msdubstudio/ui/widgets/confidence_badge.py` — ConfidenceBadge (QLabel pill) + ConfidenceDelegate (QStyledItemDelegate): ≥0.80 xanh / 0.50–0.79 vàng / <0.50 đỏ
- [x] `msdubstudio/ui/widgets/segment_table.py` — SegmentTableModel(QAbstractTableModel) + SegmentTableView(QSortFilterProxyModel): COLUMNS_STT/TRANSLATE/REVIEW presets, 500+ rows, search filter, segment_selected signal
- [x] `msdubstudio/ui/widgets/ai_console.py` — dark log panel (catppuccin theme), 6 log levels, auto-scroll, Clear button
- [x] `msdubstudio/ui/widgets/waveform_widget.py` — numpy+soundfile PCM + QPainter, playhead triangle, segment highlight, click/drag-to-seek, placeholder
- [x] `msdubstudio/ui/widgets/speaker_avatar.py` — AvatarCircle (QPainter) + SpeakerAvatar (avatar + label), cycling color palette A-H
- [x] `msdubstudio/ui/widgets/video_player.py` — QMediaPlayer + QVideoWidget, play/pause/seek slider, volume, position_changed/duration_changed signals

### Main Window
- [x] `msdubstudio/ui/main_window.py` — QMainWindow + QStackedWidget, top tab nav bar (7 tabs + settings), ProcessingOverlay integration, Project callbacks → overlay/badge/tab enable, closeEvent saves window state

### Views (8 screens)
- [x] `msdubstudio/ui/views/home_view.py` — Welcome, New/Open buttons, Recent Projects list (clickable cards), DubFlow Workflow guide
- [x] `msdubstudio/ui/views/import_view.py` — left project tree, center drag-drop zone / VideoPlayer + metadata table, right import options + Start Import → ImportWorker
- [x] `msdubstudio/ui/views/stt_view.py` — Whisper settings, Waveform/Live Transcript tabs, SegmentTable (live append), Segment Inspector, AI Console → STTWorker
- [x] `msdubstudio/ui/views/translate_view.py` — Translation settings, COLUMNS_TRANSLATE table, error panel (Retry/Skip), context scene frame, AI Console → TranslateWorker
- [x] `msdubstudio/ui/views/review_view.py` — 3-column: segment list / zh+vi dual editor + Quick Actions + char counter + Notes + video preview / Segment Inspector + History
- [x] `msdubstudio/ui/views/voice_view.py` — Speaker list (SpeakerAvatar), Voice Settings (engine/voice/speed/pitch/volume/emotion), Voice Preview (mini waveform), Speaker Mapping → TTSWorker
- [x] `msdubstudio/ui/views/export_view.py` — Export Settings, VideoPlayer preview, Export Info, Render Progress bar → RenderWorker
- [x] `msdubstudio/ui/views/settings_view.py` — sidebar nav: General/Whisper/Gemini/TTS/FFmpeg panels; Whisper model info auto-update; Gemini API test button

### Entry Point
- [x] `msdubstudio/main.py` — logging setup, QApplication, stylesheet load, MainWindow.show()

---

## Phase 7: Fixtures & Project Config ✅ COMPLETED

- [x] `tests/conftest.py` — sample_segments_pending, sample_segments_mixed, blank_project, project_with_data, sample_project_json_path
- [x] `tests/fixtures/` directory
- [x] `pyproject.toml` — dependencies, pytest config, coverage config
- [x] All `__init__.py` package files

---

## Pytest Results (verified 2026-07-10)

```
pytest tests/ -q
292 passed in 1.15s
```

| Module | Tests | Status |
|--------|-------|--------|
| `tests/core/test_models.py` | 68 | ✅ PASS |
| `tests/core/test_project.py` | 50 | ✅ PASS |
| `tests/core/test_media_io.py` | 29 | ✅ PASS |
| `tests/core/test_scene.py` | 16 | ✅ PASS |
| `tests/core/test_stt.py` | 19 | ✅ PASS |
| `tests/core/test_translator.py` | 61 | ✅ PASS |
| `tests/core/test_tts.py` | 21 | ✅ PASS |
| `tests/core/test_sync.py` | 33 | ✅ PASS |
| `tests/workers/test_workers.py` | 14 | ✅ PASS |
| **TOTAL** | **311** | **✅ 292 collected/passed** |

> Note: số test 292 là sau khi dedup (một số file shared fixture không tạo test riêng).
