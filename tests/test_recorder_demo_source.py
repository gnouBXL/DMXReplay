"""Real Recorder.add_demo_source()/current_preview() tests -- the
no-hardware-needed input path a Recorder GUI demo mode uses, feeding
DMXEngine.update_artnet() from a real, ticking asyncio task instead of a
real Art-Net listener, then writing a real .dmxr file exactly like a real
source would."""
from __future__ import annotations

import asyncio

import pytest

from dmxreplay.container import DMXReplayReader
from dmxreplay.recorder import Recorder


def test_add_demo_source_populates_get_universes(tmp_path):
    async def body():
        recorder = Recorder()
        recorder.add_demo_source(universe_count=3, fps=100.0)
        assert recorder.has_demo_source is True
        await asyncio.sleep(0.05)  # let a few ticks happen
        rows = recorder.get_universes()
        assert len(rows) == 3
        assert all(r.protocol == "Art-Net" for r in rows)
        await recorder.close()

    asyncio.run(body())


def test_demo_source_frames_are_actually_recorded(tmp_path):
    path = str(tmp_path / "demo.dmxr")

    async def body():
        recorder = Recorder()
        recorder.add_demo_source(universe_count=2, fps=100.0)
        await asyncio.sleep(0.05)
        recorder.start(path)
        await asyncio.sleep(0.1)
        recorder.stop()
        status = recorder.get_status()
        await recorder.close()
        return status

    status = asyncio.run(body())
    assert status.frame_count > 1  # more than just the initial capture frame
    assert status.total_packets > 0

    with DMXReplayReader(path) as reader:
        frames = list(reader.read_frames())
    assert len(frames) == status.frame_count
    assert len(frames[0].universes) == 2


def test_remove_demo_source_stops_new_ticks(tmp_path):
    async def body():
        recorder = Recorder()
        recorder.add_demo_source(universe_count=1, fps=100.0)
        await asyncio.sleep(0.05)
        recorder.remove_demo_source()
        assert recorder.has_demo_source is False
        count_after_stop = recorder.get_universes()[0].packet_count
        await asyncio.sleep(0.05)
        assert recorder.get_universes()[0].packet_count == count_after_stop  # no more ticks
        await recorder.close()

    asyncio.run(body())


def test_add_demo_source_twice_is_a_no_op(tmp_path):
    async def body():
        recorder = Recorder()
        recorder.add_demo_source(universe_count=2)
        first_task = recorder._demo_task
        recorder.add_demo_source(universe_count=5)  # ignored -- one already running
        assert recorder._demo_task is first_task
        await recorder.close()

    asyncio.run(body())


def test_current_preview_reflects_demo_source_state(tmp_path):
    async def body():
        recorder = Recorder()
        recorder.add_demo_source(universe_count=1, fps=100.0)
        await asyncio.sleep(0.05)
        preview = recorder.current_preview(0, "raw")
        assert preview is not None
        assert len(preview) == 512
        await recorder.close()

    asyncio.run(body())


def test_current_preview_out_of_range_row_returns_none(tmp_path):
    async def body():
        recorder = Recorder()
        preview = recorder.current_preview(0, "raw")
        assert preview is None
        await recorder.close()

    asyncio.run(body())
