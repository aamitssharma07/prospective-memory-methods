#!/usr/bin/env bash
#SBATCH --job-name=exp3-gpt-midnight-retry
#SBATCH --partition=gpu
#SBATCH --qos=gpu
#SBATCH --gres=gpu:h100:1
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --output=experiments/rgpm/jobs/%x-%j.log
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the repository}"
module load cuda12.2/toolkit/12.2.2
set -a
source .env
set +a
export SGLANG_ENABLE_JIT_DEEPGEMM=false
exec PMBench/.venv-sglang/bin/python experiments/rgpm/operations/gpt_midnight_retry.py execute --plan "${1:?Recovery plan required}"
