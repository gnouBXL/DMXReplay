"""dmxreplay-play CLI. See docs/API.md §7 and docs/RASPBERRY_PI.md §13
(--headless). This entry point never imports dmxreplay.ui, so it is headless
by construction -- the flag is accepted mainly for self-documentation and
for compatibility with the config-file-driven auto-start shape proposed in
docs/RASPBERRY_PI.md §14.

`--config` (Phase B of the cross-platform extension, docs/ARCHITECTURE.md)
loads a dmxreplay.config.PlayerConfig from a TOML file -- the systemd-unit-
friendly way to start this CLI with no other flags at all
(docs/RASPBERRY_PI_INSTALL.md). Explicit CLI flags always override the
matching config value when both are given.

Interactive transport control (pause/seek/etc. while running) is not
implemented in this CLI yet -- that's Phase C (docs/ARCHITECTURE.md's
long-running commandable service), tracked separately rather than decided
prematurely here. This command loads, configures output, and plays
straight through (once, or looping) until it reaches the end or is
interrupted (Ctrl+C/SIGTERM) -- or, if autoplay is disabled, loads and
idles without playing, ready for a future control surface to attach.
"""
from __future__ import annotations

import argparse
import asyncio
import signal
import sys

from ..config import InvalidPlayerConfigError, PlayerConfig
from ..player import Player


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dmxreplay-play",
        description="Play a .dmxr file, outputting DMX over Art-Net or sACN.",
    )
    p.add_argument("input", nargs="?", default=None, help="Path to the .dmxr file to play (omit if --config sets 'show')")
    p.add_argument(
        "--headless", action="store_true",
        help="No-op (this CLI never depends on a GUI); accepted for compatibility "
             "with the auto-start config shape in docs/RASPBERRY_PI.md §14.",
    )
    p.add_argument(
        "--config", default=None,
        help="Load defaults from a TOML config file (dmxreplay.config.PlayerConfig, "
             "docs/RASPBERRY_PI.md §14). Explicit flags below override matching config values.",
    )
    p.add_argument("--video", default=None, help="External video file to play alongside the show (docs/CONTAINER.md §7)")
    p.add_argument("--output", choices=["artnet", "sacn"], default=None)
    p.add_argument("--interface", default=None, help="IP address of the interface to send from")
    p.add_argument(
        "--destination", default=None,
        help="Unicast destination IP (default: broadcast for Art-Net, per-universe multicast for sACN)",
    )
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--priority", type=int, default=None, help="(sACN) sender priority, 0-200")
    p.add_argument(
        "--fps", type=float, default=None,
        help="Playback sampling rate (default: the file's own nominal fps, docs/TIMING.md §5)",
    )
    p.add_argument("--speed", type=float, default=None, help="Playback speed; negative plays in reverse")
    p.add_argument("--loop", action="store_true", default=None)
    p.add_argument(
        "--autoplay", action="store_true", default=None,
        help="Start playing immediately (default: true unless --config sets autoplay=false)",
    )
    p.add_argument("--seek", type=float, default=None, help="Seek to this many seconds before playing")
    return p


def _merge_config(args: argparse.Namespace, parser: argparse.ArgumentParser) -> PlayerConfig:
    """Build one effective PlayerConfig from --config (if given) with every
    explicitly-passed CLI flag overriding the matching config field. A bare
    CLI invocation (no --config) is just PlayerConfig(**args) with its own
    defaults, so --config is never required."""
    if args.config is not None:
        try:
            config = PlayerConfig.from_toml_file(args.config)
        except (InvalidPlayerConfigError, OSError) as exc:
            parser.error(f"--config {args.config}: {exc}")
    else:
        if args.input is None:
            parser.error("the following arguments are required: input (or use --config with 'show' set)")
        if args.output is None:
            parser.error("the following arguments are required: --output (or use --config with 'output' set)")
        config = PlayerConfig(show=args.input, output=args.output)

    if args.input is not None:
        config.show = args.input
    if args.video is not None:
        config.video = args.video
    if args.output is not None:
        config.output = args.output
    if args.interface is not None:
        config.interface = args.interface
    if args.destination is not None:
        config.destination = args.destination
    if args.port is not None:
        config.port = args.port
    if args.priority is not None:
        config.priority = args.priority
    if args.fps is not None:
        config.fps = args.fps
    if args.speed is not None:
        config.speed = args.speed
    if args.loop is not None:
        config.loop = args.loop
    if args.autoplay is not None:
        config.autoplay = args.autoplay
    return config


async def _run(args: argparse.Namespace) -> int:
    parser = build_parser()
    config = _merge_config(args, parser)

    player = Player()
    player.load(config.show)
    print(
        f"Loaded {config.show}: {player.manifest.height} universe(s), "
        f"{player.duration_ns / 1e9:.2f}s @ {player.manifest.fps}fps nominal",
        file=sys.stderr,
    )
    if config.video:
        player.load_external_video(config.video)
        print(f"External video: {config.video}", file=sys.stderr)

    protocol = "Art-Net" if config.output == "artnet" else "sACN"
    player.set_output(
        protocol, interface_ip=config.interface, destination_ip=config.destination,
        port=config.port, priority=config.priority,
    )
    if config.fps is not None:
        player.set_fps(config.fps)
    player.set_loop(config.loop)
    if args.seek is not None:
        player.seek(int(args.seek * 1_000_000_000))

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    if not config.autoplay:
        # Loaded and output-configured, but not playing -- idle until
        # interrupted. There is no control surface yet to tell this
        # process to start later (that's Phase C); this state exists so
        # the process/service itself can still start successfully and be
        # observed (e.g. by a health check) rather than exiting immediately.
        print("Loaded, autoplay disabled -- idling. Press Ctrl+C to stop.", file=sys.stderr)
        await stop_event.wait()
        return 0

    await player.play(speed=config.speed)
    print("Playing -- press Ctrl+C to stop.", file=sys.stderr)

    try:
        if config.loop:
            await stop_event.wait()
        else:
            remaining_s = max(0.0, (player.duration_ns - player.position_ns) / 1e9)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=remaining_s + 1.0)
            except asyncio.TimeoutError:
                pass  # reached the end of the file naturally
    finally:
        await player.stop()
        print("Stopped.", file=sys.stderr)
    return 0


def main() -> None:
    args = build_parser().parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
