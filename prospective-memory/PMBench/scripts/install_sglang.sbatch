#!/usr/bin/env bash
#SBATCH --job-name=pmbench-sglang
#SBATCH --partition=normal
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --output=runs/setup/sglang-%j.log

set -euo pipefail

ROOT="${SLURM_SUBMIT_DIR:?Submit this job from the PMBench repository root}"
cd "$ROOT"
mkdir -p runs/setup .cache/pip .cache/uv
export XDG_CACHE_HOME="$ROOT/.cache"
export HF_HOME="$ROOT/.cache/huggingface"

module load miniconda3/24.1.2
if [[ ! -x .venv-sglang/bin/python ]]; then
  python -m venv .venv-sglang
fi
if [[ ! -x .venv-sglang/bin/uv ]]; then
  PIP_CACHE_DIR="$ROOT/.cache/pip" .venv-sglang/bin/python -m pip install uv
fi

echo "[$(date -Is)] Installing pinned SGLang environment"
UV_CACHE_DIR="$ROOT/.cache/uv" .venv-sglang/bin/uv pip install \
  --prerelease=allow --python .venv-sglang/bin/python -r requirements.txt

echo "[$(date -Is)] Validating imports and versions"
.venv-sglang/bin/python -c \
  'import openai, sglang, torch; print(f"openai={openai.__version__} torch={torch.__version__} sglang={sglang.__version__}")'
.venv-sglang/bin/python -m sglang.launch_server --help >/dev/null
echo "[$(date -Is)] SGLang setup complete"
