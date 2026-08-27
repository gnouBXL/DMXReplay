"""External video output sinks. Mirrors dmxreplay.audio.sink's shape and
rationale: a narrow protocol Player drives from the master Timeline, with a
no-op default and a headless-verifiable file-writing implementation. No
display/GPU output is implemented -- this project's environment is headless
with no display attached (see docs/RASPBERRY_PI.md), so a real on-screen
sink cannot be built *or verified* here; that's future GUI-phase work, to
be written and tested against an actual display rather than guessed at now.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .reader import DecodedVideoFrame


class VideoSink(Protocol):
    def present(self, frame: DecodedVideoFrame) -> None:
        """Show one decoded frame. Called only when the frame actually
        changes (Player only presents a new frame when the external video's
        own sample-and-hold-current frame changes, mirroring the DMX path)."""
        ...


class NullVideoSink:
    """Discards frames -- the default when no sink is configured. Always
    available, does nothing observable, never raises."""

    def present(self, frame: DecodedVideoFrame) -> None:
        pass


class PPMFileVideoSink:
    """Writes each presented frame as a numbered .ppm image (portable
    pixmap -- trivial uncompressed format, no extra dependency needed) into
    a directory. Useful for headless verification/debugging (confirm the
    right frame was selected for a given timeline position without needing
    a display) and for tests, exactly like WavFileAudioSink for audio."""

    def __init__(self, output_dir: str) -> None:
        self._dir = Path(output_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self.frame_count = 0
        self.last_frame: DecodedVideoFrame | None = None

    def present(self, frame: DecodedVideoFrame) -> None:
        self.last_frame = frame
        path = self._dir / f"frame_{self.frame_count:06d}_{frame.timestamp_ns}.ppm"
        header = f"P6\n{frame.width} {frame.height}\n255\n".encode("ascii")
        path.write_bytes(header + frame.rgb_bytes)
        self.frame_count += 1
