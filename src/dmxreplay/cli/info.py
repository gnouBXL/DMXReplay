"""dmxreplay-info CLI. See docs/API.md §7."""
from __future__ import annotations

import argparse
import json
import sys

from ..container import DMXReplayReader


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dmxreplay-info",
        description="Print the manifest and container info for a .dmxr file.",
    )
    p.add_argument("input")
    p.add_argument(
        "--frames", action="store_true",
        help="Also print every frame's timestamp and active universe count (can be long)",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()
    with DMXReplayReader(args.input) as reader:
        manifest = reader.manifest
        print(json.dumps(manifest.to_dict(), indent=2))
        if args.frames:
            for i, frame in enumerate(reader.read_frames()):
                print(f"frame {i}: t={frame.timestamp_ns / 1e9:.3f}s universes={len(frame.universes)}", file=sys.stderr)


if __name__ == "__main__":
    main()
