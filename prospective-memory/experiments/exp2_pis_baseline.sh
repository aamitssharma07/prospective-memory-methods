#!/usr/bin/env bash
# Experiment 2 — PIS baseline (paper-inspired reimplementation, NOT author code).
# Usage: experiments/exp2_pis_baseline.sh <output-dir> [model]
set -euo pipefail
OUT="${1:?usage: exp2_pis_baseline.sh <output-dir> [model]}"
MODEL="${2:-Qwen/Qwen3-8B}"
exec python harness/run_memory.py \
  --mode selective --memory-version portable --memory-policy pis \
  --model "$MODEL" --memory-model "$MODEL" \
  --base-url "${ACTOR_URL:-http://127.0.0.1:30003/v1}" \
  --memory-base-url "${HELPER_URL:-http://127.0.0.1:30002/v1}" \
  --memory-max-tokens 4096 --memory-check-budget 1 \
  --output "$OUT"
