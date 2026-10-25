#!/usr/bin/env bash
#SBATCH --job-name=exp2-gpt54
#SBATCH --partition=normal
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --output=data/PMBench/runs/full_matrix/jobs/%x-%j.log

set -euo pipefail

ROOT="${SLURM_SUBMIT_DIR:?Submit from the prospective-memory-reaearch root}"
cd "$ROOT"
RUN_ROOT="$ROOT/data/PMBench/runs/full_matrix/gpt-5-4"
STATUS_DIR="$RUN_ROOT/status"
mkdir -p "$RUN_ROOT" "$STATUS_DIR" .cache/huggingface .cache/nltk_data

export HF_HOME="$ROOT/.cache/huggingface"
export NLTK_DATA="$ROOT/.cache/nltk_data"
export MEM0_TELEMETRY=False
export POSTHOG_DISABLED=1
set -a
source .env
set +a

common=(
  --provider gpt54
  --scenario data/PMBench/data/synthetic_week_v9.json
  --max-tokens 768
  --out-dir "$RUN_ROOT/results"
)

run_baseline() {
  local name="$1"
  shift
  local marker="$STATUS_DIR/${name}.complete"
  local log="$RUN_ROOT/${name}-${SLURM_JOB_ID}.log"
  if [[ -f "$marker" ]]; then
    echo "SKIP $name: completion marker exists"
    return
  fi
  echo "START $name $(date --iso-8601=seconds)"
  .venv/bin/python code/run_pm_memory.py "${common[@]}" "$@" 2>&1 | tee "$log"
  printf 'job_id=%s\ncompleted_at=%s\nlog=%s\n' \
    "$SLURM_JOB_ID" "$(date --iso-8601=seconds)" "$log" >"$marker"
  echo "COMPLETE $name $(date --iso-8601=seconds)"
}

run_baseline mem0 --setup mem0 --use-qwen-embed
run_baseline amem --setup amem
run_baseline pis_rag --setup intention --intention-retrieval similarity --use-qwen-embed
run_baseline pis --setup intention

echo "All four GPT-5.4 full-week baselines completed."
