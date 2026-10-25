#!/usr/bin/env bash
#SBATCH --job-name=exp2-local
#SBATCH --partition=gpu
#SBATCH --qos=gpu
#SBATCH --gres=gpu:h100:1
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --output=data/PMBench/runs/full_matrix/jobs/%x-%j.log

set -euo pipefail

ROOT="${SLURM_SUBMIT_DIR:?Submit from the prospective-memory-reaearch root}"
cd "$ROOT"
: "${MODEL_ID:?Set MODEL_ID}"
: "${MODEL_SLUG:?Set MODEL_SLUG}"

PORT="${PORT:-30002}"
TP_SIZE="${TP_SIZE:-1}"
BASE_URL="http://127.0.0.1:${PORT}/v1"
SGLANG_ENV="${SGLANG_ENV:-$ROOT/../prospective-memory/PMBench/.venv-sglang}"
RUN_ROOT="$ROOT/data/PMBench/runs/full_matrix/$MODEL_SLUG"
STATUS_DIR="$RUN_ROOT/status"
SERVER_LOG="$RUN_ROOT/sglang-${SLURM_JOB_ID}.log"

mkdir -p "$RUN_ROOT" "$STATUS_DIR" .cache/huggingface .cache/nltk_data
module load cuda12.2/toolkit/12.2.2

export HF_HOME="$ROOT/.cache/huggingface"
export PATH="$SGLANG_ENV/bin:$PATH"
export TRANSFORMERS_CACHE="$HF_HOME/hub"
export NLTK_DATA="$ROOT/.cache/nltk_data"
export SGLANG_ENABLE_JIT_DEEPGEMM=false
export MEM0_TELEMETRY=False
export POSTHOG_DISABLED=1

if [[ "$MODEL_ID" == mistralai/Ministral-3-* ]]; then
  export PMBENCH_MISTRAL_TOKENIZER_FIX=1
  export PYTHONPATH="$ROOT/scripts/sglang_site${PYTHONPATH:+:$PYTHONPATH}"
fi

set -a
source .env
set +a

SERVER_PID=""
cleanup() {
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

"$SGLANG_ENV/bin/sglang" serve \
  --model-path "$MODEL_ID" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --dtype bfloat16 \
  --tp-size "$TP_SIZE" \
  --sampling-backend pytorch \
  >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

ready=false
for _ in $(seq 1 180); do
  kill -0 "$SERVER_PID" 2>/dev/null || {
    echo "SGLang startup failed; see $SERVER_LOG" >&2
    exit 1
  }
  if curl -fsS --max-time 3 "$BASE_URL/models" >/dev/null; then
    ready=true
    break
  fi
  sleep 5
done
[[ "$ready" == true ]] || { echo "SGLang readiness timed out" >&2; exit 1; }

if [[ "$MODEL_ID" == mistralai/Ministral-3-* ]]; then
  unset PMBENCH_MISTRAL_TOKENIZER_FIX
  unset PYTHONPATH
fi

common=(
  --provider local
  --model "$MODEL_ID"
  --base-url "$BASE_URL"
  --api-key exp2-local
  --response-format json_schema
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

echo "All four full-week baselines completed for $MODEL_ID."
