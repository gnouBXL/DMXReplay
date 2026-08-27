"""Live recorder status, for the recorder UI. See brief §28-§29."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RecorderStatus:
    recording: bool
    duration_seconds: float
    universe_count: int
    frame_count: int
    total_packets: int
    malformed_packets: int
    file_size_bytes: int | None
