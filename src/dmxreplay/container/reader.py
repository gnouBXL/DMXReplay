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

    def _load_manifest(self) -> Manifest:
        for stream in self._container.streams:
            if stream.type == "attachment" and stream.name == MANIFEST_ATTACHMENT_NAME:
                return Manifest.from_json(stream.data.decode("utf-8"))
        raise NotADMXReplayFileError(
            f"no {MANIFEST_ATTACHMENT_NAME!r} attachment found (SPECIFICATION.md §2)"
        )

    @property
    def manifest(self) -> Manifest:
        return self._manifest

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
