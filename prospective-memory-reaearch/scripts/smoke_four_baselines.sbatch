#!/usr/bin/env bash
#SBATCH --job-name=exp2-smoke
#SBATCH --partition=gpu
#SBATCH --qos=gpu
#SBATCH --gres=gpu:h100:1
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --output=smoke_artifacts/slurm-%j.log

set -euo pipefail

ROOT="${SLURM_SUBMIT_DIR:?Submit from the prospective-memory-reaearch root}"
cd "$ROOT"
mkdir -p smoke_artifacts .cache/huggingface .cache/nltk_data

MODEL_ID="${MODEL_ID:-Qwen/Qwen3-0.6B}"
PORT="${PORT:-30002}"
BASE_URL="http://127.0.0.1:${PORT}/v1"
SGLANG_ENV="${SGLANG_ENV:-$ROOT/../prospective-memory/PMBench/.venv-sglang}"
SERVER_LOG="$ROOT/smoke_artifacts/sglang-${SLURM_JOB_ID}.log"

module load cuda12.2/toolkit/12.2.2
export HF_HOME="$ROOT/.cache/huggingface"
export PATH="$SGLANG_ENV/bin:$PATH"
export TRANSFORMERS_CACHE="$HF_HOME/hub"
export NLTK_DATA="$ROOT/.cache/nltk_data"
export SGLANG_ENABLE_JIT_DEEPGEMM=false
export MEM0_TELEMETRY=False
export POSTHOG_DISABLED=1

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
  --tp-size 1 \
  --sampling-backend pytorch \
  >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 180); do
  kill -0 "$SERVER_PID" 2>/dev/null || { echo "SGLang startup failed" >&2; exit 1; }
  curl -fsS --max-time 3 "$BASE_URL/models" >/dev/null && break
  sleep 5
done
curl -fsS --max-time 3 "$BASE_URL/models" >/dev/null

.venv/bin/python scripts/build_smoke_scenario.py

common=(
  --provider local
  --model "$MODEL_ID"
  --base-url "$BASE_URL"
  --api-key smoke-local
  --response-format json_schema
  --scenario data/slices/smoke_two_step_v9.json
  --max-tokens 768
  --out-dir smoke_artifacts/results
)

.venv/bin/python code/run_pm_memory.py "${common[@]}" --setup mem0 --use-qwen-embed
.venv/bin/python code/run_pm_memory.py "${common[@]}" --setup amem
.venv/bin/python code/run_pm_memory.py "${common[@]}" --setup intention --intention-retrieval similarity --use-qwen-embed
.venv/bin/python code/run_pm_memory.py "${common[@]}" --setup intention

echo "All four smoke baselines completed."
