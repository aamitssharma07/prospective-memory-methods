#!/usr/bin/env python3
"""Run the frozen PM-Bench fallback-audit matrix with resume support."""

from __future__ import annotations

import argparse
from importlib.metadata import version as package_version
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def slug(value: str) -> str:
    return value.lower().replace("/", "--").replace(".", "-")


def wait_for_server(base_url: str, timeout: int, process: subprocess.Popen) -> None:
    endpoint = base_url.rstrip("/") + "/models"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise RuntimeError(
                f"Inference server exited before becoming ready (exit {return_code}). "
                "Inspect server.log in the model result directory."
            )
        try:
            with urlopen(endpoint, timeout=5) as response:  # noqa: S310
                if response.status == 200:
                    return
        except Exception:  # noqa: BLE001
            time.sleep(2)
    raise TimeoutError(f"Inference server did not become ready: {endpoint}")


def server_command(model: dict, port: int) -> list[str]:
    vllm_parts = tuple(
        int(part) for part in package_version("vllm").split("+")[0].split(".")[:2]
    )
    command = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--model", model["id"], "--served-model-name", model["id"],
        "--port", str(port),
        "--tensor-parallel-size", str(model["tensor_parallel_size"]),
        "--dtype", model["dtype"], "--generation-config", "vllm",
        "--no-enable-log-requests" if vllm_parts >= (0, 27) else "--disable-log-requests",
    ]
    if model.get("trust_remote_code"):
        command.append("--trust-remote-code")
    for key in ("load_format", "quantization"):
        if model.get(key):
            command.extend(["--" + key.replace("_", "-"), model[key]])
    if model.get("max_model_len"):
        command.extend(["--max-model-len", str(model["max_model_len"])])
    if model.get("gpu_memory_utilization"):
        command.extend(["--gpu-memory-utilization", str(model["gpu_memory_utilization"])])
    if model.get("enforce_eager"):
        command.append("--enforce-eager")
    if model.get("hf_overrides"):
        command.extend(["--hf-overrides", json.dumps(model["hf_overrides"])])
    if model.get("model_impl"):
        command.extend(["--model-impl", model["model_impl"]])
    if model.get("limit_mm_per_prompt"):
        command.extend(["--limit-mm-per-prompt", json.dumps(model["limit_mm_per_prompt"])])
    return command


def select_models(registry: dict, requested: set[str], categories: set[str]) -> list[dict]:
    selected = [
        model for model in registry["models"]
        if (not requested or model["id"] in requested)
        and (not categories or model["category"] in categories)
    ]
    missing = requested - {model["id"] for model in selected}
    if missing:
        raise SystemExit(f"Unknown or filtered model IDs: {sorted(missing)}")
    return selected


def run_one(model: dict, setup: dict, config: dict, root: Path, dry_run: bool) -> None:
    label = setup.get("label", setup["name"])
    run_dir = root / slug(model["id"]) / label
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "trajectory.jsonl"
    paired_path = run_dir / "paired_metrics.json"
    if paired_path.exists():
        print(f"SKIP completed: {model['id']} / {label}")
        return
    generation = config["generation"]
    command = [
        sys.executable, str(ROOT / "PMBench/sim/run_eval.py"),
        "--setup", setup["name"],
        "--scenario", str(ROOT / config["scenario"]),
        "--model", model["id"], "--backend", config["backend"],
        "--base-url", config["base_url"], "--log", str(log_path),
        "--prompt-log", str(run_dir / "prompts.log"),
        "--invalid-response-fallback", "ground_truth",
        "--max-tokens", str(generation["max_tokens"]),
        "--temperature", str(generation["temperature"]),
        "--max-invalid-retries", str(generation["max_invalid_retries"]), "--score",
    ]
    if setup.get("heartbeat_mode"):
        command.extend(["--heartbeat-mode", setup["heartbeat_mode"]])
    manifest = {
        "model": model, "setup": setup, "scenario": config["scenario"],
        "generation": generation, "fallback_policy_at_runtime": "ground_truth",
        "command": command,
        "environment": {"cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"), "python": sys.version},
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print("RUN", shlex.join(command))
    if dry_run:
        return
    subprocess.run(command, cwd=ROOT, check=True)
    subprocess.run(
        [sys.executable, str(HERE / "score_paired.py"),
         "--scenario", str(ROOT / config["scenario"]),
         "--log", str(log_path), "--output", str(paired_path)],
        cwd=ROOT, check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="*", default=[])
    parser.add_argument("--categories", nargs="*", default=[])
    parser.add_argument(
        "--setups",
        nargs="*",
        default=[],
        help="Optional setup labels, for example single_baseline heartbeat_proactive.",
    )
    parser.add_argument("--external-server", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--server-port", type=int,
        help="Override the configured vLLM port (needed for parallel GPU workers).",
    )
    args = parser.parse_args()
    registry = load_json(HERE / "models.json")
    config = load_json(HERE / "experiment.json")
    if args.server_port is not None:
        config["server_port"] = args.server_port
        config["base_url"] = f"http://127.0.0.1:{args.server_port}/v1"
    models = select_models(registry, set(args.models), set(args.categories))
    requested_setups = set(args.setups)
    setups = [
        setup for setup in config["setups"]
        if not requested_setups
        or setup.get("label", setup["name"]) in requested_setups
    ]
    missing_setups = requested_setups - {
        setup.get("label", setup["name"]) for setup in setups
    }
    if missing_setups:
        raise SystemExit(f"Unknown setup labels: {sorted(missing_setups)}")
    results_root = ROOT / config["output_dir"]
    results_root.mkdir(parents=True, exist_ok=True)

    for model in models:
        server = None
        server_log = None
        if not args.external_server:
            command = server_command(model, config["server_port"])
            print("SERVER", shlex.join(command))
            if not args.dry_run:
                model_dir = results_root / slug(model["id"])
                model_dir.mkdir(parents=True, exist_ok=True)
                server_log = (model_dir / "server.log").open("a", encoding="utf-8")
                server_env = os.environ.copy()
                server_env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + server_env.get("PATH", "")
                bundled_cuda = Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages" / "nvidia" / "cu13"
                if (bundled_cuda / "bin" / "nvcc").exists():
                    server_env["CUDA_HOME"] = str(bundled_cuda)
                    server_env["PATH"] = str(bundled_cuda / "bin") + os.pathsep + server_env["PATH"]
                server = subprocess.Popen(
                    command, cwd=ROOT, stdout=server_log,
                    stderr=subprocess.STDOUT, start_new_session=True, env=server_env,
                )
                wait_for_server(
                    config["base_url"],
                    config["server_start_timeout_seconds"],
                    server,
                )
        try:
            for setup in setups:
                run_one(model, setup, config, results_root, args.dry_run)
        finally:
            if server is not None:
                # vLLM launches engine/worker children. Terminating only the API
                # parent can leave those children holding GPU memory.
                try:
                    os.killpg(server.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    server.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(server.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    server.wait()
            if server_log is not None:
                server_log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
