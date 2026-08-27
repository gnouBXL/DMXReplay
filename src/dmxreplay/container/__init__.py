"""Matroska container read/write + manifest attachment I/O (Phase 4).
See docs/CONTAINER.md. Requires the optional `av` (PyAV) dependency."""
from .reader import DMXReplayReader, NotADMXReplayFileError
from .writer import (
    MANIFEST_ATTACHMENT_MIMETYPE,
    MANIFEST_ATTACHMENT_NAME,
    STORAGE_TIME_BASE,
    STORAGE_TIMESTAMP_RESOLUTION_NS,
    DMXReplayWriter,
)

__all__ = [
    "DMXReplayWriter",
    "DMXReplayReader",
    "NotADMXReplayFileError",
    "MANIFEST_ATTACHMENT_NAME",
    "MANIFEST_ATTACHMENT_MIMETYPE",
    "STORAGE_TIME_BASE",
    "STORAGE_TIMESTAMP_RESOLUTION_NS",
]
