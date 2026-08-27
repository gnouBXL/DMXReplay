"""sACN output (player side). See docs/SACN.md §8, brief §31/§33."""
from __future__ import annotations

import asyncio
import socket
import uuid

from .listener import multicast_group_for_universe
from .packet import SACN_PORT, E131DataPacket


class SACNSender:
    """Sends E1.31 data packets, unicast or multicast.

    Maintains one wrapping 0-255 sequence number per universe (docs/SACN.md
    §8). The network interface to bind on is always explicit (brief §48).
    """

    def __init__(self, source_name: str = "DMXReplay", cid: bytes | None = None) -> None:
        self._transport: asyncio.DatagramTransport | None = None
        self._sequences: dict[int, int] = {}
        self._source_name = source_name
        self._cid = cid or uuid.uuid4().bytes

    async def start(self, interface_ip: str = "0.0.0.0", multicast_ttl: int = 8) -> None:
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, multicast_ttl)
        sock.setsockopt(
            socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(interface_ip)
        )
        sock.bind((interface_ip, 0))
        self._transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol, sock=sock
        )

    def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def _next_sequence(self, universe: int) -> int:
        nxt = (self._sequences.get(universe, 0) + 1) & 0xFF
        self._sequences[universe] = nxt
        return nxt

    def send(
        self,
        universe: int,
        dmx_data: bytes,
        destination_ip: str | None = None,
        priority: int = 100,
        port: int = SACN_PORT,
    ) -> E131DataPacket:
        """Build and send one E1.31 data packet. If destination_ip is None,
        sends to the universe's standard multicast group (docs/SACN.md §8);
        otherwise sends unicast to destination_ip. Returns the packet sent."""
        if self._transport is None:
            raise RuntimeError("SACNSender.start() must be called before send()")
        packet = E131DataPacket(
            universe=universe,
            dmx_data=dmx_data,
            cid=self._cid,
            source_name=self._source_name,
            priority=priority,
            sequence_number=self._next_sequence(universe),
        )
        dest_ip = destination_ip or multicast_group_for_universe(universe)
        self._transport.sendto(packet.to_bytes(), (dest_ip, port))
        return packet
