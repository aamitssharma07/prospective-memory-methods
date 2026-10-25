#!/usr/bin/env bash
# Experiment 3: resumable source-bound method on PMBench.
# Usage: experiments/exp3_method.sh <output-dir> [model]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:?usage: exp3_method.sh <output-dir> [model]}"
MODEL="${2:-Qwen/Qwen3-8B}"
: "${PROJECTOR_ID:?Set PROJECTOR_ID from the actual served checkpoint and decoding configuration}"
exec "${RGPM_PYTHON:-$ROOT/PMBench/.venv-sglang/bin/python}" "$ROOT/experiments/rgpm/run.py" \
  --model "$MODEL" --base-url "${ACTOR_URL:-http://127.0.0.1:30003/v1}" \
  --projector-id "$PROJECTOR_ID" --kind "${RGPM_KIND:-benchmark}" \
  --scenario "${SCENARIO:-$ROOT/benchmark/data/synthetic_week_v9.json}" --output "$OUT"
