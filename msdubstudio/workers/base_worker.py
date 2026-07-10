"""
workers/base_worker.py — Base class cho tất cả QThread workers

Cung cấp:
- Cờ cancel thread-safe (`_is_cancelled`)
- `cancel()` method
- `is_cancelled` property
- Error signal chuẩn (`error` pyqtSignal)
- Bắt exception không mong đợi trong `run()` và emit error signal

Pattern sử dụng:
    class STTWorker(BaseWorker):
        my_signal = pyqtSignal(...)

        def run(self):
            try:
                # ... business logic ...
                if self.is_cancelled:
                    return
            except Exception as e:
                self.error.emit(str(e))
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class BaseWorker(QThread):
    """Base QThread worker với cancel, error handling chuẩn.

    Tất cả workers trong ms-dubstudio kế thừa từ đây.

    Signals:
        error(str): Emit khi có exception không xử lý được.
                    UI layer bắt để hiển thị thông báo lỗi.
    """

    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel_flag = threading.Event()

    # ------------------------------------------------------------------
    # Cancel interface
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        """Yêu cầu worker dừng lại.

        Non-blocking: đặt cờ, worker tự kiểm tra trong vòng lặp.
        Sau khi gọi cancel(), gọi wait() nếu cần đảm bảo thread đã dừng.
        """
        self._cancel_flag.set()
        logger.debug(f"{type(self).__name__}: cancel requested")

    @property
    def is_cancelled(self) -> bool:
        """True nếu cancel đã được yêu cầu."""
        return self._cancel_flag.is_set()

    def reset_cancel(self) -> None:
        """Reset cờ cancel — gọi trước khi reuse worker."""
        self._cancel_flag.clear()

    # ------------------------------------------------------------------
    # Safe run wrapper
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Override trong subclass. Nên bắt exception và emit self.error."""
        raise NotImplementedError(
            f"{type(self).__name__} phải implement run()"
        )
