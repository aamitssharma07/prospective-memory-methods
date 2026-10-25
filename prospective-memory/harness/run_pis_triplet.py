#!/usr/bin/env python3
"""Run the predeclared PIS-inspired three-arm experiment, without tuning in between."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--shutdown-server-pids", nargs="*", type=int, default=[],
                        help="Explicit owned model-server PIDs to release after successful completion")
    args = parser.parse_args()
    owned_servers = {}
    for pid in args.shutdown_server_pids:
        proc = Path(f"/proc/{pid}")
        command = (proc / "cmdline").read_bytes().split(b"\0")
        if not ({b"vllm.entrypoints.openai.api_server", b"prospective_memory.serve"} & set(command)
                and b"Qwen/Qwen3-8B" in command):
            raise ValueError(f"PID {pid} is not the expected model server")
        owned_servers[pid] = (proc / "stat").read_text().split()[21]
    for port in (30002, 30003):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=10) as reply:
            if reply.status != 200:
                raise RuntimeError("Server unavailable")
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    protocol = ROOT / "prospective_memory/PIS_EXPERIMENT.md"
    (output / "PROTOCOL.md").write_bytes(protocol.read_bytes())
    environment = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "protocol_sha256": hashlib.sha256(protocol.read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "packages": {p: importlib.metadata.version(p) for p in ("vllm", "torch", "transformers", "openai")},
        "gpu": subprocess.check_output(["nvidia-smi"], text=True),
        "servers": subprocess.check_output(["ps", "-u", str(__import__("os").getuid()), "-o", "pid,args"], text=True),
        "runs": [],
    }
    environment["servers"] = [line for line in environment["servers"].splitlines()
                              if "--served-model-name Qwen/Qwen3-8B" in line]
    common = [sys.executable, str(ROOT / "harness/run_memory.py"),
              "--model", "Qwen/Qwen3-8B", "--base-url", "http://127.0.0.1:30003/v1",
              "--memory-base-url", "http://127.0.0.1:30002/v1", "--memory-max-tokens", "4096",
              "--memory-check-budget", "1"]
    for arm in ("baseline", "pis", "pis_verified"):
        cmd = common + ["--output", str(output / arm)]
        cmd += (["--mode", "baseline"] if arm == "baseline" else
                ["--mode", "selective", "--memory-version", "portable", "--memory-policy", arm])
        record = {"arm": arm, "command": cmd, "started_at": datetime.now(timezone.utc).isoformat()}
        environment["runs"].append(record)
        (output / "environment.json").write_text(json.dumps(environment, indent=2))
        print(f"Starting {arm}", flush=True)
        start = time.monotonic()
        result = subprocess.run(cmd, cwd=ROOT)
        record.update(exit_code=result.returncode, elapsed_seconds=time.monotonic() - start,
                      completed_at=datetime.now(timezone.utc).isoformat())
        (output / "environment.json").write_text(json.dumps(environment, indent=2))
        if result.returncode:
            raise SystemExit(result.returncode)
        print(f"Completed {arm} in {record['elapsed_seconds']:.1f}s", flush=True)
    print(f"All three arms completed: {output}", flush=True)
    subprocess.run([sys.executable, str(ROOT / "harness/summarize_pis_triplet.py"),
                    str(output)], cwd=ROOT, check=True)
    for pid, start in owned_servers.items():
        proc = Path(f"/proc/{pid}")
        if proc.exists() and (proc / "stat").read_text().split()[21] == start:
            os.kill(pid, signal.SIGINT)
            print(f"Released owned server PID {pid}", flush=True)


if __name__ == "__main__":
    main()
