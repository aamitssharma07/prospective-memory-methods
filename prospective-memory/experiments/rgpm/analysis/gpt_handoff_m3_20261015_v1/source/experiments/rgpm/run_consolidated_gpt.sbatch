#!/usr/bin/env bash
#SBATCH --job-name=exp3-gpt-consolidated
#SBATCH --partition=gpu
#SBATCH --qos=gpu
#SBATCH --gres=gpu:h100:1
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --output=experiments/rgpm/jobs/%x-%j.log
set -euo pipefail
export LOCAL_ONLY=0 RUN_FULL=1
export ACTOR_MODEL=openai/gpt-5.4 HELPER_MODEL=Qwen/Qwen3-8B
export SOURCE_ROUTING=1 SCOPE_GROUNDING=1 BOUNDED_PRIORITY=1
export REGISTRATION_GROUNDING=1
export ACTOR_GUIDANCE=none QUERY_HANDOFF=legacy QUERY_BUDGET=1
export GATE_STYLE=terse REPORT_GATES=0 VERIFY_ACTIONS=0
export SMOKE_MAX_ACTOR_CALLS=24 SMOKE_MAX_ACTOR_TOKENS=500000
export MAX_ACTOR_CALLS=160 MAX_ACTOR_TOKENS=2000000
export SMOKE_MAX_FP=0 SMOKE_MAX_FN=0
export RUNS_ROOT=experiments/rgpm/runs/consolidated_v1
exec bash "${SLURM_SUBMIT_DIR:?Submit from the repository}/experiments/rgpm/run_gpt_actor.sbatch"
