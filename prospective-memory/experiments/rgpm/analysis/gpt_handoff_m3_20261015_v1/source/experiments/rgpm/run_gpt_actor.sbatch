#!/usr/bin/env bash
#SBATCH --job-name=exp3-gpt-actor
#SBATCH --partition=gpu
#SBATCH --qos=gpu
#SBATCH --gres=gpu:h100:1
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --output=experiments/rgpm/jobs/%x-%j.log
set -euo pipefail
ROOT="${SLURM_SUBMIT_DIR:?Submit from the prospective-memory repository}"
cd "$ROOT"
source experiments/rgpm/launcher_options.sh
LOCAL_ONLY="$(rgpm_bool "${LOCAL_ONLY:-0}")"
RUN_FULL="$(rgpm_bool "${RUN_FULL:-0}")"
[[ "$LOCAL_ONLY" != 1 || "$RUN_FULL" != 1 ]] || { echo "Local validation cannot launch a full experiment"; exit 2; }
PYTHON="$ROOT/PMBench/.venv-sglang/bin/python"
PORT=30003
HELPER_MODEL="${HELPER_MODEL:?Set HELPER_MODEL to a local model}"
if [[ "$LOCAL_ONLY" == 1 ]]; then
  ACTOR_MODEL="$HELPER_MODEL"
  ACTOR_BACKEND=sglang
else
  ACTOR_MODEL="${ACTOR_MODEL:?Set ACTOR_MODEL, e.g. openai/gpt-5.4}"
  ACTOR_BACKEND=openrouter
fi
RUNS_ROOT="${RUNS_ROOT:-experiments/rgpm/runs/synthetic_week_v9}"
HELPER_SLUG="$(printf '%s' "$HELPER_MODEL" | sed 's|.*/||; s|\.|-|g' | tr '[:upper:]' '[:lower:]')"
ACTOR_SLUG="$(printf '%s' "$ACTOR_MODEL" | sed 's|.*/||; s|\.|-|g' | tr '[:upper:]' '[:lower:]')"
module load cuda12.2/toolkit/12.2.2
export SGLANG_ENABLE_JIT_DEEPGEMM=false

if [[ "$LOCAL_ONLY" != 1 ]]; then
  set -a
  source "$ROOT/.env"
  set +a
fi
for rgpm_flag in REPORT_GATES VERIFY_ACTIONS SCOPE_GROUNDING BOUNDED_PRIORITY SOURCE_ROUTING REGISTRATION_GROUNDING; do
  rgpm_value="$(rgpm_bool "${!rgpm_flag:-0}")"
  printf -v "$rgpm_flag" '%s' "$rgpm_value"
done
smoke_budget=()
full_budget=()
if [[ "$LOCAL_ONLY" != 1 ]]; then
  smoke_budget=(--max-actor-calls "${SMOKE_MAX_ACTOR_CALLS:-24}" --max-actor-tokens "${SMOKE_MAX_ACTOR_TOKENS:-500000}")
  if [[ "$RUN_FULL" == 1 ]]; then
    full_budget=(--max-actor-calls "${MAX_ACTOR_CALLS:?Set the authorized full-run actor call limit}" \
                 --max-actor-tokens "${MAX_ACTOR_TOKENS:?Set the authorized full-run actor token limit}")
  fi
fi

# Only the helper needs a local server: it runs the structured decoding this
# method depends on. The actor is GPT-5.4 via OpenRouter -- a plain hosted
# chat completion, no local GPU server of its own.
RUN_ID="${ACTOR_SLUG}-actor-helper-${HELPER_SLUG}-${SLURM_JOB_ID}"
JOB_ROOT="$ROOT/experiments/rgpm/jobs/$RUN_ID"
SMOKE="$ROOT/experiments/rgpm/smoke_artifacts/${ACTOR_SLUG}-helper-${HELPER_SLUG}/sbpm/$RUN_ID"
FULL="$ROOT/$RUNS_ROOT/${ACTOR_SLUG}-helper-${HELPER_SLUG}/sbpm/$RUN_ID"
mkdir -p "$JOB_ROOT/helper"
"$PYTHON" experiments/rgpm/preflight.py --output "$JOB_ROOT/preflight"
"$PYTHON" experiments/rgpm/prepare_server.py --output "$JOB_ROOT/helper" --port "$PORT" --model "$HELPER_MODEL"

HELPER_PID=""
cleanup() {
  [[ -n "$HELPER_PID" ]] || return 0
  if kill -0 "$HELPER_PID" 2>/dev/null; then
    kill -TERM -- "-$HELPER_PID" 2>/dev/null || true
    for _ in $(seq 1 15); do
      kill -0 "$HELPER_PID" 2>/dev/null || break
      sleep 1
    done
    kill -0 "$HELPER_PID" 2>/dev/null && kill -KILL -- "-$HELPER_PID" 2>/dev/null || true
  fi
  wait "$HELPER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

setsid "$PYTHON" -c \
  'import json,os,sys; c=json.load(open(sys.argv[1]))["command"]; os.execv(c[0],c)' \
  "$JOB_ROOT/helper/server_provenance.json" >"$JOB_ROOT/helper/server.log" 2>&1 &
HELPER_PID=$!
ready=false
for _ in $(seq 1 180); do
  kill -0 "$HELPER_PID" 2>/dev/null || { echo "Helper server failed: $JOB_ROOT/helper/server.log"; exit 1; }
  if curl -fsS --max-time 3 "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then ready=true; break; fi
  sleep 5
done
[[ "$ready" == true ]] || { echo "Helper server readiness timed out"; exit 1; }

HELPER_PROJECTOR_ID="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["projector_id"])' "$JOB_ROOT/helper/server_provenance.json")"
common=(--model "$ACTOR_MODEL" --actor-backend "$ACTOR_BACKEND"
        --helper-model "$HELPER_MODEL" --helper-base-url "http://127.0.0.1:$PORT/v1"
        --projector-id "$HELPER_PROJECTOR_ID"
        --provenance "$JOB_ROOT/helper/server_provenance.json"
        --actor-guidance "${ACTOR_GUIDANCE:-balanced_v2}"
        --query-handoff "${QUERY_HANDOFF:-explicit}"
        --query-budget "${QUERY_BUDGET:-1}")
[[ "$REPORT_GATES" != 1 ]] || common+=(--report-gates)
[[ "$VERIFY_ACTIONS" != 1 ]] || common+=(--verify-actions)
[[ "$SCOPE_GROUNDING" != 1 ]] || common+=(--scope-grounding)
[[ "$BOUNDED_PRIORITY" != 1 ]] || common+=(--bounded-priority)
[[ "$REGISTRATION_GROUNDING" != 1 ]] || common+=(--registration-grounding)
[[ -z "${GATE_STYLE:-}" ]] || common+=(--gate-style "$GATE_STYLE")
if [[ "$LOCAL_ONLY" == 1 ]]; then
  common+=(--local-only --base-url "http://127.0.0.1:$PORT/v1")
fi

if [[ "$SOURCE_ROUTING" == "1" ]]; then
  common+=(--source-routing)
  "$PYTHON" experiments/rgpm/routing_probe.py --model "$HELPER_MODEL" \
    --base-url "http://127.0.0.1:$PORT/v1" --output "$JOB_ROOT/routing_probe"
fi

if [[ "$LOCAL_ONLY" == 1 || "$SCOPE_GROUNDING" == 1 || "$BOUNDED_PRIORITY" == 1 || "$REGISTRATION_GROUNDING" == 1 ]]; then
  "$PYTHON" experiments/rgpm/helper_probe.py --model "$HELPER_MODEL" \
    --base-url "http://127.0.0.1:$PORT/v1" --output "$JOB_ROOT/helper_probe"
fi

if [[ -n "${QUERY_UPTAKE_INPUT:-}" ]]; then
  "$PYTHON" experiments/rgpm/query_uptake_probe.py --model "$HELPER_MODEL" \
    --base-url "http://127.0.0.1:$PORT/v1" --input-run "$QUERY_UPTAKE_INPUT" \
    --output "$JOB_ROOT/query_uptake_probe"
fi

"$PYTHON" experiments/rgpm/run.py "${common[@]}" "${smoke_budget[@]}" --kind smoke \
  --scenario experiments/rgpm/smoke_scenario.json --output "$SMOKE"
smoke_quality=()
[[ -z "${SMOKE_MAX_FP:-}" ]] || smoke_quality+=(--max-false-positives "$SMOKE_MAX_FP")
[[ -z "${SMOKE_MAX_FN:-}" ]] || smoke_quality+=(--max-false-negatives "$SMOKE_MAX_FN")
"$PYTHON" experiments/rgpm/smoke_gate.py "$SMOKE" "${smoke_quality[@]}"
if [[ "$LOCAL_ONLY" == 1 || "$RUN_FULL" != 1 ]]; then
  echo "Validation complete: $SMOKE"
  exit 0
fi
echo "Smoke passed; starting the authorized GPT-actor PMBench run."
"$PYTHON" experiments/rgpm/run.py "${common[@]}" "${full_budget[@]}" --kind benchmark \
  --scenario benchmark/data/synthetic_week_v9.json --output "$FULL"
echo "Completed Experiment 3 $ACTOR_MODEL (actor) / $HELPER_MODEL (helper): $FULL"
