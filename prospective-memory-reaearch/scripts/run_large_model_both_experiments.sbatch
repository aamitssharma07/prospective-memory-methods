#!/usr/bin/env bash
#SBATCH --job-name=pm-large
#SBATCH --partition=gpu-res-01
#SBATCH --qos=gpu-res-01
#SBATCH --gres=gpu:2
#SBATCH --time=3-00:00:00
#SBATCH --cpus-per-task=32
#SBATCH --mem=256G
#SBATCH --output=data/PMBench/runs/large_models/jobs/%x-%j.log

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
SMOKE_SCENARIO="$ROOT/data/slices/smoke_two_step_v9.json"

mkdir -p "$RUN_ROOT" "$STATUS_DIR" "$ROOT/.cache/huggingface" \
  "$ROOT/.cache/nltk_data"

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
  # --tp-size 2 forks NCCL worker processes under the sglang process; a plain
  # `kill $SERVER_PID` only signals that one PID, not its workers, and one can
  # survive as a zombie holding both GPUs. Slurm's epilog then can't reap it
  # ("Kill task failed"), which drains the node for everyone until an admin
  # clears it by hand. setsid below puts the whole server in its own process
  # group so `-$SERVER_PID` (the group) reaches every worker, and a bounded
  # SIGKILL fallback catches anything that ignores SIGTERM.
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
CUDA_GRAPH_ARGS=()
if [[ "${DISABLE_CUDA_GRAPH:-0}" == "1" ]]; then
  # At tight mem-fraction margins, CUDA graph capture for a 70B+ model has
  # failed two different ways on this card: a hard OOM at 0.96, and a
  # PyTorch internal assertion ("markCaptureEnd called with no captures in
  # progress") at 0.94 -- both during graph capture specifically, not during
  # ordinary forward passes. Disabling graphs trades some throughput for much
  # more predictable memory behaviour; fine for a one-time scoring run.
  CUDA_GRAPH_ARGS=(--disable-prefill-cuda-graph --disable-decode-cuda-graph)
  echo "CUDA graph capture disabled (DISABLE_CUDA_GRAPH=1)"
fi
echo "Starting $MODEL_ID in BF16 with TP=2 (mem-fraction-static=$MEM_FRACTION_STATIC)"
# sglang's auto-computed default (observed 0.828) left no room for the KV
# cache after loading ~70-72GB/GPU of weights for these two models: both
# Llama-3.3-70B and Qwen2.5-72B failed with "Raise --mem-fraction-static
# above 0.843/0.869". Pinning it above both, with a few GB of headroom for
# an actual (not just nonzero) KV cache.
setsid "$SGLANG_ENV/bin/sglang" serve \
  --model-path "$MODEL_ID" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --dtype bfloat16 \
  --tp-size 2 \
  --sampling-backend pytorch \
  --mem-fraction-static "$MEM_FRACTION_STATIC" \
  "${CUDA_GRAPH_ARGS[@]}" \
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

echo "Running Experiment 1 two-step smoke"
EXP1_SMOKE="$RUN_ROOT/smoke_exp1"
mkdir -p "$EXP1_SMOKE"
"$EXP1/.venv/bin/python" "$EXP1/sim/run_eval.py" \
  --setup single_baseline \
  --scenario "$SMOKE_SCENARIO" \
  --backend sglang \
  --model "$MODEL_ID" \
  --base-url "$BASE_URL" \
  --out-dir "$EXP1_SMOKE" \
  --log "$EXP1_SMOKE/trajectory.jsonl" \
  --prompt-log "$EXP1_SMOKE/prompts.log" \
  --checkpoint "$EXP1_SMOKE/checkpoint.json" \
  --max-tokens 768 \
  --max-invalid-retries 2 \
  --temperature 0.0 \
  --score

echo "Running Experiment 2 four-method two-step smoke"
EXP2_SMOKE="$RUN_ROOT/smoke_exp2"
smoke_common=(
  --provider local
  --model "$MODEL_ID"
  --base-url "$BASE_URL"
  --api-key smoke-local
  --response-format json_schema
  --scenario "$SMOKE_SCENARIO"
  --max-tokens 768
  --out-dir "$EXP2_SMOKE/results"
)
"$ROOT/.venv/bin/python" "$ROOT/code/run_pm_memory.py" "${smoke_common[@]}" --setup mem0 --use-qwen-embed
"$ROOT/.venv/bin/python" "$ROOT/code/run_pm_memory.py" "${smoke_common[@]}" --setup amem
"$ROOT/.venv/bin/python" "$ROOT/code/run_pm_memory.py" "${smoke_common[@]}" --setup intention --intention-retrieval similarity --use-qwen-embed
"$ROOT/.venv/bin/python" "$ROOT/code/run_pm_memory.py" "${smoke_common[@]}" --setup intention
touch "$STATUS_DIR/smoke.complete"

echo "Running Experiment 1 core four"
(
  cd "$EXP1"
  .venv/bin/python sim/run_experiment_matrix.py \
    --model "$MODEL_ID" \
    --base-url "$BASE_URL" \
    --execute
)
touch "$STATUS_DIR/experiment1.complete"

echo "Running Experiment 2 four methods"
EXP2_OUT="$RUN_ROOT/experiment2/results"
full_common=(
  --provider local
  --model "$MODEL_ID"
  --base-url "$BASE_URL"
  --api-key exp2-local
  --response-format json_schema
  --scenario "$ROOT/data/PMBench/data/synthetic_week_v9.json"
  --max-tokens 768
  --out-dir "$EXP2_OUT"
)

run_exp2() {
  local name="$1"
  shift
  local marker="$STATUS_DIR/experiment2_${name}.complete"
  if [[ -f "$marker" ]]; then
    echo "SKIP Experiment 2 $name: completion marker exists"
    return
  fi
  "$ROOT/.venv/bin/python" "$ROOT/code/run_pm_memory.py" \
    "${full_common[@]}" "$@" 2>&1 | tee "$RUN_ROOT/experiment2_${name}-${SLURM_JOB_ID}.log"
  touch "$marker"
}

run_exp2 mem0 --setup mem0 --use-qwen-embed
run_exp2 amem --setup amem
run_exp2 pis_rag --setup intention --intention-retrieval similarity --use-qwen-embed
run_exp2 pis --setup intention

touch "$STATUS_DIR/all.complete"
echo "Both experiments completed for $MODEL_ID"
