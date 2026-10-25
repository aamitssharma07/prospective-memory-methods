"""Regenerate Experiment 3 metrics and diagnostic tables without inference."""

import argparse
import csv
import io
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "benchmark/sim", ROOT / "harness", Path(__file__).parent):
    sys.path.insert(0, str(path))
import pm_bench
from score_paired import metric_payload
from artifacts import atomic, digest, rows, save


def table(path, records, columns):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for record in records:
        writer.writerow({k: json.dumps(v) if isinstance(v, (dict, list)) else v
                         for k, v in record.items() if k in columns})
    atomic(path, stream.getvalue())


def validate(output, scenario, entries):
    expected = [(d["name"], s["id"]) for d in scenario["days"] for s in d["steps"]]
    actual = [(e["day"], e["step_id"]) for e in entries]
    if len(set(expected)) != len(expected) or actual != expected:
        raise ValueError("Missing, duplicate, reordered or unexpected trajectory steps")
    required = ("manifest.json", "scenario.json", "calls.jsonl", "memory.jsonl",
                "memory_calls.jsonl", "events.jsonl", "prompts.log", "console.log", "server.log",
                "memory_snapshot.json")
    for name in required:
        if not (output / name).is_file():
            raise ValueError(f"Missing artifact: {name}")
    for index in range(1, len(entries) + 1):
        for name in ("checkpoints", "snapshots"):
            if not (output / name / f"{index:06d}.json").is_file():
                raise ValueError(f"Missing {name} at step {index}")
    calls = rows(output / "calls.jsonl")
    ids = [c["call_id"] for c in calls]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate call IDs")
    if any(c["request"].get("max_tokens") != 768 for c in calls):
        raise ValueError("Output token budget mismatch")


def cost_summary(calls):
    result = {}
    for role in ("actor", "helper"):
        selected = [c for c in calls if c["role"] == role]
        usage = [c["usage"] for c in selected if isinstance(c.get("usage"), dict)
                 and type(c["usage"].get("total_tokens")) is int]
        token_keys = ("prompt_tokens", "completion_tokens", "total_tokens")
        token_known = {key: sum(type(c.get("usage", {}).get(key)) is int
                               for c in selected if isinstance(c.get("usage"), dict)) for key in token_keys}
        result[role] = {"calls": len(selected), "failed_calls": sum(not c["valid"] for c in selected),
                        "usage_known_calls": len(usage), "usage_unknown_calls": len(selected) - len(usage),
                        "summed_call_seconds": sum(c["duration_seconds"] for c in selected),
                        "median_call_seconds": statistics.median(c["duration_seconds"] for c in selected) if selected else None,
                        "token_usage_known_calls": token_known,
                        "token_totals_are_partial": any(n != len(selected) for n in token_known.values()),
                        "tokens": {key: sum(c["usage"][key] for c in selected
                                            if isinstance(c.get("usage"), dict)
                                            and type(c["usage"].get(key)) is int) if token_known[key] else None
                                   for key in token_keys}}
    return result


def actor_check_uptake(trace, memory_row, calls):
    plan = trace.get("query_plan")
    if not plan:
        return []
    result = []
    for call in calls:
        if (call["role"] != "actor" or call.get("cycle") != trace["cycle"]
                or call.get("session_id") != trace.get("session_id")
                or call["step_key"] != trace["step_key"]):
            continue
        action = call.get("parsed")
        valid = call["valid"] and isinstance(action, dict)
        source = ("clock" if action.get("action") == "check_time" else action.get("channel")) if valid else None
        kind = action.get("action") if valid else None
        uptake = ("invalid_actor_response" if not valid else
                  "followed" if kind in {"query_state", "check_time"} and source == plan["next_action"]["channel"] else
                  "advanced_without_offered_check" if kind == "choose" else "different_action")
        result.append({"stage": "actor_check_uptake", "memory_row": memory_row,
                       "step_key": trace["step_key"], "cycle": trace["cycle"],
                       "session_id": trace.get("session_id"),
                       "call_id": call["call_id"], "plan": plan, "actor_action": action,
                       "uptake": uptake,
                       "note": "Observed choice; does not establish a cause for the scored outcome."})
    return result


def observed_stages(memory, trace_rows, calls):
    """Trace behaviors without pretending they causally explain a scored miss."""
    result = []
    for line in trace_rows:
        trace = memory[line - 1]
        if trace["event"] == "instruction_intake":
            changes = trace.get("accepted_changes", [])
            result.append({"stage": "instruction_intake", "memory_row": line,
                           "instruction_id": trace["instruction"]["id"],
                           "disposition": "accepted_changes" if changes else "no_accepted_change",
                           "changed_intention_ids": [c["intention_id"] for c in changes],
                           "new_errors": trace.get("new_errors", [])})
        for d in trace.get("decisions", []):
            result.append({"stage": "helper_proposal", "memory_row": line, **d,
                           "status": "observed_behavior; not established failure cause"})
        if trace["event"] == "memory_cycle":
            before, after = trace["before"]["engine"], trace["after"]["engine"]
            result.extend(actor_check_uptake(trace, line, calls))
            result.extend({"stage": "query_selection", "memory_row": line, **entry}
                          for entry in after.get("arbitration_log", [])[len(before.get("arbitration_log", [])):])
            if after.get("step_queries") != before.get("step_queries"):
                result.append({"stage": "query_attempt_ledger_change", "memory_row": line,
                               "before_step_id": before.get("step_id"), "after_step_id": after.get("step_id"),
                               "before": before.get("step_queries"), "after": after.get("step_queries"),
                               "note": "May include a new-step reset; inspect step IDs and public conversation for execution."})
        if trace.get("error"):
            result.append({"stage": "memory_cycle_error", "memory_row": line, "error": trace["error"]})
    for call in calls:
        if not call["valid"]:
            result.append({"stage": "call_validation_or_transport", "role": call["role"],
                           "phase": call["phase"], "call_id": call["call_id"], "error": call.get("error")})
    return result


def analyze(output):
    output = Path(output)
    scenario = json.loads((output / "scenario.json").read_text())
    entries = rows(output / "trajectory.jsonl")
    validate(output, scenario, entries)
    diagnostics = {"steps": [], "tasks": []}
    summary, per_day, count = pm_bench.score_log(scenario, entries, strict_invalid=True,
                                               diagnostics=diagnostics)
    metrics = {"schema_version": 1, "metrics": metric_payload(summary), "summary": summary,
               "per_day": per_day, "steps": count, "coverage": 1.0,
               "invalid_responses": sum(bool(e.get("fallback_triggered")) for e in entries),
               "exact_match_rate": summary["exact_set_match_steps"] / count if count else 0}
    save(output / "metrics.json", metrics)
    calls = rows(output / "calls.jsonl")
    memory = rows(output / "memory.jsonl")
    calls_by_cycle = {}
    for call in calls:
        calls_by_cycle.setdefault(call.get("cycle"), []).append(call)
    uptake = [record for index, trace in enumerate(memory, 1) if trace["event"] == "memory_cycle"
              for record in actor_check_uptake(trace, index, calls_by_cycle.get(trace["cycle"], []))]
    table(output / "query_uptake.csv", uptake,
          ["step_key", "session_id", "cycle", "memory_row", "call_id", "uptake", "plan", "actor_action", "note"])
    failures, attributions = [], []
    for index, step in enumerate(diagnostics["steps"], 1):
        key = [step["day"], step["step_id"]]
        matching = [c for c in calls if c["step_key"] == key]
        traces = [i + 1 for i, row in enumerate(memory) if row["step_key"] == key]
        step.update(cost=cost_summary(matching), snapshot=f"snapshots/{index:06d}.json",
                    memory_rows=traces, call_ids=[c["call_id"] for c in matching])
        if step["fp"] or step["fn"] or step["invalid"]:
            failures.append(step)
            attributions.append({"schema_version": 1, "run_id": output.name, "step_key": key,
                "false_negative_tasks": sorted(set(step["expected"]) - set(step["selected"])),
                "false_positive_tasks": sorted(set(step["selected"]) - set(step["expected"])),
                "status": "established_by_trace" if step["invalid"] else "unresolved",
                "reason_codes": ["actor_invalid_response"] if step["invalid"] else [],
                "task_to_intention_alignment": "unresolved; inspect source spans in linked traces",
                "helper_failed_calls": [c["call_id"] for c in matching if c["role"] == "helper" and not c["valid"]],
                "observed_stages": observed_stages(memory, traces, matching),
                "evidence": {"memory_rows": traces, "call_ids": step["call_ids"], "snapshot": step["snapshot"]}})
    columns = ["day", "step_id", "expected", "selected", "tp", "fp", "fn", "exact_match",
               "invalid", "invalid_reason", "state_queries", "cost", "snapshot", "memory_rows", "call_ids"]
    table(output / "steps.csv", diagnostics["steps"], columns)
    table(output / "failures.csv", failures, columns)
    table(output / "per_task.csv", diagnostics["tasks"],
          ["day", "task_id", "type", "regular", "cross_day", "updated", "result", "completed_at", "state"])
    atomic(output / "failure_attribution.jsonl", "".join(json.dumps(a) + "\n" for a in attributions))
    active_sessions = {}
    for event in rows(output / "events.jsonl"):
        session_id = event["session_id"]
        active_sessions[session_id] = max(active_sessions.get(session_id, 0), event.get("session_elapsed_seconds", 0))
    cost = {"schema_version": 1, "all_attempts": cost_summary(calls),
            "by_phase": {phase: cost_summary([c for c in calls if c["phase"] == phase])
                         for phase in sorted({c["phase"] for c in calls})},
            "active_session_wall_seconds": sum(active_sessions.values()),
            "wall_time_definition": "sum of last recorded elapsed time per session; excludes downtime; includes local orchestration",
            "warmup": cost_summary([c for c in calls if c["step_key"] is None]),
            "incomplete_attempts": [e["call_id"] for e in rows(output / "events.jsonl")
                                    if e.get("event") == "call_start" and e["call_id"] not in {c["call_id"] for c in calls}]}
    save(output / "cost.json", cost)
    atomic(output / "ANALYSIS.md", f"# RGPM run {output.name}\n\n"
           f"Set-F1: {metrics['metrics']['set_f1']:.4f}\n\n"
           f"Completed steps: {count}; invalid responses: {metrics['invalid_responses']}.\n\n"
           "Failure causes are unresolved unless established by a saved trace. "
           "Inspect failure_attribution.jsonl, memory.jsonl and calls.jsonl for source evidence.\n")
    save(output / "analysis_provenance.json", {"schema_version": 1,
         "analyzer_sha256": digest(__file__),
         "inputs": {name: digest(output / name) for name in
                    ("scenario.json", "trajectory.jsonl", "calls.jsonl", "memory.jsonl", "manifest.json")}})
    return metrics


def index_artifacts(output):
    output = Path(output)
    save(output / "artifact_index.json", {"schema_version": 1,
         "artifacts": {str(p.relative_to(output)): {"bytes": p.stat().st_size, "sha256": digest(p)}
                       for p in sorted(output.rglob("*")) if p.is_file()
                       and p.name not in {"artifact_index.json", ".lock"} and not p.name.endswith(".tmp")}})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.output), indent=2))
