"""In-memory ring buffer of recent log lines, exposed by the local web
config UI's `GET /config/logs` (cross-platform extension Phase E, extension
brief §7's "logs" requirement) -- a device that may have no screen and no
SSH access configured still needs *some* way to see recent status/errors
from a browser. Deliberately not a `journalctl`/systemd-journal
integration (would need shelling out with elevated permissions, or a
platform-specific Python binding, on top of only existing on Linux at
all) -- this works identically on Windows/macOS/Linux since it's just a
`logging.Handler`.
"""
from __future__ import annotations

import logging
from collections import deque

DEFAULT_CAPACITY = 200


class RingBufferLogHandler(logging.Handler):
    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        super().__init__()
        self._buffer: deque[str] = deque(maxlen=capacity)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        self._buffer.append(self.format(record))

    def lines(self) -> list[str]:
        return list(self._buffer)
