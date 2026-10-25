#!/usr/bin/env bash
# Experiment 1 — PM-Bench baseline (no memory) for one action agent.
# Usage: experiments/exp1_pmbench_baselines.sh <output-dir> [model]
set -euo pipefail
OUT="${1:?usage: exp1_pmbench_baselines.sh <output-dir> [model]}"
MODEL="${2:-Qwen/Qwen3-8B}"
exec python harness/run_memory.py \
  --mode baseline --model "$MODEL" \
  --base-url "${ACTOR_URL:-http://127.0.0.1:30003/v1}" \
  --output "$OUT"
