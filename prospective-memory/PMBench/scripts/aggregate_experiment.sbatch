#!/usr/bin/env bash
#SBATCH --job-name=pmbench-aggregate
#SBATCH --partition=normal
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=runs/jobs/%x-%j.log

set -euo pipefail

ROOT="${SLURM_SUBMIT_DIR:?Submit this job from the PMBench repository root}"
cd "$ROOT"

.venv/bin/python sim/aggregate_results.py \
  --results runs/core-four \
  --output-dir runs/core-four
