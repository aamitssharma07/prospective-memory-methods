#!/usr/bin/env bash
#SBATCH --job-name=pmbench-serve
#SBATCH --partition=gpu
#SBATCH --qos=gpu
#SBATCH --gres=gpu:h100:1
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --output=runs/servers/sglang-%j.log

set -euo pipefail

ROOT="${SLURM_SUBMIT_DIR:?Submit this job from the PMBench repository root}"
cd "$ROOT"

: "${MODEL_ID:?Set MODEL_ID to an approved Hugging Face model ID}"
TP_SIZE="${TP_SIZE:-1}"
PORT="${PORT:-30002}"

.venv-sglang/bin/python scripts/verify_model_precision.py "$MODEL_ID"

mkdir -p runs/servers .cache/sglang .cache/huggingface
module load cuda12.2/toolkit/12.2.2
# The cluster FFmpeg module has a broken MPI dependency and static-only libs.
FFMPEG_ROOT="$ROOT/.runtime/ffmpeg"
if [[ -d "$FFMPEG_ROOT/lib" ]]; then
  export LD_LIBRARY_PATH="$FFMPEG_ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
if [[ "$MODEL_ID" == mistralai/Ministral-3-* ]]; then
  export PMBENCH_MISTRAL_TOKENIZER_FIX=1
  export PYTHONPATH="$ROOT/scripts/sglang_site${PYTHONPATH:+:$PYTHONPATH}"
fi
export XDG_CACHE_HOME="$ROOT/.cache"
export FLASHINFER_WORKSPACE_BASE="$ROOT/.cache"
export HF_HOME="$ROOT/.cache/huggingface"
export TRANSFORMERS_CACHE="$HF_HOME/hub"
export PATH="$ROOT/.venv-sglang/bin:$PATH"
# The cluster provides CUDA 12.2 headers while SGLang's optional Hopper
# DeepGEMM path expects a CUDA 13 compiler. Dense BF16 serving does not use it.
export SGLANG_ENABLE_JIT_DEEPGEMM=false

set -a
source .env
set +a

echo "[$(date -Is)] Serving $MODEL_ID with SGLang 0.5.20, BF16, TP=$TP_SIZE, port=$PORT"
exec .venv-sglang/bin/sglang serve \
  --model-path "$MODEL_ID" \
  --host 0.0.0.0 \
  --port "$PORT" \
  --dtype bfloat16 \
  --tp-size "$TP_SIZE"
