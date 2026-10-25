#!/usr/bin/env bash
#SBATCH --job-name=exp3-qwen3-8b
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
for rgpm_flag in REPORT_GATES VERIFY_ACTIONS SCOPE_GROUNDING BOUNDED_PRIORITY SOURCE_ROUTING REGISTRATION_GROUNDING; do
  rgpm_value="$(rgpm_bool "${!rgpm_flag:-0}")"
  printf -v "$rgpm_flag" '%s' "$rgpm_value"
done
PYTHON="$ROOT/PMBench/.venv-sglang/bin/python"
PORT=30003
MODEL="${MODEL:-Qwen/Qwen3-8B}"
HELPER_MODEL="${HELPER_MODEL:-$MODEL}"
TP_SIZE="${TP_SIZE:-1}"
RUNS_ROOT="${RUNS_ROOT:-experiments/rgpm/runs/synthetic_week_v9}"
SLUG="$(printf '%s' "$MODEL" | sed 's|.*/||; s|\.|-|g' | tr '[:upper:]' '[:lower:]')"
module load cuda12.2/toolkit/12.2.2
export SGLANG_ENABLE_JIT_DEEPGEMM=false
if [[ -n "${CONSISTENCY_SPEC:-}" ]]; then
  "$PYTHON" experiments/rgpm/consistency_check.py --spec "$CONSISTENCY_SPEC" \
    --index "${CONSISTENCY_INDEX:?Set CONSISTENCY_INDEX}" --stage prelaunch
fi

if [[ "$HELPER_MODEL" == "$MODEL" ]]; then
  # Single server shared by actor and helper calls. Unchanged from the
  # original homogeneous launch path.
  RUN_ID="${SLUG}-${SLURM_JOB_ID}"
  JOB_ROOT="$ROOT/experiments/rgpm/jobs/$RUN_ID"
  SMOKE="$ROOT/experiments/rgpm/smoke_artifacts/$SLUG/sbpm/$RUN_ID"
  FULL="$ROOT/$RUNS_ROOT/$SLUG/sbpm/$RUN_ID"
  mkdir -p "$JOB_ROOT"
  "$PYTHON" experiments/rgpm/preflight.py --output "$JOB_ROOT/preflight"
  HOMOG_MEM_ARGS=()
  if [[ "$TP_SIZE" -gt 1 ]]; then
    # sglang's auto-computed fraction leaves no room for KV cache on 70B+
    # class models (same issue fixed in the other large-model launcher).
    HOMOG_MEM_ARGS=(--mem-fraction "${MEM_FRACTION_STATIC:-0.92}")
    if [[ "${DISABLE_CUDA_GRAPH:-0}" == "1" ]]; then
      # At tight mem-fraction margins, CUDA graph capture for a 70B+ model
      # has failed two different ways (hard OOM, PyTorch internal assertion)
      # during graph capture specifically, not ordinary inference.
      HOMOG_MEM_ARGS+=(--disable-cuda-graph)
    fi
  fi
  "$PYTHON" experiments/rgpm/prepare_server.py --output "$JOB_ROOT" --port "$PORT" --model "$MODEL" --tp-size "$TP_SIZE" "${HOMOG_MEM_ARGS[@]}"
  SERVER_PID=""
  cleanup() {
    if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
      kill "$SERVER_PID" || true
      wait "$SERVER_PID" || true
    fi
  }
  trap cleanup EXIT
  trap 'exit 130' INT TERM
  "$PYTHON" -c 'import json,os,sys; c=json.load(open(sys.argv[1]))["command"]; os.execv(c[0],c)' \
    "$JOB_ROOT/server_provenance.json" >"$JOB_ROOT/server.log" 2>&1 &
  SERVER_PID=$!
  ready=false
  for _ in $(seq 1 180); do
    kill -0 "$SERVER_PID" 2>/dev/null || { echo "Server failed: $JOB_ROOT/server.log"; exit 1; }
    if curl -fsS --max-time 3 "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then
      ready=true
      break
    fi
    sleep 5
  done
  [[ "$ready" == true ]] || { echo "Server readiness timed out"; exit 1; }
  PROJECTOR_ID="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["projector_id"])' "$JOB_ROOT/server_provenance.json")"
  common=(--model "$MODEL" --base-url "http://127.0.0.1:$PORT/v1"
          --projector-id "$PROJECTOR_ID" --provenance "$JOB_ROOT/server_provenance.json"
          --actor-guidance "${ACTOR_GUIDANCE:-balanced_v2}"
          --query-handoff "${QUERY_HANDOFF:-explicit}"
          --query-budget "${QUERY_BUDGET:-1}")
  PROBE_PORT="$PORT"
  PROBE_PROVENANCE="$JOB_ROOT/server_provenance.json"
else
  # Asymmetric actor/helper: two private servers. Uses one GPU each when 2 are
  # visible (sbatch --gres=gpu:h100:2); otherwise co-locates both on the single
  # visible GPU via --mem-fraction-static, sized to leave real headroom for
  # each model's weights plus its own KV cache/CUDA context. Override the
  # split with MEM_FRACTION_ACTOR/MEM_FRACTION_HELPER if a pairing OOMs.
  HELPER_PORT=30004
  HELPER_SLUG="$(printf '%s' "$HELPER_MODEL" | sed 's|.*/||; s|\.|-|g' | tr '[:upper:]' '[:lower:]')"
  RUN_ID="${SLUG}-actor-helper-${HELPER_SLUG}-${SLURM_JOB_ID}"
  JOB_ROOT="$ROOT/experiments/rgpm/jobs/$RUN_ID"
  SMOKE="$ROOT/experiments/rgpm/smoke_artifacts/${SLUG}-helper-${HELPER_SLUG}/sbpm/$RUN_ID"
  FULL="$ROOT/$RUNS_ROOT/${SLUG}-helper-${HELPER_SLUG}/sbpm/$RUN_ID"
  mkdir -p "$JOB_ROOT/actor" "$JOB_ROOT/helper"
  IFS=',' read -r -a GPU_IDS <<< "${CUDA_VISIBLE_DEVICES:-}"
  if [[ "${#GPU_IDS[@]}" -lt 1 ]]; then
    echo "No GPU visible (CUDA_VISIBLE_DEVICES='${CUDA_VISIBLE_DEVICES:-}')." >&2
    exit 1
  fi
  ACTOR_GPU="${GPU_IDS[0]}"
  if [[ "${#GPU_IDS[@]}" -ge 2 ]]; then
    HELPER_GPU="${GPU_IDS[1]}"
    ACTOR_MEM_ARGS=(); HELPER_MEM_ARGS=()
  else
    HELPER_GPU="${GPU_IDS[0]}"
    ACTOR_MEM_ARGS=(--mem-fraction "${MEM_FRACTION_ACTOR:-0.25}")
    HELPER_MEM_ARGS=(--mem-fraction "${MEM_FRACTION_HELPER:-0.55}")
    echo "Co-locating actor+helper on one GPU: mem-fraction-static actor=${MEM_FRACTION_ACTOR:-0.25} helper=${MEM_FRACTION_HELPER:-0.55}"
    if [[ "${DISABLE_CUDA_GRAPH:-0}" == "1" ]]; then
      # At tight co-located margins (e.g. Qwen3-32B sharing a GPU with a
      # small helper), CUDA graph capture's extra, mem-fraction-untracked
      # overhead is what tips a process over into OOM, not the nominal
      # weights+KV budget. Disabling graphs on both trades throughput for
      # headroom; fine for a one-time scoring run.
      ACTOR_MEM_ARGS+=(--disable-cuda-graph)
      HELPER_MEM_ARGS+=(--disable-cuda-graph)
      echo "CUDA graph capture disabled on both servers (DISABLE_CUDA_GRAPH=1)"
    fi
  fi
  "$PYTHON" experiments/rgpm/preflight.py --output "$JOB_ROOT/preflight"
  "$PYTHON" experiments/rgpm/prepare_server.py --output "$JOB_ROOT/actor" --port "$PORT" --model "$MODEL" "${ACTOR_MEM_ARGS[@]}"
  "$PYTHON" experiments/rgpm/prepare_server.py --output "$JOB_ROOT/helper" --port "$HELPER_PORT" --model "$HELPER_MODEL" "${HELPER_MEM_ARGS[@]}"
  ACTOR_PID=""; HELPER_PID=""
  cleanup() {
    for pid in "$ACTOR_PID" "$HELPER_PID"; do
      if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" || true
        wait "$pid" || true
      fi
    done
  }
  trap cleanup EXIT
  trap 'exit 130' INT TERM
  # Launched sequentially, not in parallel: when co-located on one GPU,
  # sglang's --mem-fraction-static sizing profiles currently-available memory
  # at startup, so a concurrent sibling still mid-load produces a race and an
  # inconsistent "no memory for KV cache" failure. Starting the actor first and
  # waiting for it to be ready means the helper always profiles against the
  # true post-actor memory state. Costs a little startup time when two GPUs
  # are available; harmless there.
  CUDA_VISIBLE_DEVICES="$ACTOR_GPU" "$PYTHON" -c \
    'import json,os,sys; c=json.load(open(sys.argv[1]))["command"]; os.execv(c[0],c)' \
    "$JOB_ROOT/actor/server_provenance.json" >"$JOB_ROOT/actor/server.log" 2>&1 &
  ACTOR_PID=$!
  for name_pid_port in "actor:$ACTOR_PID:$PORT"; do
    name="${name_pid_port%%:*}"; rest="${name_pid_port#*:}"; pid="${rest%%:*}"; port="${rest##*:}"
    ready=false
    for _ in $(seq 1 180); do
      kill -0 "$pid" 2>/dev/null || { echo "$name server failed: $JOB_ROOT/$name/server.log"; exit 1; }
      if curl -fsS --max-time 3 "http://127.0.0.1:$port/v1/models" >/dev/null 2>&1; then ready=true; break; fi
      sleep 5
    done
    [[ "$ready" == true ]] || { echo "$name server readiness timed out"; exit 1; }
  done
  CUDA_VISIBLE_DEVICES="$HELPER_GPU" "$PYTHON" -c \
    'import json,os,sys; c=json.load(open(sys.argv[1]))["command"]; os.execv(c[0],c)' \
    "$JOB_ROOT/helper/server_provenance.json" >"$JOB_ROOT/helper/server.log" 2>&1 &
  HELPER_PID=$!
  for name_pid_port in "helper:$HELPER_PID:$HELPER_PORT"; do
    name="${name_pid_port%%:*}"; rest="${name_pid_port#*:}"; pid="${rest%%:*}"; port="${rest##*:}"
    ready=false
    for _ in $(seq 1 180); do
      kill -0 "$pid" 2>/dev/null || { echo "$name server failed: $JOB_ROOT/$name/server.log"; exit 1; }
      if curl -fsS --max-time 3 "http://127.0.0.1:$port/v1/models" >/dev/null 2>&1; then ready=true; break; fi
      sleep 5
    done
    [[ "$ready" == true ]] || { echo "$name server readiness timed out"; exit 1; }
  done
  ACTOR_PROJECTOR_ID="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["projector_id"])' "$JOB_ROOT/actor/server_provenance.json")"
  HELPER_PROJECTOR_ID="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["projector_id"])' "$JOB_ROOT/helper/server_provenance.json")"
  common=(--model "$MODEL" --base-url "http://127.0.0.1:$PORT/v1"
          --helper-model "$HELPER_MODEL" --helper-base-url "http://127.0.0.1:$HELPER_PORT/v1"
          --projector-id "$HELPER_PROJECTOR_ID" --actor-projector-id "$ACTOR_PROJECTOR_ID"
          --provenance "$JOB_ROOT/helper/server_provenance.json"
          --actor-provenance "$JOB_ROOT/actor/server_provenance.json"
          --actor-guidance "${ACTOR_GUIDANCE:-balanced_v2}"
          --query-handoff "${QUERY_HANDOFF:-explicit}"
          --query-budget "${QUERY_BUDGET:-1}")
  PROBE_PORT="$HELPER_PORT"
  PROBE_PROVENANCE="$JOB_ROOT/helper/server_provenance.json"
fi
if [[ -n "${CONSISTENCY_SPEC:-}" ]]; then
  "$PYTHON" experiments/rgpm/consistency_check.py --spec "$CONSISTENCY_SPEC" \
    --index "$CONSISTENCY_INDEX" --stage served --job-root "$JOB_ROOT"
fi
[[ "$REPORT_GATES" != 1 ]] || common+=(--report-gates)
[[ "$VERIFY_ACTIONS" != 1 ]] || common+=(--verify-actions)
[[ "$SCOPE_GROUNDING" != 1 ]] || common+=(--scope-grounding)
[[ "$BOUNDED_PRIORITY" != 1 ]] || common+=(--bounded-priority)
[[ "$SOURCE_ROUTING" != 1 ]] || common+=(--source-routing)
[[ "$REGISTRATION_GROUNDING" != 1 ]] || common+=(--registration-grounding)
[[ -z "${GATE_STYLE:-}" ]] || common+=(--gate-style "$GATE_STYLE")
if [[ "${RUN_HELPER_PROBES:-0}" == 1 ]]; then
  "$PYTHON" experiments/rgpm/routing_probe.py --model "$HELPER_MODEL" \
    --base-url "http://127.0.0.1:$PROBE_PORT/v1" --output "$JOB_ROOT/routing_probe"
  "$PYTHON" experiments/rgpm/helper_probe.py --model "$HELPER_MODEL" \
    --base-url "http://127.0.0.1:$PROBE_PORT/v1" --output "$JOB_ROOT/helper_probe"
  "$PYTHON" experiments/rgpm/registration_probe.py --model "$HELPER_MODEL" \
    --base-url "http://127.0.0.1:$PROBE_PORT/v1" --output "$JOB_ROOT/registration_probe" \
    --provenance "$PROBE_PROVENANCE"
fi
"$PYTHON" experiments/rgpm/run.py "${common[@]}" --kind smoke \
  --scenario experiments/rgpm/smoke_scenario.json --output "$SMOKE"
"$PYTHON" experiments/rgpm/smoke_gate.py "$SMOKE" --admission-policy "${SMOKE_ADMISSION_POLICY:-strict}"
echo "Smoke admission completed; starting the authorized single-model PMBench run."
"$PYTHON" experiments/rgpm/run.py "${common[@]}" --kind benchmark \
  --scenario benchmark/data/synthetic_week_v9.json --output "$FULL"
echo "Completed Experiment 3 $MODEL: $FULL"
