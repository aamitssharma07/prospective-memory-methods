#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA_BIN="${CONDA_BIN:-/cm/shared/tamucc/apps/miniconda3/24.1.2/bin/conda}"
export CONDA_PKGS_DIRS="$ROOT/.cache/conda"
"$CONDA_BIN" create --prefix "$ROOT/.runtime/ffmpeg" --override-channels \
  -c conda-forge 'ffmpeg=7.1.1' --no-default-packages -y
