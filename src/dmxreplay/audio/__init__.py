"""Audio output, synchronized to the master timeline (Phase 7). See
docs/TIMING.md §1, docs/API.md. `NullAudioSink`/`WavFileAudioSink` need no
extra dependency or hardware; `SoundDeviceAudioSink` needs the optional
`sounddevice` dependency and a real output device."""
from .sink import (
    AudioDeviceUnavailableError,
    AudioSink,
    NullAudioSink,
    SoundDeviceAudioSink,
    WavFileAudioSink,
)

__all__ = [
    "AudioSink",
    "AudioDeviceUnavailableError",
    "NullAudioSink",
    "WavFileAudioSink",
    "SoundDeviceAudioSink",
]
