"""Run the resumable RGPM candidate with fully recorded local model calls."""

import argparse
import contextlib
import copy
import fcntl
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "benchmark/sim", ROOT / "harness", Path(__file__).parent):
    sys.path.insert(0, str(path))
import pm_bench
from adapter import RGPMAdapter
from prospective_memory.adapters.pmbench import PMBenchAdapter
from prospective_memory.baselines.pis_registration import set_extract_spans
from prospective_memory.method.fair_trigger import SourceBoundFairTriggerEngine
from run_memory import portable_phase
from artifacts import Session, digest, now, save, traced_adapter_class
from analyze import analyze, index_artifacts
from source_routing import route_specifications
from improved_engine import ImprovedTriggerEngine


def local_url(value):
    url = urlsplit(value)
    if (url.scheme not in {"http", "https"} or url.hostname not in {"127.0.0.1", "localhost"}
            or url.username or url.password or url.query or url.fragment):
        raise ValueError("Local execution requires a credential-free loopback server URL")
    return value


def bounded_actor_request(request, adapter, session):
    def bounded(*args, **kwargs):
        queries = adapter.engine.step_queries
        if len(queries) >= 12:
            reason = "actor_query_limit: 12 state queries without advancing"
            session.event("actor_query_limit", step_id=adapter.engine.step_id,
                          query_attempts=list(queries), recovery="empty_incorrect")
            raise pm_bench.InvalidModelResponseError(reason)
        return request(*args, **kwargs)
    return bounded


def source_files():
    return sorted(set([ROOT / "benchmark/sim/pm_bench.py", ROOT / "harness/run_memory.py",
                       ROOT / "harness/score_paired.py",
                       *ROOT.joinpath("prospective_memory").rglob("*.py"),
                       *Path(__file__).parent.glob("*.py"),
                       *Path(__file__).parent.glob("*.sbatch"),
                       *Path(__file__).parent.glob("*.sh")]))


def run(args, helper_client=None):
    actor_backend = getattr(args, "actor_backend", "sglang")
    if getattr(args, "local_only", False) and actor_backend != "sglang":
        raise ValueError("--local-only forbids a hosted actor backend")
    # The helper always stays local: it runs the structured decoding this
    # method depends on, with no case yet for a hosted API there. The actor
    # is a plain chat completion, so a hosted backend (OpenRouter) is allowed
    # for it specifically, with no credential embedded in the URL itself --
    # the API key travels only via build_llm_client's own env lookup.
    helper_candidate = getattr(args, "helper_base_url", None) or (
        args.base_url if actor_backend == "sglang" else "http://127.0.0.1:30003/v1")
    local_url(helper_candidate)
    if actor_backend == "sglang":
        local_url(args.base_url)
    elif actor_backend in {"openrouter", "openai_chat"}:
        url = urlsplit(args.base_url)
        if url.scheme != "https" or url.username or url.password:
            raise ValueError("The OpenRouter actor backend requires a plain https URL with no embedded credentials")
    else:
        raise ValueError(f"Unknown actor backend: {actor_backend}")
    scenario_path = Path(args.scenario)
    scenario = pm_bench.load_scenario(str(scenario_path))
    sources = {str(p.relative_to(ROOT)): digest(p) for p in source_files()}
    helper_model = getattr(args, "helper_model", None) or args.model
    helper_base_url = helper_candidate
    candidate = bool(getattr(args, "scope_grounding", False) or getattr(args, "bounded_priority", False)
                     or getattr(args, "registration_grounding", False))
    config = {"actor_model": args.model, "helper_model": helper_model,
              "helper_base_url": helper_base_url, "actor_backend": actor_backend,
              "max_tokens": 768, "helper_max_tokens": 768, "temperature": 0,
              "enable_thinking": False, "policy": "sbpm_consolidated" if candidate else "sbpm", "extract_spans": True,
              "query_handoff": getattr(args, "query_handoff", "explicit"),
              "actor_guidance": getattr(args, "actor_guidance", "balanced_v2"),
              "report_gates": bool(getattr(args, "report_gates", False)),
              "gate_style": getattr(args, "gate_style", "terse"),
              "verify_actions": bool(getattr(args, "verify_actions", False)),
              "source_routing": bool(getattr(args, "source_routing", False)),
              "scope_grounding": bool(getattr(args, "scope_grounding", False)),
              "bounded_priority": bool(getattr(args, "bounded_priority", False)),
              "registration_grounding": bool(getattr(args, "registration_grounding", False)),
              "local_only": bool(getattr(args, "local_only", False)),
              "max_actor_calls": getattr(args, "max_actor_calls", None),
              "max_actor_tokens": getattr(args, "max_actor_tokens", None),
              "actor_query_limit": 12, "query_limit_recovery": "empty_incorrect",
              "day_gate": "scope", "query_budget": getattr(args, "query_budget", 1),
              "step_query_budget": 2, "projection_batch_size": 1,
              "compile_batch_size": 1,
              "skip_unevidenced": False, "reuse_stable_waits": False,
              "assess_batch_size": 1, "seed": None, "seed_reason": "server default; temperature zero",
              "projector_id": args.projector_id, "base_url": args.base_url,
              "actor_projector_id": getattr(args, "actor_projector_id", None),
              "scenario_sha256": digest(scenario_path), "source_sha256": sources,
              "kind": args.kind}
    fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    output = Path(args.output)
    if not args.resume:
        output.mkdir(parents=True, exist_ok=False)
    lock = (output / ".lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        if args.resume:
            manifest = json.loads((output / "manifest.json").read_text())
            if manifest["fingerprint"] != fingerprint:
                raise ValueError("Scenario, configuration or source changed; use a new run")
            if json.loads((output / "status.json").read_text())["status"] == "complete":
                return analyze(output)
        else:
            provenance = json.loads(Path(args.provenance).read_text()) if args.provenance else {
                "server": None, "reason": "externally managed; metadata not supplied"}
            actor_provenance = (json.loads(Path(args.actor_provenance).read_text())
                                if getattr(args, "actor_provenance", None) else
                                {"backend": actor_backend, "model": args.model, "base_url": args.base_url,
                                 "temperature": 0, "max_tokens": 768,
                                 "serving": "hosted; provider response metadata retained per call"}
                                if actor_backend in {"openrouter", "openai_chat"} else provenance)
            save(output / "manifest.json", {"schema_version": 1, "run_id": output.name,
                 "created_at": now(), "fingerprint": fingerprint, **config,
                 "canonical_scenario_sha256": hashlib.sha256(json.dumps(scenario, sort_keys=True).encode()).hexdigest(),
                 "provenance": provenance, "actor_provenance": actor_provenance,
                 "dependencies": {name: importlib.metadata.version(name) for name in ("openai", "jsonschema")}})
            (output / "scenario.json").write_bytes(scenario_path.read_bytes())
            for source in source_files():
                target = output / "source" / source.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
            for name in ("calls.jsonl", "memory_calls.jsonl", "memory.jsonl", "events.jsonl",
                         "trajectory.jsonl", "prompts.log", "console.log"):
                (output / name).touch()
            save(output / "server.log", {"externally_managed_server": True, "provenance": provenance})
        session = Session(output, fingerprint, args.resume, args.stop_after,
                          max_actor_calls=config["max_actor_calls"], max_actor_tokens=config["max_actor_tokens"])
        try:
            client = helper_client or pm_bench.build_llm_client("sglang", base_url=helper_base_url)
            if hasattr(client, "with_options"):
                client = client.with_options(max_retries=0, timeout=180)

            def request(system, payload, schema):
                # Long instruction lists cannot fit a typed row per operation in 768 tokens.
                # Keep the same source/target context while compiling one row per call.
                if "specifications" in schema["properties"] and len(payload.get("operations", [])) > 1:
                    specifications = []
                    for operation in payload["operations"]:
                        reply = request(system, {**payload, "operations": [operation]}, schema)
                        specifications.extend(reply["specifications"])
                    return {"specifications": specifications}
                if candidate:
                    schema = copy.deepcopy(schema)
                    counts = {"unit_classifications": 1, "identity_reviews": 1,
                              "specifications": len(payload.get("operations", [])),
                              "trigger_projections": len(payload.get("records", [])),
                              "assessments": len(payload.get("intentions", [])) or 1}
                    for key, count in counts.items():
                        if key in schema["properties"] and count:
                            schema["properties"][key].update(minItems=count, maxItems=count)
                previous, previous_phase = session.operation_id, session.phase
                phase = ("registration_repair" if payload.get("classification_repair")
                         else "registration_review" if payload.get("classification_review")
                         else "registration_target_resolution" if "target_resolutions" in schema["properties"]
                         else "registration_target_action_match" if "target_matches" in schema["properties"]
                         else "registration_reference_resolution" if "reference_resolutions" in schema["properties"]
                         else "registration_occasion_comparison" if "occasion_comparisons" in schema["properties"]
                         else "registration_partition" if "parts" in schema["properties"]
                         else "source_routing" if set(schema["properties"]) == {"status", "watched_sources", "reason"}
                         else portable_phase(schema))
                session.operation(phase)
                session.event("helper_operation", parent_operation_id=previous,
                              phase=phase, intention_id=payload.get("intention_id"),
                              revision=payload.get("revision"),
                              projection_binding=payload.get("projection_binding"))
                try:
                    response = session.call(client, "helper", model=helper_model, temperature=0,
                        max_tokens=768, messages=[{"role": "system", "content": system},
                            {"role": "user", "content": json.dumps(payload)}],
                        response_format={"type": "json_schema", "json_schema": {
                            "name": "rgpm_helper", "strict": True, "schema": schema}},
                        extra_body={"chat_template_kwargs": {"enable_thinking": False}})
                    reply = json.loads(response.choices[0].message.content)
                    if config["source_routing"] and "specifications" in schema["properties"]:
                        reply = route_specifications(reply, payload, request, session.event)
                    return reply
                finally:
                    session.operation_id = previous
                    session.phase = previous_phase

            set_extract_spans(True)
            engine_class = ImprovedTriggerEngine if candidate else SourceBoundFairTriggerEngine
            candidate_options = {"scope_grounding": config["scope_grounding"],
                                 "bounded_priority": config["bounded_priority"],
                                 "registration_grounding": config["registration_grounding"]} if candidate else {}
            engine = engine_class(request, projector_id=args.projector_id,
                                                  projection_batch_size=1,
                                                  query_budget=config["query_budget"],
                                                  step_query_budget=config["step_query_budget"],
                                                  verify_actions=config["verify_actions"], **candidate_options)
            adapter = traced_adapter_class(RGPMAdapter)(engine, session)
            adapter.guidance = config["actor_guidance"]
            adapter.query_handoff = config["query_handoff"]
            adapter.report_gates = config["report_gates"]
            adapter.gate_style = config["gate_style"]
            session.bind(adapter)
            with (output / "console.log").open("a", buffering=1) as console:
                with contextlib.redirect_stdout(console), contextlib.redirect_stderr(console), patch.object(
                        pm_bench, "request_model_action",
                        bounded_actor_request(pm_bench.request_model_action, adapter, session)):
                    actor_api_key = (pm_bench.load_openrouter_api_key()
                                     if actor_backend == "openrouter" else None)
                    pm_bench.run_llm(scenario, str(output / "trajectory.jsonl"), args.model,
                        None, 5, actor_backend, args.base_url, actor_api_key, max_tokens=768,
                        invalid_response_fallback="empty", memory_adapter=adapter, session=session)
            save(output / "memory_snapshot.json", adapter.snapshot())
            metrics = analyze(output)
            session.event("complete")
            session.status("complete")
            index_artifacts(output)
            return metrics
        except BaseException as exc:
            from artifacts import ActorBudgetExceeded
            state = "interrupted" if isinstance(exc, (KeyboardInterrupt, InterruptedError, ActorBudgetExceeded)) else "failed"
            session.event(state, error={"type": type(exc).__name__, "message": str(exc)})
            session.status(state, error={"type": type(exc).__name__, "message": str(exc)})
            raise
    finally:
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--scenario", default=str(ROOT / "benchmark/data/synthetic_week_v9.json"))
    parser.add_argument("--model", default="Qwen/Qwen3-8B")
    parser.add_argument("--actor-backend", choices=("sglang", "openrouter", "openai_chat"), default="sglang",
                        help="The helper always stays local (sglang); this selects the actor's backend only")
    parser.add_argument("--base-url", default=None,
                        help="Defaults to a local sglang server, or to OpenRouter when --actor-backend=openrouter")
    parser.add_argument("--helper-model", default=None,
                        help="Defaults to --model; set to run a different helper model (asymmetric actor/helper)")
    parser.add_argument("--helper-base-url", default=None,
                        help="Defaults to --base-url; required when --helper-model differs from --model")
    parser.add_argument("--projector-id", required=True,
                        help="Serving identity of the HELPER model, which runs structured decoding")
    parser.add_argument("--actor-projector-id", default=None,
                        help="Serving identity of the actor model, recorded for provenance only")
    parser.add_argument("--provenance")
    parser.add_argument("--actor-provenance", default=None,
                        help="Actor server provenance JSON, recorded only when it differs from --provenance")
    parser.add_argument("--kind", choices=("smoke", "benchmark"), required=True)
    parser.add_argument("--actor-guidance", choices=("balanced_v2", "none", "query_first"), default="balanced_v2")
    parser.add_argument("--query-handoff", choices=("explicit", "legacy"), default="explicit")
    parser.add_argument("--report-gates", action="store_true",
                        help="Tell the actor which stored obligations fail their own typed clock/day gate")
    parser.add_argument("--gate-style", choices=("terse", "verbose"), default="terse",
                        help="How --report-gates is phrased: a one-line-per-item list (terse, the "
                             "default) or the original reasoning-heavy JSON block (verbose)")
    parser.add_argument("--verify-actions", action="store_true",
                        help="Re-check every proposed ACT with a second helper call against the "
                             "original unredacted instructions before it reaches the actor; "
                             "downgrades an unsupported ACT to WAIT")
    parser.add_argument("--source-routing", action="store_true",
                        help="Choose evidence sources separately for new requests using their validated spans")
    parser.add_argument("--scope-grounding", action="store_true")
    parser.add_argument("--bounded-priority", action="store_true")
    parser.add_argument("--registration-grounding", action="store_true")
    parser.add_argument("--local-only", action="store_true", help="Reject hosted actors before any client construction")
    parser.add_argument("--max-actor-calls", type=int, help="Total actor attempts, including retries and resumed sessions")
    parser.add_argument("--max-actor-tokens", type=int, help="Actor token ceiling; missing usage blocks subsequent calls")
    parser.add_argument("--query-budget", type=int, default=1,
                        help="Distinct CHECK sources the arbiter may offer per assessment cycle")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop-after", type=int, help="Diagnostic interruption after N committed steps")
    args = parser.parse_args()
    if args.base_url is None:
        args.base_url = ("https://openrouter.ai/api/v1" if args.actor_backend == "openrouter"
                          else "https://api.openai.com/v1" if args.actor_backend == "openai_chat"
                          else "http://127.0.0.1:30003/v1")
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    main()
