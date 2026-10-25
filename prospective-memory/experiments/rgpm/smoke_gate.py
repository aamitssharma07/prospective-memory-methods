"""Require a complete, parseable, instrumented live smoke before the benchmark."""

import argparse
import json
from pathlib import Path

from analyze import analyze, index_artifacts
from artifacts import rows, save


def gate(output, *, max_false_positives=None, max_false_negatives=None, admission_policy="strict"):
    if admission_policy not in {"strict", "report_only"}:
        raise ValueError("Unknown smoke admission policy")
    for limit in (max_false_positives, max_false_negatives):
        if limit is not None and (type(limit) is not int or limit < 0):
            raise ValueError("Smoke error limits must be nonnegative integers")
    output = Path(output)
    metrics = analyze(output)
    calls = rows(output / "calls.jsonl")
    snapshot = json.loads((output / "memory_snapshot.json").read_text())
    phases = {c["phase"] for c in calls if c["role"] == "helper"}
    required = {"classify_unit", "compile_typed", "trigger_projection", "assess", "identity_review"}
    checks = {
        "complete": json.loads((output / "status.json").read_text())["status"] == "complete",
        "no_invalid_actor_steps": metrics["invalid_responses"] == 0,
        "all_calls_schema_valid": bool(calls) and all(c["valid"] for c in calls),
        "memory_registered": bool(snapshot["engine"]["intentions"]),
        "stage_coverage": required.issubset(phases),
        "query_exercised": metrics["summary"]["state_query_calls"] > 0,
    }
    manifest = json.loads((output / "manifest.json").read_text())
    if manifest.get("scope_grounding") or manifest.get("bounded_priority") or manifest.get("registration_grounding"):
        intentions = snapshot["engine"]["intentions"]
        checks.update(
            no_semantic_errors=not snapshot["engine"]["errors"],
            memory_update_exercised=any(i["revision"] > 1 and i["status"] != "cancelled" for i in intentions),
            memory_cancellation_exercised=any(i["status"] == "cancelled" for i in intentions))
    if manifest.get("source_routing"):
        checks["routing_exercised"] = "source_routing" in phases
    if max_false_positives is not None:
        checks["false_positives_within_limit"] = metrics["summary"]["set_fp"] <= max_false_positives
    if max_false_negatives is not None:
        checks["false_negatives_within_limit"] = metrics["summary"]["set_fn"] <= max_false_negatives
    result = {"schema_version": 1, "passed": all(checks.values()), "checks": checks,
              "admission_policy": admission_policy,
              "admitted_to_benchmark": all(checks.values()) if admission_policy == "strict" else checks["complete"],
              "blocking_checks": sorted(checks) if admission_policy == "strict" else ["complete"],
              "quality_limits": {"max_false_positives": max_false_positives,
                                 "max_false_negatives": max_false_negatives},
              "observed_helper_phases": sorted(phases), "metrics": metrics,
              "semantic_errors": snapshot["engine"]["errors"],
              "note": "Passing establishes execution/trace health, not superiority to baselines."}
    save(output / "smoke_gate.json", result)
    index_artifacts(output)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    parser.add_argument("--max-false-positives", type=int)
    parser.add_argument("--max-false-negatives", type=int)
    parser.add_argument("--admission-policy", choices=("strict", "report_only"), default="strict")
    args = parser.parse_args()
    result = gate(args.output, max_false_positives=args.max_false_positives,
                  max_false_negatives=args.max_false_negatives, admission_policy=args.admission_policy)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["admitted_to_benchmark"] else 1)
