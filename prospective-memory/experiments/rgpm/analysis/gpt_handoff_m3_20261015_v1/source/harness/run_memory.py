#!/usr/bin/env python3
"""Run a fresh empty-fallback memory experiment against a local model server."""
import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmark" / "sim"))
import pm_bench
from memory_intervention import MemoryAssistant
from structured_memory import StructuredMemory
from score_paired import metric_payload
from prospective_memory import Engine
from prospective_memory.grounded import make_policy
from prospective_memory.baselines.pis import PISEngine
from prospective_memory.pis_grounded import GroundedPISEngine
from prospective_memory.adapters.pmbench import PMBenchAdapter
from prospective_memory.decoding import WHITESPACE_REMEDY, probe_compact_decoding


SOURCE_BOUND_VARIANTS = {"sbpm_minimal": "sbpm_minimal",
                         "sbpm_no_projection": "sbpm_no_projection",
                         "sbpm_no_arbiter": "sbpm_no_arbiter",
                         "sbpm": "sbpm"}
PROJECTED_POLICIES = frozenset({"sbpm_no_arbiter", "sbpm"})
PIS_POLICIES = frozenset({"pis", "pis_verified", "pis_grounded", *SOURCE_BOUND_VARIANTS})


def portable_phase(schema):
    """Name the logged operation without modifying its structured-output schema."""
    properties = schema["properties"]
    for key, phase in (("operations", "extract"),
                       ("unit_classifications", "classify_unit"),
                       ("identity_reviews", "identity_review"),
                       ("specifications", "compile_typed"),
                       ("trigger_projections", "trigger_projection"),
                       ("changes", "compile"),
                       ("reviews", "change_review"),
                       ("resolutions", "resolve"),
                       ("verdict", "verify")):
        if key in properties:
            return phase
    return "assess"


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
    parser.add_argument("--base-url", default="http://127.0.0.1:30002/v1",
                        help="Actor server. Keep its grammar backend matched to the baseline.")
    parser.add_argument("--memory-base-url", default=None,
                        help="Memory-helper server; defaults to --base-url. PM-Bench's actor "
                             "schema carries maxItems, which xgrammar rejects, so a "
                             "whitespace-free helper server must be separate from the actor's.")
    parser.add_argument("--scenario", default=str(ROOT / "benchmark/data/synthetic_week_v9.json"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--memory-max-tokens", type=int, default=None,
                        help="Per helper-call output limit; defaults to 4096 for "
                             "source-bound policies and 2048 for other policies.")
    parser.add_argument("--memory-version", choices=["v1", "v2", "portable"], default="v1")
    parser.add_argument("--memory-policy", choices=['legacy', 'grounded', 'verified', 'pis', 'pis_verified', 'pis_grounded', *SOURCE_BOUND_VARIANTS], default='legacy')
    parser.add_argument("--allow-grammar-whitespace", action="store_true",
                        help="Skip the preflight that refuses a server whose JSON grammar "
                             "permits whitespace. Over a long run that trap turns completed "
                             "helper answers into decode errors that read as silence.")
    parser.add_argument("--memory-check-budget", type=int, default=1,
                        help="Portable: distinct CHECK proposals per assessment; not a total actor query limit")
    parser.add_argument("--memory-projector-id",
                        help="V4/V5: explicit stable helper model/checkpoint/decoding identity for cached views")
    parser.add_argument("--memory-projection-batch-size", type=int, default=4)
    parser.add_argument("--memory-assess-workers", type=int, default=1,
                        help="Dispatch this many order-independent intention assessments at "
                             "once. Assessments that could spend the query budget stay "
                             "sequential, so decisions are unchanged; only wall-clock differs. "
                             "1 (default) reproduces the original strictly serial loop.")
    parser.add_argument("--memory-skip-unevidenced", action="store_true",
                        help="Skip assessments for intentions with no current observation on a "
                             "watched source and no queryable source left. Such a call can only "
                             "return WAIT, so the decision is unchanged and the call is saved.")
    parser.add_argument("--memory-reuse-stable-waits", action="store_true",
                        help="Within one step, reuse an intention's previous WAIT when nothing "
                             "on its watched sources has changed. Queryable sources only shrink "
                             "within a step, so re-asking cannot surface new evidence.")
    parser.add_argument("--memory-assess-batch-size", type=int, default=1,
                        help="Judge this many order-independent intentions in one prompt. "
                             "They share the observations and system prompt, so calls fall "
                             "roughly by this factor. 1 (default) keeps one call each.")
    parser.add_argument("--memory-extract-spans", action="store_true",
                        help="Store the marked action/condition spans from a request instead of "
                             "the whole prose unit. Spans must be verbatim substrings; anything "
                             "else falls back to the unit, so no intention is lost.")
    parser.add_argument("--memory-day-gate", choices=("scope", "explicit"), default="scope",
                        help="'scope' (default) gates an undated intention to the day it was "
                             "announced. 'explicit' gates only on a day named in the text, so a "
                             "purely event-based intention can still fire on a later day.")
    parser.add_argument("--memory-query-handoff", choices=("legacy", "explicit"), default="legacy",
                        help="Portable optional query advice: exact host query JSON, never forced execution")
    args = parser.parse_args()
    if args.memory_max_tokens is None:
        args.memory_max_tokens = 4096 if args.memory_policy in SOURCE_BOUND_VARIANTS else 2048
    if args.memory_max_tokens < 1 or args.memory_check_budget < 0:
        parser.error("Memory tokens must be positive and check budget nonnegative")
    if args.memory_version == "portable" and args.mode != "selective":
        parser.error("Portable memory currently supports --mode selective only")
    if args.memory_policy != 'legacy' and args.memory_version != 'portable':
        parser.error("An experimental memory policy requires --memory-version portable")
    if args.memory_query_handoff != 'legacy' and args.memory_version != 'portable':
        parser.error("Explicit query handoff requires --memory-version portable")
    if not 1 <= args.memory_projection_batch_size <= 32:
        parser.error("Projection batch size must be between 1 and 32")
    if args.memory_policy in PROJECTED_POLICIES:
        if not args.memory_projector_id or not args.memory_projector_id.strip():
            parser.error("Projected policies require --memory-projector-id identifying the model/checkpoint/decoding configuration")
    elif args.memory_projector_id is not None or args.memory_projection_batch_size != 4:
        parser.error("Projector configuration is only supported for V4/V5 projected policies")
    output = Path(args.output)
    # Never overwrite a prior experiment.
    output.mkdir(parents=True, exist_ok=False)
    source_files = [Path(__file__), ROOT / "benchmark/sim/pm_bench.py"]
    if args.memory_version == "portable":
        source_files += [ROOT / "prospective_memory" / file for file in
                         ("core.py", "llm.py", "grounded.py", "adapters/pmbench.py")]
        if args.memory_policy in PIS_POLICIES:
            source_files.append(ROOT / "prospective_memory/baselines/pis.py")
        if args.memory_policy == 'pis_grounded':
            source_files.append(ROOT / "prospective_memory/pis_grounded.py")
        if args.memory_policy in SOURCE_BOUND_VARIANTS:
            source_files += [ROOT / "prospective_memory" / file for file in
                             ("method/source_bound.py", "baselines/pis_registration.py", "method/calendar_guard.py")]
        if args.memory_policy in {'sbpm_no_projection', *PROJECTED_POLICIES}:
            source_files += [ROOT / "prospective_memory" / file for file in
                             ("method/source_bound_v3.py", "method/registration.py")]
        if args.memory_policy in PROJECTED_POLICIES:
            source_files += [ROOT / "prospective_memory" / file for file in
                             ("method/projection_cache.py", "method/trigger_engine.py")]
        if args.memory_policy == 'sbpm':
            source_files += [ROOT / "prospective_memory" / file for file in
                             ("method/fair_checks.py", "method/fair_trigger.py")]
    else:
        source_files += [ROOT / "harness" / file for file in
                         ("memory_intervention.py", "structured_memory.py")]
    # Preserve executable policy sources, not only hashes: this workspace need
    # not be a git checkout and later experiments may edit the same files.
    for source in source_files:
        snapshot = output / "source" / source.relative_to(ROOT)
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes(source.read_bytes())
    (output / "scenario.json").write_bytes(Path(args.scenario).read_bytes())
    projection_metadata = None
    if args.memory_policy in PROJECTED_POLICIES:
        from prospective_memory.method.projection_cache import projection_definition
        projection_metadata = projection_definition()
    (output / "manifest.json").write_text(json.dumps({**vars(args), "fallback": "empty", "max_tokens": 768, "temperature": 0.0,
        "memory_output": "json_schema", "memory_enable_thinking": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in source_files},
        "scenario_sha256": hashlib.sha256(Path(args.scenario).read_bytes()).hexdigest(),
        "pis_step_query_budget": 2 if args.memory_policy in PIS_POLICIES else None,
        "pis_query_abort_limit": 12 if args.memory_policy in PIS_POLICIES else None,
        "policy_variant": SOURCE_BOUND_VARIANTS.get(args.memory_policy),
        "projection_definition": projection_metadata,
        "check_budget_scope": "distinct proposals per helper assessment, not actor query enforcement"
        if args.memory_version == "portable" else None}, indent=2))
    if args.memory_extract_spans:
        from prospective_memory.baselines.pis_registration import set_extract_spans
        set_extract_spans(True)
    if args.memory_day_gate == "explicit":
        from prospective_memory.baselines.pis_registration import set_implicit_day_gate
        set_implicit_day_gate(False)
    client = pm_bench.build_llm_client("sglang", base_url=args.memory_base_url or args.base_url)
    if args.mode not in {"baseline", "heartbeat"}:
        def probe(system, payload, schema):
            response = generate_helper(client, args.memory_model or args.model,
                                       system, payload, 256, schema=schema)
            return response.choices[0].message.content or ""
        if not probe_compact_decoding(probe) and not args.allow_grammar_whitespace:
            raise SystemExit(WHITESPACE_REMEDY + " Pass --allow-grammar-whitespace to "
                             "record a run without that guarantee.")
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
            call_lock = threading.Lock()
            def request(system, payload, schema):
                nonlocal call_id
                with call_lock:
                    call_id += 1
                    my_call_id = call_id
                phase = portable_phase(schema)
                started = time.monotonic()
                record = {"call_id": my_call_id, "cycle": assistant.cycles, "phase": phase,
                          "system": system, "payload": payload, "schema": schema,
                          "max_tokens": args.memory_max_tokens}
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
                    with call_lock:
                        calls.write(json.dumps(record) + "\n")
                        calls.flush()
            if args.memory_policy in PIS_POLICIES:
                engine_options = {}
                if args.memory_policy in PROJECTED_POLICIES:
                    from prospective_memory.method.trigger_engine import SourceBoundTriggerEngine
                    from prospective_memory.method.fair_trigger import SourceBoundFairTriggerEngine
                    engine_class = (SourceBoundFairTriggerEngine if args.memory_policy == 'sbpm'
                                    else SourceBoundTriggerEngine)
                    engine_options = {"projector_id": args.memory_projector_id,
                                      "projection_batch_size": args.memory_projection_batch_size}
                elif args.memory_policy == 'sbpm_no_projection':
                    from prospective_memory.method.source_bound_v3 import SourceBoundV3Engine
                    engine_class = SourceBoundV3Engine
                elif args.memory_policy == 'sbpm_minimal':
                    from prospective_memory.method.source_bound import SourceBoundPISEngine
                    engine_class = SourceBoundPISEngine
                else:
                    engine_class = GroundedPISEngine if args.memory_policy == 'pis_grounded' else PISEngine
                engine = engine_class(request, sources=("events",), queryable_sources=(),
                                   query_budget=args.memory_check_budget,
                                   verify_actions=args.memory_policy == 'pis_verified',
                                   max_assess_workers=args.memory_assess_workers,
                                   skip_unevidenced=args.memory_skip_unevidenced,
                                   reuse_stable_waits=args.memory_reuse_stable_waits,
                                   assess_batch_size=args.memory_assess_batch_size, **engine_options)
            else:
                policy = make_policy(request, args.memory_policy)
                engine = Engine(policy.compile, policy.assess, sources=("events",),
                                queryable_sources=(), query_budget=args.memory_check_budget)
            assistant = PMBenchAdapter(engine, log=memory_log, query_handoff=args.memory_query_handoff)
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
