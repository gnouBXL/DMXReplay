from __future__ import annotations

import wave

import pytest

from dmxreplay.audio import (
    AudioDeviceUnavailableError,
    NullAudioSink,
    SoundDeviceAudioSink,
    WavFileAudioSink,
)


def _tone_pcm(n_samples: int = 100, channels: int = 2, sample_width: int = 2) -> bytes:
    # Simple ramp "tone" -- not a real sine wave, just deterministic bytes.
    frame = bytearray()
    for i in range(n_samples):
        for _ch in range(channels):
            value = (i * 37) % 32768
            frame += value.to_bytes(sample_width, "little", signed=False)
    return bytes(frame)


def test_null_audio_sink_never_raises():
    sink = NullAudioSink()
    sink.load(_tone_pcm(), sample_rate=44100, channels=2, sample_width=2)
    sink.play(start_sample=10)
    sink.stop()  # just must not raise


def test_wav_file_sink_writes_a_valid_readable_wav(tmp_path):
    path = str(tmp_path / "out.wav")
    pcm = _tone_pcm(n_samples=50, channels=2, sample_width=2)
    sink = WavFileAudioSink(path)
    sink.load(pcm, sample_rate=48000, channels=2, sample_width=2)

    with wave.open(path, "rb") as wav:
        assert wav.getnchannels() == 2
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 48000
        read_back = wav.readframes(wav.getnframes())
    assert read_back == pcm  # byte-exact: this sink must not alter samples


def test_wav_file_sink_tracks_play_and_stop_calls():
    sink = WavFileAudioSink("/dev/null")  # not read back in this test
    sink.load(_tone_pcm(), sample_rate=44100, channels=1, sample_width=2)
    assert sink.play_count == 0

    sink.play(start_sample=123)
    assert sink.play_count == 1
    assert sink.last_play_start_sample == 123
    assert sink.stopped is False

    sink.stop()
    assert sink.stopped is True

    sink.play(start_sample=0)
    assert sink.play_count == 2


def test_sounddevice_sink_construction_and_play_without_hardware():
    """Real test against the real optional dependency: in this development
    sandbox there is no audio output device (docs/RASPBERRY_PI.md), so
    play() must raise AudioDeviceUnavailableError -- a clear, catchable
    signal -- rather than hanging or crashing inside PortAudio."""
    sd = pytest.importorskip("sounddevice")
    try:
        sd.query_devices()
    except Exception as exc:
        pytest.skip(f"PortAudio not usable in this environment: {exc}")

    sink = SoundDeviceAudioSink()
    sink.load(_tone_pcm(), sample_rate=44100, channels=2, sample_width=2)
    with pytest.raises(AudioDeviceUnavailableError):
        sink.play()
