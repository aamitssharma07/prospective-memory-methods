#!/usr/bin/env bash
#SBATCH --job-name=exp3-qwen3-8b-smoke
#SBATCH --partition=gpu
#SBATCH --qos=gpu
#SBATCH --gres=gpu:h100:1
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --output=experiments/rgpm/jobs/%x-%j.log
set -euo pipefail
ROOT="${SLURM_SUBMIT_DIR:?Submit from the prospective-memory repository}"
cd "$ROOT"
PYTHON="$ROOT/PMBench/.venv-sglang/bin/python"
PORT=30003
RUN_ID="qwen3-8b-${SLURM_JOB_ID}"
JOB_ROOT="$ROOT/experiments/rgpm/jobs/$RUN_ID"
SMOKE="$ROOT/experiments/rgpm/smoke_artifacts/qwen3-8b/sbpm/$RUN_ID"
mkdir -p "$JOB_ROOT"
module load cuda12.2/toolkit/12.2.2
export SGLANG_ENABLE_JIT_DEEPGEMM=false
"$PYTHON" experiments/rgpm/preflight.py --output "$JOB_ROOT/preflight"
"$PYTHON" experiments/rgpm/prepare_server.py --output "$JOB_ROOT" --port "$PORT"
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
"$PYTHON" experiments/rgpm/run.py --model Qwen/Qwen3-8B \
  --base-url "http://127.0.0.1:$PORT/v1" --projector-id "$PROJECTOR_ID" \
  --provenance "$JOB_ROOT/server_provenance.json" --kind smoke \
  --scenario experiments/rgpm/smoke_scenario.json --output "$SMOKE"
"$PYTHON" experiments/rgpm/smoke_gate.py "$SMOKE"
echo "Completed Experiment 3 Qwen3-8B smoke: $SMOKE"
