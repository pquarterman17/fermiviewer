"""In-memory log ring buffer (checklist O — logging + bug-report
capture). A logging.Handler keeps the last N records so the bug-report
endpoint can hand them to the client without any file I/O."""

from __future__ import annotations

import logging
import time
from collections import deque

_BUFFER: deque[dict[str, str | float]] = deque(maxlen=500)


class RingBufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            _BUFFER.append({
                "t": time.strftime(
                    "%H:%M:%S", time.localtime(record.created)
                ),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            })
        except Exception:  # noqa: BLE001 — logging must never raise
            pass


def install() -> None:
    """Attach the ring buffer to the root + uvicorn loggers (idempotent)."""
    root = logging.getLogger()
    if any(isinstance(h, RingBufferHandler) for h in root.handlers):
        return
    h = RingBufferHandler(level=logging.INFO)
    root.addHandler(h)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        if not any(isinstance(x, RingBufferHandler) for x in lg.handlers):
            lg.addHandler(h)


def entries() -> list[dict[str, str | float]]:
    return list(_BUFFER)
