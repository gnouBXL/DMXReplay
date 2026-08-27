"""dmxreplay-play CLI. See docs/API.md §7 and docs/RASPBERRY_PI.md §13
(--headless). This entry point never imports dmxreplay.ui, so it is headless
by construction -- the flag is accepted mainly for self-documentation and
for compatibility with the config-file-driven auto-start shape proposed in
docs/RASPBERRY_PI.md §14, not because behavior differs without it.

Interactive transport control (pause/seek/etc. while running) is not
implemented in this CLI yet -- docs/RASPBERRY_PI.md §13 defers designing
that control surface to Phase 6 rather than deciding it prematurely here.
This command loads, configures output, and plays straight through (once,
or looping) until it reaches the end or is interrupted (Ctrl+C/SIGTERM).
"""
from __future__ import annotations

import argparse
import asyncio
import signal
import sys

from ..player import Player


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dmxreplay-play",
        description="Play a .dmxr file, outputting DMX over Art-Net or sACN.",
    )
    p.add_argument("input", help="Path to the .dmxr file to play")
    p.add_argument(
        "--headless", action="store_true",
        help="No-op (this CLI never depends on a GUI); accepted for compatibility "
             "with the auto-start config shape in docs/RASPBERRY_PI.md §14.",
    )
    p.add_argument("--output", choices=["artnet", "sacn"], required=True)
    p.add_argument("--interface", default="0.0.0.0", help="IP address of the interface to send from")
    p.add_argument(
        "--destination", default=None,
        help="Unicast destination IP (default: broadcast for Art-Net, per-universe multicast for sACN)",
    )
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--priority", type=int, default=100, help="(sACN) sender priority, 0-200")
    p.add_argument(
        "--fps", type=float, default=None,
        help="Playback sampling rate (default: the file's own nominal fps, docs/TIMING.md §5)",
    )
    p.add_argument("--speed", type=float, default=1.0, help="Playback speed; negative plays in reverse")
    p.add_argument("--loop", action="store_true")
    p.add_argument("--seek", type=float, default=None, help="Seek to this many seconds before playing")
    return p


async def _run(args: argparse.Namespace) -> int:
    player = Player()
    player.load(args.input)
    print(
        f"Loaded {args.input}: {player.manifest.height} universe(s), "
        f"{player.duration_ns / 1e9:.2f}s @ {player.manifest.fps}fps nominal",
        file=sys.stderr,
    )

    protocol = "Art-Net" if args.output == "artnet" else "sACN"
    player.set_output(
        protocol, interface_ip=args.interface, destination_ip=args.destination,
        port=args.port, priority=args.priority,
    )
    if args.fps is not None:
        player.set_fps(args.fps)
    player.set_loop(args.loop)
    if args.seek is not None:
        player.seek(int(args.seek * 1_000_000_000))

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    await player.play(speed=args.speed)
    print("Playing -- press Ctrl+C to stop.", file=sys.stderr)

    try:
        if args.loop:
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
