#!/usr/bin/env bash
# Driver for realtime_playback_benchmark.py (Phase H, docs/ARCHITECTURE.md):
# runs the 1/50-universe x {dmx, audio, video, audio_video} matrix at 30fps
# for 3 real seconds each, and writes benchmark/realtime_playback_results.json.
# 1 and 50 universes are representative low/high points, not a re-run of
# player_pipeline_benchmark.py's full 1/10/50/128 sweep -- see
# docs/PERFORMANCE.md for why that's a deliberate scoping choice, not a gap.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=".venv/bin/python"
OUT="benchmark/realtime_playback_results.json"
FPS=30
SECONDS_PER_RUN=3

echo "[" > "$OUT"
first=1
for universes in 1 50; do
  for variant in dmx audio video audio_video; do
    label="${universes}u_${variant}"
    echo "[bench] $label ..." >&2
    result_json=$("$PY" benchmark/realtime_playback_benchmark.py "$universes" "$FPS" "$SECONDS_PER_RUN" "$variant")
    if [ "$first" -eq 0 ]; then echo "," >> "$OUT"; fi
    first=0
    echo "$result_json" >> "$OUT"
  done
done
echo "]" >> "$OUT"
echo "Wrote $OUT" >&2
