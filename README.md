# MS DubStudio

MS DubStudio is a desktop application for translating and dubbing Chinese-language video into Vietnamese. It runs a full pipeline — speech recognition, AI translation, voice synthesis, and video rendering — from a single graphical interface built with PyQt6.

---

## Requirements

**Operating system:** Windows 10/11, macOS 12+, or Linux (Ubuntu 22.04+)

**Python:** 3.11 or 3.12 (3.13 is supported but some optional GPU packages may lag behind)

**FFmpeg:** must be installed separately and available on `PATH`.
- Windows: download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH, or install via `winget install ffmpeg`
- macOS: `brew install ffmpeg`
- Linux: `sudo apt install ffmpeg`

**GPU (optional but recommended for STT):** CUDA 11.8+ with a compatible NVIDIA driver. Without a GPU, Whisper runs on CPU — still works, but is significantly slower on large models.

---

## Installation

**1. Clone the repository**

```bash
git clone https://github.com/yourname/ms-dubstudio.git
cd ms-dubstudio
```

**2. Create and activate a virtual environment**

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

**3. Install core dependencies**

```bash
pip install -e .
```

**4. (Optional) Install GPU support for faster Whisper**

```bash
pip install -e ".[gpu]"
```

This installs PyTorch with CUDA. If you already have a specific version of PyTorch installed for your CUDA toolkit, install it first before running this step.

**5. (Optional) Install development/test dependencies**

```bash
pip install -e ".[dev]"
```

---

## Configuration

### Gemini API key

MS DubStudio uses the Google Gemini API for translation. You need a free API key from [Google AI Studio](https://aistudio.google.com/app/apikey).

You can provide the key in two ways:

**Option A — environment variable (recommended):**
```bash
# Windows (PowerShell)
$env:GEMINI_API_KEY = "your-key-here"

# macOS / Linux
export GEMINI_API_KEY="your-key-here"
```

**Option B — inside the app:**
Open **Settings → Gemini (Translate)** and paste the key into the API Key field. The key is saved to `%APPDATA%\MS DubStudio\config.json` (Windows) or `~/.config/ms-dubstudio/config.json` (Linux) — never committed to the repository.

---

## Running the App

```bash
python -m msdubstudio.main
```

The window opens at 1280 × 800. All project data is saved to `~/Documents/MS DubStudio Projects/` by default (configurable in Settings → General).

---

## Basic Workflow

**1. New Project**
On the Home screen, click "New Project", select your source video file (MP4, MKV, MOV, AVI), and enter a project name.

**2. Import**
The Import screen shows a video preview and detected metadata. Choose whether to extract audio, detect scene cuts, and auto-detect source language, then click "Start Import". This extracts the audio track and splits the video into scenes.

**3. STT (Speech-to-Text)**
Select the Whisper model size and source language (default: Chinese, large-v3 model). Click "Start STT". Segments appear in the table as they are recognized. On GPU, large-v3 takes roughly 5–15 minutes for a 30-minute video.

**4. Translate**
Select the Gemini model and target language (default: Vietnamese). Click "Translate All". The AI Console on the right shows live batch progress. Segments with errors can be retried individually or skipped.

**5. Review**
The Review screen shows the original Chinese and the translated Vietnamese side by side. Click any segment to edit the translation directly. Quick Actions (Improve Fluency, Shorten, Expand, Formalize, Simplify) call Gemini to refine the selected segment in one click. A video preview lets you watch the segment while editing.

**6. Voice**
Map each detected speaker to a TTS voice. Choose voice engine (Edge TTS by default), voice name, speed, pitch, and volume per speaker. Click "Generate TTS" to synthesize all segments. A mini waveform previews each generated clip.

**7. Export**
Choose output format (MP4 H.264 by default), resolution, frame rate, and audio codec. Options include burning subtitles into the video, keeping the original background music, and normalizing audio to −14 LUFS. Click "Start Export", choose a save location, and the render pipeline produces the final video via FFmpeg.

---

## Running Tests

```bash
pytest tests/ -v
```

All 292 tests run without requiring real API keys, ffmpeg, or GPU — external calls are mocked. Integration tests that need a real environment are excluded by default and can be enabled with `--run-integration`.

---

## Project Data and Privacy

- **Projects** are stored in `~/Documents/MS DubStudio Projects/` — outside the repository.
- **App config and logs** are stored in the OS-standard app data directory (`%APPDATA%\MS DubStudio\` on Windows) — outside the repository.
- **Whisper model weights** are cached by `faster-whisper` in `~/.cache/huggingface/hub/` — outside the repository.
- The Gemini API key is never written to any file inside the repository.

---

## Documentation

Detailed design documents are in [`docs/`](docs/):

- [`ms-dubstudio-design-doc.md`](docs/ms-dubstudio-design-doc.md) — architecture and core layer design
- [`ms-dubstudio-ui-design-doc.md`](docs/ms-dubstudio-ui-design-doc.md) — UI/UX design specifications and mockups
- [`implementation_plan.md`](docs/implementation_plan.md) — phased implementation plan
- [`task.md`](docs/task.md) — completed work per phase
