#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage:
  sim/launch_experiments/run_all_setups.sh --backend BACKEND [model options] [setup options] [options]

Required:
  --backend BACKEND         openrouter or sglang

Model selection (pick one or combine):
  --model MODEL             single model ID
  --models LIST             comma-separated model IDs
  --all-working-models      include built-in WORKING_MODELS list

Optional:
  --setups LIST             comma-separated setup IDs; supported values:
                            single_baseline,todo_ledger,single_heartbeat,
                            single_heartbeat:auto30,single_heartbeat:auto60,
                            multi_baseline,multi_union_query,multi_majority_vote
  --scenario PATH           default: data/synthetic_week_v9.json
  --base-url URL            override backend base URL
  --api-key KEY             override backend API key
  --out-dir PATH            default: runs/local
  --max-tokens N            default: 768
  --request-timeout-seconds N
                            default: 120
  --num-subagents N         default: 3
  --task-legend             pass through to run_eval.py
  --include-auto-heartbeats include auto30 and auto60 in default setup list
                            (enabled by default)
  Note: when multi_union_query is run, replayed vote artifacts are also produced:
        hier-majority-vote-replay and hier-unanimous-vote-replay (if missing)

Examples:
  # One model, default setups
  sim/launch_experiments/run_all_setups.sh \
    --backend openrouter \
    --model meta-llama/llama-3.3-70b-instruct

  # Multiple models, explicit setup list
  sim/launch_experiments/run_all_setups.sh \
    --backend openrouter \
    --models "meta-llama/llama-3.3-70b-instruct,mistralai/mistral-large-2512,openai/gpt-5.4" \
    --setups "single_baseline,todo_ledger,single_heartbeat,multi_baseline,multi_union_query,multi_majority_vote"

  # Built-in WORKING_MODELS list
  sim/launch_experiments/run_all_setups.sh \
    --backend openrouter \
    --all-working-models \
    --setups "single_baseline,todo_ledger,single_heartbeat,multi_baseline,multi_union_query,multi_majority_vote"

  sim/launch_experiments/run_all_setups.sh \
    --backend sglang \
    --base-url http://127.0.0.1:30002/v1 \
    --model Qwen/Qwen3-14B \
    --include-auto-heartbeats
EOF
}

BACKEND=""
MODEL=""
MODELS_RAW=""
SETUPS_RAW=""
ALL_WORKING_MODELS="0"
SCENARIO="data/synthetic_week_v9.json"
BASE_URL=""
API_KEY=""
OUT_DIR="runs/local"
MAX_TOKENS="768"
REQUEST_TIMEOUT_SECONDS="120"
NUM_SUBAGENTS="3"
TASK_LEGEND="0"
INCLUDE_AUTO_HEARTBEATS="1"

WORKING_MODELS=(
  "meta-llama/llama-3.3-70b-instruct"
  "mistralai/mistral-large-2512"
  "mistralai/mistral-small-3.2-24b-instruct"
  # "anthropic/claude-opus-4.6"
  # "anthropic/claude-sonnet-4.6"
  # "google/gemma-3-27b-it"
  # "google/gemini-3.1-flash-lite-preview"
  # "google/gemini-2.5-flash"
  # "z-ai/glm-5"
  # "moonshotai/kimi-k2.5"
  "openai/gpt-5.4"
  "openai/gpt-5.3-codex"
)

split_list_items() {
  python - "$1" <<'PY'
import re
import sys

raw = sys.argv[1]
for item in re.split(r"[,\n]", raw):
    item = item.strip()
    if item:
        print(item)
PY
}

append_unique() {
  local item="$1"
  local array_name="$2"
  local -n array_ref="$array_name"
  local existing
  for existing in "${array_ref[@]:-}"; do
    if [[ "$existing" == "$item" ]]; then
      return 0
    fi
  done
  array_ref+=("$item")
}

sanitize_model_label() {
  python - "$1" <<'PY'
import sys
model = sys.argv[1].strip().lower()
for prefix in (
    "openai/",
    "anthropic/",
    "google/",
    "mistralai/",
    "meta-llama/",
    "qwen/",
    "moonshotai/",
    "z-ai/",
    "deepseek/",
    "alibaba/",
):
    if model.startswith(prefix):
        model = model[len(prefix):]
        break
model = model.replace("/", "-").replace(":", "-").replace(" ", "-").replace(".", "")
print(model)
PY
}

canonical_setup_label() {
  local setup="$1"
  local heartbeat_mode="${2:-}"
  case "$setup" in
    single_baseline) echo "single-baseline" ;;
    todo_ledger) echo "single-todo-ledger" ;;
    single_heartbeat)
      case "$heartbeat_mode" in
        optional) echo "heartbeat-proactive" ;;
        auto30) echo "heartbeat-auto-30m" ;;
        auto60) echo "heartbeat-auto-60m" ;;
        *) echo "single-heartbeat" ;;
      esac
      ;;
    multi_baseline) echo "hier-baseline" ;;
    multi_union_query) echo "hier-union-query" ;;
    multi_majority_vote) echo "hier-majority-vote" ;;
    *) echo "${setup//_/-}" ;;
  esac
}

normalize_setup_spec() {
  local raw="$1"
  local token="${raw,,}"
  token="${token// /}"

  case "$token" in
    single_baseline|single-baseline)
      echo "single_baseline|"
      ;;
    todo_ledger|todo-ledger|single-todo-ledger)
      echo "todo_ledger|"
      ;;
    single_heartbeat|single-heartbeat|single_heartbeat:optional|single-heartbeat:optional|heartbeat-proactive|heartbeat_optional)
      echo "single_heartbeat|optional"
      ;;
    single_heartbeat:auto30|single-heartbeat:auto30|heartbeat-auto-30m|heartbeat_auto30)
      echo "single_heartbeat|auto30"
      ;;
    single_heartbeat:auto60|single-heartbeat:auto60|heartbeat-auto-60m|heartbeat_auto60)
      echo "single_heartbeat|auto60"
      ;;
    multi_baseline|multi-baseline|hier-baseline)
      echo "multi_baseline|"
      ;;
    multi_union_query|multi-union-query|hier-union-query)
      echo "multi_union_query|"
      ;;
    multi_majority_vote|multi-majority-vote|hier-majority-vote)
      echo "multi_majority_vote|"
      ;;
    *)
      return 1
      ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend)
      BACKEND="${2:-}"
      shift 2
      ;;
    --model)
      MODEL="${2:-}"
      shift 2
      ;;
    --models)
      MODELS_RAW="${2:-}"
      shift 2
      ;;
    --setups)
      SETUPS_RAW="${2:-}"
      shift 2
      ;;
    --all-working-models)
      ALL_WORKING_MODELS="1"
      shift
      ;;
    --scenario)
      SCENARIO="${2:-}"
      shift 2
      ;;
    --base-url)
      BASE_URL="${2:-}"
      shift 2
      ;;
    --api-key)
      API_KEY="${2:-}"
      shift 2
      ;;
    --out-dir)
      OUT_DIR="${2:-}"
      shift 2
      ;;
    --max-tokens)
      MAX_TOKENS="${2:-}"
      shift 2
      ;;
    --request-timeout-seconds)
      REQUEST_TIMEOUT_SECONDS="${2:-}"
      shift 2
      ;;
    --num-subagents)
      NUM_SUBAGENTS="${2:-}"
      shift 2
      ;;
    --task-legend)
      TASK_LEGEND="1"
      shift
      ;;
    --include-auto-heartbeats)
      INCLUDE_AUTO_HEARTBEATS="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$BACKEND" ]]; then
  echo "--backend is required." >&2
  usage >&2
  exit 1
fi

if [[ "$BACKEND" != "openrouter" && "$BACKEND" != "sglang" ]]; then
  echo "--backend must be openrouter or sglang." >&2
  exit 1
fi

declare -a MODELS=()
declare -a SETUP_SPECS=()

if [[ -n "$MODEL" ]]; then
  append_unique "$MODEL" MODELS
fi

if [[ -n "$MODELS_RAW" ]]; then
  while IFS= read -r parsed_model; do
    append_unique "$parsed_model" MODELS
  done < <(split_list_items "$MODELS_RAW")
fi

if [[ "$ALL_WORKING_MODELS" == "1" ]]; then
  for working_model in "${WORKING_MODELS[@]}"; do
    append_unique "$working_model" MODELS
  done
fi

if [[ ${#MODELS[@]} -eq 0 ]]; then
  echo "At least one model is required (--model, --models, or --all-working-models)." >&2
  usage >&2
  exit 1
fi

if [[ -n "$SETUPS_RAW" ]]; then
  while IFS= read -r setup_token; do
    if ! setup_spec="$(normalize_setup_spec "$setup_token")"; then
      echo "Unsupported setup token: $setup_token" >&2
      exit 1
    fi
    append_unique "$setup_spec" SETUP_SPECS
  done < <(split_list_items "$SETUPS_RAW")
else
  SETUP_SPECS=(
    "single_baseline|"
    "todo_ledger|"
    "single_heartbeat|optional"
    "multi_union_query|"
    "multi_majority_vote|"
  )
  if [[ "$INCLUDE_AUTO_HEARTBEATS" == "1" ]]; then
    append_unique "single_heartbeat|auto30" SETUP_SPECS
    append_unique "single_heartbeat|auto60" SETUP_SPECS
  fi
fi

MODEL=""
MODEL_LABEL=""
MODEL_OUT_DIR=""
COMMON_ARGS=()
UNION_REPLAY_PENDING="0"

run_cmd() {
  echo
  echo "==> $*"
  "$@"
}

find_existing_score_for_prefix() {
  local prefix="$1"
  find "$MODEL_OUT_DIR" -maxdepth 2 -type f -name '*.score.md' \
    | grep "/${prefix}.*\\.score\\.md$" \
    | sort \
    | tail -n 1 || true
}

run_if_missing() {
  local setup="$1"
  local heartbeat_mode="$2"
  shift 2
  local -a extra_args=("$@")
  local setup_label
  setup_label="$(canonical_setup_label "$setup" "$heartbeat_mode")"
  local prefix="${setup_label}-${MODEL_LABEL}-v9-"

  local existing_score
  existing_score="$(find_existing_score_for_prefix "$prefix")"
  if [[ -n "$existing_score" ]]; then
    echo
    echo "==> Skipping ${setup_label} (${MODEL})"
    echo "    Found existing score: ${existing_score}"
    return 0
  fi

  run_cmd "${COMMON_ARGS[@]}" --setup "$setup" "${extra_args[@]}"
}

ensure_union_vote_replays_if_missing() {
  local union_prefix="hier-union-query-${MODEL_LABEL}-v9-"
  local majority_prefix="hier-majority-vote-replay-${MODEL_LABEL}-v9-"
  local unanimous_prefix="hier-unanimous-vote-replay-${MODEL_LABEL}-v9-"

  local majority_score unanimous_score
  majority_score="$(find_existing_score_for_prefix "$majority_prefix")"
  unanimous_score="$(find_existing_score_for_prefix "$unanimous_prefix")"
  if [[ -n "$majority_score" && -n "$unanimous_score" ]]; then
    return 0
  fi

  local union_score
  union_score="$(find_existing_score_for_prefix "$union_prefix")"
  if [[ -z "$union_score" ]]; then
    echo
    echo "==> Skipping vote replay generation (${MODEL})"
    echo "    No union-query score found for prefix: ${union_prefix}"
    return 0
  fi

  local union_run_dir
  union_run_dir="$(dirname "$union_score")"
  run_cmd python sim/replay_union_votes.py \
    --scenario "$SCENARIO" \
    --source-run-dir "$union_run_dir" \
    --out-model-dir "$MODEL_OUT_DIR"
}

run_setup_spec() {
  local spec="$1"
  local setup="${spec%%|*}"
  local heartbeat_mode="${spec#*|}"

  case "$setup" in
    single_baseline)
      run_if_missing single_baseline ""
      ;;
    todo_ledger)
      run_if_missing todo_ledger ""
      ;;
    single_heartbeat)
      run_if_missing single_heartbeat "$heartbeat_mode" --heartbeat-mode "$heartbeat_mode"
      ;;
    multi_baseline)
      run_if_missing multi_baseline "" --num-subagents "$NUM_SUBAGENTS"
      ;;
    multi_union_query)
      run_if_missing multi_union_query "" --num-subagents "$NUM_SUBAGENTS"
      UNION_REPLAY_PENDING="1"
      ;;
    multi_majority_vote)
      run_if_missing multi_majority_vote "" --num-subagents "$NUM_SUBAGENTS"
      ;;
    *)
      echo "Unsupported setup spec: $spec" >&2
      exit 1
      ;;
  esac
}

echo
echo "Selected models (${#MODELS[@]}):"
for selected_model in "${MODELS[@]}"; do
  echo "  - $selected_model"
done

echo
echo "Selected setup specs (${#SETUP_SPECS[@]}):"
for selected_setup in "${SETUP_SPECS[@]}"; do
  echo "  - $selected_setup"
done

for MODEL in "${MODELS[@]}"; do
  MODEL_LABEL="$(sanitize_model_label "$MODEL")"
  MODEL_OUT_DIR="${OUT_DIR}/${MODEL_LABEL}"
  mkdir -p "$MODEL_OUT_DIR"
  UNION_REPLAY_PENDING="0"

  COMMON_ARGS=(
    python sim/run_eval.py
    --backend "$BACKEND"
    --model "$MODEL"
    --scenario "$SCENARIO"
    --out-dir "$OUT_DIR"
    --max-tokens "$MAX_TOKENS"
    --request-timeout-seconds "$REQUEST_TIMEOUT_SECONDS"
    --score
  )

  if [[ -n "$BASE_URL" ]]; then
    COMMON_ARGS+=(--base-url "$BASE_URL")
  fi

  if [[ -n "$API_KEY" ]]; then
    COMMON_ARGS+=(--api-key "$API_KEY")
  fi

  if [[ "$TASK_LEGEND" == "1" ]]; then
    COMMON_ARGS+=(--task-legend)
  fi

  echo
  echo "==== Running model: ${MODEL} ===="
  for setup_spec in "${SETUP_SPECS[@]}"; do
    run_setup_spec "$setup_spec"
  done
  if [[ "$UNION_REPLAY_PENDING" == "1" ]]; then
    ensure_union_vote_replays_if_missing
  fi
done

echo
echo "All requested runs completed."
