"""dmxreplay-record CLI. See docs/API.md §7."""
from __future__ import annotations

import argparse
import asyncio
import signal
import sys

from ..recorder import Recorder


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dmxreplay-record",
        description="Record a live Art-Net or sACN DMX stream to a .dmxr file.",
    )
    p.add_argument("--input", choices=["artnet", "sacn"], required=True)
    p.add_argument(
        "--interface", default="0.0.0.0",
        help="IP address of the network interface to listen on (default: all interfaces). "
             "Resolving a device name like 'eth0' to an IP is not implemented -- pass the IP directly.",
    )
    p.add_argument("--port", type=int, default=None, help="UDP port (default: protocol standard)")
    p.add_argument("--fps", type=float, default=30.0, help="Nominal frame rate stored in the manifest")
    p.add_argument("--encoding", choices=["grayscale", "rgb_packed"], default="grayscale")
    p.add_argument("--output", required=True, help="Output .dmxr path")
    p.add_argument(
        "--discovery-seconds", type=float, default=3.0,
        help="How long to listen for universes before recording starts (brief §28 discovery phase)",
    )
    p.add_argument(
        "--multicast-universe", type=int, action="append", default=None,
        help="(sACN) join the multicast group for this universe; repeatable",
    )
    return p


async def _run(args: argparse.Namespace) -> int:
    protocol = "Art-Net" if args.input == "artnet" else "sACN"
    recorder = Recorder()
    await recorder.add_source(
        protocol, interface_ip=args.interface, port=args.port,
        multicast_universes=args.multicast_universe,
    )

    print(
        f"Listening for {protocol} on {args.interface} "
        f"(discovering universes for {args.discovery_seconds}s)...", file=sys.stderr,
    )
    await asyncio.sleep(args.discovery_seconds)

    rows = recorder.get_universes()
    if not rows:
        print("No DMX universes detected -- nothing to record.", file=sys.stderr)
        await recorder.close()
        return 1

    print(f"Discovered {len(rows)} universe(s):", file=sys.stderr)
    for r in rows:
        addr = (
            f"net={r.net} subnet={r.subnet} universe={r.universe}"
            if r.protocol == "Art-Net" else f"universe={r.universe}"
        )
        print(f"  row {r.row}: {r.protocol} {addr} (from {r.source_ip})", file=sys.stderr)

    recorder.start(args.output, encoding=args.encoding, fps=args.fps)
    print(f"Recording to {args.output} -- press Ctrl+C to stop.", file=sys.stderr)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass  # e.g. Windows

    try:
        await stop_event.wait()
    finally:
        recorder.stop()
        status = recorder.get_status()
        await recorder.close()
        print(
            f"Stopped. {status.frame_count} frames, {status.file_size_bytes} bytes, "
            f"{status.duration_seconds:.2f}s, {status.malformed_packets} malformed packets dropped.",
            file=sys.stderr,
        )
    return 0


def main() -> None:
    args = build_parser().parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
