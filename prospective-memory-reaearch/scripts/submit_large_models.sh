#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p data/PMBench/runs/large_models/jobs

llama_job="$(sbatch \
  --job-name=pm-llama70b \
  --export=ALL,MODEL_SLUG=llama-3-3-70b,MODEL_ID=meta-llama/Llama-3.3-70B-Instruct \
  scripts/run_large_model_both_experiments.sbatch | awk '{print $NF}')"

qwen_job="$(sbatch \
  --dependency="afterany:${llama_job}" \
  --job-name=pm-qwen2-5-72b \
  --export=ALL,MODEL_SLUG=qwen2-5-72b,MODEL_ID=Qwen/Qwen2.5-72B-Instruct \
  scripts/run_large_model_both_experiments.sbatch | awk '{print $NF}')"

printf 'Llama-3.3-70B job: %s\nQwen2.5-72B job: %s\n' "$llama_job" "$qwen_job"
