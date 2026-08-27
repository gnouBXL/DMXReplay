"""External conventional video, synchronized to the master timeline
(Phase 8). See docs/CONTAINER.md §7: never embedded in .dmxr, always a
separate file the player loads alongside it."""
from .reader import DecodedVideoFrame, ExternalVideoReader
from .sink import NullVideoSink, PPMFileVideoSink, VideoSink

__all__ = [
    "ExternalVideoReader",
    "DecodedVideoFrame",
    "VideoSink",
    "NullVideoSink",
    "PPMFileVideoSink",
]
