#!/usr/bin/env python3
"""Smoke-test every registered model through the experiment's vLLM interface."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import signal
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from run_matrix import HERE, ROOT, load_json, select_models, server_command, slug, wait_for_server


SCHEMA = {
    "name": "memory_action",
    "schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["read", "write", "none"]},
            "key": {"type": "string"},
        },
        "required": ["action", "key"],
        "additionalProperties": False,
    },
}


def request_completion(base_url: str, model_id: str, timeout: int) -> dict:
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": "You control a memory system. Select one action and return only schema-valid JSON."},
            {"role": "user", "content": "No memory operation is needed at this step."},
        ],
        "temperature": 0,
        "max_tokens": 768,
        "response_format": {"type": "json_schema", "json_schema": SCHEMA},
    }
    if "qwen" in model_id.lower():
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    request = Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = json.loads(response.read().decode())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    content = body["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    if parsed.get("action") not in {"read", "write", "none"} or not isinstance(parsed.get("key"), str):
        raise ValueError(f"Response did not match schema: {parsed!r}")
    return {"content": content, "parsed": parsed, "usage": body.get("usage")}


def write_report(path: Path, results: list[dict]) -> None:
    summary = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "passed": sum(item["status"] == "passed" for item in results),
        "failed": sum(item["status"] == "failed" for item in results),
        "results": results,
    }
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="*", default=[])
    parser.add_argument("--categories", nargs="*", default=[])
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--startup-timeout", type=int)
    parser.add_argument("--request-timeout", type=int, default=180)
    parser.add_argument("--min-free-gb", type=float, default=20.0)
    args = parser.parse_args()
    registry = load_json(HERE / "models.json")
    experiment = load_json(HERE / "experiment.json")
    models = select_models(registry, set(args.models), set(args.categories))
    output_dir = HERE / "model_smoke"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.json"
    previous = load_json(report_path).get("results", []) if report_path.exists() else []
    by_id = {item["model"]: item for item in previous}
    timeout = args.startup_timeout or experiment["server_start_timeout_seconds"]

    for model in models:
        model_id = model["id"]
        if not args.no_resume and by_id.get(model_id, {}).get("status") == "passed":
            print(f"SKIP passed: {model_id}", flush=True)
            continue
        free_gb = shutil.disk_usage(ROOT).free / (1024 ** 3)
        if free_gb < args.min_free_gb:
            print(f"STOP: only {free_gb:.1f} GiB free", flush=True)
            break
        model_dir = output_dir / slug(model_id)
        model_dir.mkdir(parents=True, exist_ok=True)
        log_path = model_dir / "server.log"
        command = server_command(model, experiment["server_port"])
        started = time.monotonic()
        result = {
            "model": model_id, "status": "failed",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "command": shlex.join(command), "log": str(log_path.relative_to(ROOT)),
            "free_gb_before": round(free_gb, 2),
        }
        server = None
        print(f"TEST {model_id}", flush=True)
        try:
            with log_path.open("w", encoding="utf-8") as server_log:
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
                wait_for_server(experiment["base_url"], timeout, server)
                result["response"] = request_completion(experiment["base_url"], model_id, args.request_timeout)
            result["status"] = "passed"
            print(f"PASS {model_id}", flush=True)
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"{type(exc).__name__}: {exc}"
            print(f"FAIL {model_id}: {result['error']}", flush=True)
        finally:
            if server is not None and server.poll() is None:
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
            result["duration_seconds"] = round(time.monotonic() - started, 2)
            result["free_gb_after"] = round(shutil.disk_usage(ROOT).free / (1024 ** 3), 2)
            by_id[model_id] = result
            ordered = [by_id[item["id"]] for item in registry["models"] if item["id"] in by_id]
            write_report(report_path, ordered)
    return 0 if all(by_id.get(model["id"], {}).get("status") == "passed" for model in models) else 1


if __name__ == "__main__":
    raise SystemExit(main())
