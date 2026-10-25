#!/usr/bin/env bash
#SBATCH --job-name=pmbench-local
#SBATCH --partition=gpu
#SBATCH --qos=gpu
#SBATCH --gres=gpu:h100:1
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --output=runs/jobs/%x-%j.log

set -euo pipefail

ROOT="${SLURM_SUBMIT_DIR:?Submit this job from the PMBench repository root}"
cd "$ROOT"

: "${MODEL_ID:?Set MODEL_ID to an enabled SGLang model ID}"
PORT="${PORT:-30002}"
TP_SIZE="${TP_SIZE:-1}"
BASE_URL="http://127.0.0.1:${PORT}/v1"
SERVER_LOG="runs/jobs/sglang-${SLURM_JOB_ID}.log"

mkdir -p runs/jobs .cache/sglang .cache/huggingface
module load cuda12.2/toolkit/12.2.2

export XDG_CACHE_HOME="$ROOT/.cache"
export FLASHINFER_WORKSPACE_BASE="$ROOT/.cache"
export HF_HOME="$ROOT/.cache/huggingface"
export TRANSFORMERS_CACHE="$HF_HOME/hub"
export PATH="$ROOT/.venv-sglang/bin:$PATH"
export SGLANG_ENABLE_JIT_DEEPGEMM=false

FFMPEG_ROOT="$ROOT/.runtime/ffmpeg"
if [[ -d "$FFMPEG_ROOT/lib" ]]; then
  export LD_LIBRARY_PATH="$FFMPEG_ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
if [[ "$MODEL_ID" == mistralai/Ministral-3-* || "$MODEL_ID" == mistralai/Mistral-* ]]; then
  export PMBENCH_MISTRAL_TOKENIZER_FIX=1
  export PYTHONPATH="$ROOT/scripts/sglang_site${PYTHONPATH:+:$PYTHONPATH}"
fi

set -a
source .env
set +a

.venv-sglang/bin/python scripts/verify_model_precision.py "$MODEL_ID"

SERVER_PID=""
cleanup() {
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "[$(date -Is)] Starting SGLang for $MODEL_ID with TP=$TP_SIZE"
.venv-sglang/bin/sglang serve \
  --model-path "$MODEL_ID" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --dtype bfloat16 \
  --tp-size "$TP_SIZE" \
  >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

ready=0
for _ in $(seq 1 180); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "SGLang exited during startup; see $SERVER_LOG" >&2
    exit 1
  fi
  if curl -fsS --max-time 3 "$BASE_URL/models" >/dev/null; then
    ready=1
    break
  fi
  sleep 5
done
if [[ "$ready" != "1" ]]; then
  echo "SGLang did not become ready within 15 minutes; see $SERVER_LOG" >&2
  exit 1
fi

# The server inherited the Ministral tokenizer shim. The benchmark client uses
# the regular environment and must not try to import SGLang's sitecustomize.
if [[ "$MODEL_ID" == mistralai/Ministral-3-* || "$MODEL_ID" == mistralai/Mistral-* ]]; then
  unset PMBENCH_MISTRAL_TOKENIZER_FIX
  unset PYTHONPATH
fi

echo "[$(date -Is)] Running four baselines for $MODEL_ID"
.venv/bin/python sim/run_experiment_matrix.py \
  --model "$MODEL_ID" \
  --base-url "$BASE_URL" \
  --execute
echo "[$(date -Is)] Completed four baselines for $MODEL_ID"
