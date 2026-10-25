#!/usr/bin/env bash
#SBATCH --job-name=exp2-gate
#SBATCH --partition=normal
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=data/PMBench/runs/full_matrix/jobs/gate-%j.log

set -euo pipefail

ROOT="${SLURM_SUBMIT_DIR:?Submit from the prospective-memory-reaearch root}"
cd "$ROOT"
export ANCHOR_JOB_ID="${ANCHOR_JOB_ID:-1502585}"

.venv/bin/python scripts/validate_anchor_run.py
bash scripts/submit_full_matrix.sh
