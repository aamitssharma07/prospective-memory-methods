#!/usr/bin/env bash
#SBATCH --job-name=pmbench-download
#SBATCH --partition=normal
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --output=runs/jobs/%x-%j.log

set -euo pipefail

ROOT="${SLURM_SUBMIT_DIR:?Submit this job from the PMBench repository root}"
cd "$ROOT"
mkdir -p runs/jobs .cache/huggingface

export HF_HOME="$ROOT/.cache/huggingface"
set -a
source .env
set +a

.venv-sglang/bin/python scripts/download_models.py \
  --model Mistral-Small-3.2-24B \
  --model Llama-3.3-70B \
  --workers 2
