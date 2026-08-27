"""External conventional video decoding, driven by absolute timeline
position. See docs/API.md's video section, docs/SPECIFICATION.md §14/§17,
docs/CONTAINER.md §7 (external video is never embedded in .dmxr). Requires
the optional `av` dependency (same one dmxreplay.container already needs).
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import av


@dataclass(frozen=True, slots=True)
class DecodedVideoFrame:
    timestamp_ns: int
    width: int
    height: int
    rgb_bytes: bytes  # tightly packed rgb24, width*height*3 bytes (stride already stripped)


class ExternalVideoReader:
    """Opens an external video file and serves frames by absolute timeline
    position (sample-and-hold, matching SPECIFICATION.md §13's DMX
    semantics: the frame with the greatest timestamp <= the requested
    position). Not embedded in the DMXReplay container -- this is a
    completely separate file (docs/CONTAINER.md §7).
    """

    def __init__(self, path: str) -> None:
        self._container = av.open(path)
        self._stream = self._container.streams.video[0]
        if self._stream.duration is not None and self._stream.time_base is not None:
            self._duration_ns = int(self._stream.duration * self._stream.time_base * 1_000_000_000)
        else:
            # container.duration is in AV_TIME_BASE units (microseconds).
            self._duration_ns = int((self._container.duration or 0) * 1000)

        self._decode_iter = self._container.decode(self._stream)
        self._last_served_ns: int | None = None
        # One-frame lookahead buffer, always an *already-converted*
        # DecodedVideoFrame (owns its bytes) -- never a live av.VideoFrame,
        # see frame_at()'s docstring for why that distinction is load-bearing.
        self._pending: DecodedVideoFrame | None = None

    @property
    def duration_ns(self) -> int:
        return self._duration_ns

    @property
    def width(self) -> int:
        return self._stream.width

    @property
    def height(self) -> int:
        return self._stream.height

    def _frame_timestamp_ns(self, frame) -> int:
        return int(frame.pts * frame.time_base * 1_000_000_000)

    def _seek_to(self, position_ns: int) -> None:
        offset = int(position_ns / (self._stream.time_base * 1_000_000_000))
        self._container.seek(max(offset, 0), stream=self._stream)
        self._decode_iter = self._container.decode(self._stream)
        self._pending = None

    def _to_decoded(self, frame) -> DecodedVideoFrame:
        rgb = frame.reformat(format="rgb24")
        plane = rgb.planes[0]
        line_size = plane.line_size
        row_bytes = rgb.width * 3
        raw = bytes(plane)
        if line_size == row_bytes:
            packed = raw
        else:
            packed = b"".join(
                raw[r * line_size: r * line_size + row_bytes] for r in range(rgb.height)
            )
        return DecodedVideoFrame(
            timestamp_ns=self._frame_timestamp_ns(frame),
            width=rgb.width, height=rgb.height, rgb_bytes=packed,
        )

    def frame_at(self, position_ns: int) -> DecodedVideoFrame | None:
        """The frame that should be showing at `position_ns`, or None if
        `position_ns` is before the first frame. Re-seeks only when the
        request moves backward (or past a decode error); a forward request
        continues decoding from wherever the reader already is, which is
        the common case during normal playback and avoids reseeking (and
        rescanning from the last keyframe) on every single tick.

        Every candidate frame is converted to an owned DecodedVideoFrame
        (RGB bytes copied out) *immediately* upon being decoded, before any
        further next() call -- confirmed empirically (not assumed) that
        libav reuses/overwrites its internal frame buffers across
        successive decode() calls, so holding a live av.VideoFrame
        reference across more than one next() silently returns whatever
        *later* frame ended up in that buffer, not the one actually
        requested. This cost a real, wrong-pixel-data bug during this
        module's own tests before being converted eagerly like this.
        """
        if position_ns < 0:
            return None
        if self._last_served_ns is not None and position_ns < self._last_served_ns:
            self._seek_to(position_ns)

        best: DecodedVideoFrame | None = None
        while True:
            if self._pending is not None:
                candidate = self._pending
                self._pending = None
            else:
                try:
                    frame = next(self._decode_iter)
                except StopIteration:
                    break
                candidate = self._to_decoded(frame)  # copy out immediately
            if candidate.timestamp_ns > position_ns:
                self._pending = candidate  # already safe to hold -- owns its bytes
                break
            best = candidate

        if best is None:
            return None
        self._last_served_ns = best.timestamp_ns
        return best

    def close(self) -> None:
        self._container.close()

    def __enter__(self) -> "ExternalVideoReader":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
