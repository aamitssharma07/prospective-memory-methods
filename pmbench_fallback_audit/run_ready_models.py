#!/usr/bin/env python3
"""Run smoke-approved models, using both GPUs without oversubscribing them."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "pmbench_fallback_audit" / "run_matrix.py"
LOG_DIR = ROOT / "pmbench_fallback_audit" / "run_logs"
MODERN_PYTHON = ROOT / ".venv-modern" / "bin" / "python"

GPU_0_MODELS = [
    "Qwen/Qwen3-0.6B",
    "Qwen/Qwen3-4B",
    "Qwen/Qwen3-14B",
    "meta-llama/Llama-3.2-1B-Instruct",
]
GPU_1_MODELS = [
    "Qwen/Qwen3-1.7B",
    "Qwen/Qwen3-8B",
    "meta-llama/Llama-3.2-3B-Instruct",
    "microsoft/Phi-4-mini-instruct",
]
TWO_GPU_MODELS = [
    "Qwen/Qwen3-32B",
    "meta-llama/Llama-3.3-70B-Instruct",
]
MODERN_GPU_0_MODELS = ["mistralai/Ministral-3-3B-Instruct-2512"]
MODERN_GPU_1_MODELS = ["mistralai/Ministral-3-8B-Instruct-2512"]
MODERN_TWO_GPU_MODELS = ["mistralai/Mistral-Small-3.2-24B-Instruct-2506"]


def command(models: list[str], port: int, python: str | Path = sys.executable) -> list[str]:
    return [str(python), str(RUNNER), "--server-port", str(port), "--models", *models]


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    workers = []
    for gpu, port, models in (("0", 30002, GPU_0_MODELS), ("1", 30003, GPU_1_MODELS)):
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = gpu
        log = (LOG_DIR / f"gpu{gpu}.log").open("a", encoding="utf-8")
        process = subprocess.Popen(
            command(models, port), cwd=ROOT, env=env,
            stdout=log, stderr=subprocess.STDOUT,
        )
        workers.append((process, log, gpu))
        print(f"Started GPU {gpu} worker (PID {process.pid}): {', '.join(models)}", flush=True)

    failed = False
    for process, log, gpu in workers:
        code = process.wait()
        log.close()
        print(f"GPU {gpu} worker exited {code}", flush=True)
        failed |= code != 0
    if failed:
        print("A single-GPU worker failed; inspect run_logs before two-GPU runs.", flush=True)
        return 1

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "0,1"
    with (LOG_DIR / "two_gpu.log").open("a", encoding="utf-8") as log:
        print(f"Starting two-GPU models: {', '.join(TWO_GPU_MODELS)}", flush=True)
        code = subprocess.run(
            command(TWO_GPU_MODELS, 30002), cwd=ROOT, env=env,
            stdout=log, stderr=subprocess.STDOUT,
        ).returncode
    if code:
        return code

    workers = []
    for gpu, port, models in (("0", 30002, MODERN_GPU_0_MODELS), ("1", 30003, MODERN_GPU_1_MODELS)):
        modern_env = os.environ.copy()
        modern_env["CUDA_VISIBLE_DEVICES"] = gpu
        log = (LOG_DIR / f"modern_gpu{gpu}.log").open("a", encoding="utf-8")
        process = subprocess.Popen(
            command(models, port, MODERN_PYTHON), cwd=ROOT, env=modern_env,
            stdout=log, stderr=subprocess.STDOUT,
        )
        workers.append((process, log, gpu))
        print(f"Started modern GPU {gpu} worker: {', '.join(models)}", flush=True)
    for process, log, gpu in workers:
        code = process.wait()
        log.close()
        if code:
            print(f"Modern GPU {gpu} worker exited {code}", flush=True)
            return code

    with (LOG_DIR / "modern_two_gpu.log").open("a", encoding="utf-8") as log:
        print(f"Starting modern two-GPU model: {MODERN_TWO_GPU_MODELS[0]}", flush=True)
        return subprocess.run(
            command(MODERN_TWO_GPU_MODELS, 30002, MODERN_PYTHON),
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
