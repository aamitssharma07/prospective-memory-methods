#!/usr/bin/env bash
#SBATCH --job-name=pmbench-hosted
#SBATCH --partition=normal
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=runs/jobs/%x-%j.log

set -euo pipefail

ROOT="${SLURM_SUBMIT_DIR:?Submit this job from the PMBench repository root}"
cd "$ROOT"
mkdir -p runs/jobs

set -a
source .env
set +a
: "${OPENROUTER_API_KEY:?OPENROUTER_API_KEY is required}"
: "${MODEL_NAME:=GPT-5.4}"

echo "[$(date -Is)] Running four baselines for ${MODEL_NAME}"
.venv/bin/python sim/run_experiment_matrix.py \
  --model "$MODEL_NAME" \
  --execute
echo "[$(date -Is)] Completed four baselines for ${MODEL_NAME}"
