"""Read-only independent audits and fresh reports for completed helper runs.

This never calls a model. Proposal alignment is not semantic action correctness,
actor uptake, execution success, or PM-Bench performance.
"""

import argparse
from collections import Counter
import copy
import csv
import hashlib
import json
import math
from pathlib import Path

from .pis_grounded import GroundedPISEngine
from .method.source_bound import SourceBoundPISEngine
from .method.source_bound_v3 import SourceBoundV3Engine
from .method.trigger_engine import SourceBoundTriggerEngine
from .method.fair_trigger import SourceBoundFairTriggerEngine


ENGINES = {"pis_grounded_v1": GroundedPISEngine,
           "sbpm_minimal": SourceBoundPISEngine,
           "sbpm_no_projection": SourceBoundV3Engine,
           "sbpm_no_arbiter": SourceBoundTriggerEngine,
           "sbpm": SourceBoundFairTriggerEngine}
PROTECTIONS = {"clock_guard", "change_review", "v2_clock_guard", "v2_day_guard",
               "v3_clock_guard", "v3_day_guard"}
NOTICE = ("Helper-only development diagnostics, NOT PM-Bench scores. ACT precision/recall/F1 "
          "measure intention-origin, tick and round alignment, not semantic action correctness. "
          "Lexical action/condition checks are limited diagnostics, not semantic proof. "
          "A scripted host follows CHECK; no actor uptake or execution success is measured. "
          "Snapshot restoration checks compatibility with the current matching engine class; "
          "Projection definitions are reconstructed from fingerprint-validated recorded prompt/schema data; "
          "frozen sources are hashed, not executed or replayed.")


def read_json(path):
    return json.loads(path.read_text())


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def equal(left, right):
    if isinstance(left, float) and isinstance(right, (int, float)):
        return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)
    return left == right


def _checked_projection_definition(value, require_hash=False):
    if (not isinstance(value, dict) or set(value) - {"prompt", "schema", "sha256"}
            or not isinstance(value.get("prompt"), str) or not value["prompt"].strip()
            or not isinstance(value.get("schema"), dict)
            or not isinstance(value["schema"].get("properties"), dict)
            or "trigger_projections" not in value["schema"].get("properties", {})):
        raise ValueError("Invalid recorded projection prompt/schema definition")
    payload = {"prompt": value["prompt"], "schema": copy.deepcopy(value["schema"])}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    if (require_hash and "sha256" not in value) or ("sha256" in value and value["sha256"] != digest):
        raise ValueError("Recorded projection definition fingerprint mismatch")
    return {**payload, "sha256": digest}


def _saved_projection_caches(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "trigger_projection_cache":
                yield item
            else:
                yield from _saved_projection_caches(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _saved_projection_caches(item)


def recorded_projection_definition(manifest, calls, saved_states=()):
    """Recover one recorded definition as DATA, verifying all calls/cache hashes.

    Older V4 manifests lack this field, so their audited projector call's exact
    system/schema supplies it. No calls and no manifest definition is unresolved,
    never permission to substitute today's projection prompt.
    """
    definitions = []
    if "projection_definition" in manifest:
        definitions.append(_checked_projection_definition(manifest["projection_definition"], True))
    for call in calls:
        request = call.get("request") or {}
        schema = call.get("schema") or request.get("response_format", {}).get("json_schema", {}).get("schema")
        if (call.get("phase") != "trigger_projection"
                and not (isinstance(schema, dict) and "trigger_projections" in schema.get("properties", {}))):
            continue
        prompt = call.get("system")
        if prompt is None:
            systems = [row.get("content") for row in request.get("messages", []) if row.get("role") == "system"]
            if len(systems) == 1:
                prompt = systems[0]
        definitions.append(_checked_projection_definition({"prompt": prompt, "schema": schema}))
    if not definitions:
        raise ValueError("No recorded projection definition in manifest or projector calls")
    definition = definitions[0]
    if any(item != definition for item in definitions[1:]):
        raise ValueError("Projection definitions disagree within the recorded run")
    for cache in _saved_projection_caches(saved_states):
        if (not isinstance(cache, dict) or not isinstance(cache.get("projector"), dict)
                or cache["projector"].get("prompt_schema_sha256") != definition["sha256"]):
            raise ValueError("Recorded projection definition disagrees with saved cache fingerprint")
        for entry in cache.get("entries", []):
            profile = entry.get("binding", {}).get("projector", {})
            if profile.get("prompt_schema_sha256") != definition["sha256"]:
                raise ValueError("Recorded projection definition disagrees with saved entry fingerprint")
    return definition


def recorded_projection_engine_class(engine_class, definition):
    """An offline-only class preserving validated recorded definition on fresh().

    Pass the actual matching engine class: its unchanged strict restore validates
    ALL policy-specific state, including state added by later subclasses. Callers
    first resolve the definition against all recorded cache fingerprints with
    recorded_projection_definition. Only prompt/schema DATA is configured here;
    frozen Python is never imported or executed. Inference callbacks are refused.
    """
    definition = _checked_projection_definition(definition, True)
    if not isinstance(engine_class, type) or not issubclass(engine_class, SourceBoundTriggerEngine):
        raise ValueError("Expected a matching trigger-projection engine class")

    class RecordedProjectionAuditEngine(engine_class):
        def __init__(self, request, *args, **kwargs):
            if request is not None:
                raise ValueError("Recorded projection audit engines forbid inference callbacks")
            super().__init__(None, *args, **kwargs)
            cache = self.projections
            cache._prompt, cache._schema = definition["prompt"], copy.deepcopy(definition["schema"])
            cache._projector = {"identity": self._projector_id,
                                "prompt_schema_sha256": definition["sha256"]}

    RecordedProjectionAuditEngine.__name__ = "RecordedProjectionAudit" + engine_class.__name__
    return RecordedProjectionAuditEngine


def restore_trigger_snapshot(state, *, projector_id, projection_batch_size, definition):
    """V4-only convenience wrapper; other variants use the matching-class factory."""
    if not isinstance(state, dict) or state.get("policy_variant") != SourceBoundTriggerEngine.POLICY:
        raise ValueError("This offline projection restorer supports V4 snapshots only")
    definition = _checked_projection_definition(definition, True)
    cache_state = state.get("trigger_projection_cache")
    if (not isinstance(cache_state, dict) or cache_state.get("batch_size") != projection_batch_size
            or cache_state.get("projector", {}).get("prompt_schema_sha256") != definition["sha256"]):
        raise ValueError("Recorded projector definition/batch configuration differs from snapshot")
    cls = recorded_projection_engine_class(SourceBoundTriggerEngine, definition)
    engine = cls(None, projector_id=projector_id, projection_batch_size=projection_batch_size)
    engine.restore(state)
    return engine


def record_checks(state, expected, initial):
    """Recompute contracts from raw saved records, not evaluator check booleans."""
    records = state["intentions"]
    before = {row["id"]: row for row in initial["intentions"]}
    failures = []
    if len(records) != len(expected):
        failures.append(f"record count {len(records)} != {len(expected)}")
    for requirement in expected:
        origin = requirement["origin_id"]
        found = [row for row in records if row["instruction_ids"] and row["instruction_ids"][0] == origin]
        if len(found) != 1:
            failures.append(f"{origin}: expected one record, found {len(found)}")
            continue
        row = found[0]
        checks = {"status": row["status"] == requirement.get("status", "pending")}
        if "instruction_ids" in requirement:
            checks["provenance"] = row["instruction_ids"] == requirement["instruction_ids"]
        if "required_sources" in requirement:
            checks["sources"] = set(requirement["required_sources"]) <= set(row["sources"])
        for key in ("clock_op", "clock_time"):
            if key in requirement:
                checks[key] = state["triggers"][row["id"]][key] == requirement[key]
        for field in ("action", "condition"):
            fragments = requirement.get(field + "_contains_any")
            if fragments:
                checks[field + " lexical diagnostic"] = any(value.lower() in row[field].lower()
                                                               for value in fragments)
        if requirement.get("preserve_identity"):
            checks["identity"] = row["id"] in before
        if requirement.get("unchanged_from_initial"):
            checks["unchanged"] = row == before.get(row["id"])
        failures.extend(f"{origin}: {key}" for key, passed in checks.items() if not passed)
    return failures


def normalized(round_row):
    bank = {row["id"]: row for row in round_row["state"]["intentions"]}
    return [{"origin_id": bank[d["intention_id"]]["instruction_ids"][0],
             "kind": d["kind"], "source": d["source"]} for d in round_row["decisions"]]


def decision_counts(rows):
    return Counter((row["origin_id"], row["kind"], row.get("source", "")) for row in rows)


def boundary_violation_count(round_row):
    bank = {row["id"]: row for row in round_row["state"]["intentions"]}
    observations = {row["id"]: row for row in round_row["observations"] if row["current"]}
    observed_sources = {row["source"] for row in observations.values()}
    bad = 0
    for decision in round_row["decisions"]:
        intention = bank[decision["intention_id"]]
        if decision["kind"] == "ACT":
            ids = decision["evidence_ids"]
            bad += bool(decision["source"] or not ids or any(key not in observations for key in ids)
                        or not any(observations[key]["source"] in intention["sources"]
                                   for key in ids if key in observations))
        elif decision["kind"] == "CHECK":
            source = decision["source"]
            bad += bool(decision["evidence_ids"] or source not in round_row["state"]["queryable_sources"]
                        or source not in intention["sources"] or source in observed_sources)
    return bad


def audit_run(directory):
    directory = Path(directory).resolve()
    manifest = read_json(directory / "manifest.json")
    metrics = read_json(directory / "metrics.json")
    status = read_json(directory / "status.json")
    if metrics.get("status") != "completed" or status.get("status") != "completed":
        raise ValueError(f"Refusing incomplete run: {directory}")
    policy = manifest["policy"]
    if policy not in ENGINES:
        raise ValueError(f"Unsupported engine variant: {policy}")
    projection_policy = issubclass(ENGINES[policy], SourceBoundTriggerEngine)
    dataset = read_json(directory / "cases.json")
    results = read_json(directory / "case_results.json")
    calls = jsonl(directory / "calls.jsonl")
    trace = jsonl(directory / "trace.jsonl")
    mismatches = []
    projection_definition = None
    if projection_policy:
        try:
            projection_definition = recorded_projection_definition(manifest, calls, [results, trace])
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            mismatches.append({"field": "projection_definition", "error": str(exc)})

    def check(label, actual, expected):
        if not equal(actual, expected):
            mismatches.append({"field": label, "recomputed": actual, "recorded": expected})

    hashes = {"cases.json": digest(directory / "cases.json")}
    check("cases_sha256", hashes["cases.json"], manifest["cases_sha256"])
    for name, expected in manifest["source_hashes"].items():
        source = (directory / "source" / name).resolve()
        if not source.is_relative_to(directory / "source"):
            raise ValueError("Source snapshot path escapes its run")
        actual = digest(source) if source.is_file() else None
        hashes["source/" + name] = actual
        check("source hash: " + name, actual, expected)

    check("ordered case IDs", [r["case_id"] for r in results], [c["id"] for c in dataset["cases"]])
    by_id = {row["case_id"]: row for row in results}
    check("unique result cases", len(by_id), len(results))
    cases, proposal_counts, expected_trace = [], Counter(), []
    totals = Counter()
    for case in dataset["cases"]:
        case_id = case["id"]
        if case_id not in by_id:
            continue
        result = by_id[case_id]
        per_case_path = directory / (case_id + ".json")
        if not per_case_path.resolve().is_relative_to(directory):
            raise ValueError("Case output path escapes its run")
        check(case_id + ": per-case file", read_json(per_case_path), result)
        initial, final = result["initial_state"], result["final_state"]
        failures = ["initial: " + value for value in record_checks(initial, case["expected_initial_records"], initial)]
        coverage = {}

        def cover(state, requirements):
            origins = {r["instruction_ids"][0] for r in state["intentions"] if r["instruction_ids"]}
            for requirement in requirements:
                origin = requirement["origin_id"]
                coverage.setdefault(origin, origin in origins)

        cover(initial, case["expected_initial_records"])
        actual_ticks = {row["tick_id"]: row for row in result["ticks"]}
        check(case_id + ": ordered tick IDs", [t["tick_id"] for t in result["ticks"]],
              [t["id"] for t in case["ticks"]])
        registrations = result["registration_events"]
        for event in registrations:
            expected_trace.append({"case_id": case_id, "event": "registration", **event})
        # Trace is chronological; compare by unique event identity below.
        tp = fp = fn = 0
        for expected_tick in case["ticks"]:
            tick_id = expected_tick["id"]
            actual_tick = actual_ticks.get(tick_id)
            if actual_tick is None:
                failures.append(tick_id + ": missing tick")
                fn += sum(d["kind"] == "ACT" for rnd in expected_tick["expected_rounds"] for d in rnd)
                continue
            rounds = actual_tick["rounds"]
            tick_state = rounds[0]["state"] if rounds else final
            cover(tick_state, expected_tick["expected_records"])
            failures.extend(tick_id + ": " + value for value in record_checks(tick_state, expected_tick["expected_records"], initial))
            gold_rounds = expected_tick["expected_rounds"]
            check(case_id + ": " + tick_id + " frozen expected rounds", actual_tick["expected_rounds"], gold_rounds)
            actual_normalized = []
            for rnd in rounds:
                rows = normalized(rnd)
                actual_normalized.append(rows)
                check(case_id + ": " + tick_id + f" normalized round {rnd['round']}", rows, rnd["normalized"])
                proposal_counts.update(d["kind"] for d in rows)
                expected_trace.append({"case_id": case_id, "event": "decision", "tick_id": tick_id, **rnd})
                boundary_count = boundary_violation_count(rnd)
                check(case_id + ": " + tick_id + f" boundary count round {rnd['round']}",
                      boundary_count, len(rnd["boundary_errors"]))
                if boundary_count:
                    failures.append(tick_id + ": evidence/source boundary failure")
                failures.extend(tick_id + ": " + error["phase"] + ": " + error["error"]
                                for error in rnd["engine_errors"] if error["phase"] not in PROTECTIONS)
            exact = len(actual_normalized) == len(gold_rounds) and all(
                decision_counts(actual) == decision_counts(gold)
                for actual, gold in zip(actual_normalized, gold_rounds))
            check(case_id + ": " + tick_id + " exact_decisions", exact, actual_tick["exact_decisions"])
            if not exact:
                failures.append(tick_id + ": decision sequence differs")
            failures.extend(tick_id + ": " + error for error in actual_tick["fixture_errors"])
            for index in range(max(len(actual_normalized), len(gold_rounds))):
                actual = actual_normalized[index] if index < len(actual_normalized) else []
                gold = gold_rounds[index] if index < len(gold_rounds) else []
                a = Counter(d["origin_id"] for d in actual if d["kind"] == "ACT")
                b = Counter(d["origin_id"] for d in gold if d["kind"] == "ACT")
                overlap = sum((a & b).values())
                tp += overlap
                fp += sum(a.values()) - overlap
                fn += sum(b.values()) - overlap
        errors = final["errors"]
        check(case_id + ": engine errors", errors, result["engine_errors"])
        failures.extend(error["phase"] + ": " + error["error"] for error in errors
                        if error["phase"] not in PROTECTIONS)
        failures.extend(origin + ": no registration at first required checkpoint"
                        for origin, present in coverage.items() if not present)
        check(case_id + ": coverage", coverage, result["registration_coverage"])
        restored = False
        try:
            options = {}
            if projection_policy:
                arguments = manifest.get("args", {})
                identity = arguments.get("projector_id")
                if not isinstance(identity, str) or not identity.strip():
                    raise ValueError("Projection-policy manifest must record an explicit projector_id")
                batch_size = arguments.get("projection_batch_size")
                if type(batch_size) is not int or not 1 <= batch_size <= 32:
                    raise ValueError("Projection-policy manifest must record projection_batch_size in 1..32")
                options = {"projector_id": identity, "projection_batch_size": batch_size}
                check(case_id + ": projection batch configuration",
                      final["trigger_projection_cache"]["batch_size"], batch_size)
                if final["trigger_projection_cache"]["batch_size"] != batch_size:
                    raise ValueError("Recorded projection batch configuration differs from snapshot")
            if projection_policy:
                if projection_definition is None:
                    raise ValueError("Projection definition could not be verified")
                cls = recorded_projection_engine_class(ENGINES[policy], projection_definition)
                engine = cls(None, **options)
                engine.restore(final)
            else:
                engine = ENGINES[policy](None, **options)
                engine.restore(final)
            restored = json.loads(json.dumps(engine.snapshot())) == final
            check(case_id + ": restored snapshot", restored, True)
        except Exception as exc:
            mismatches.append({"field": case_id + ": snapshot restore", "error": str(exc)})
        passed = not failures
        for key, value in (("passed", passed), ("act_tp", tp), ("act_fp", fp), ("act_fn", fn), ("act_count", tp + fp)):
            check(case_id + ": " + key, value, result[key])
        item = {"case_id": case_id, "passed": passed, "registered": sum(coverage.values()),
                "required": len(coverage), "final_records": len(final["intentions"]),
                "act_tp": tp, "act_fp": fp, "act_fn": fn, "snapshot_restored": restored,
                "failures": sorted(set(failures))}
        cases.append(item)
        totals.update({"passed_cases": int(passed), "registered_requirement_count": item["registered"],
                       "required_registration_count": item["required"], "final_records": item["final_records"],
                       "act_tp": tp, "act_fp": fp, "act_fn": fn,
                       "engine_event_count": len(errors),
                       "protection_event_count": sum(e["phase"] in PROTECTIONS for e in errors),
                       "unexpected_error_count": sum(e["phase"] not in PROTECTIONS for e in errors)})

    def trace_key(row):
        return (row["case_id"], row["event"], row["tick_id"],
                row.get("instruction_id", ""), row.get("round", -1))

    check("trace events", sorted(trace, key=trace_key), sorted(expected_trace, key=trace_key))
    api_calls = [row for row in calls if "call_id" in row]
    check("call log contains only API calls", len(api_calls), len(calls))
    check("call IDs", [row["call_id"] for row in api_calls], list(range(1, len(api_calls) + 1)))
    usage, phases = Counter(), Counter()
    for call in api_calls:
        phases[call["phase"]] += 1
        raw_response = json.loads(call["raw_http_response"]) if call.get("raw_http_response") and not call.get("error") else call.get("response", {})
        raw_usage = raw_response.get("usage") or {}
        check(f"call {call['call_id']}: usage", raw_usage, call.get("usage", {}))
        usage.update({key: raw_usage.get(key, 0) or 0 for key in ("prompt_tokens", "completion_tokens", "total_tokens")})
    required, registered = totals["required_registration_count"], totals["registered_requirement_count"]
    tp, fp, fn = (totals["act_" + key] for key in ("tp", "fp", "fn"))
    api_errors = sum(bool(call.get("error")) for call in api_calls)
    summary = {**totals, "case_count": len(cases), "all_cases_passed": all(c["passed"] for c in cases) and api_errors == 0,
               "registration_coverage": registered / required if required else None,
               "delivered_act_proposals": tp + fp, "proposal_counts": dict(proposal_counts),
               "act_precision": tp / (tp + fp) if tp + fp else None,
               "act_recall": tp / (tp + fn) if tp + fn else None,
               "act_f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
               "model_calls_including_preflight": len(api_calls), "calls_by_phase": dict(phases),
               "usage": dict(usage), "transport_or_decode_errors": api_errors}
    for key, value in summary.items():
        if key != "final_records":
            check("metrics: " + key, value, metrics.get(key))
    provenance = {"run": str(directory), "policy": policy, "manifest": manifest,
                  "verified_hashes": hashes,
                  "artifact_hashes": {name: digest(directory / name) for name in
                                      ("manifest.json", "metrics.json", "status.json", "case_results.json", "trace.jsonl", "calls.jsonl")}}
    return {"run": str(directory), "policy": policy, "audit_passed": not mismatches,
            "summary": summary, "cases": cases, "mismatches": mismatches, "provenance": provenance}


def write_report(directories, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    audits = [audit_run(directory) for directory in directories]
    output.mkdir(parents=True, exist_ok=False)
    (output / "AUDIT.json").write_text(json.dumps({"notice": NOTICE, "runs": audits}, indent=2) + "\n")
    (output / "PROVENANCE.json").write_text(json.dumps([run["provenance"] for run in audits], indent=2) + "\n")
    with (output / "CASE_RESULTS.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["run", "policy", "case_id", "passed", "registered", "required",
                                                    "final_records", "act_tp", "act_fp", "act_fn", "snapshot_restored", "failures"])
        writer.writeheader()
        for run in audits:
            for case in run["cases"]:
                writer.writerow({"run": run["run"], "policy": run["policy"], **case, "failures": " | ".join(case["failures"])})
    fields = ["run", "policy", "audit_passed", "case_count", "passed_cases", "registered_requirement_count",
              "required_registration_count", "final_records", "act_tp", "act_fp", "act_fn", "act_precision",
              "act_recall", "act_f1", "unexpected_error_count", "model_calls_including_preflight",
              "prompt_tokens", "completion_tokens", "total_tokens"]
    with (output / "COMPARISON.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for run in audits:
            values = {"run": run["run"], "policy": run["policy"], "audit_passed": run["audit_passed"],
                      **run["summary"], **run["summary"]["usage"]}
            writer.writerow({key: values.get(key) for key in fields})
    lines = ["# Helper-only comparison", "", NOTICE, "",
             "Every supplied attempt is retained. Only runs with identical cases hashes are directly comparable; different suites are separate checks.", "",
             "| Run | Audit | Contracts | Registration | ACT TP/FP/FN | Alignment F1 | Unexpected errors | Calls | Tokens |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for run in audits:
        s = run["summary"]
        f1 = f"{s['act_f1']:.1%}" if s["act_f1"] is not None else "n/a"
        lines.append(f"| {Path(run['run']).name} | {'PASS' if run['audit_passed'] else 'MISMATCH'} | "
                     f"{s['passed_cases']}/{s['case_count']} | {s['registered_requirement_count']}/{s['required_registration_count']} | "
                     f"{s['act_tp']}/{s['act_fp']}/{s['act_fn']} | {f1} | {s['unexpected_error_count']} | "
                     f"{s['model_calls_including_preflight']} | {s['usage'].get('total_tokens', 0)} |")
    lines += ["", "Audit PASS means artifact consistency, not that the method passed its contracts.", "",
              "Per-case failures: [CASE_RESULTS.csv](CASE_RESULTS.csv). Exact counts: [COMPARISON.csv](COMPARISON.csv). "
              "All mismatches and checks: [AUDIT.json](AUDIT.json). Manifests and hashes: [PROVENANCE.json](PROVENANCE.json).", ""]
    (output / "README.md").write_text("\n".join(lines))
    return audits


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    audits = write_report(args.runs, args.output)
    print(args.output / "README.md")
    return 0 if all(run["audit_passed"] for run in audits) else 1


if __name__ == "__main__":
    raise SystemExit(main())
