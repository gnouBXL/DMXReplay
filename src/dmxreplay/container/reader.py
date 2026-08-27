"""DMXReplay file reader: Matroska + FFV1 + manifest attachment -> DMXFrame
stream. See docs/CONTAINER.md, docs/SPECIFICATION.md §2/§20 (Reader
conformance). Requires the optional `av` dependency.
"""
from __future__ import annotations

from typing import Iterator

import av

from ..codec.frame_codec import pixel_rows_to_dmxframe
from ..codec.video_frame import video_frame_to_pixel_rows
from ..dmx import DMXFrame
from ..metadata import Manifest
from .writer import MANIFEST_ATTACHMENT_NAME


class NotADMXReplayFileError(ValueError):
    """Raised when a file has no recognizable DMXReplay manifest attachment
    (SPECIFICATION.md §2: identification requires the manifest, not just the
    file extension or a grayscale-shaped video track)."""


class DMXReplayReader:
    """Reads one DMXReplay (.dmxr) file: parses the manifest, then decodes
    DMX frames on demand via read_frames()."""

    def __init__(self, path: str) -> None:
        self._container = av.open(path)
        self._manifest = self._load_manifest()
        self._video_stream = self._container.streams.video[0]

        # Decode audio eagerly, through a SEPARATE av.open() of the same
        # file. Confirmed empirically (not assumed): container.decode() on
        # one stream advances one shared demuxer read cursor past *every*
        # packet it encounters, including other streams' -- so decoding
        # audio first via the same container object left nothing for a
        # subsequent read_frames() video decode to find (it saw 0 frames
        # instead of the 5 that were actually written). A second, wholly
        # independent container avoids that rather than requiring callers to
        # decode video and audio in one combined pass. Eager (not lazy, like
        # read_frames()) for the same reason Player eager-loads all DMX
        # frames: simple and correct at V1 show lengths; a documented RAM
        # tradeoff, not a new one.
        self._audio_pcm: bytes | None = None
        self._audio_sample_rate = 0
        self._audio_channels = 0
        self._audio_sample_width = 2
        if self._container.streams.audio:
            self._decode_audio(path)

    def _load_manifest(self) -> Manifest:
        for stream in self._container.streams:
            if stream.type == "attachment" and stream.name == MANIFEST_ATTACHMENT_NAME:
                return Manifest.from_json(stream.data.decode("utf-8"))
        raise NotADMXReplayFileError(
            f"no {MANIFEST_ATTACHMENT_NAME!r} attachment found (SPECIFICATION.md §2)"
        )

    def _decode_audio(self, path: str) -> None:
        audio_container = av.open(path)
        try:
            astream = audio_container.streams.audio[0]
            self._audio_sample_rate = astream.rate
            self._audio_channels = 2 if astream.channels >= 2 else 1
            layout = "stereo" if self._audio_channels == 2 else "mono"
            resampler = av.AudioResampler(format="s16", layout=layout, rate=astream.rate)
            pcm = bytearray()
            for frame in audio_container.decode(astream):
                for resampled in resampler.resample(frame):
                    pcm += bytes(resampled.planes[0])
            self._audio_pcm = bytes(pcm)
        finally:
            audio_container.close()

    @property
    def manifest(self) -> Manifest:
        return self._manifest

    @property
    def has_audio(self) -> bool:
        return self._audio_pcm is not None

    def read_audio_pcm(self) -> tuple[bytes, int, int, int]:
        """(pcm_bytes, sample_rate, channels, sample_width_bytes) -- signed
        16-bit interleaved PCM, decoded from the file's AAC audio track."""
        if self._audio_pcm is None:
            raise RuntimeError("this file has no audio track (check has_audio first)")
        return self._audio_pcm, self._audio_sample_rate, self._audio_channels, self._audio_sample_width

    def read_frames(self) -> Iterator[DMXFrame]:
        """Decode every DMX video frame, in timeline order, reproducing each
        frame's stored timestamp (SPECIFICATION.md §20 Reader conformance).
        """
        for frame in self._container.decode(self._video_stream):
            timestamp_ns = round(frame.pts * frame.time_base * 1_000_000_000)
            rows = video_frame_to_pixel_rows(frame, self._manifest.encoding)
            yield pixel_rows_to_dmxframe(rows, timestamp_ns, self._manifest.encoding)

    def close(self) -> None:
        self._container.close()

    def __enter__(self) -> "DMXReplayReader":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
