#!/usr/bin/env bash
#SBATCH --job-name=exp3-qwen8-consolidated-local
#SBATCH --partition=gpu
#SBATCH --qos=gpu
#SBATCH --gres=gpu:h100:1
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --output=experiments/rgpm/jobs/%x-%j.log
set -euo pipefail
export LOCAL_ONLY=1 RUN_FULL=0
export HELPER_MODEL="${HELPER_MODEL:-Qwen/Qwen3-8B}"
export SOURCE_ROUTING=1 SCOPE_GROUNDING=1 BOUNDED_PRIORITY=1
export REGISTRATION_GROUNDING=1
export ACTOR_GUIDANCE="${ACTOR_GUIDANCE:-none}" QUERY_HANDOFF=legacy QUERY_BUDGET=1
export REPORT_GATES=0 VERIFY_ACTIONS=0
export RUNS_ROOT="${RUNS_ROOT:-experiments/rgpm/runs/consolidated_v1}"
exec bash "${SLURM_SUBMIT_DIR:?Submit from the repository}/experiments/rgpm/run_gpt_actor.sbatch"
