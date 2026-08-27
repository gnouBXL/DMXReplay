from __future__ import annotations

from dmxreplay.dmx import DMXEngine


def test_first_update_assigns_row_0():
    engine = DMXEngine()
    frame = engine.update_artnet(net=0, subnet=0, universe=1, data=bytes([10, 20, 30]), timestamp_ns=100)
    assert engine.active_row_count == 1
    assert frame.universes[0].get_channel(1) == 10
    assert frame.universes[0].get_channel(2) == 20
    assert frame.universes[0].get_channel(4) == 0  # untouched channel stays 0


def test_rows_assigned_in_first_seen_order_across_protocols():
    engine = DMXEngine()
    engine.update_sacn(universe=9, data=bytes([1]), timestamp_ns=0)
    engine.update_artnet(net=0, subnet=0, universe=1, data=bytes([2]), timestamp_ns=1)
    engine.update_sacn(universe=9, data=bytes([3]), timestamp_ns=2)  # already known -> same row

    rows = engine.get_row_infos()
    assert len(rows) == 2
    assert rows[0].protocol == "sACN" and rows[0].universe == 9
    assert rows[1].protocol == "Art-Net" and rows[1].universe == 1
    assert rows[0].packet_count == 2
    assert rows[1].packet_count == 1


def test_committed_frame_includes_every_row_not_just_the_updated_one():
    engine = DMXEngine()
    engine.update_artnet(net=0, subnet=0, universe=1, data=bytes([111]), timestamp_ns=0)
    frame = engine.update_artnet(net=0, subnet=0, universe=2, data=bytes([222]), timestamp_ns=1)
    assert len(frame.universes) == 2
    assert frame.universes[0].get_channel(1) == 111  # row 0 retains its prior value
    assert frame.universes[1].get_channel(1) == 222


def test_short_packet_updates_only_declared_channels_and_preserves_the_rest():
    engine = DMXEngine()
    engine.update_artnet(net=0, subnet=0, universe=1, data=bytes([1, 2, 3, 4, 5]), timestamp_ns=0)
    frame = engine.update_artnet(net=0, subnet=0, universe=1, data=bytes([99]), timestamp_ns=1)
    u = frame.universes[0]
    assert u.get_channel(1) == 99  # updated
    assert u.get_channel(2) == 2   # preserved from the earlier, longer packet
    assert u.get_channel(5) == 5   # preserved


def test_current_frame_snapshot_without_new_update():
    engine = DMXEngine()
    engine.update_artnet(net=0, subnet=0, universe=1, data=bytes([7]), timestamp_ns=0)
    snap = engine.current_frame(timestamp_ns=999)
    assert snap.timestamp_ns == 999
    assert snap.universes[0].get_channel(1) == 7


def test_data_longer_than_512_channels_is_rejected():
    engine = DMXEngine()
    import pytest
    with pytest.raises(ValueError):
        engine.update_artnet(net=0, subnet=0, universe=1, data=bytes(513), timestamp_ns=0)
