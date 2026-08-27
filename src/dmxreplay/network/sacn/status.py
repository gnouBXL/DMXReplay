"""Live per-universe status for sACN, mirroring
dmxreplay.network.artnet.status.UniverseStatus. See brief §13/§28."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UniverseStatus:
    universe: int
    source_ip: str
    source_name: str = ""
    priority: int = 100
    packet_count: int = 0
    dropped_count: int = 0
    non_dmx_count: int = 0  # non-zero start code packets seen (docs/SACN.md §3)
    channel_count: int = 0
    last_packet_ns: int | None = None
    first_packet_ns: int | None = None

    @property
    def packets_per_second(self) -> float:
        if self.first_packet_ns is None or self.last_packet_ns is None:
            return 0.0
        elapsed_s = (self.last_packet_ns - self.first_packet_ns) / 1_000_000_000
        if elapsed_s <= 0:
            return 0.0
        return (self.packet_count - 1) / elapsed_s
