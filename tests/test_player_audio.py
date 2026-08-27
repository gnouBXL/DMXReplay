"""Player audio-sync tests. No audio hardware exists in this environment
(docs/RASPBERRY_PI.md), so these test the real sync *trigger logic* --
Player calling an AudioSink's load()/play()/stop() at the right times with
the right sample offsets -- against a recording test double that implements
the real dmxreplay.audio.AudioSink protocol, rather than against real sound
output."""
from __future__ import annotations

import asyncio
import math
import struct
import wave

from dmxreplay.codec import ENCODINGS
from dmxreplay.container import DMXReplayWriter
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe
from dmxreplay.metadata import Manifest, UniverseMapping
from dmxreplay.network.artnet import ArtNetListener
from dmxreplay.player import Player


class RecordingAudioSink:
    """Implements dmxreplay.audio.AudioSink for test assertions."""

    def __init__(self) -> None:
        self.loaded = None  # (pcm, sample_rate, channels, sample_width)
        self.play_calls: list[int] = []
        self.stop_count = 0

    def load(self, pcm_data, sample_rate, channels, sample_width):
        self.loaded = (pcm_data, sample_rate, channels, sample_width)

    def play(self, start_sample: int = 0) -> None:
        self.play_calls.append(start_sample)

    def stop(self) -> None:
        self.stop_count += 1


def _write_tone_wav(path: str, seconds: float = 0.5, sample_rate: int = 22050) -> None:
    n = int(seconds * sample_rate)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n):
            v = int(6000 * math.sin(2 * math.pi * 440 * i / sample_rate))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


def _make_dmxr_with_audio(dmxr_path: str, wav_path: str, frame_count: int = 5) -> None:
    mapping = [UniverseMapping.from_artnet_port_address(row=0, port_address=1)]
    manifest = Manifest(
        encoding="grayscale", fps=30.0, vfr=True, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS["grayscale"]["width"], height=1,
        universes=mapping, created_at="2026-08-27T00:00:00Z", duration_seconds=1.0,
        recorder={"name": "dmxreplay-tests", "version": "0.1.0-dev"},
    )
    with DMXReplayWriter(dmxr_path, manifest, audio_path=wav_path) as w:
        for t in range(frame_count):
            w.write_frame(DMXFrame(timestamp_ns=t * 33_333_333, universes=(Universe.blank(),)))


def test_player_reports_has_audio(tmp_path):
    wav_path = str(tmp_path / "tone.wav")
    _write_tone_wav(wav_path)
    dmxr_path = str(tmp_path / "s.dmxr")
    _make_dmxr_with_audio(dmxr_path, wav_path)

    player = Player()
    player.load(dmxr_path)
    assert player.has_audio is True


def test_player_without_audio_track_reports_false():
    # A file with no audio_path given at write time has no audio track --
    # reuse an existing helper pattern from test_player.py's own writer.
    import tempfile

    from dmxreplay.dmx import DMXFrame as _F
    from dmxreplay.dmx import Universe as _U

    mapping = [UniverseMapping.from_artnet_port_address(row=0, port_address=1)]
    manifest = Manifest(
        encoding="grayscale", fps=30.0, vfr=False, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS["grayscale"]["width"], height=1,
        universes=mapping, created_at="2026-08-27T00:00:00Z", duration_seconds=0.0,
        recorder={"name": "dmxreplay-tests", "version": "0.1.0-dev"},
    )
    with tempfile.TemporaryDirectory() as d:
        path = f"{d}/silent.dmxr"
        with DMXReplayWriter(path, manifest) as w:
            w.write_frame(_F(timestamp_ns=0, universes=(_U.blank(),)))
        player = Player()
        player.load(path)
        assert player.has_audio is False


def test_play_starts_audio_from_the_correct_offset(tmp_path):
    wav_path = str(tmp_path / "tone.wav")
    _write_tone_wav(wav_path, seconds=2.0)
    dmxr_path = str(tmp_path / "s.dmxr")
    # 40 frames * 33.33ms = ~1.33s of DMX video, so a 1.0s seek target below
    # is within range (SPECIFICATION.md §4 duration is set by the video
    # track, independent of the audio track's own length).
    _make_dmxr_with_audio(dmxr_path, wav_path, frame_count=40)

    sink = RecordingAudioSink()

    async def body():
        listener = ArtNetListener()
        await listener.start(interface_ip="127.0.0.1", port=0)
        port = listener._transport.get_extra_info("sockname")[1]

        player = Player()
        player.load(dmxr_path)
        player.set_audio_sink(sink)
        player.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)

        player.seek(1_000_000_000)  # 1.0s in, before playing
        await player.play()
        await asyncio.sleep(0.05)
        await player.stop()
        listener.stop()

    asyncio.run(body())

    assert sink.loaded is not None
    pcm, sample_rate, channels, sample_width = sink.loaded
    assert len(pcm) > 0
    assert len(sink.play_calls) >= 1
    # 1.0s in at the AAC-reencoded sample rate (48000, docs/CONTAINER.md) ->
    # start_sample should be at or very near 48000, not 0.
    assert sink.play_calls[0] > 40_000
    assert sink.stop_count >= 1  # stop() called by Player.stop()


def test_seek_while_playing_recues_audio(tmp_path):
    wav_path = str(tmp_path / "tone.wav")
    _write_tone_wav(wav_path)
    dmxr_path = str(tmp_path / "s.dmxr")
    _make_dmxr_with_audio(dmxr_path, wav_path)

    sink = RecordingAudioSink()

    async def body():
        listener = ArtNetListener()
        await listener.start(interface_ip="127.0.0.1", port=0)
        port = listener._transport.get_extra_info("sockname")[1]

        player = Player()
        player.load(dmxr_path)
        player.set_audio_sink(sink)
        player.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)

        await player.play()
        await asyncio.sleep(0.02)
        player.seek(2_000_000_000)  # jump to 2.0s while playing
        await asyncio.sleep(0.02)
        await player.stop()
        listener.stop()

    asyncio.run(body())

    assert len(sink.play_calls) >= 2  # initial play + re-cue after seek
    assert sink.play_calls[-1] > sink.play_calls[0]  # later seek -> later sample offset


def test_reverse_speed_stops_audio_instead_of_playing_it(tmp_path):
    wav_path = str(tmp_path / "tone.wav")
    _write_tone_wav(wav_path)
    dmxr_path = str(tmp_path / "s.dmxr")
    _make_dmxr_with_audio(dmxr_path, wav_path)

    sink = RecordingAudioSink()

    async def body():
        listener = ArtNetListener()
        await listener.start(interface_ip="127.0.0.1", port=0)
        port = listener._transport.get_extra_info("sockname")[1]

        player = Player()
        player.load(dmxr_path)
        player.set_audio_sink(sink)
        player.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=port)

        await player.play(speed=-1.0)
        await asyncio.sleep(0.02)
        await player.stop()
        listener.stop()

    asyncio.run(body())

    # AudioSink has no reverse-playback support (documented) -- must never
    # be told to play during reverse speed.
    assert sink.play_calls == []
