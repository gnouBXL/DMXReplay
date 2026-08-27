"""Art-Net input (recorder side). See docs/ARTNET.md §3-§4, brief §13/§29."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from ...clock import MasterClock
from .packet import ARTNET_PORT, ArtDmxPacket, MalformedArtNetPacketError
from .status import UniverseStatus

logger = logging.getLogger("dmxreplay.network.artnet")

PacketCallback = Callable[[ArtDmxPacket, str, int], None]
"""Called for every *valid* received packet: (packet, source_ip, timestamp_ns)."""


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, listener: "ArtNetListener") -> None:
        self._listener = listener

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._listener._handle_datagram(data, addr[0])

    def error_received(self, exc: Exception) -> None:
        logger.warning("Art-Net socket error: %s", exc)


class ArtNetListener:
    """Listens for Art-Net `OpDmx` packets on one network interface.

    Validates and drops malformed packets (never crashes, never forwards bad
    data -- docs/SPECIFICATION.md §15/§18), tracks live per-universe status for
    the recorder UI (brief §13/§28), and invokes an optional callback with
    every valid packet so a recorder can timestamp and commit it
    (docs/TIMING.md §3).
    """

    def __init__(
        self,
        on_packet: PacketCallback | None = None,
        clock: MasterClock | None = None,
    ) -> None:
        self._on_packet = on_packet
        self._clock = clock or MasterClock()
        self._universes: dict[tuple[int, int, int], UniverseStatus] = {}
        self._transport: asyncio.DatagramTransport | None = None
        self._malformed_count = 0

    async def start(self, interface_ip: str = "0.0.0.0", port: int = ARTNET_PORT) -> None:
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _Protocol(self),
            local_addr=(interface_ip, port),
            allow_broadcast=True,
        )

    def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def _handle_datagram(self, data: bytes, source_ip: str) -> None:
        # Timestamp as early as possible on the capture path (docs/TIMING.md §3).
        timestamp_ns = self._clock.now_ns()
        try:
            packet = ArtDmxPacket.parse(data)
        except MalformedArtNetPacketError as exc:
            self._malformed_count += 1
            logger.warning("dropped malformed Art-Net packet from %s: %s", source_ip, exc)
            return

        key = (packet.net, packet.subnet, packet.universe)
        status = self._universes.get(key)
        if status is None:
            status = UniverseStatus(
                net=packet.net, subnet=packet.subnet, universe=packet.universe,
                source_ip=source_ip,
            )
            self._universes[key] = status
            status.first_packet_ns = timestamp_ns
        status.packet_count += 1
        status.channel_count = len(packet.data)
        status.last_packet_ns = timestamp_ns
        status.source_ip = source_ip

        if self._on_packet is not None:
            self._on_packet(packet, source_ip, timestamp_ns)

    def get_universes(self) -> list[UniverseStatus]:
        """Snapshot of every universe seen so far, in first-seen order --
        matches the row-assignment order DMXReplay uses for recording
        (docs/SPECIFICATION.md §7)."""
        return list(self._universes.values())

    @property
    def malformed_packet_count(self) -> int:
        return self._malformed_count
