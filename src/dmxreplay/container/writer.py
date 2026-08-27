"""DMXReplay file writer: DMXFrame stream -> Matroska + FFV1 + manifest
attachment. See docs/CONTAINER.md. Requires the optional `av` dependency.
"""
from __future__ import annotations

from fractions import Fraction

import av

from ..codec.frame_codec import Encoding, dmxframe_to_pixel_rows
from ..codec.pixels import ENCODINGS
from ..codec.video_frame import pixel_rows_to_video_frame
from ..dmx import DMXFrame
from ..metadata import Manifest

# Measured, not assumed: ffmpeg's Matroska muxer hardcodes a 1ms
# TimecodeScale (no AVOption exposes a finer one -- confirmed via
# `ffmpeg -h muxer=matroska`, see FORMAT-RESEARCH.md §11). Requesting a finer
# time_base is silently overridden by the muxer, so DMXReplayWriter works in
# whole milliseconds explicitly rather than pretending otherwise.
STORAGE_TIME_BASE = Fraction(1, 1000)
STORAGE_TIMESTAMP_RESOLUTION_NS = 1_000_000

MANIFEST_ATTACHMENT_NAME = "dmxreplay-manifest.json"
MANIFEST_ATTACHMENT_MIMETYPE = "application/json"


class DMXReplayWriter:
    """Writes one DMXReplay (.dmxr) file. The manifest (SPECIFICATION.md §10)
    must be fully known at construction time -- in particular `encoding`,
    `width`, `height`, and `universes[]` -- because the video track's
    dimensions and the manifest attachment are both fixed at container-header
    time (docs/API.md's Recorder.start() happens after universe discovery,
    matching the brief §28 recorder GUI: universes are selected before
    recording starts).
    """

    def __init__(self, path: str, manifest: Manifest) -> None:
        spec = ENCODINGS[manifest.encoding]
        if manifest.width != spec["width"]:
            raise ValueError(
                f"manifest.width ({manifest.width}) does not match the "
                f"{manifest.encoding!r} encoding's required width ({spec['width']})"
            )

        self._manifest = manifest
        self._encoding: Encoding = manifest.encoding
        # Explicit format="matroska": the .dmxr extension (SPECIFICATION.md §2)
        # isn't a muxer libav recognizes by suffix, so it must be told what the
        # physical container actually is (docs/CONTAINER.md §1).
        self._container = av.open(path, mode="w", format="matroska")

        # NOTE: deliberately NOT passing rate=... to add_stream(), and setting
        # codec_context.time_base (not stream.time_base) directly. Verified
        # empirically (see FORMAT-RESEARCH.md "encoder time_base"): passing a
        # nominal rate pins the codec context's internal time_base to 1/rate,
        # and frame.pts values finer than that grid get silently rescaled/
        # truncated onto it *inside the encoder* -- two source frames 22ms
        # apart at 30fps (1/30 ~= 33ms ticks) both collapsed onto the same
        # output tick, destroying real VFR timing. Setting
        # codec_context.time_base directly avoids this; the manifest's own
        # `fps` field (SPECIFICATION.md §12) remains the nominal-rate source
        # of truth, independent of container-level framerate metadata.
        self._video_stream = self._container.add_stream("ffv1")
        self._video_stream.width = manifest.width
        self._video_stream.height = manifest.height
        self._video_stream.pix_fmt = spec["pix_fmt"]
        self._video_stream.codec_context.time_base = STORAGE_TIME_BASE

        self._container.add_attachment(
            MANIFEST_ATTACHMENT_NAME,
            MANIFEST_ATTACHMENT_MIMETYPE,
            manifest.to_json().encode("utf-8"),
        )

        self._last_pts_ms: int | None = None
        self._frame_count = 0
        self._closed = False

    def write_frame(self, frame: DMXFrame) -> None:
        """Encode and mux one DMXFrame. Timestamps are quantized to whole
        milliseconds (STORAGE_TIME_BASE) and forced strictly increasing --
        two source frames within the same millisecond collapse onto adjacent
        ms ticks rather than producing a non-monotonic or duplicate pts,
        which the muxer would reject (docs/TIMING.md §4.1 commit-policy note).
        """
        if self._closed:
            raise RuntimeError("cannot write_frame() after close()")
        if len(frame.universes) != self._manifest.height:
            raise ValueError(
                f"frame has {len(frame.universes)} universes, manifest declares "
                f"height={self._manifest.height}"
            )

        rows = dmxframe_to_pixel_rows(frame, self._encoding)
        video_frame = pixel_rows_to_video_frame(rows, self._encoding)

        pts_ms = round(frame.timestamp_ns / 1_000_000)
        if self._last_pts_ms is not None and pts_ms <= self._last_pts_ms:
            pts_ms = self._last_pts_ms + 1
        self._last_pts_ms = pts_ms

        video_frame.pts = pts_ms
        video_frame.time_base = STORAGE_TIME_BASE
        for packet in self._video_stream.encode(video_frame):
            self._container.mux(packet)
        self._frame_count += 1

    def close(self) -> None:
        if self._closed:
            return
        for packet in self._video_stream.encode():  # flush
            self._container.mux(packet)
        self._container.close()
        self._closed = True

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def __enter__(self) -> "DMXReplayWriter":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
