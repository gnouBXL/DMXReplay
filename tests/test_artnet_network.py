"""Real UDP loopback tests for Art-Net I/O -- not mocked: an actual
ArtNetSender transmits to an actual ArtNetListener over 127.0.0.1."""
from __future__ import annotations

import asyncio

from dmxreplay.network.artnet import ArtNetListener, ArtNetSender


def test_sender_to_listener_round_trip_over_udp_loopback():
    received: list[tuple] = []

    async def body():
        listener = ArtNetListener(on_packet=lambda pkt, ip, ts: received.append((pkt, ip, ts)))
        await listener.start(interface_ip="127.0.0.1", port=0)
        assert listener._transport is not None
        listener_port = listener._transport.get_extra_info("sockname")[1]

        sender = ArtNetSender()
        await sender.start(interface_ip="127.0.0.1")

        data = bytes(range(1, 11))
        sent_packet = sender.send(
            net=0, subnet=1, universe=2, data=data,
            destination_ip="127.0.0.1", port=listener_port,
        )

        # Give the event loop a moment to deliver the datagram.
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


def test_listener_tracks_universe_status_and_ignores_malformed_datagrams():
    async def body():
        listener = ArtNetListener()
        await listener.start(interface_ip="127.0.0.1", port=0)
        port = listener._transport.get_extra_info("sockname")[1]

        sender = ArtNetSender()
        await sender.start(interface_ip="127.0.0.1")

        for i in range(3):
            sender.send(
                net=0, subnet=0, universe=5, data=bytes([i] * 4),
                destination_ip="127.0.0.1", port=port,
            )
        await asyncio.sleep(0.1)

        # Fire one malformed (too-short) datagram directly, bypassing the
        # sender's own validation, to exercise the drop path end-to-end.
        import socket

        junk_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        junk_sock.sendto(b"not-art-net", ("127.0.0.1", port))
        junk_sock.close()
        await asyncio.sleep(0.1)

        sender.stop()
        listener.stop()
        return listener

    listener = asyncio.run(body())

    universes = listener.get_universes()
    assert len(universes) == 1
    status = universes[0]
    assert (status.net, status.subnet, status.universe) == (0, 0, 5)
    assert status.packet_count == 3
    assert status.channel_count == 4
    assert listener.malformed_packet_count == 1
