"""
ui/views/settings_view.py — Settings Screen

Theo mockup settings.png:
- Sidebar con: General / Whisper (STT) / Gemini (Translate) / TTS (Voice) / FFmpeg (Render) / Shortcuts / Advanced
- Panel phải: các field settings tương ứng
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from msdubstudio.ui.main_window import MainWindow

from msdubstudio.config import AppConfig


class _SectionTitle(QLabel):
    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self.setStyleSheet(
            "font-size: 15px; font-weight: 700; color: #1C1C1C; margin-bottom: 8px;"
        )


class _GeneralSection(QWidget):
    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(16)
        layout.addWidget(_SectionTitle("General"))

        grp = QGroupBox("Paths")
        form = QFormLayout(grp)
        self._projects_dir = QLineEdit(str(cfg.projects_dir))
        btn_browse = QPushButton("Browse…")
        btn_browse.setFixedWidth(72)
        btn_browse.clicked.connect(self._on_browse)
        row = QHBoxLayout()
        row.addWidget(self._projects_dir)
        row.addWidget(btn_browse)
        form.addRow("Projects Directory:", row)
        layout.addWidget(grp)

        grp2 = QGroupBox("Appearance")
        form2 = QFormLayout(grp2)
        self._cmb_theme = QComboBox()
        self._cmb_theme.addItems(["Light", "Dark", "System"])
        form2.addRow("Theme:", self._cmb_theme)
        layout.addWidget(grp2)

        btn_save = QPushButton("Save Settings")
        btn_save.setFixedWidth(120)
        btn_save.setStyleSheet(
            "background: #0078D4; color: white; border-radius: 6px; border: none; padding: 6px 16px;"
        )
        btn_save.clicked.connect(lambda: cfg.save())
        layout.addWidget(btn_save)

    def _on_browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select Projects Directory")
        if d:
            self._projects_dir.setText(d)
            AppConfig.get().projects_dir = d


class _WhisperSection(QWidget):
    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(16)
        layout.addWidget(_SectionTitle("Whisper Settings (STT)"))

        main_row = QHBoxLayout()

        # Left: settings form
        grp = QGroupBox("Whisper Settings")
        form = QFormLayout(grp)
        form.setSpacing(10)

        self._cmb_model = QComboBox()
        self._cmb_model.addItems(["tiny", "base", "small", "medium", "large-v2", "large-v3"])
        self._cmb_model.setCurrentText(cfg.last_whisper_model)

        self._cmb_lang = QComboBox()
        self._cmb_lang.addItems(["Chinese", "Japanese", "Korean", "English", "Auto"])
        self._cmb_lang.setCurrentText("Chinese")

        self._chk_auto_lang = QCheckBox("Auto Detect Language")
        self._chk_auto_lang.setChecked(True)

        self._cmb_task = QComboBox()
        self._cmb_task.addItems(["Transcribe", "Translate"])

        self._cmb_device = QComboBox()
        self._cmb_device.addItems(["auto", "cpu", "cuda", "mps"])

        sl_beam = QSlider(Qt.Orientation.Horizontal)
        sl_beam.setRange(1, 10)
        sl_beam.setValue(5)
        lbl_beam = QLabel("5")
        sl_beam.valueChanged.connect(lambda v: lbl_beam.setText(str(v)))
        beam_row = QHBoxLayout()
        beam_row.addWidget(sl_beam)
        beam_row.addWidget(lbl_beam)

        sl_bestof = QSlider(Qt.Orientation.Horizontal)
        sl_bestof.setRange(1, 10)
        sl_bestof.setValue(5)
        lbl_bestof = QLabel("5")
        sl_bestof.valueChanged.connect(lambda v: lbl_bestof.setText(str(v)))
        bestof_row = QHBoxLayout()
        bestof_row.addWidget(sl_bestof)
        bestof_row.addWidget(lbl_bestof)

        form.addRow("Model:", self._cmb_model)
        form.addRow("Language:", self._cmb_lang)
        form.addRow(self._chk_auto_lang)
        form.addRow("Task:", self._cmb_task)
        form.addRow("Device:", self._cmb_device)
        form.addRow("Beam Size:", beam_row)
        form.addRow("Best Of:", bestof_row)
        main_row.addWidget(grp)

        # Right: Model Info
        grp_info = QGroupBox("Model Info")
        info_form = QFormLayout(grp_info)
        self._lbl_size  = QLabel("1.55 GB")
        self._lbl_vram  = QLabel("~3.2 GB")
        self._lbl_speed = QLabel("Fast")
        self._lbl_acc   = QLabel("High")
        info_form.addRow("Size:", self._lbl_size)
        info_form.addRow("VRAM Usage:", self._lbl_vram)
        info_form.addRow("Speed:", self._lbl_speed)
        info_form.addRow("Accuracy:", self._lbl_acc)

        btn_bench = QPushButton("Run Benchmark")
        btn_bench.setStyleSheet(
            "background: #0078D4; color: white; border-radius: 6px; border: none; padding: 6px;"
        )
        info_layout = QVBoxLayout(grp_info)
        info_layout.addLayout(info_form)
        info_layout.addWidget(btn_bench)
        main_row.addWidget(grp_info)

        layout.addLayout(main_row)

        self._cmb_model.currentTextChanged.connect(self._update_model_info)

    def _update_model_info(self, model: str) -> None:
        info = {
            "tiny":     ("39 MB",  "~0.5 GB", "Very Fast", "Low"),
            "base":     ("74 MB",  "~1 GB",   "Fast",      "Medium"),
            "small":    ("244 MB", "~2 GB",   "Fast",      "Medium"),
            "medium":   ("769 MB", "~5 GB",   "Medium",    "High"),
            "large-v2": ("1.55 GB","~10 GB",  "Slow",      "Very High"),
            "large-v3": ("1.55 GB","~10 GB",  "Slow",      "Very High"),
        }
        size, vram, speed, acc = info.get(model, ("?", "?", "?", "?"))
        self._lbl_size.setText(size)
        self._lbl_vram.setText(vram)
        self._lbl_speed.setText(speed)
        self._lbl_acc.setText(acc)
        AppConfig.get().last_whisper_model = model


class _GeminiSection(QWidget):
    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(16)
        layout.addWidget(_SectionTitle("Gemini (Translate)"))

        grp = QGroupBox("API Settings")
        form = QFormLayout(grp)
        form.setSpacing(10)

        self._txt_key = QLineEdit()
        self._txt_key.setPlaceholderText("Enter your Gemini API key…")
        self._txt_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._txt_key.setText(cfg.gemini_api_key)
        self._txt_key.textChanged.connect(lambda t: setattr(cfg, "gemini_api_key", t))

        self._cmb_model = QComboBox()
        self._cmb_model.addItems(["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"])
        self._cmb_model.setCurrentText(cfg.last_gemini_model)

        self._spn_temp = QDoubleSpinBox()
        self._spn_temp.setRange(0.0, 2.0)
        self._spn_temp.setValue(0.3)
        self._spn_temp.setSingleStep(0.1)

        self._spn_batch = QSpinBox()
        self._spn_batch.setRange(1, 50)
        self._spn_batch.setValue(10)

        form.addRow("API Key:", self._txt_key)
        form.addRow("Default Model:", self._cmb_model)
        form.addRow("Temperature:", self._spn_temp)
        form.addRow("Batch Size:", self._spn_batch)
        layout.addWidget(grp)

        btn_test = QPushButton("Test API Key")
        btn_test.setFixedWidth(120)
        btn_test.clicked.connect(self._on_test_api)
        layout.addWidget(btn_test)

    def _on_test_api(self) -> None:
        from PyQt6.QtWidgets import QMessageBox
        key = self._txt_key.text().strip()
        if not key:
            QMessageBox.warning(self, "Missing Key", "Please enter your API key first.")
            return
        QMessageBox.information(self, "API Test", "API key format looks valid. (Real test requires network call)")


class _TTSSection(QWidget):
    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(16)
        layout.addWidget(_SectionTitle("TTS (Voice)"))

        grp = QGroupBox("Default TTS Settings")
        form = QFormLayout(grp)
        self._cmb_engine = QComboBox()
        self._cmb_engine.addItems(["Edge TTS", "Coqui TTS"])
        self._cmb_male = QComboBox()
        self._cmb_male.addItems(["vi-VN-NamMinhNeural", "vi-VN-DucAnh-custom"])
        self._cmb_female = QComboBox()
        self._cmb_female.addItems(["vi-VN-HoaiMyNeural", "vi-VN-ThuHuong-custom"])
        form.addRow("Engine:", self._cmb_engine)
        form.addRow("Default Male Voice:", self._cmb_male)
        form.addRow("Default Female Voice:", self._cmb_female)
        layout.addWidget(grp)


class _FFmpegSection(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(16)
        layout.addWidget(_SectionTitle("FFmpeg (Render)"))

        grp = QGroupBox("FFmpeg Settings")
        form = QFormLayout(grp)
        self._txt_ffmpeg = QLineEdit("ffmpeg")
        self._txt_ffprobe = QLineEdit("ffprobe")
        form.addRow("ffmpeg binary:", self._txt_ffmpeg)
        form.addRow("ffprobe binary:", self._txt_ffprobe)
        layout.addWidget(grp)

        btn_detect = QPushButton("Auto-detect")
        btn_detect.clicked.connect(self._on_autodetect)
        layout.addWidget(btn_detect)

    def _on_autodetect(self) -> None:
        import shutil
        ffmpeg = shutil.which("ffmpeg") or "Not found"
        ffprobe = shutil.which("ffprobe") or "Not found"
        self._txt_ffmpeg.setText(ffmpeg)
        self._txt_ffprobe.setText(ffprobe)


_SIDEBAR_ITEMS = [
    ("⚙️  General",           "general"),
    ("🎙️  Whisper (STT)",     "whisper"),
    ("🌐  Gemini (Translate)", "gemini"),
    ("🔊  TTS (Voice)",       "tts"),
    ("🎬  FFmpeg (Render)",   "ffmpeg"),
]


class SettingsView(QWidget):
    """Settings screen — sidebar navigation + section panels."""

    def __init__(self, main_window: "MainWindow") -> None:
        super().__init__()
        self._mw = main_window
        self._cfg = AppConfig.get()
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet("background: #F9F9F9; border-right: 1px solid #E0E0E0;")
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(0, 16, 0, 16)
        sb_layout.setSpacing(2)

        lbl = QLabel("Settings")
        lbl.setStyleSheet(
            "font-size: 15px; font-weight: 700; color: #1C1C1C;"
            "padding: 0 16px 8px 16px;"
        )
        sb_layout.addWidget(lbl)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: #FFFFFF;")

        sections = {
            "general": _GeneralSection(self._cfg),
            "whisper": _WhisperSection(self._cfg),
            "gemini":  _GeminiSection(self._cfg),
            "tts":     _TTSSection(self._cfg),
            "ffmpeg":  _FFmpegSection(),
        }

        self._buttons: dict[str, QPushButton] = {}
        for label, sid in _SIDEBAR_ITEMS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; border-radius: 6px;"
                "text-align: left; padding: 8px 16px; font-size: 13px; color: #1C1C1C; }"
                "QPushButton:checked { background: #DCEEFB; color: #0078D4; font-weight: 600; }"
                "QPushButton:hover:!checked { background: #E8E8E8; }"
            )
            btn.clicked.connect(lambda _, s=sid: self._switch_section(s))
            sb_layout.addWidget(btn)
            self._buttons[sid] = btn

            w = sections.get(sid, QWidget())
            self._stack.addWidget(w)

        sb_layout.addStretch()
        root.addWidget(sidebar)

        # Content area
        content = QWidget()
        content.setStyleSheet("background: #FFFFFF;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(32, 32, 32, 32)
        content_layout.addWidget(self._stack)
        root.addWidget(content, stretch=1)

        # Default: whisper
        self._switch_section("whisper")

    def _switch_section(self, section_id: str) -> None:
        for sid, btn in self._buttons.items():
            btn.setChecked(sid == section_id)
        idx = list(k for k, _ in _SIDEBAR_ITEMS).index(section_id) if section_id in [k for k, _ in _SIDEBAR_ITEMS] else 0
        self._stack.setCurrentIndex(idx)

    def on_activated(self) -> None:
        pass
