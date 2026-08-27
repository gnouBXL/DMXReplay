#!/usr/bin/env bash
# Driver for player_pipeline_benchmark.py: runs the 1/10/50/128-universe x
# Art-Net/sACN matrix at 30fps under `/usr/bin/time -v` (for CPU%/max RSS),
# and writes benchmark/pi_readiness_results.json. See docs/RASPBERRY_PI.md.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=".venv/bin/python"
OUT="benchmark/pi_readiness_results.json"
FRAMES=300   # 10s of nominal content @ 30fps
FPS=30

echo "[" > "$OUT"
first=1
for universes in 1 10 50 128; do
  for protocol in artnet sacn; do
    label="${universes}u_${protocol}"
    echo "[bench] $label ..." >&2
    timelog=$(mktemp)
    outlog=$(mktemp)
    /usr/bin/time -v "$PY" benchmark/player_pipeline_benchmark.py \
      "$universes" "$FRAMES" "$FPS" "$protocol" grayscale \
      > "$outlog" 2> "$timelog" || { echo "FAILED: $label"; cat "$timelog" >&2; exit 1; }

    result_json=$(cat "$outlog")
    max_rss_kb=$(grep "Maximum resident set size" "$timelog" | awk -F': ' '{print $2}')
    cpu_percent=$(grep "Percent of CPU" "$timelog" | awk -F': ' '{print $2}' | tr -d '%')
    elapsed=$(grep "Elapsed (wall clock)" "$timelog" | awk -F': ' '{print $2}')

    if [ "$first" -eq 0 ]; then echo "," >> "$OUT"; fi
    first=0
    python3 -c "
import json, sys
r = json.loads('''$result_json''')
r['process_max_rss_kb'] = $max_rss_kb
r['process_cpu_percent'] = '$cpu_percent'
r['process_elapsed_wall'] = '$elapsed'
print(json.dumps(r, indent=2))
" >> "$OUT"

    rm -f "$timelog" "$outlog"
  done
done
echo "]" >> "$OUT"
echo "Wrote $OUT" >&2
