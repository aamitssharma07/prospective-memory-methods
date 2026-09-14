#!/usr/bin/env python3
"""Run a fresh empty-fallback memory experiment against a local model server."""
import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "PMBench" / "sim"))
import pm_bench
from memory_intervention import MemoryAssistant
from structured_memory import StructuredMemory
from score_paired import metric_payload
from prospective_memory import Engine
from prospective_memory.llm import LLMMemoryPolicy
from prospective_memory.adapters.pmbench import PMBenchAdapter


def helper_response_format(system):
    text = {"type": "string"}
    if "STRUCTURED_INTENTIONS_V2" in system:
        fields = {f: {"type": "string", "minLength": 1, "maxLength": 800} for f in
                  ("id", "action", "trigger", "day", "channel", "status", "evidence")}
        fields["status"] = {"type": "string", "enum": ["pending", "attempted", "cancelled", "expired"]}
        properties = {"records": {"type": "array", "maxItems": 16, "items": {
            "type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}}}
    elif '"edits"' in system:
        variants = []
        for op, fields in (("status", {"text": text}),
                           ("save", {"section": {"type": "string", "enum": ["knowledge", "procedural"]}, "id": text, "text": text}),
                           ("delete", {"section": {"type": "string", "enum": ["knowledge", "procedural"]}, "id": text})):
            properties = {"op": {"type": "string", "enum": [op]}, **fields}
            variants.append({"type": "object", "properties": properties,
                             "required": list(properties), "additionalProperties": False})
        properties = {"edits": {"type": "array", "maxItems": 16, "items": {"anyOf": variants}}}
    else:
        properties = {"reminder": {"type": "string", "maxLength": 1200}}
    return {"type": "json_schema", "json_schema": {"name": "memory_output", "strict": True,
            "schema": {"type": "object", "properties": properties,
                       "required": list(properties), "additionalProperties": False}}}


def generate_helper(client, model, system, payload, max_tokens=2048, schema=None):
    return client.chat.completions.create(
        model=model, temperature=0.0, max_tokens=max_tokens,
        response_format=helper_response_format(system) if schema is None else {
            "type": "json_schema", "json_schema": {
                "name": "portable_memory_output", "strict": True, "schema": schema}},
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": json.dumps(payload)}])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["baseline", "heartbeat", "full_bank", "always", "selective"], required=True)
    parser.add_argument("--model", default="Qwen/Qwen3-8B")
    parser.add_argument("--memory-model", default=None)
    parser.add_argument("--base-url", default="http://127.0.0.1:30002/v1")
    parser.add_argument("--scenario", default=str(ROOT / "PMBench/data/synthetic_week_v9.json"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--memory-max-tokens", type=int, default=2048)
    parser.add_argument("--memory-version", choices=["v1", "v2", "portable"], default="v1")
    parser.add_argument("--memory-check-budget", type=int, default=1,
                        help="Portable: distinct CHECK proposals per assessment; not a total actor query limit")
    args = parser.parse_args()
    if args.memory_max_tokens < 1 or args.memory_check_budget < 0:
        parser.error("Memory tokens must be positive and check budget nonnegative")
    if args.memory_version == "portable" and args.mode != "selective":
        parser.error("Portable memory currently supports --mode selective only")
    output = Path(args.output)
    # Never overwrite a prior experiment.
    output.mkdir(parents=True, exist_ok=False)
    source_files = [Path(__file__), ROOT / "PMBench/sim/pm_bench.py"]
    if args.memory_version == "portable":
        source_files += [ROOT / "prospective_memory" / file for file in
                         ("core.py", "llm.py", "adapters/pmbench.py")]
    else:
        source_files += [ROOT / "pmbench_fallback_audit" / file for file in
                         ("memory_intervention.py", "structured_memory.py")]
    (output / "manifest.json").write_text(json.dumps({**vars(args), "fallback": "empty", "max_tokens": 768, "temperature": 0.0,
        "memory_output": "json_schema", "memory_enable_thinking": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in source_files},
        "scenario_sha256": hashlib.sha256(Path(args.scenario).read_bytes()).hexdigest(),
        "check_budget_scope": "distinct proposals per helper assessment, not actor query enforcement"
        if args.memory_version == "portable" else None}, indent=2))
    client = pm_bench.build_llm_client("sglang", base_url=args.base_url)
    with (output / "memory.jsonl").open("w") as memory_log, (output / "memory_calls.jsonl").open("w") as calls:
        def generate(system, payload):
            response = generate_helper(client, args.memory_model or args.model,
                                       system, payload, args.memory_max_tokens)
            calls.write(json.dumps({"usage": response.usage.model_dump() if response.usage else None,
                                    "finish_reason": response.choices[0].finish_reason}) + "\n")
            calls.flush()
            return response.choices[0].message.content or ""
        adapter = StructuredMemory if args.memory_version == "v2" else MemoryAssistant
        if args.memory_version == "portable":
            call_id = 0
            def request(system, payload, schema):
                nonlocal call_id
                call_id += 1
                phase = "compile" if "changes" in schema["properties"] else "assess"
                started = time.monotonic()
                record = {"call_id": call_id, "cycle": assistant.cycles, "phase": phase,
                          "payload": payload}
                try:
                    response = generate_helper(client, args.memory_model or args.model,
                                               system, payload, args.memory_max_tokens, schema=schema)
                    raw = response.choices[0].message.content or ""
                    record.update(usage=response.usage.model_dump() if response.usage else None,
                                  finish_reason=response.choices[0].finish_reason, raw=raw)
                    return json.loads(raw)
                except Exception as exc:
                    record["error"] = str(exc)
                    raise
                finally:
                    record["elapsed_seconds"] = time.monotonic() - started
                    calls.write(json.dumps(record) + "\n")
                    calls.flush()
            policy = LLMMemoryPolicy(request)
            engine = Engine(policy.compile, policy.assess, sources=("events",),
                            queryable_sources=(), query_budget=args.memory_check_budget)
            assistant = PMBenchAdapter(engine, log=memory_log)
        else:
            assistant = None if args.mode in {"baseline", "heartbeat"} else adapter(generate, args.mode, memory_log)
        scenario = pm_bench.load_scenario(args.scenario)
        try:
            # Keep the full actor dialogue even if an interrupted run cannot
            # write its final trajectory. This changes logging only, not policy.
            class Tee:
                def __init__(self, *streams):
                    self.streams = streams
                def write(self, text):
                    for stream in self.streams:
                        stream.write(text)
                        stream.flush()
                    return len(text)
                def flush(self):
                    for stream in self.streams:
                        stream.flush()
            with (output / "console.log").open("w") as console, \
                 contextlib.redirect_stdout(Tee(sys.stdout, console)):
                entries = pm_bench.run_llm(
                    scenario, str(output / "trajectory.jsonl"), args.model, ".env", 5,
                    "sglang", args.base_url, None, max_tokens=768,
                    auto_heartbeat_minutes=30 if args.mode == "heartbeat" else None,
                    invalid_response_fallback="empty", memory_adapter=assistant,
                    prompt_log_path=str(output / "prompts.log"))
        finally:
            if args.memory_version == "portable":
                (output / "memory_snapshot.json").write_text(json.dumps(assistant.snapshot(), indent=2))
        summary, per_day, steps = pm_bench.score_log(scenario, entries)
        (output / "metrics.json").write_text(json.dumps({"metrics": metric_payload(summary),
            "summary": summary, "per_day": per_day, "steps": steps,
            "fallback_steps": sum(bool(e.get("fallback_triggered")) for e in entries)}, indent=2))


if __name__ == "__main__":
    main()
