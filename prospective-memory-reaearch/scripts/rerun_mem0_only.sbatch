#!/usr/bin/env bash
#SBATCH --job-name=pm-mem0-rerun
#SBATCH --partition=gpu-res-01
#SBATCH --qos=gpu-res-01
#SBATCH --gres=gpu:2
#SBATCH --time=1-00:00:00
#SBATCH --cpus-per-task=32
#SBATCH --mem=256G
#SBATCH --output=data/PMBench/runs/large_models/jobs/%x-%j.log

# Targeted rerun of ONLY the Mem0 method, for a model whose earlier Mem0 run
# was contaminated by an exhausted embedding-API credit balance (confirmed via
# "credit_balance_exhausted" in its memory.jsonl, embed.calls=0 in cost.json).
# Skips smoke/Experiment-1/other-Experiment-2-methods entirely: those already
# have valid results and re-running them would reload 70B+ weights for nothing.

set -euo pipefail

ROOT="${SLURM_SUBMIT_DIR:?Submit from the prospective-memory-reaearch root}"
EXP1="$ROOT/../prospective-memory/PMBench"
: "${MODEL_ID:?Set MODEL_ID}"
: "${MODEL_SLUG:?Set MODEL_SLUG}"

PORT="${PORT:-30002}"
BASE_URL="http://127.0.0.1:${PORT}/v1"
SGLANG_ENV="${SGLANG_ENV:-$EXP1/.venv-sglang}"
RUN_ROOT="$ROOT/data/PMBench/runs/large_models/$MODEL_SLUG"
STATUS_DIR="$RUN_ROOT/status"
SERVER_LOG="$RUN_ROOT/sglang-${SLURM_JOB_ID}.log"

mkdir -p "$RUN_ROOT" "$STATUS_DIR" "$ROOT/.cache/huggingface" "$ROOT/.cache/nltk_data"

module load cuda12.2/toolkit/12.2.2
export HF_HOME="$ROOT/.cache/huggingface"
export PATH="$SGLANG_ENV/bin:$PATH"
export TRANSFORMERS_CACHE="$HF_HOME/hub"
export NLTK_DATA="$ROOT/.cache/nltk_data"
export SGLANG_ENABLE_JIT_DEEPGEMM=false
export MEM0_TELEMETRY=False
export POSTHOG_DISABLED=1

set -a
source "$ROOT/.env"
set +a

SERVER_PID=""
cleanup() {
  [[ -n "$SERVER_PID" ]] || return 0
  if kill -0 "$SERVER_PID" 2>/dev/null; then
    kill -TERM -- "-$SERVER_PID" 2>/dev/null || true
    for _ in $(seq 1 15); do
      kill -0 "$SERVER_PID" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "$SERVER_PID" 2>/dev/null; then
      echo "Server group $SERVER_PID still alive after SIGTERM; sending SIGKILL" >&2
      kill -KILL -- "-$SERVER_PID" 2>/dev/null || true
    fi
  fi
  wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

MEM_FRACTION_STATIC="${MEM_FRACTION_STATIC:-0.92}"
echo "Starting $MODEL_ID in BF16 with TP=2 (mem-fraction-static=$MEM_FRACTION_STATIC)"
setsid "$SGLANG_ENV/bin/sglang" serve \
  --model-path "$MODEL_ID" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --dtype bfloat16 \
  --tp-size 2 \
  --sampling-backend pytorch \
  --mem-fraction-static "$MEM_FRACTION_STATIC" \
  >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

ready=false
for _ in $(seq 1 360); do
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

echo "Running Experiment 2 Mem0 only (rerun after embedding-credit fix)"
EXP2_OUT="$RUN_ROOT/experiment2/results"
"$ROOT/.venv/bin/python" "$ROOT/code/run_pm_memory.py" \
  --provider local \
  --model "$MODEL_ID" \
  --base-url "$BASE_URL" \
  --api-key exp2-local \
  --response-format json_schema \
  --scenario "$ROOT/data/PMBench/data/synthetic_week_v9.json" \
  --max-tokens 768 \
  --out-dir "$EXP2_OUT" \
  --setup mem0 --use-qwen-embed \
  2>&1 | tee "$RUN_ROOT/experiment2_mem0_rerun-${SLURM_JOB_ID}.log"
touch "$STATUS_DIR/experiment2_mem0.complete"

echo "Mem0 rerun complete for $MODEL_ID"
