"""Validate matched serving settings and record long-request diagnostics locally."""

import argparse
import copy
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from artifacts import save
from run import ROOT, pm_bench


def option(command, name, default=None):
    return command[command.index(name) + 1] if name in command else default


def validate_served(expected, provenance):
    for key in ("model", "revision", "dtype", "mem_fraction_static"):
        if provenance.get(key) != expected.get(key):
            raise ValueError(f"Serving mismatch: {key}")
    command = provenance["command"]
    if option(command, "--tp-size") != "1":
        raise ValueError("Consistency rerun requires TP=1")
    disabled = all(flag in command for flag in ("--disable-prefill-cuda-graph", "--disable-decode-cuda-graph"))
    if disabled != expected["disable_cuda_graph"]:
        raise ValueError("CUDA graph settings differ from the reference")
    config = json.loads((Path(provenance["checkpoint"]) / "config.json").read_text())
    text_config = config.get("text_config", config)
    if config.get("quantization_config") or text_config.get("quantization_config"):
        raise ValueError("Expected an unquantized BF16 checkpoint")
    if text_config.get("max_position_embeddings") != expected["model_context_tokens"]:
        raise ValueError("Checkpoint context configuration differs from reference")
    log = Path(provenance["server_log"]).read_text()
    capacities = re.findall(r"max_total_num_tokens=(\d+).*?context_len=(\d+)", log)
    if not capacities:
        raise ValueError("Effective KV capacity missing from startup log")
    cache, context = map(int, capacities[-1])
    if context != expected["model_context_tokens"]:
        raise ValueError("Served context differs from checkpoint configuration")
    minimum = expected.get("minimum_cache_tokens")
    if minimum is not None and cache < minimum:
        raise ValueError(f"KV capacity {cache} is below historical {minimum}")
    return {"model": provenance["model"], "revision": provenance["revision"],
            "quantization_config": config.get("quantization_config"),
            "model_context_tokens": context, "effective_cache_tokens": cache,
            "historical_minimum_cache_tokens": minimum}


def longest_requests(root):
    result = {}
    with (root / "calls.jsonl").open() as stream:
        for line in stream:
            call = json.loads(line)
            role = call["role"]
            if role not in {"actor", "helper"}:
                continue
            size = len(json.dumps(call["request"], ensure_ascii=False).encode())
            if role not in result or size > result[role][0]:
                result[role] = (size, call["call_id"], call["request"])
    return result


def probe(client, request, role, source_call_id):
    record = {"role": role, "phase": "matched_serving_long_request",
              "source_call_id": source_call_id, "request": request,
              "response": None, "raw": None, "parsed": None, "usage": None}
    started = time.monotonic()
    try:
        response = client.chat.completions.create(**request)
        record["response"] = response.model_dump()
        record["usage"] = response.usage.model_dump() if response.usage else None
        record["raw"] = response.choices[0].message.content
        record["finish_reason"] = response.choices[0].finish_reason
        record["transport_accepted"] = True
        try:
            record["parsed"] = json.loads(record["raw"])
        except (ValueError, TypeError):
            pass
        return record, None
    except Exception as exc:
        record["transport_accepted"] = False
        record["error"] = {"type": type(exc).__name__, "message": str(exc)}
        text = str(exc).lower()
        context_limit = ("maximum context length" in text or
                         ("input length" in text and "maximum allowed length" in text))
        record["context_limit_rejected"] = context_limit
        # Matching a historical input budget does not guarantee the updated
        # method fits it. Preserve that limitation, without changing the input.
        return record, None if context_limit else exc
    finally:
        record["duration_seconds"] = time.monotonic() - started


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument("--stage", choices=("prelaunch", "served"), required=True)
    parser.add_argument("--job-root", type=Path)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text())["pairs"][args.index]
    output = (args.job_root or ROOT / "experiments/rgpm/jobs" / f"consistency-{os.environ['SLURM_JOB_ID']}") / "consistency_admission"
    output.mkdir(parents=True, exist_ok=True)
    save(output / "spec.json", spec)
    if args.stage == "prelaunch":
        visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
        if not visible or "," in visible:
            raise ValueError("Historical co-location requires exactly one visible GPU")
        raw = subprocess.check_output(["nvidia-smi", "--id=" + visible,
            "--query-gpu=name,uuid,memory.total", "--format=csv,noheader,nounits"], text=True)
        row = next(csv.reader([raw.strip()]))
        result = {"gpu_name": row[0].strip(), "uuid": row[1].strip(), "memory_mib": int(row[2].strip())}
        save(output / "gpu.json", result)
        if "H100 NVL" not in result["gpu_name"] or result["memory_mib"] < 95000:
            raise ValueError("Historical serving requires the 96GB-class H100 NVL")
        for role, variable in (("actor", "MODEL"), ("helper", "HELPER_MODEL")):
            if os.environ.get(variable) != spec[role]["model"]:
                raise ValueError(f"Submission model does not match spec: {role}")
        return
    if args.job_root is None:
        raise ValueError("--job-root is required for served checks")
    report = {"settings": {}, "probe_outcomes": {},
              "guard_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    for role in ("actor", "helper"):
        provenance = json.loads((args.job_root / role / "server_provenance.json").read_text())
        report["settings"][role] = validate_served(spec[role], provenance)
    save(output / "settings.json", report)
    requests = longest_requests(ROOT / spec["original_updated_result_directory"])
    for role in ("actor", "helper"):
        _, source_id, request = requests[role]
        request = copy.deepcopy(request)
        request["model"] = spec[role]["model"]
        if request.get("max_tokens") != 768:
            raise ValueError("Long-request probe must retain the 768-token cap")
        url = "http://127.0.0.1:" + ("30003" if role == "actor" else "30004") + "/v1"
        client = pm_bench.build_llm_client("sglang", base_url=url).with_options(max_retries=0, timeout=180)
        record, fatal = probe(client, request, role, source_id)
        with (output / "calls.jsonl").open("a") as stream:
            stream.write(json.dumps(record) + "\n")
        report["probe_outcomes"][role] = {k: record.get(k) for k in
            ("transport_accepted", "context_limit_rejected", "duration_seconds", "error")}
        save(output / "settings.json", report)
        if fatal is not None:
            raise fatal
    report["passed_serving_consistency"] = True
    report["note"] = "Historical capacity matched; any over-budget public inputs remain reported limitations, not silently truncated or repaired. Probe calls are separate from scored benchmark calls."
    save(output / "settings.json", report)


if __name__ == "__main__":
    main()
