from __future__ import annotations

import pytest

from dmxreplay.network.artnet import ArtDmxPacket, MalformedArtNetPacketError
from dmxreplay.network.artnet.packet import ARTNET_ID, MIN_PROTOCOL_VERSION, OP_DMX


def _sample_data(length: int = 512) -> bytes:
    return bytes(i % 256 for i in range(length))


def test_build_then_parse_round_trips_exactly():
    packet = ArtDmxPacket(
        sequence=7, physical=0, net=1, subnet=2, universe=3, data=_sample_data()
    )
    raw = packet.to_bytes()
    parsed = ArtDmxPacket.parse(raw)
    assert parsed == packet


def test_wire_layout_matches_artnet_spec_offsets():
    packet = ArtDmxPacket(sequence=1, physical=0, net=0, subnet=1, universe=1, data=_sample_data(4))
    raw = packet.to_bytes()
    assert raw[0:8] == ARTNET_ID
    assert int.from_bytes(raw[8:10], "little") == OP_DMX
    assert int.from_bytes(raw[10:12], "big") == MIN_PROTOCOL_VERSION
    assert raw[12] == 1  # sequence
    assert raw[13] == 0  # physical
    assert raw[14] == (1 << 4) | 1  # SubUni = (subnet<<4)|universe
    assert raw[15] == 0  # net
    assert int.from_bytes(raw[16:18], "big") == 4  # length
    assert raw[18:] == _sample_data(4)


def test_port_address_17_decomposes_as_documented():
    # Cross-check against docs/ARTNET.md §1.1's worked example.
    packet = ArtDmxPacket(sequence=0, physical=0, net=0, subnet=1, universe=1, data=_sample_data(2))
    assert packet.port_address() == 17


@pytest.mark.parametrize(
    "mutate,expected_message_fragment",
    [
        (lambda raw: b"XXXXXXXX" + raw[8:], "ID"),
        (lambda raw: raw[:8] + b"\x00\x51" + raw[10:], "OpCode"),
        (lambda raw: raw[:10] + b"\x00\x01" + raw[12:], "protocol version"),
        (lambda raw: raw[:15] + b"\xFF" + raw[16:], "net"),
        (lambda raw: raw[:16] + b"\x02\x01" + raw[18:], "length"),  # odd declared length
        (lambda raw: raw[:16] + b"\x00\x00" + raw[18:], "length"),  # declared length 0, < minimum
        (lambda raw: raw[:5], "too short"),
    ],
)
def test_parse_rejects_malformed_packets(mutate, expected_message_fragment):
    packet = ArtDmxPacket(sequence=0, physical=0, net=0, subnet=0, universe=0, data=_sample_data(4))
    mutated = mutate(packet.to_bytes())
    with pytest.raises(MalformedArtNetPacketError, match=expected_message_fragment):
        ArtDmxPacket.parse(mutated)


def test_parse_rejects_truncated_payload_shorter_than_declared_length():
    packet = ArtDmxPacket(sequence=0, physical=0, net=0, subnet=0, universe=0, data=_sample_data(10))
    raw = packet.to_bytes()
    truncated = raw[:-3]  # declared length still says 10, but only 7 bytes follow
    with pytest.raises(MalformedArtNetPacketError, match="does not match"):
        ArtDmxPacket.parse(truncated)


def test_construction_rejects_out_of_range_fields():
    with pytest.raises(ValueError):
        ArtDmxPacket(sequence=0, physical=0, net=128, subnet=0, universe=0, data=_sample_data(2))
    with pytest.raises(ValueError):
        ArtDmxPacket(sequence=0, physical=0, net=0, subnet=16, universe=0, data=_sample_data(2))
    with pytest.raises(ValueError):
        ArtDmxPacket(sequence=0, physical=0, net=0, subnet=0, universe=16, data=_sample_data(2))
    with pytest.raises(ValueError):
        ArtDmxPacket(sequence=0, physical=0, net=0, subnet=0, universe=0, data=_sample_data(1))  # odd
    with pytest.raises(ValueError):
        ArtDmxPacket(sequence=0, physical=0, net=0, subnet=0, universe=0, data=_sample_data(514))  # too long
