#!/usr/bin/env python3
"""Run pinned, unedited author baseline/PIS locally, with auditable API traces.

This changes transport, disables Qwen thinking, and records calls; it does not
replace the authors' memory policy, prompt, schemas, or status transitions.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
AUTHOR = ROOT / "third_party/author_pis"
COMMIT = "43e9b426a478bdd6b4e6fb12cb609ca26bd71ff9"
MODEL = "Qwen/Qwen3-8B"
SCENARIO = ROOT / "benchmark/data/synthetic_week_v9.json"


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")


def install_trace(create, helper, role_fn, log):
    """Wrap the author's already-patched SDK method; preserve native parameters."""
    count = 0

    def traced(self, *args, **kwargs):
        nonlocal count
        count += 1
        if count > 2000:
            # The upstream memory layer catches Exception and continues. A
            # safety stop must bypass that recovery path, not become a miss.
            raise SystemExit("Safety abort: 2000 API calls; no synthetic action/score")
        role = role_fn()
        extra = dict(kwargs.get("extra_body") or {})
        template = dict(extra.get("chat_template_kwargs") or {})
        template["enable_thinking"] = False
        extra["chat_template_kwargs"] = template
        kwargs["extra_body"] = extra
        event = {"call": count, "role": role,
                 "endpoint": "actor:30003" if role == "choose" else "helper:30002",
                 "request": kwargs}
        started = time.monotonic()
        try:
            response = create(self if role == "choose" else helper, *args, **kwargs)
            event["raw"] = response.choices[0].message.content
            event["finish_reason"] = response.choices[0].finish_reason
            usage = getattr(response, "usage", None)
            event["usage"] = {key: getattr(usage, key, 0) for key in
                              ("prompt_tokens", "completion_tokens", "total_tokens")}
            return response
        except BaseException as exc:
            event["error"] = repr(exc)
            raise
        finally:
            event["elapsed_seconds"] = time.monotonic() - started
            log.write(json.dumps(event, default=str) + "\n")
            log.flush()
            if count % 25 == 0:
                print(f"trace: {count} API calls, latest role={role}", flush=True)

    return traced


def run_arm(root, arm):
    sys.path.insert(0, str(AUTHOR / "code"))
    import run_pm_memory as author_runner
    import llm_env
    import llm_cost
    from openai import OpenAI
    from openai.resources.chat.completions import Completions

    destination = root / arm
    destination.mkdir(exist_ok=False)
    llm_env.install_model_chat_extras(MODEL)
    original = Completions.create
    helper_client = OpenAI(base_url="http://127.0.0.1:30002/v1", api_key="EMPTY")
    argv = ["run_pm_memory.py", "--provider", "qwen", "--setup", arm,
            "--model", MODEL, "--base-url", "http://127.0.0.1:30003/v1",
            "--api-key", "EMPTY", "--response-format", "json_schema",
            "--out-dir", str(destination), "--scenario", str(SCENARIO),
            "--max-tokens", "768"]
    write_json(destination / "argv.json", argv)
    start = time.time()
    with (destination / "api_calls.jsonl").open("x") as log:
        Completions.create = install_trace(original, helper_client.chat.completions,
                                          llm_cost.current_role, log)
        sys.argv = argv
        try:
            result = author_runner.main()
            write_json(destination / "completion.json", {
                "status": "completed", "exit_code": result,
                "duration_seconds": time.time() - start})
            return result or 0
        finally:
            Completions.create = original
            helper_client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--arm", choices=["baseline", "intention"])
    args = parser.parse_args()
    root = args.directory.resolve()
    if args.arm:
        return run_arm(root, args.arm)
    actual = subprocess.check_output(["git", "-C", str(AUTHOR), "rev-parse", "HEAD"], text=True).strip()
    if actual != COMMIT:
        raise RuntimeError(f"Unexpected upstream revision: {actual}")
    if subprocess.check_output(["git", "-C", str(AUTHOR), "diff", "HEAD", "--"], text=True):
        raise RuntimeError("Author tracked source has local modifications")
    if json.loads(SCENARIO.read_text()) != json.loads((AUTHOR / "data/PMBench/data/synthetic_week_v9.json").read_text()):
        raise RuntimeError("Benchmarks differ semantically")
    root.mkdir(parents=True, exist_ok=False)
    sources = list((AUTHOR / "code").rglob("*.py")) + list((AUTHOR / "data/PMBench/sim").glob("*.py"))
    hashes = {}
    for source in sources:
        relative = source.relative_to(AUTHOR)
        target = root / "author_source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        hashes[str(relative)] = hashlib.sha256(source.read_bytes()).hexdigest()
    shutil.copy2(__file__, root / "run_author_pis.py")
    shutil.copy2(SCENARIO, root / "scenario.json")
    shutil.copy2(AUTHOR / "LICENSE", root / "AUTHOR_LICENSE")
    write_json(root / "manifest.json", {
        "author_url": "https://github.com/ChengcanWu/prospective-memory-reaearch",
        "author_commit": COMMIT, "source_sha256": hashes,
        "scenario_sha256": hashlib.sha256(SCENARIO.read_bytes()).hexdigest(),
        "model": MODEL, "dtype": "bfloat16", "quantization": None,
        "model_snapshot": "b968826d9c46dd6066d109eabc6255188de91218",
        "temperature": 0, "thinking": False, "actor_max_tokens": 768,
        "helper_max_tokens": "unchanged author defaults (per-call trace records exact values)",
        "actor_server": "vllm 0.8.5.post1, port 30003, GPU1, seed0, context32768",
        "helper_server": "vllm 0.8.5.post1, port 30002, GPU0, seed0, context32768, xgrammar:disable-any-whitespace",
        "adaptations": ["Local-only helper routing", "Qwen thinking disabled on all calls", "Raw API trace logging"],
        "safety": "Abort after 2000 API calls or 2 hours per arm; never fabricate actions",
        "policy": "Unchanged author defaults: due retrieval, compact history, force-clock, attempted-action done marking",
        "comparison": "Prior independent PIS triplet 20260922-03; not cost/prompt/cardinality matched"})
    for arm in ("baseline", "intention"):
        print(f"Starting author {arm}", flush=True)
        with (root / f"{arm}.console.log").open("x") as log:
            try:
                result = subprocess.run([sys.executable, "-u", __file__, str(root), "--arm", arm],
                                        stdout=log, stderr=subprocess.STDOUT, timeout=7200)
            except subprocess.TimeoutExpired:
                write_json(root / "status.json", {"status": "aborted", "arm": arm, "reason": "wall timeout"})
                raise
        if result.returncode:
            write_json(root / "status.json", {"status": "failed", "arm": arm, "returncode": result.returncode})
            return result.returncode
        print(f"Completed author {arm}", flush=True)
    write_json(root / "status.json", {"status": "completed"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
