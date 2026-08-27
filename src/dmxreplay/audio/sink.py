"""Audio output sinks. See docs/API.md §Audio, docs/TIMING.md §1.

`AudioSink` is deliberately narrow: load a fully-decoded PCM buffer once,
then start/stop playback from a given sample offset. `Player` (Phase 6-7)
drives a sink's start()/stop() calls in lockstep with its Timeline -- audio
never runs its own clock (docs/TIMING.md §1). Once playback starts, the
sink's own hardware clock is what actually paces the sound; this version
does not discipline Timeline against it (documented limitation, see
docs/RASPBERRY_PI.md's audio section) -- acceptable at V1 scope since both
start from the same instant and typical show lengths won't accumulate
audible drift from that alone.
"""
from __future__ import annotations

from typing import Protocol


class AudioDeviceUnavailableError(RuntimeError):
    """Raised by a hardware AudioSink when no output device is available.
    Never raised by NullAudioSink or WavFileAudioSink."""


class AudioSink(Protocol):
    def load(self, pcm_data: bytes, sample_rate: int, channels: int, sample_width: int) -> None:
        """Provide the full, already-decoded PCM buffer (interleaved,
        signed little-endian integers of `sample_width` bytes/sample)."""
        ...

    def play(self, start_sample: int = 0) -> None:
        """Start playback from `start_sample` (samples, not bytes)."""
        ...

    def stop(self) -> None:
        """Stop playback immediately, if playing."""
        ...


class NullAudioSink:
    """Discards audio -- the default when no sink is configured. Always
    available, does nothing observable, never raises."""

    def load(self, pcm_data: bytes, sample_rate: int, channels: int, sample_width: int) -> None:
        pass

    def play(self, start_sample: int = 0) -> None:
        pass

    def stop(self) -> None:
        pass


class WavFileAudioSink:
    """Writes the loaded PCM to a .wav file instead of playing it -- useful
    for headless verification/debugging (confirm decode correctness without
    needing audio hardware) and for tests. play()/stop() only record their
    arguments (`last_play_start_sample`, `play_count`, `stopped`) for
    assertions; no actual timed playback happens."""

    def __init__(self, path: str) -> None:
        self._path = path
        self.last_play_start_sample: int | None = None
        self.play_count = 0
        self.stopped = False

    def load(self, pcm_data: bytes, sample_rate: int, channels: int, sample_width: int) -> None:
        import wave

        with wave.open(self._path, "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(sample_width)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm_data)

    def play(self, start_sample: int = 0) -> None:
        self.last_play_start_sample = start_sample
        self.play_count += 1
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class SoundDeviceAudioSink:
    """Real hardware output via the optional `sounddevice` dependency
    (`pip install dmxreplay[audio]`), which wraps PortAudio.

    NOTE: this class has not been exercised against real audio hardware in
    this project's development environment (no sound device was present --
    see docs/RASPBERRY_PI.md). `play()` raises AudioDeviceUnavailableError
    up front if no output device is present, rather than failing deeper
    inside PortAudio, so callers get a clear, catchable signal either way.
    """

    def __init__(self) -> None:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise ImportError(
                "SoundDeviceAudioSink requires the optional 'sounddevice' "
                "dependency: pip install dmxreplay[audio]"
            ) from exc
        self._sd = sd
        self._stream = None
        self._pcm: bytes | None = None
        self._sample_rate = 0
        self._channels = 0
        self._sample_width = 2

    def load(self, pcm_data: bytes, sample_rate: int, channels: int, sample_width: int) -> None:
        self._pcm = pcm_data
        self._sample_rate = sample_rate
        self._channels = channels
        self._sample_width = sample_width

    def _has_output_device(self) -> bool:
        try:
            device = self._sd.default.device
            output_index = device[1] if isinstance(device, (list, tuple)) else device
            return output_index is not None and output_index >= 0
        except Exception:
            return False

    def play(self, start_sample: int = 0) -> None:
        if self._pcm is None:
            raise RuntimeError("load() must be called before play()")
        if not self._has_output_device():
            raise AudioDeviceUnavailableError("no audio output device is available")

        dtype_name = {1: "int8", 2: "int16", 4: "int32"}[self._sample_width]
        frame_size = self._sample_width * self._channels
        byte_offset = start_sample * frame_size
        self.stop()
        # RawOutputStream takes raw interleaved bytes directly -- no numpy
        # dependency needed (consistent with dmxreplay.codec.pixels' own
        # numpy-free approach).
        self._stream = self._sd.RawOutputStream(
            samplerate=self._sample_rate, channels=self._channels, dtype=dtype_name,
        )
        self._stream.start()
        self._stream.write(self._pcm[byte_offset:])

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
