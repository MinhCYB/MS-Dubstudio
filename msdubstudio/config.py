"""
config.py — App-level settings và constants

Quản lý:
- Đường dẫn mặc định (Projects folder, log folder)
- API key storage (dùng keyring nếu có, fallback về config file)
- App metadata (tên, version)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App metadata
# ---------------------------------------------------------------------------

APP_NAME = "MS DubStudio"
APP_VERSION = "0.1.0"
APP_ORGANIZATION = "MS DubStudio"

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

def get_default_projects_dir() -> Path:
    """Thư mục mặc định chứa tất cả projects.

    Windows: ~/Documents/MS DubStudio Projects
    macOS/Linux: ~/MS DubStudio Projects
    """
    home = Path.home()
    docs = home / "Documents"
    if docs.exists():
        return docs / "MS DubStudio Projects"
    return home / "MS DubStudio Projects"


def get_app_data_dir() -> Path:
    """Thư mục chứa app config/log.

    Windows: %APPDATA%/MS DubStudio
    macOS: ~/Library/Application Support/MS DubStudio
    Linux: ~/.config/ms-dubstudio
    """
    if os.name == "nt":  # Windows
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "MS DubStudio"
    elif os.uname().sysname == "Darwin":  # macOS
        return Path.home() / "Library" / "Application Support" / "MS DubStudio"
    else:  # Linux
        xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        return Path(xdg) / "ms-dubstudio"


def get_log_path() -> Path:
    return get_app_data_dir() / "app.log"


def get_config_file_path() -> Path:
    return get_app_data_dir() / "config.json"


# ---------------------------------------------------------------------------
# AppConfig — persistent settings
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: dict = {
    "projects_dir": str(get_default_projects_dir()),
    "gemini_api_key": "",
    "recent_projects": [],  # list[str] — đường dẫn project dirs, tối đa 10
    "theme": "light",
    "window_width": 1280,
    "window_height": 800,
    "last_whisper_model": "large-v3",
    "last_gemini_model": "gemini-1.5-pro",
    "last_tts_engine": "edge-tts",
}


class AppConfig:
    """Singleton quản lý app-level settings, load/save từ config.json."""

    _instance: Optional["AppConfig"] = None

    def __init__(self) -> None:
        self._data: dict = dict(_DEFAULT_CONFIG)
        self._path = get_config_file_path()
        self._load()

    @classmethod
    def get(cls) -> "AppConfig":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def projects_dir(self) -> Path:
        return Path(self._data.get("projects_dir", str(get_default_projects_dir())))

    @projects_dir.setter
    def projects_dir(self, value: Path | str) -> None:
        self._data["projects_dir"] = str(value)

    @property
    def gemini_api_key(self) -> str:
        """API key — trả về từ config file hoặc env var GEMINI_API_KEY."""
        env_key = os.environ.get("GEMINI_API_KEY", "")
        if env_key:
            return env_key
        return self._data.get("gemini_api_key", "")

    @gemini_api_key.setter
    def gemini_api_key(self, value: str) -> None:
        self._data["gemini_api_key"] = value

    @property
    def recent_projects(self) -> list[str]:
        return list(self._data.get("recent_projects", []))

    @property
    def window_width(self) -> int:
        return int(self._data.get("window_width", 1280))

    @property
    def window_height(self) -> int:
        return int(self._data.get("window_height", 800))

    @property
    def last_whisper_model(self) -> str:
        return self._data.get("last_whisper_model", "large-v3")

    @last_whisper_model.setter
    def last_whisper_model(self, value: str) -> None:
        self._data["last_whisper_model"] = value

    @property
    def last_gemini_model(self) -> str:
        return self._data.get("last_gemini_model", "gemini-1.5-pro")

    @last_gemini_model.setter
    def last_gemini_model(self, value: str) -> None:
        self._data["last_gemini_model"] = value

    # ------------------------------------------------------------------
    # Recent Projects
    # ------------------------------------------------------------------

    def add_recent_project(self, project_dir: str) -> None:
        """Thêm project vào đầu danh sách recent (tối đa 10)."""
        recent = [p for p in self.recent_projects if p != project_dir]
        recent.insert(0, project_dir)
        self._data["recent_projects"] = recent[:10]

    def remove_recent_project(self, project_dir: str) -> None:
        """Xóa project khỏi danh sách recent."""
        self._data["recent_projects"] = [
            p for p in self.recent_projects if p != project_dir
        ]

    # ------------------------------------------------------------------
    # Window State
    # ------------------------------------------------------------------

    def save_window_state(self, width: int, height: int) -> None:
        self._data["window_width"] = width
        self._data["window_height"] = height

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = self._path.read_text(encoding="utf-8")
            loaded = json.loads(raw)
            # Merge với defaults để đảm bảo keys mới luôn có giá trị mặc định
            self._data = {**_DEFAULT_CONFIG, **loaded}
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Không load được config: {e}. Dùng giá trị mặc định.")

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as e:
            logger.error(f"Không save được config: {e}")
