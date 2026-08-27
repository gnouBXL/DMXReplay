"""Real test of dmxreplay-convert --add-audio: reads an existing (silent)
.dmxr, writes a new one with a real audio track muxed in, and verifies both
the DMX content and the audio survive correctly."""
from __future__ import annotations

import math
import struct
import wave

from dmxreplay.cli import convert as convert_cli
from dmxreplay.codec import ENCODINGS
from dmxreplay.container import DMXReplayReader, DMXReplayWriter
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe
from dmxreplay.metadata import Manifest, UniverseMapping


def _write_tone_wav(path: str, seconds: float = 0.3, sample_rate: int = 22050) -> None:
    n = int(seconds * sample_rate)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n):
            v = int(5000 * math.sin(2 * math.pi * 440 * i / sample_rate))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


def test_add_audio_preserves_dmx_and_adds_a_real_audio_track(tmp_path):
    src_path = str(tmp_path / "silent.dmxr")
    mapping = [UniverseMapping.from_artnet_port_address(row=0, port_address=1)]
    manifest = Manifest(
        encoding="grayscale", fps=30.0, vfr=True, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS["grayscale"]["width"], height=1,
        universes=mapping, created_at="2026-08-27T00:00:00Z", duration_seconds=0.1,
        recorder={"name": "dmxreplay-tests", "version": "0.1.0-dev"},
    )
    frames = [
        DMXFrame(timestamp_ns=t * 33_333_333, universes=(Universe(channels=tuple((t * 5 + ch) % 256 for ch in range(CHANNELS_PER_UNIVERSE))),))
        for t in range(4)
    ]
    with DMXReplayWriter(src_path, manifest) as w:
        for f in frames:
            w.write_frame(f)

    wav_path = str(tmp_path / "tone.wav")
    _write_tone_wav(wav_path)
    out_path = str(tmp_path / "with_audio.dmxr")

    args = convert_cli.build_parser().parse_args([src_path, out_path, "--add-audio", wav_path])
    exit_code = convert_cli._run(args)
    assert exit_code == 0

    with DMXReplayReader(out_path) as reader:
        assert reader.has_audio is True
        pcm, sample_rate, channels, _width = reader.read_audio_pcm()
        decoded = list(reader.read_frames())

    assert len(pcm) > 0
    assert sample_rate == 48000
    assert channels == 1
    assert len(decoded) == 4
    for original, got in zip(frames, decoded):
        assert got.universes == original.universes


def test_convert_cli_parses_arguments():
    args = convert_cli.build_parser().parse_args(["in.dmxr", "out.dmxr", "--add-audio", "song.mp3"])
    assert args.input == "in.dmxr"
    assert args.output == "out.dmxr"
    assert args.add_audio == "song.mp3"
