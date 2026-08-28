"""Long-running, commandable Player/Recorder services (cross-platform
extension Phase C, docs/ARCHITECTURE.md). Plain asyncio-native Python
objects -- no network, no GUI toolkit -- that stay alive and accept new
commands after a transport (play()/start()) begins, unlike
`dmxreplay-play`/`dmxreplay-record`'s CLI wrappers, which run once to
completion. Phase D's HTTP/WebSocket Control API is a thin layer over
these same classes; the real-time playback/capture loop stays inside
`dmxreplay.player.Player`/`dmxreplay.recorder.Recorder`, never duplicated
here.
"""
from .player_service import PlayerService, PlayerStatus
from .recorder_service import RecorderService
from .show_library import ShowLibrary, ShowNotFoundError

__all__ = [
    "PlayerService",
    "PlayerStatus",
    "RecorderService",
    "ShowLibrary",
    "ShowNotFoundError",
]
