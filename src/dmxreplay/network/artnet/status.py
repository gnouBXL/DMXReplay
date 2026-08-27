"""Live per-universe status, for the recorder UI (brief §13/§28) and for
deciding which universes were actually active (docs/SPECIFICATION.md §7)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UniverseStatus:
    """Live status of one Art-Net universe being received. Mutated in place
    by ArtNetListener as packets arrive; read by the recorder UI."""

    net: int
    subnet: int
    universe: int
    source_ip: str
    packet_count: int = 0
    dropped_count: int = 0
    channel_count: int = 0
    last_packet_ns: int | None = None
    first_packet_ns: int | None = None

    @property
    def packets_per_second(self) -> float:
        """Average rate since the first packet from this universe. A simple
        average (not an instantaneous/windowed rate) is sufficient for V1's
        diagnostic display (brief §13) and avoids the complexity of a sliding
        window; revisit if the recorder UI needs finer-grained live rate."""
        if self.first_packet_ns is None or self.last_packet_ns is None:
            return 0.0
        elapsed_s = (self.last_packet_ns - self.first_packet_ns) / 1_000_000_000
        if elapsed_s <= 0:
            return 0.0
        return (self.packet_count - 1) / elapsed_s

    def key(self) -> tuple[int, int, int]:
        return (self.net, self.subnet, self.universe)
