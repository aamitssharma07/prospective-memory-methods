#!/usr/bin/env bash
# Detached Computation Cost runs (survives Cursor chat abort).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT="${OUT:-data/PMBench/runs/cost}"
LOG="${LOG:-$OUT/cost_runs.log}"
PY="${PY:-/Users/cyanie/machine learning/Content_条件延迟记忆_2/.venv/bin/python}"
mkdir -p "$OUT"
{
  echo "===== $(date) start remaining cost runs ====="
  echo "python=$PY"
  for setup in amem intention; do
    echo "===== $(date) $setup ====="
    PYTHONUNBUFFERED=1 "$PY" code/run_pm_memory.py \
      --provider deepseek \
      --model deepseek-v4-flash \
      --setup "$setup" \
      --out-dir "$OUT"
  done
  echo "===== $(date) ALL_COST_RUNS_DONE ====="
} >>"$LOG" 2>&1
