#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p data/PMBench/runs/full_matrix/jobs

submit_local() {
  local slug="$1"
  local model_id="$2"
  sbatch \
    --job-name="exp2-${slug}" \
    --export="ALL,MODEL_SLUG=${slug},MODEL_ID=${model_id},TP_SIZE=1" \
    scripts/run_full_local_model.sbatch
}

# Qwen3-8B is excluded because the anchor run already supplies its four rows.
submit_local qwen3-0-6b Qwen/Qwen3-0.6B
submit_local qwen3-1-7b Qwen/Qwen3-1.7B
submit_local qwen3-4b Qwen/Qwen3-4B
submit_local gemma-4-e2b google/gemma-4-E2B-it
submit_local ministral-3-3b mistralai/Ministral-3-3B-Instruct-2512-BF16
submit_local ministral-3-8b mistralai/Ministral-3-8B-Instruct-2512-BF16
submit_local qwen3-32b Qwen/Qwen3-32B

sbatch scripts/run_full_gpt54.sbatch

# Llama-3.3-70B remains intentionally disabled for its later TP=2 run.
