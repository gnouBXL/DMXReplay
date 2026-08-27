#!/usr/bin/env python3
"""DMXReplay Phase 0 format benchmark harness.

Generates synthetic DMX-shaped frame sequences, encodes/decodes them with real
ffmpeg container/codec combinations, and measures:

  - losslessness (exact byte-for-byte round trip)
  - file size
  - encode wall-clock time
  - decode wall-clock time
  - peak RSS during encode/decode (via GNU `time -v`)
  - approximate seek latency

This produces the data behind ../FORMAT-RESEARCH.md. It does not simulate numbers:
every row in results.json comes from an actual `ffmpeg`/`ffprobe` invocation on this
machine. Absolute numbers will vary by machine; the *relative* comparison and the
correctness/support findings (does mp4 accept ffv1? is grayscale really byte-identical
after a round trip?) are what the recommendation in FORMAT-RESEARCH.md is based on.

Usage:
    python3 benchmark/format_benchmark.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
RESULTS_PATH = ROOT / "results.json"

FPS = 30
CHANNELS_PER_UNIVERSE = 512
RGB_PIXELS_PER_UNIVERSE = -(-CHANNELS_PER_UNIVERSE // 3)  # ceil(512/3) = 171


# --------------------------------------------------------------------------- #
# Synthetic DMX pattern generation (no numpy dependency, kept intentionally
# minimal so the benchmark harness has no non-stdlib requirements).
# --------------------------------------------------------------------------- #

def pattern_ramp(frame: int, channel: int) -> int:
    """Every channel changes every frame -- worst case for intra-frame delta coding."""
    return (frame + channel) % 256


def pattern_alternating(frame: int, channel: int) -> int:
    """Highly compressible: whole frame flips between 0 and 255."""
    return 0 if frame % 2 == 0 else 255


def _det_random(seed: int, frame: int, channel: int) -> int:
    # Deterministic pseudo-random byte from (seed, frame, channel): fast, reproducible,
    # no per-call Random object construction overhead.
    x = (seed * 2654435761 + frame * 40503 + channel * 2246822519) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 2246822519) & 0xFFFFFFFF
    x ^= x >> 13
    return x & 0xFF


PATTERNS = {
    "ramp": pattern_ramp,
    "alternating": pattern_alternating,
    "random": lambda frame, channel: _det_random(1234, frame, channel),
}


def build_grayscale_sequence(pattern, universes: int, frames: int) -> bytes:
    width = CHANNELS_PER_UNIVERSE
    height = universes
    buf = bytearray(width * height * frames)
    i = 0
    for f in range(frames):
        for u in range(height):
            for ch in range(width):
                buf[i] = pattern(f, ch)  # pattern is universe-agnostic by design (§5/§6)
                i += 1
    return bytes(buf), width, height


def build_rgb_sequence(pattern, universes: int, frames: int) -> bytes:
    width = RGB_PIXELS_PER_UNIVERSE
    height = universes
    buf = bytearray(width * 3 * height * frames)
    i = 0
    for f in range(frames):
        for u in range(height):
            for p in range(width):
                for comp in range(3):
                    ch = p * 3 + comp
                    buf[i] = pattern(f, ch) if ch < CHANNELS_PER_UNIVERSE else 0
                    i += 1
    return bytes(buf), width, height


# --------------------------------------------------------------------------- #
# ffmpeg / GNU time wrappers
# --------------------------------------------------------------------------- #

HAVE_GNU_TIME = shutil.which("time") is not None or Path("/usr/bin/time").exists()


@dataclass
class RunResult:
    ok: bool
    wall_seconds: float
    max_rss_kb: int | None
    cpu_percent: str | None
    stderr_tail: str


def run_timed(cmd: list[str]) -> RunResult:
    timelog = OUT / "_time.log"
    if timelog.exists():
        timelog.unlink()
    full_cmd = ["/usr/bin/time", "-v", "-o", str(timelog), *cmd]
    t0 = time.perf_counter()
    proc = subprocess.run(full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    wall = time.perf_counter() - t0
    max_rss = None
    cpu_pct = None
    if timelog.exists():
        text = timelog.read_text()
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("Maximum resident set size"):
                max_rss = int(line.split(":")[-1].strip())
            elif line.startswith("Percent of CPU"):
                cpu_pct = line.split(":")[-1].strip()
    return RunResult(
        ok=proc.returncode == 0,
        wall_seconds=wall,
        max_rss_kb=max_rss,
        cpu_percent=cpu_pct,
        stderr_tail="\n".join(proc.stderr.decode(errors="replace").splitlines()[-15:]),
    )


def encode(raw_path: Path, width: int, height: int, pix_fmt: str, codec: str,
           container_ext: str, out_path: Path) -> RunResult:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", pix_fmt, "-s", f"{width}x{height}", "-r", str(FPS),
        "-i", str(raw_path),
        "-c:v", codec,
    ]
    if codec != "rawvideo":
        cmd += ["-pix_fmt", pix_fmt]
    cmd += [str(out_path)]
    return run_timed(cmd)


def decode(in_path: Path, pix_fmt: str, out_raw: Path) -> RunResult:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(in_path),
        "-f", "rawvideo", "-pix_fmt", pix_fmt,
        str(out_raw),
    ]
    return run_timed(cmd)


def measure_seek(in_path: Path, seek_seconds: float) -> float | None:
    """Approximate seek latency: time for ffmpeg to seek + decode exactly one frame."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(seek_seconds), "-i", str(in_path),
        "-frames:v", "1", "-f", "rawvideo", str(OUT / "_seek_probe.raw"),
    ]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    wall = time.perf_counter() - t0
    return wall if proc.returncode == 0 else None


# --------------------------------------------------------------------------- #
# Benchmark matrix
# --------------------------------------------------------------------------- #

CODECS = {
    # name -> (ffmpeg codec, lossless expected)
    "ffv1": "ffv1",
    "utvideo": "utvideo",
    "huffyuv": "huffyuv",
    "rawvideo": "rawvideo",
}

CONTAINERS = {
    "mkv": "matroska",
    "mov": "mov",
    "mp4": "mp4",
}


def run_case(label: str, pattern_name: str, universes: int, frames: int,
             packing: str, codec_name: str, container: str) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    pattern = PATTERNS[pattern_name]

    if packing == "gray":
        raw_bytes, width, height = build_grayscale_sequence(pattern, universes, frames)
        pix_fmt = "gray"
    else:
        raw_bytes, width, height = build_rgb_sequence(pattern, universes, frames)
        pix_fmt = "rgb24"

    raw_path = OUT / f"{label}_input.raw"
    raw_path.write_bytes(raw_bytes)

    out_path = OUT / f"{label}.{container}"
    enc = encode(raw_path, width, height, pix_fmt, codec_name, container, out_path)

    result = {
        "label": label,
        "pattern": pattern_name,
        "universes": universes,
        "frames": frames,
        "packing": packing,
        "width": width,
        "height": height,
        "codec": codec_name,
        "container": container,
        "encode_ok": enc.ok,
        "encode_wall_seconds": round(enc.wall_seconds, 4),
        "encode_max_rss_kb": enc.max_rss_kb,
        "encode_cpu_percent": enc.cpu_percent,
        "encode_stderr_tail": enc.stderr_tail if not enc.ok else "",
        "input_raw_bytes": len(raw_bytes),
    }

    if not enc.ok:
        result.update({
            "file_size_bytes": None, "lossless": None,
            "decode_ok": False, "decode_wall_seconds": None,
            "seek_seconds": None,
        })
        return result

    result["file_size_bytes"] = out_path.stat().st_size
    result["compression_ratio"] = round(len(raw_bytes) / max(out_path.stat().st_size, 1), 3)

    out_raw = OUT / f"{label}_decoded.raw"
    dec = decode(out_path, pix_fmt, out_raw)
    result["decode_ok"] = dec.ok
    result["decode_wall_seconds"] = round(dec.wall_seconds, 4) if dec.ok else None
    result["decode_max_rss_kb"] = dec.max_rss_kb
    if not dec.ok:
        result["lossless"] = None
        result["decode_stderr_tail"] = dec.stderr_tail
    else:
        decoded_bytes = out_raw.read_bytes()
        result["lossless"] = (decoded_bytes == raw_bytes)
        if not result["lossless"]:
            # Record where the first mismatch occurs to aid debugging.
            n = min(len(decoded_bytes), len(raw_bytes))
            first_diff = next((i for i in range(n) if decoded_bytes[i] != raw_bytes[i]), None)
            result["lossless_note"] = (
                f"length in={len(raw_bytes)} out={len(decoded_bytes)}, "
                f"first_diff_at={first_diff}"
            )

    duration_s = frames / FPS
    if duration_s > 0.5:
        result["seek_seconds"] = measure_seek(out_path, duration_s * 0.6)
    else:
        result["seek_seconds"] = None

    # Clean up large temp files immediately to bound disk usage across the matrix.
    for p in (raw_path, out_raw):
        p.unlink(missing_ok=True)

    return result


def main() -> None:
    if shutil.which("ffmpeg") is None:
        print("ffmpeg not found on PATH", file=sys.stderr)
        sys.exit(1)

    OUT.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    # --- A) Codec/container comparison at a representative scale ------------
    for container in ("mkv", "mov", "mp4"):
        for codec in ("ffv1", "utvideo", "huffyuv", "rawvideo"):
            label = f"A_codec_{codec}_{container}"
            print(f"[A] {label} ...", file=sys.stderr)
            results.append(run_case(label, "ramp", universes=10, frames=150,
                                     packing="gray", codec_name=codec, container=container))

    # --- B) Pixel packing comparison (grayscale vs RGB packed), ffv1/mkv ----
    for packing in ("gray", "rgb"):
        label = f"B_packing_{packing}"
        print(f"[B] {label} ...", file=sys.stderr)
        results.append(run_case(label, "ramp", universes=10, frames=150,
                                 packing=packing, codec_name="ffv1", container="mkv"))

    # --- C) Pattern comparison (compressibility spread), ffv1/mkv/gray ------
    for pattern_name in ("ramp", "alternating", "random"):
        label = f"C_pattern_{pattern_name}"
        print(f"[C] {label} ...", file=sys.stderr)
        results.append(run_case(label, pattern_name, universes=10, frames=150,
                                 packing="gray", codec_name="ffv1", container="mkv"))

    # --- D) Scale benchmark: 1 / 10 / 50 / 128 universes, ffv1/mkv/gray -----
    for universes in (1, 10, 50, 128):
        label = f"D_scale_{universes}u"
        print(f"[D] {label} ...", file=sys.stderr)
        results.append(run_case(label, "ramp", universes=universes, frames=150,
                                 packing="gray", codec_name="ffv1", container="mkv"))

    RESULTS_PATH.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {len(results)} results to {RESULTS_PATH}", file=sys.stderr)

    # Clean up the output/ working directory (raw/encoded temp files); keep
    # only results.json, which is what FORMAT-RESEARCH.md is derived from.
    shutil.rmtree(OUT, ignore_errors=True)


if __name__ == "__main__":
    main()
