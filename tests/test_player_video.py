"""Player external-video-sync tests. No display exists in this environment
(docs/RASPBERRY_PI.md), so these verify the real sync logic -- Player
presenting the correct external-video frame for the current Timeline
position, in lockstep with DMX -- via a recording test double, plus the
real PPMFileVideoSink (headless-verifiable, writes actual image files)."""
from __future__ import annotations

import asyncio
from fractions import Fraction

import av
import pytest

from dmxreplay.codec import ENCODINGS
from dmxreplay.container import DMXReplayWriter
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe
from dmxreplay.metadata import Manifest, UniverseMapping
from dmxreplay.network.artnet import ArtNetListener
from dmxreplay.player import Player
from dmxreplay.video import DecodedVideoFrame, PPMFileVideoSink


class RecordingVideoSink:
    def __init__(self) -> None:
        self.presented: list[DecodedVideoFrame] = []

    def present(self, frame: DecodedVideoFrame) -> None:
        self.presented.append(frame)


def _make_test_video(path: str, fps: int = 25, frame_count: int = 50, width: int = 32, height: int = 24) -> None:
    container = av.open(path, mode="w")
    stream = container.add_stream("libx264", rate=fps)
    stream.width, stream.height = width, height
    stream.pix_fmt = "yuv420p"
    stream.codec_context.time_base = Fraction(1, 1000)
    stream.codec_context.options = {"crf": "0", "preset": "ultrafast"}
    stream.codec_context.color_range = 2  # see tests/test_video_reader.py's note

    for i in range(frame_count):
        frame = av.VideoFrame(width, height, format="yuv420p")
        y, u, v = frame.planes
        y.update(bytes([i % 256]) * y.buffer_size)
        u.update(bytes([128]) * u.buffer_size)
        v.update(bytes([128]) * v.buffer_size)
        frame.pts = round(i * 1000 / fps)
        frame.time_base = Fraction(1, 1000)
        for p in stream.encode(frame):
            container.mux(p)
    for p in stream.encode():
        container.mux(p)
    container.close()


def _make_dmxr(path: str, frame_count: int = 60, period_ns: int = 33_333_333) -> None:
    mapping = [UniverseMapping.from_artnet_port_address(row=0, port_address=1)]
    manifest = Manifest(
        encoding="grayscale", fps=30.0, vfr=False, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS["grayscale"]["width"], height=1,
        universes=mapping, created_at="2026-08-27T00:00:00Z",
        duration_seconds=frame_count * period_ns / 1e9,
        recorder={"name": "dmxreplay-tests", "version": "0.1.0-dev"},
    )
    with DMXReplayWriter(path, manifest) as w:
        for t in range(frame_count):
            w.write_frame(DMXFrame(timestamp_ns=t * period_ns, universes=(Universe.blank(),)))


@pytest.fixture
def dmxr_and_video(tmp_path):
    dmxr_path = str(tmp_path / "s.dmxr")
    video_path = str(tmp_path / "s.mp4")
    _make_dmxr(dmxr_path)  # ~2s of DMX content
    _make_test_video(video_path)  # 2s of video content
    return dmxr_path, video_path


def test_has_external_video_reflects_load_external_video(dmxr_and_video):
    dmxr_path, video_path = dmxr_and_video
    player = Player()
    player.load(dmxr_path)
    assert player.has_external_video is False
    player.load_external_video(video_path)
    assert player.has_external_video is True


def test_play_presents_video_frames_in_sync_with_dmx(dmxr_and_video):
    dmxr_path, video_path = dmxr_and_video
    sink = RecordingVideoSink()

    async def body():
        listener = ArtNetListener()
        await listener.start(interface_ip="127.0.0.1", port=0)
        port = listener._transport.get_extra_info("sockname")[1]

        player = Player()
        player.load(dmxr_path)
        player.load_external_video(video_path)
        player.set_video_sink(sink)
        player.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)

        await player.play()
        await asyncio.sleep(0.3)
        await player.stop()
        listener.stop()

    asyncio.run(body())

    assert len(sink.presented) >= 2
    # Video is a 25fps source; presented frame values (Y under neutral
    # chroma survives as R -- see test_video_reader.py) must be
    # non-decreasing, proving frames were selected in correct time order.
    values = [f.rgb_bytes[0] for f in sink.presented]
    assert values == sorted(values)
    assert values[0] == 0


def test_seek_recues_video_to_the_correct_frame(dmxr_and_video):
    dmxr_path, video_path = dmxr_and_video
    sink = RecordingVideoSink()

    async def body():
        listener = ArtNetListener()
        await listener.start(interface_ip="127.0.0.1", port=0)
        port = listener._transport.get_extra_info("sockname")[1]

        player = Player()
        player.load(dmxr_path)
        player.load_external_video(video_path)
        player.set_video_sink(sink)
        player.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)

        player.seek(1_000_000_000)  # 1.0s in -> video frame 25 (Y=25)
        await player.play()
        await asyncio.sleep(0.05)
        await player.stop()
        listener.stop()

    asyncio.run(body())

    assert len(sink.presented) >= 1
    assert sink.presented[0].rgb_bytes[0] >= 20  # near frame 25, allowing a little tick slack


def test_ppm_sink_writes_real_files_during_playback(dmxr_and_video, tmp_path):
    dmxr_path, video_path = dmxr_and_video
    out_dir = str(tmp_path / "frames")
    sink = PPMFileVideoSink(out_dir)

    async def body():
        listener = ArtNetListener()
        await listener.start(interface_ip="127.0.0.1", port=0)
        port = listener._transport.get_extra_info("sockname")[1]

        player = Player()
        player.load(dmxr_path)
        player.load_external_video(video_path)
        player.set_video_sink(sink)
        player.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)

        await player.play()
        await asyncio.sleep(0.2)
        await player.stop()
        listener.stop()

    asyncio.run(body())

    assert sink.frame_count >= 1
    written = list((tmp_path / "frames").glob("*.ppm"))
    assert len(written) == sink.frame_count
