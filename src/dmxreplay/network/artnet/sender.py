"""Art-Net output (player side). See docs/ARTNET.md §6, brief §31-§32."""
from __future__ import annotations

import asyncio

from .packet import ArtDmxPacket, ARTNET_PORT


class ArtNetSender:
    """Sends Art-Net `OpDmx` packets, unicast or broadcast.

    Maintains one wrapping 1-255 sequence number per destination universe
    (docs/ARTNET.md §6). The network interface to bind on is always explicit
    (brief §48) -- never auto-selected.
    """

    def __init__(self) -> None:
        self._transport: asyncio.DatagramTransport | None = None
        self._sequences: dict[tuple[int, int, int], int] = {}

    async def start(self, interface_ip: str = "0.0.0.0") -> None:
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol,
            local_addr=(interface_ip, 0),
            allow_broadcast=True,
        )

    def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def _next_sequence(self, key: tuple[int, int, int]) -> int:
        current = self._sequences.get(key, 0)
        nxt = current + 1
        if nxt > 255:
            nxt = 1
        self._sequences[key] = nxt
        return nxt

    def send(
        self,
        net: int,
        subnet: int,
        universe: int,
        data: bytes,
        destination_ip: str,
        physical: int = 0,
        port: int = ARTNET_PORT,
    ) -> ArtDmxPacket:
        """Build and send one OpDmx packet. Returns the packet actually sent
        (useful for tests/logging). `destination_ip` may be a unicast address
        or the interface's broadcast address (e.g. 255.255.255.255) -- the
        transport was opened with allow_broadcast=True to permit either."""
        if self._transport is None:
            raise RuntimeError("ArtNetSender.start() must be called before send()")
        key = (net, subnet, universe)
        packet = ArtDmxPacket(
            sequence=self._next_sequence(key),
            physical=physical,
            net=net,
            subnet=subnet,
            universe=universe,
            data=data,
        )
        self._transport.sendto(packet.to_bytes(), (destination_ip, port))
        return packet
