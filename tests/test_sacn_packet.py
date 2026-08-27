from __future__ import annotations

import uuid

import pytest

from dmxreplay.network.sacn import E131DataPacket, MalformedE131PacketError
from dmxreplay.network.sacn.packet import ACN_PACKET_IDENTIFIER, VECTOR_ROOT_E131_DATA


def _sample_data(length: int = 512) -> bytes:
    return bytes(i % 256 for i in range(length))


def test_build_then_parse_round_trips_exactly():
    cid = uuid.uuid4().bytes
    packet = E131DataPacket(
        universe=42, dmx_data=_sample_data(), cid=cid, source_name="Test Source",
        priority=150, sequence_number=9, sync_address=0,
    )
    raw = packet.to_bytes()
    parsed = E131DataPacket.parse(raw)
    assert parsed == packet


def test_full_512_channel_packet_is_638_bytes():
    # Well-known E1.31 wire size for a full universe (root 38 + framing 77 +
    # DMP header 10 + start code 1 + 512 data bytes = 638).
    packet = E131DataPacket(universe=1, dmx_data=_sample_data(512))
    assert len(packet.to_bytes()) == 638


def test_wire_layout_has_expected_identifiers():
    packet = E131DataPacket(universe=1, dmx_data=_sample_data(4))
    raw = packet.to_bytes()
    assert raw[4:16] == ACN_PACKET_IDENTIFIER
    assert int.from_bytes(raw[18:22], "big") == VECTOR_ROOT_E131_DATA


def test_start_code_and_is_dmx_data():
    dmx_packet = E131DataPacket(universe=1, dmx_data=_sample_data(4), start_code=0x00)
    assert dmx_packet.is_dmx_data

    rdm_packet = E131DataPacket(universe=1, dmx_data=_sample_data(4), start_code=0xCC)
    assert not rdm_packet.is_dmx_data
    # Round trip preserves the non-zero start code.
    assert E131DataPacket.parse(rdm_packet.to_bytes()).start_code == 0xCC


def test_options_bits_round_trip():
    packet = E131DataPacket(
        universe=1, dmx_data=_sample_data(4),
        preview_data=True, stream_terminated=True, force_sync=False,
    )
    parsed = E131DataPacket.parse(packet.to_bytes())
    assert parsed.preview_data is True
    assert parsed.stream_terminated is True
    assert parsed.force_sync is False


def test_universe_multicast_address_derivation():
    from dmxreplay.network.sacn import multicast_group_for_universe

    # Universe 1 -> 239.255.0.1 ; Universe 300 -> 239.255.1.44 (300 = 0x012C)
    assert multicast_group_for_universe(1) == "239.255.0.1"
    assert multicast_group_for_universe(300) == "239.255.1.44"


def test_construction_rejects_out_of_range_fields():
    with pytest.raises(ValueError):
        E131DataPacket(universe=0, dmx_data=_sample_data(4))
    with pytest.raises(ValueError):
        E131DataPacket(universe=64000, dmx_data=_sample_data(4))
    with pytest.raises(ValueError):
        E131DataPacket(universe=1, dmx_data=b"")
    with pytest.raises(ValueError):
        E131DataPacket(universe=1, dmx_data=_sample_data(513))
    with pytest.raises(ValueError):
        E131DataPacket(universe=1, dmx_data=_sample_data(4), priority=201)


@pytest.mark.parametrize(
    "mutate,expected_fragment",
    [
        (lambda raw: b"\xFF\xFF" + raw[2:], "preamble"),
        (lambda raw: raw[:4] + b"X" * 12 + raw[16:], "identifier"),
        (lambda raw: raw[:18] + b"\x00\x00\x00\x05" + raw[22:], "root vector"),
        (lambda raw: raw[:40] + b"\x00\x00\x00\x05" + raw[44:], "framing vector"),
        (lambda raw: raw[:113] + b"\xFF\xFF" + raw[115:], "universe"),
        (lambda raw: raw[:10], "too short"),
    ],
)
def test_parse_rejects_malformed_packets(mutate, expected_fragment):
    packet = E131DataPacket(universe=1, dmx_data=_sample_data(4))
    mutated = mutate(packet.to_bytes())
    with pytest.raises(MalformedE131PacketError, match=expected_fragment):
        E131DataPacket.parse(mutated)
