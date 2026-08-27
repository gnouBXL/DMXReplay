"""sACN input (recorder side). See docs/SACN.md §2-§4, brief §13/§29."""
from __future__ import annotations

import asyncio
import logging
import socket
import struct
from typing import Callable

from ...clock import MasterClock
from .packet import SACN_PORT, E131DataPacket, MalformedE131PacketError
from .status import UniverseStatus

logger = logging.getLogger("dmxreplay.network.sacn")

PacketCallback = Callable[[E131DataPacket, str, int], None]
"""Called for every *valid, DMX-carrying* (null start code) received packet:
(packet, source_ip, timestamp_ns)."""


def multicast_group_for_universe(universe: int) -> str:
    """The standard sACN multicast address for a universe: 239.255.hi.lo,
    where hi/lo are the big-endian bytes of the universe number
    (docs/SACN.md §8)."""
    if not (1 <= universe <= 63999):
        raise ValueError(f"universe must be in [1, 63999], got {universe}")
    hi = (universe >> 8) & 0xFF
    lo = universe & 0xFF
    return f"239.255.{hi}.{lo}"


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, listener: "SACNListener") -> None:
        self._listener = listener

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._listener._handle_datagram(data, addr[0])

    def error_received(self, exc: Exception) -> None:
        logger.warning("sACN socket error: %s", exc)


class SACNListener:
    """Listens for E1.31 data packets on one network interface.

    Supports plain unicast listening, and/or joining the standard multicast
    group for specific universes (docs/SACN.md §8). Validates and drops
    malformed packets (docs/SPECIFICATION.md §15/§18); packets with a
    non-null DMX start code are counted separately and not forwarded as DMX
    (docs/SACN.md §3).
    """

    def __init__(
        self,
        on_packet: PacketCallback | None = None,
        clock: MasterClock | None = None,
    ) -> None:
        self._on_packet = on_packet
        self._clock = clock or MasterClock()
        self._universes: dict[int, UniverseStatus] = {}
        self._transport: asyncio.DatagramTransport | None = None
        self._malformed_count = 0
        self._interface_ip = "0.0.0.0"

    async def start(
        self,
        interface_ip: str = "0.0.0.0",
        port: int = SACN_PORT,
        multicast_universes: list[int] | None = None,
    ) -> None:
        self._interface_ip = interface_ip
        loop = asyncio.get_running_loop()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.bind((interface_ip, port))

        for universe in multicast_universes or []:
            group = multicast_group_for_universe(universe)
            mreq = struct.pack(
                "4s4s", socket.inet_aton(group), socket.inet_aton(interface_ip)
            )
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _Protocol(self), sock=sock
        )

    def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def _handle_datagram(self, data: bytes, source_ip: str) -> None:
        timestamp_ns = self._clock.now_ns()
        try:
            packet = E131DataPacket.parse(data)
        except MalformedE131PacketError as exc:
            self._malformed_count += 1
            logger.warning("dropped malformed sACN packet from %s: %s", source_ip, exc)
            return

        status = self._universes.get(packet.universe)
        if status is None:
            status = UniverseStatus(universe=packet.universe, source_ip=source_ip)
            self._universes[packet.universe] = status
            status.first_packet_ns = timestamp_ns

        if not packet.is_dmx_data:
            status.non_dmx_count += 1
            logger.debug(
                "sACN universe %d: non-DMX start code 0x%02X, dropped",
                packet.universe, packet.start_code,
            )
            return

        status.packet_count += 1
        status.channel_count = len(packet.dmx_data)
        status.last_packet_ns = timestamp_ns
        status.source_ip = source_ip
        status.source_name = packet.source_name
        status.priority = packet.priority

        if packet.stream_terminated:
            logger.info("sACN universe %d: stream terminated by sender", packet.universe)

        if self._on_packet is not None:
            self._on_packet(packet, source_ip, timestamp_ns)

    def get_universes(self) -> list[UniverseStatus]:
        return list(self._universes.values())

    @property
    def malformed_packet_count(self) -> int:
        return self._malformed_count
