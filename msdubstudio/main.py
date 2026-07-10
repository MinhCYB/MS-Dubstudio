"""
main.py — Entry point cho MS DubStudio

Usage:
    python -m msdubstudio.main
    python msdubstudio/main.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def _setup_logging() -> None:
    from msdubstudio.config import get_log_path

    log_path = get_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
    )


def main() -> None:
    _setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("MS DubStudio starting…")

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt

    app = QApplication(sys.argv)
    app.setApplicationName("MS DubStudio")
    app.setOrganizationName("MS DubStudio")

    # High DPI support (PyQt6 enables by default, but be explicit)
    # app.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)

    # Load stylesheet
    qss_path = Path(__file__).parent / "resources" / "styles.qss"
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
        logger.info(f"Stylesheet loaded: {qss_path}")
    else:
        logger.warning(f"Stylesheet not found: {qss_path}")

    # Create and show main window
    from msdubstudio.ui.main_window import MainWindow
    window = MainWindow()
    window.show()

    logger.info("MainWindow shown")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
