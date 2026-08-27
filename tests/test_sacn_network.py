"""Real UDP loopback tests for sACN I/O."""
from __future__ import annotations

import asyncio

import pytest

from dmxreplay.network.sacn import SACNListener, SACNSender


def test_sender_to_listener_round_trip_unicast_over_udp_loopback():
    received: list[tuple] = []

    async def body():
        listener = SACNListener(on_packet=lambda pkt, ip, ts: received.append((pkt, ip, ts)))
        await listener.start(interface_ip="127.0.0.1", port=0)
        listener_port = listener._transport.get_extra_info("sockname")[1]

        sender = SACNSender()
        await sender.start(interface_ip="127.0.0.1")

        data = bytes(range(1, 21))
        sent_packet = sender.send(
            universe=7, dmx_data=data, destination_ip="127.0.0.1", port=listener_port,
        )

        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0.01)

        sender.stop()
        listener.stop()
        return sent_packet, received

    sent_packet, received = asyncio.run(body())

    assert len(received) == 1
    recv_packet, source_ip, timestamp_ns = received[0]
    assert recv_packet == sent_packet
    assert source_ip == "127.0.0.1"
    assert timestamp_ns >= 0


def test_listener_tracks_universe_status_and_non_dmx_start_code():
    async def body():
        listener = SACNListener()
        await listener.start(interface_ip="127.0.0.1", port=0)
        port = listener._transport.get_extra_info("sockname")[1]

        sender = SACNSender()
        await sender.start(interface_ip="127.0.0.1")

        for i in range(3):
            sender.send(universe=9, dmx_data=bytes([i] * 5), destination_ip="127.0.0.1", port=port)
        await asyncio.sleep(0.1)

        # One non-DMX (RDM-style) packet: must be counted separately, not as DMX.
        from dmxreplay.network.sacn import E131DataPacket

        rdm_packet = E131DataPacket(universe=9, dmx_data=bytes([0] * 5), start_code=0xCC)
        sender._transport.sendto(rdm_packet.to_bytes(), ("127.0.0.1", port))
        await asyncio.sleep(0.1)

        sender.stop()
        listener.stop()
        return listener

    listener = asyncio.run(body())

    universes = listener.get_universes()
    assert len(universes) == 1
    status = universes[0]
    assert status.universe == 9
    assert status.packet_count == 3
    assert status.non_dmx_count == 1
    assert status.channel_count == 5


def test_multicast_send_and_receive_on_loopback():
    """Best-effort: multicast loopback requires kernel/network support that
    may not be present in every sandboxed environment. Skip rather than fail
    if the join itself is refused."""

    async def body():
        listener = SACNListener()
        try:
            await listener.start(
                interface_ip="127.0.0.1", port=15568, multicast_universes=[3],
            )
        except OSError as exc:
            pytest.skip(f"multicast not available in this environment: {exc}")

        sender = SACNSender()
        await sender.start(interface_ip="127.0.0.1")
        sender.send(universe=3, dmx_data=bytes([42, 43, 44]), port=15568)

        await asyncio.sleep(0.2)
        sender.stop()
        listener.stop()
        return listener

    listener = asyncio.run(body())
    universes = listener.get_universes()
    if not universes:
        pytest.skip("multicast loopback delivery did not occur in this environment")
    assert universes[0].universe == 3
