"""Frozen registration-only diagnostic with request-unit, one-to-one scoring.

The callback receives public Instructions/capabilities, never scorer rubrics.
No tick, query, ACT, actor action or acknowledgement is performed by this harness.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import re
import time

from ..core import Instruction
from ..decoding import WHITESPACE_REMEDY, probe_compact_decoding
from ..evaluate_pis_grounded import AuditedRequest, SmokeAbort, projection_definition, projection_options, utc_now, write_json
from ..baselines.pis import DAYS, PISEngine


DEFAULT_CASES = Path(__file__).parent.parent / "examples/batch_registration_v1.json"
POLICIES = ("sbpm_minimal", "sbpm_no_projection", "sbpm_no_arbiter", "sbpm")
SOURCE_FILES = (
    "prospective_memory/__init__.py", "prospective_memory/core.py",
    "prospective_memory/llm.py", "prospective_memory/baselines/pis.py",
    "prospective_memory/pis_grounded.py", "prospective_memory/method/source_bound.py",
    "prospective_memory/baselines/pis_registration.py", "prospective_memory/decoding.py",
    # AuditedRequest's module imports both policy generations. Preserve all
    # imported local dependencies even when the selected runtime policy is v2.
    "prospective_memory/method/source_bound_v3.py", "prospective_memory/method/registration.py",
    "prospective_memory/method/trigger_engine.py", "prospective_memory/method/projection_cache.py",
    "prospective_memory/method/fair_trigger.py", "prospective_memory/method/fair_checks.py",
    "prospective_memory/method/calendar_guard.py",
    "docs/dev_protocols/PIS_SOURCE_BOUND_V3.md",
    "prospective_memory/evaluate_pis_grounded.py",
    "prospective_memory/method/evaluate_registration_cases.py",
    "docs/dev_protocols/BATCH_REGISTRATION_PROTOCOL.md",
)


def engine_class(policy):
    if policy == "sbpm_minimal":
        from .source_bound import SourceBoundPISEngine
        return SourceBoundPISEngine
    if policy == "sbpm_no_projection":
        from .source_bound_v3 import SourceBoundV3Engine
        return SourceBoundV3Engine
    if policy == "sbpm_no_arbiter":
        from .trigger_engine import SourceBoundTriggerEngine
        return SourceBoundTriggerEngine
    if policy == "sbpm":
        from .fair_trigger import SourceBoundFairTriggerEngine
        return SourceBoundFairTriggerEngine
    raise ValueError("Unknown registration policy")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def contains(text, fragments):
    return all(fragment.casefold() in text.casefold() for fragment in fragments)


def validate_cases(dataset):
    require(dataset.get("version") == 1 and bool(dataset.get("cases")), "Expected nonempty v1 cases")
    case_ids = set()
    for case in dataset["cases"]:
        require(re.fullmatch(r"[a-z0-9_]+", case["id"]) and case["id"] not in case_ids,
                "Invalid or duplicate case ID")
        case_ids.add(case["id"])
        require(case["sources"] and len(case["sources"]) == len(set(case["sources"])), "Invalid sources")
        require(set(case["queryable_sources"]) <= set(case["sources"]), "Queryable source unavailable")
        instructions, known_keys, stage_ids = {}, {}, set()
        require(bool(case["stages"]), "Case requires stages")
        for stage in case["stages"]:
            require(stage["id"] not in stage_ids, "Duplicate stage ID")
            stage_ids.add(stage["id"])
            for raw in stage["instructions"]:
                item = Instruction(**raw)
                require(item.id not in instructions and bool(item.text), "Duplicate/empty instruction")
                instructions[item.id] = item
            expected = stage["expected_records"]
            require(expected and len({r["key"] for r in expected}) == len(expected), "Duplicate/empty rubric keys")
            for row in expected:
                origin = row["origin_id"]
                provenance = row.get("instruction_ids", [origin])
                require(origin in instructions and provenance and provenance[0] == origin and
                        len(provenance) == len(set(provenance)) and set(provenance) <= instructions.keys(),
                        "Invalid rubric provenance")
                source = "\n".join(instructions[key].text for key in provenance)
                for field in ("action_fragments", "condition_fragments", "forbidden_action_fragments"):
                    require(isinstance(row[field], list) and all(isinstance(x, str) and x for x in row[field]),
                            "Invalid source-fragment rubric")
                require(bool(row["action_fragments"]) and bool(row["condition_fragments"]), "Incomplete rubric")
                require(contains(source, row["action_fragments"] + row["condition_fragments"] + row.get("context_fragments", [])),
                        "Required rubric fragments must occur in original public messages")
                require(row["sources"] and set(row["sources"]) <= set(case["sources"]), "Unknown expected source")
                PISEngine._validate_trigger({k: row[k] for k in ("days", "clock_op", "clock_time")})
                require(type(row["repeat"]) is bool and row.get("status", "pending") in {"pending", "cancelled"},
                        "Invalid recurrence/status rubric")
                require(row["key"] not in known_keys or known_keys[row["key"]] == origin, "Rubric origin changed")
                if row.get("preserve_identity") or row.get("unchanged_from_previous"):
                    require(row["key"] in known_keys, "Identity check requires an earlier expected record")
                known_keys[row["key"]] = origin


def checks_for(engine, item, gold, anchors, previous):
    provenance = gold.get("instruction_ids", [gold["origin_id"]])
    trigger = engine.triggers.get(item.id, {})
    source = "\n".join(engine.instructions[key].text for key in provenance if key in engine.instructions)
    checks = {
        "origin": bool(item.instruction_ids) and item.instruction_ids[0] == gold["origin_id"],
        "complete_action": contains(item.action, gold["action_fragments"]),
        "complete_condition": contains(item.condition, gold["condition_fragments"]),
        "separate_request": not any(fragment.casefold() in (item.action + "\n" + item.condition).casefold()
                                    for fragment in gold["forbidden_action_fragments"]),
        "exact_sources": set(item.sources) == set(gold["sources"]),
        # The engine treats [] as unrestricted, exactly like all seven weekdays.
        "effective_days": set(trigger.get("days") or DAYS) == set(gold["days"] or DAYS),
        "clock_op": trigger.get("clock_op") == gold["clock_op"],
        "clock_time": trigger.get("clock_time") == gold["clock_time"],
        "recurrence": item.repeat == gold["repeat"],
        "status": item.status == gold.get("status", "pending"),
        "provenance": list(item.instruction_ids) == provenance,
        "context_retained": all(key in engine.instructions for key in provenance) and contains(source, gold.get("context_fragments", [])),
    }
    if gold.get("preserve_identity"):
        checks["preserve_identity"] = anchors.get(gold["key"]) == item.id
    if gold.get("unchanged_from_previous"):
        prior = previous.get(gold["key"])
        checks["unchanged_from_previous"] = bool(prior and prior == {"record": asdict(item), "trigger": trigger})
    return checks


def score_stage(engine, expected, anchors=None, previous=None):
    """Maximum fully-correct matching; no shared origin-ID coverage shortcut."""
    anchors, previous = anchors or {}, previous or {}
    records = dict(engine.intentions)
    checks = [{key: checks_for(engine, item, gold, anchors, previous)
               for key, item in records.items()} for gold in expected]
    owners = {}

    def assign(index, visited):
        for key, flags in checks[index].items():
            if not all(flags.values()) or key in visited:
                continue
            visited.add(key)
            if key not in owners or assign(owners[key], visited):
                owners[key] = index
                return True
        return False

    for index in range(len(expected)):
        assign(index, set())
    selected = {index: key for key, index in owners.items()}
    rows, bindings, states = [], {}, {}
    for index, gold in enumerate(expected):
        key = selected.get(index)
        candidates = checks[index]
        # Diagnostic candidates never count as successful matching or identity.
        best = max(candidates, key=lambda k: (candidates[k]["origin"], sum(candidates[k].values())), default=None)
        rows.append({"key": gold["key"], "origin_id": gold["origin_id"], "matched_id": key,
                     "passed": key is not None, "diagnostic_id": key or best,
                     "checks": candidates[key or best] if key or best else {}, "expected": gold})
        if key is not None:
            bindings[gold["key"]] = key
            states[gold["key"]] = {"record": asdict(records[key]), "trigger": dict(engine.triggers[key])}
    tp, fp, fn = len(selected), len(records) - len(selected), len(expected) - len(selected)
    return {"passed": fp == fn == 0, "tp": tp, "fp": fp, "fn": fn,
            "expected_count": len(expected), "actual_count": len(records), "rows": rows,
            "unmatched_record_ids": sorted(set(records) - set(owners)),
            "bindings": bindings, "matched_states": states}


def run_case(case, request, cls, log=None, engine_options=None):
    engine = cls(request, sources=case["sources"], queryable_sources=case["queryable_sources"],
                 **(engine_options or {}))
    anchors, previous, originals, first_coverage, stages = {}, {}, {}, {}, []
    for stage in case["stages"]:
        for raw in stage["instructions"]:
            if hasattr(request, "context"):
                request.context = {"case_id": case["id"], "stage_id": stage["id"], "instruction_id": raw["id"]}
            instruction = Instruction(**raw)
            originals[instruction.id] = instruction
            changed = engine.ingest(instruction)
            if log:
                log({"event": "ingest", "case_id": case["id"], "stage_id": stage["id"],
                     "instruction_id": instruction.id, "changed_ids": changed, "snapshot": engine.snapshot()})
        scored = score_stage(engine, stage["expected_records"], anchors, previous)
        for row in scored["rows"]:
            first_coverage.setdefault(row["key"], row["passed"])
        anchors.update({key: value for key, value in scored["bindings"].items() if key not in anchors})
        previous = scored["matched_states"]
        retained = engine.instructions == originals
        row = {"stage_id": stage["id"], **scored, "originals_retained": retained,
               "snapshot": engine.snapshot(), "engine_errors": list(engine.errors)}
        row["passed"] = row["passed"] and retained and not engine.errors
        stages.append(row)
        if log:
            log({"event": "stage_score", "case_id": case["id"], **row})
    return {"case_id": case["id"], "passed": all(s["passed"] for s in stages), "stages": stages,
            "first_registration_coverage": first_coverage, "engine_errors": list(engine.errors),
            "final_snapshot": engine.snapshot()}


def summarize(results):
    tp, fp, fn = (sum(s[k] for r in results for s in r["stages"]) for k in ("tp", "fp", "fn"))
    coverage = [ok for r in results for ok in r["first_registration_coverage"].values()]
    return {"case_count": len(results), "passed_cases": sum(r["passed"] for r in results),
            "all_cases_passed": bool(results) and all(r["passed"] for r in results),
            "stage_record_tp": tp, "stage_record_fp": fp, "stage_record_fn": fn,
            "stage_record_precision": tp / (tp + fp) if tp + fp else 0.0,
            "stage_record_recall": tp / (tp + fn) if tp + fn else 0.0,
            "stage_record_f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0,
            "distinct_required_requests": len(coverage), "fully_registered_at_first_stage": sum(coverage),
            "first_registration_coverage": sum(coverage) / len(coverage) if coverage else 0.0,
            "engine_error_count": sum(len(r["engine_errors"]) for r in results)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--policy", choices=POLICIES, default="sbpm_no_projection")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="Qwen/Qwen3-8B")
    parser.add_argument("--base-url", default="http://127.0.0.1:30002/v1")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--projector-id", help="Required for V4/V5: stable model/version and decoding/config identity")
    parser.add_argument("--projection-batch-size", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--max-calls", type=int, default=300)
    args = parser.parse_args(argv)
    try:
        engine_options = projection_options(args.policy, args.projector_id, args.projection_batch_size)
    except ValueError as exc:
        parser.error(str(exc))
    if args.max_tokens < 1 or args.timeout <= 0 or not 1 <= args.max_calls <= 300:
        parser.error("Positive tokens/timeout and a call budget of 1..300 are required")
    raw = args.cases.read_bytes()
    dataset = json.loads(raw)
    validate_cases(dataset)
    cls = engine_class(args.policy)
    root = Path(__file__).resolve().parents[2]
    frozen = {name: (root / name).read_bytes() for name in SOURCE_FILES}
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "cases.json").write_bytes(raw)
    for name, data in frozen.items():
        destination = args.output / "source" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    manifest = {"started_at": utc_now(), "python": platform.python_version(), "policy": cls.POLICY,
                "args": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                "cases_sha256": hashlib.sha256(raw).hexdigest(), "temperature": 0.0, "enable_thinking": False,
                "source_hashes": {name: hashlib.sha256(data).hexdigest() for name, data in frozen.items()},
                "protocol": "Registration only; source-fragment rubrics scorer-only; maximum one-to-one matching; no tick or action execution",
                "limitation": "Development source-preservation/lifecycle diagnostic, not PM-Bench or semantic/action correctness"}
    if engine_options:
        manifest["projection_definition"] = projection_definition()
    write_json(args.output / "manifest.json", manifest)
    write_json(args.output / "status.json", {"status": "running", "stage": "preflight", "updated_at": utc_now()})
    started, request, results = time.monotonic(), None, []
    try:
        with (args.output / "calls.jsonl").open("w") as calls, (args.output / "trace.jsonl").open("w") as trace:
            request = AuditedRequest(args.base_url, args.model, args.max_tokens, calls,
                                     timeout=args.timeout, max_calls=args.max_calls)
            request.context = {"stage": "preflight"}

            def probe(system, payload, schema):
                try:
                    request(system, payload, schema)
                except Exception:
                    if request.last_raw is None:
                        raise
                return request.last_raw

            compact = probe_compact_decoding(probe)
            manifest["whitespace_free_grammar_verified"] = compact
            write_json(args.output / "manifest.json", manifest)
            if not compact:
                raise SmokeAbort(WHITESPACE_REMEDY)
            if request.error_count or json.loads(request.last_raw).get("label") != "ready":
                raise SmokeAbort("Preflight did not return valid ready output")

            def log(row):
                trace.write(json.dumps(row, ensure_ascii=False) + "\n")
                trace.flush()

            for case in dataset["cases"]:
                print("Starting " + case["id"], flush=True)
                result = run_case(case, request, cls, log, engine_options)
                results.append(result)
                write_json(args.output / (case["id"] + ".json"), result)
                write_json(args.output / "case_results.json", results)
                write_json(args.output / "status.json", {"status": "running", "stage": "cases",
                           "completed_cases": len(results), "total_cases": len(dataset["cases"]), "updated_at": utc_now()})
                print(f"Completed {case['id']}: passed={result['passed']}", flush=True)
            metrics = summarize(results)
            metrics["all_cases_passed"] = metrics["all_cases_passed"] and request.error_count == 0
            metrics.update(status="completed", **request.summary(), elapsed_seconds=time.monotonic() - started,
                           completed_at=utc_now())
            write_json(args.output / "metrics.json", metrics)
            write_json(args.output / "status.json", {"status": "completed", "completed_cases": len(results),
                       "all_cases_passed": metrics["all_cases_passed"], "updated_at": utc_now()})
            print(json.dumps(metrics, indent=2), flush=True)
    except BaseException as exc:
        failure = {"status": "failed", "error_type": type(exc).__name__, "error": str(exc),
                   "completed_cases": len(results), "elapsed_seconds": time.monotonic() - started, "updated_at": utc_now()}
        if request is not None:
            failure.update(request.summary())
        write_json(args.output / "status.json", failure)
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
