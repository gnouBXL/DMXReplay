"""Real audio muxing tests: a real WAV tone gets encoded to AAC and muxed
alongside the DMX video track (via PyAV, no ffmpeg subprocess), then read
back and decoded, using dmxreplay.container's real writer/reader."""
from __future__ import annotations

import math
import struct
import wave

from dmxreplay.codec import ENCODINGS
from dmxreplay.container import DMXReplayReader, DMXReplayWriter
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe
from dmxreplay.metadata import Manifest, UniverseMapping


def _write_tone_wav(path: str, seconds: float = 0.5, freq: float = 440.0, sample_rate: int = 22050) -> None:
    n = int(seconds * sample_rate)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n):
            v = int(8000 * math.sin(2 * math.pi * freq * i / sample_rate))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


def _manifest(universe_count: int = 1) -> Manifest:
    mapping = [
        UniverseMapping.from_artnet_port_address(row=i, port_address=i + 1)
        for i in range(universe_count)
    ]
    return Manifest(
        encoding="grayscale", fps=30.0, vfr=True, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS["grayscale"]["width"], height=universe_count,
        universes=mapping, created_at="2026-08-27T00:00:00Z", duration_seconds=1.0,
        recorder={"name": "dmxreplay-tests", "version": "0.1.0-dev"},
    )


def test_writer_without_audio_produces_no_audio_track(tmp_path):
    path = str(tmp_path / "silent.dmxr")
    with DMXReplayWriter(path, _manifest()) as w:
        w.write_frame(DMXFrame(timestamp_ns=0, universes=(Universe.blank(),)))
    with DMXReplayReader(path) as r:
        assert r.has_audio is False


def test_writer_muxes_real_audio_and_reader_decodes_it(tmp_path):
    wav_path = str(tmp_path / "tone.wav")
    _write_tone_wav(wav_path, seconds=0.3)

    dmxr_path = str(tmp_path / "with_audio.dmxr")
    manifest = _manifest()
    with DMXReplayWriter(dmxr_path, manifest, audio_path=wav_path) as w:
        for t in range(5):
            u = Universe(channels=tuple((t + ch) % 256 for ch in range(CHANNELS_PER_UNIVERSE)))
            w.write_frame(DMXFrame(timestamp_ns=t * 33_333_333, universes=(u,)))

    # Manifest's audio field is populated as a side effect of muxing (writer.py).
    assert manifest.audio == {"codec": "aac", "sample_rate": 48000, "channels": 1}

    with DMXReplayReader(dmxr_path) as reader:
        assert reader.has_audio is True
        assert reader.manifest.audio["codec"] == "aac"
        pcm, sample_rate, channels, sample_width = reader.read_audio_pcm()

        # DMX video content must be completely unaffected by adding audio.
        decoded_frames = list(reader.read_frames())

    assert sample_rate == 48000
    assert channels == 1
    assert sample_width == 2
    assert len(pcm) > 0
    # ~0.3s of 48kHz mono 16-bit audio, plus AAC's known encoder priming
    # delay (~1024-2112 samples -- see docs/CONTAINER.md's audio note): not
    # an exact byte count, but must be in the right ballpark, not empty or
    # wildly larger/smaller.
    expected_min_samples = int(0.3 * 48000 * 0.9)
    actual_samples = len(pcm) // (sample_width * channels)
    assert actual_samples >= expected_min_samples

    assert len(decoded_frames) == 5
    for t, frame in enumerate(decoded_frames):
        expected = Universe(channels=tuple((t + ch) % 256 for ch in range(CHANNELS_PER_UNIVERSE)))
        assert frame.universes[0] == expected


def test_stereo_source_audio_is_preserved_as_stereo(tmp_path):
    wav_path = str(tmp_path / "stereo.wav")
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(22050)
        n = 2205
        frames = bytearray()
        for i in range(n):
            v = int(4000 * math.sin(2 * math.pi * 440 * i / 22050))
            frames += struct.pack("<hh", v, -v)
        w.writeframes(bytes(frames))

    dmxr_path = str(tmp_path / "stereo.dmxr")
    with DMXReplayWriter(dmxr_path, _manifest(), audio_path=wav_path) as w:
        w.write_frame(DMXFrame(timestamp_ns=0, universes=(Universe.blank(),)))

    with DMXReplayReader(dmxr_path) as reader:
        _pcm, _rate, channels, _width = reader.read_audio_pcm()
    assert channels == 2
