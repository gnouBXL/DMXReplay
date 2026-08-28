"""dmxreplay-server CLI: runs the network Control API (cross-platform
extension Phase D, docs/API.md §10, docs/MOBILE_API.md) -- HTTP + WebSocket
commands over a PlayerService (and, with --enable-recorder, also a
RecorderService). This is the process docs/RASPBERRY_PI_INSTALL.md's
appliance flow ultimately runs headless on a Raspberry Pi; `dmxreplay-play`
remains the simpler play-straight-through CLI for one-off/scripted use.

Reuses `dmxreplay.config.PlayerConfig` (the same TOML shape
`dmxreplay-play --config` accepts, docs/RASPBERRY_PI.md §14) to auto-load
a show and output configuration at startup -- so the same config file
works whether the Pi is running the simple CLI or this server.
"""
from __future__ import annotations

import argparse
import os
import sys

from aiohttp import web

from ..config import PlayerConfig
from ..control import ApiToken, CommandRouter, ControlServer
from ..service import PlayerService, RecorderService

DEFAULT_TOKEN_FILENAME = ".dmxreplay-token"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dmxreplay-server",
        description="Run the DMXReplay network Control API (HTTP + WebSocket).",
    )
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument(
        "--shows-dir", default=None,
        help="Show library directory (dmxreplay.service.ShowLibrary) -- enables GET_SHOWS/NEXT/PREVIOUS",
    )
    p.add_argument(
        "--config", default=None,
        help="PlayerConfig TOML to auto-load a show/output at startup (docs/RASPBERRY_PI.md §14) -- same shape dmxreplay-play --config accepts",
    )
    p.add_argument(
        "--token-file", default=None,
        help=f"Path to persist/load the API auth token (default: <shows-dir or .>/{DEFAULT_TOKEN_FILENAME})",
    )
    p.add_argument(
        "--no-auth", action="store_true",
        help="Disable authentication entirely -- local dev only, never for a real deployment (docs/API.md §10)",
    )
    p.add_argument(
        "--enable-recorder", action="store_true",
        help="Also expose RECORD_START/RECORD_STOP over a RecorderService",
    )
    return p


def _build_services(args: argparse.Namespace) -> tuple[PlayerService, RecorderService | None]:
    player = PlayerService(shows_directory=args.shows_dir)
    recorder = RecorderService(shows_directory=args.shows_dir) if args.enable_recorder else None
    return player, recorder


def _apply_config(player: PlayerService, config: PlayerConfig) -> None:
    player.load_show(config.show)
    if config.video:
        player.load_external_video(config.video)
    player.set_output(
        "Art-Net" if config.output == "artnet" else "sACN",
        interface_ip=config.interface, destination_ip=config.destination,
        port=config.port, priority=config.priority,
    )
    player.set_loop(config.loop)
    if config.fps is not None:
        player.set_fps(config.fps)
    player.set_speed(config.speed)


def _build_token(args: argparse.Namespace) -> ApiToken | None:
    if args.no_auth:
        print(
            "WARNING: authentication disabled (--no-auth) -- do not expose this port "
            "beyond a fully trusted local network.", file=sys.stderr,
        )
        return None
    token_path = args.token_file or os.path.join(args.shows_dir or ".", DEFAULT_TOKEN_FILENAME)
    token = ApiToken.load_or_create(token_path)
    print(f"API token (enter this in the mobile app to pair): {token.value}", file=sys.stderr)
    print(f"  (persisted at {token_path} -- re-running reuses it)", file=sys.stderr)
    return token


def main() -> None:
    args = build_parser().parse_args()
    player, recorder = _build_services(args)

    autoplay = False
    if args.config:
        config = PlayerConfig.from_toml_file(args.config)
        _apply_config(player, config)
        autoplay = config.autoplay
        print(f"Loaded {config.show} from {args.config}", file=sys.stderr)

    token = _build_token(args)
    router = CommandRouter(player_service=player, recorder_service=recorder)
    server = ControlServer(router, token=token)

    async def _startup_play(app: web.Application) -> None:
        if autoplay:
            await player.play()

    async def _shutdown_services(app: web.Application) -> None:
        await player.shutdown()
        if recorder is not None:
            await recorder.shutdown()

    server.app.on_startup.append(_startup_play)
    server.app.on_cleanup.append(_shutdown_services)

    print(f"DMXReplay Control API listening on http://{args.host}:{args.port}/api/v1/", file=sys.stderr)
    web.run_app(server.app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
