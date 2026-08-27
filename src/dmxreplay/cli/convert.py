"""dmxreplay-convert CLI. See docs/API.md §7.

V1 scope: `--add-audio`, the one concrete, well-justified use case that
falls out of how audio muxing works (docs/CONTAINER.md's audio note): an
audio track can only be added to a DMXReplayWriter at construction, from an
already-complete source file, so "attach audio to a show recorded without
it" is naturally a convert operation, not something Recorder itself can do
mid-recording. Other possible conversions (re-encode to a different pixel
encoding, remap universes into a new file, change fps) remain unimplemented
-- brief §51 never specified them, so they're left for whenever a concrete
need defines their scope, rather than guessed at now.
"""
from __future__ import annotations

import argparse
import sys

from ..container import DMXReplayReader, DMXReplayWriter


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dmxreplay-convert",
        description="Convert or modify a .dmxr file. V1: --add-audio only.",
    )
    p.add_argument("input", help="Path to the source .dmxr file")
    p.add_argument("output", help="Path to write the converted .dmxr file")
    p.add_argument(
        "--add-audio", metavar="AUDIO_FILE", required=True,
        help="Audio file (any format PyAV/ffmpeg can decode) to mux in, re-encoded to AAC",
    )
    return p


def _run(args: argparse.Namespace) -> int:
    with DMXReplayReader(args.input) as reader:
        manifest = reader.manifest
        frames = list(reader.read_frames())

    if manifest.audio is not None:
        print(f"Warning: {args.input} already has an audio track; it will be replaced.", file=sys.stderr)
        manifest.audio = None  # DMXReplayWriter repopulates this from --add-audio

    with DMXReplayWriter(args.output, manifest, audio_path=args.add_audio) as writer:
        for frame in frames:
            writer.write_frame(frame)

    print(f"Wrote {args.output} ({len(frames)} DMX frames + audio from {args.add_audio}).", file=sys.stderr)
    return 0


def main() -> None:
    args = build_parser().parse_args()
    sys.exit(_run(args))


if __name__ == "__main__":
    main()
