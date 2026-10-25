"""Read-only paired-run audit; stdout JSON, no model calls or benchmark labels sent anywhere."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def summarize(path):
    manifest = json.loads((path / "manifest.json").read_text())
    result = json.loads((path / "metrics.json").read_text())  # incomplete runs fail, never look completed
    calls = jsonl(path / "memory_calls.jsonl")
    cycles = jsonl(path / "memory.jsonl")
    trace = jsonl(path / "trajectory.jsonl")
    usage = Counter()
    for c in calls:
        usage.update({k: (c.get("usage") or {}).get(k, 0) or 0 for k in
                      ("prompt_tokens", "completion_tokens", "total_tokens")})
    metadata = next((row for row in trace if row.get("record_type") == "run_metadata"), {})
    phases = Counter(c.get("phase", "unknown") for c in calls)
    cycle_kinds = Counter()
    for cycle in cycles:
        kinds = {d["kind"] for d in cycle.get("decisions", [])}
        for kind in kinds:
            cycle_kinds[kind] += 1
    bank = cycles[-1]["bank"] if cycles else {}
    preserved = bank.get("preserved_bank", {})
    errors = [e for cycle in cycles for e in cycle.get("errors", [])]
    resolutions = bank.get("resolution_log", [])
    digest_ok = all(hashlib.sha256((path / "source" / name).read_bytes()).hexdigest() == digest
                    for name, digest in manifest["source_sha256"].items())
    return {
        "path": str(path), "manifest": manifest, "metrics": result["metrics"],
        "steps": result["steps"], "fallback_steps": result["fallback_steps"],
        "chosen_tasks": result["summary"]["chosen_tasks"],
        "actor_selection_cardinality": dict(Counter(len(row.get("task_ids", []))
                                                    for row in trace if "step_id" in row)),
        "duration_seconds": metadata.get("duration_seconds"),
        "helper_calls": len(calls), "helper_calls_by_phase": dict(phases),
        "helper_tokens_excluding_probe": dict(usage),
        "helper_api_or_json_errors": sum("error" in c for c in calls),
        "helper_length_finishes": sum(c.get("finish_reason") == "length" for c in calls),
        "max_helper_prompt_tokens": max(((c.get("usage") or {}).get("prompt_tokens", 0) for c in calls), default=0),
        "cycles": len(cycles), "cycles_with_reminders": sum(bool(c.get("reminder")) for c in cycles),
        "cycles_by_decision_kind_overlapping": dict(cycle_kinds),
        "engine_errors_by_phase": dict(Counter(e["phase"] for e in errors)),
        "engine_error_messages": dict(Counter(e["error"] for e in errors)),
        "bank_entries": len(bank.get("intentions", [])),
        "bank_statuses": dict(Counter(i["status"] for i in bank.get("intentions", []))),
        "receipts": dict(Counter(r["state"] for r in preserved.get("receipts", {}).values())),
        "update_resolutions": dict(Counter(r["decision"] for r in resolutions)),
        "unresolved_updates": sum(p["state"] == "unresolved" for p in preserved.get("proposals", [])),
        "source_snapshot_hashes_verified": digest_ok,
        "scenario_snapshot_hash_verified": hashlib.sha256((path / "scenario.json").read_bytes()).hexdigest() == manifest["scenario_sha256"],
        "per_day": {day: {key: values["metrics"][key] for key in ("set_tp", "set_fp", "set_fn")}
                    for day, values in result["per_day"].items()},
    }


def compare(baseline, candidate):
    base, memory = summarize(baseline), summarize(candidate)
    fields = ("model", "base_url", "scenario_sha256", "max_tokens", "temperature", "fallback")
    matches = {field: base["manifest"][field] == memory["manifest"][field] for field in fields}
    matches["benchmark_source"] = (base["manifest"]["source_sha256"]["benchmark/sim/pm_bench.py"] ==
                                    memory["manifest"]["source_sha256"]["benchmark/sim/pm_bench.py"])
    return {"baseline": base, "candidate": memory, "matched_actor_fields": matches,
            "set_f1_difference_percentage_points": 100 * (memory["metrics"]["set_f1"] - base["metrics"]["set_f1"]),
            "caveat": "Single end-to-end pair, not a pure extraction ablation or significance test. Helper costs exclude grammar probe; actor token use is not logged."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.baseline, args.candidate), indent=2))


if __name__ == "__main__":
    main()
