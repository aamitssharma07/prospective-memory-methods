#!/usr/bin/env python3
"""Offline completed-run report: fresh plain agent versus source-bound PIS.

Read-only inputs, fresh report output, no inference or benchmark labels sent to
models. Reuse the native state-aware scorer; never infer FN from static task lists.
Historical arms are separate references, not part of the fresh matched pair.
"""

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmark/sim"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pm_bench
from score_paired import metric_payload
from summarize_author_pis import score_with_rows
from prospective_memory.adapters.pmbench import PMBenchAdapter
from prospective_memory.baselines.pis import PISEngine
from prospective_memory.pis_grounded import GroundedPISEngine
from prospective_memory.method.source_bound import SourceBoundPISEngine
from prospective_memory.method.source_bound_v3 import SourceBoundV3Engine
from prospective_memory.method.trigger_engine import SourceBoundTriggerEngine
from prospective_memory.method.fair_trigger import SourceBoundFairTriggerEngine
from prospective_memory.report_helper_runs import recorded_projection_definition, recorded_projection_engine_class


SIMULATOR = "benchmark/sim/pm_bench.py"
PROJECTED_POLICIES = {"sbpm_no_arbiter", "sbpm"}
SOURCE_BOUND_POLICIES = {"sbpm_minimal", "sbpm_no_projection", *PROJECTED_POLICIES}
COMMON_FIELDS = ("model", "base_url", "scenario_sha256", "max_tokens", "temperature", "fallback")
FAILURE_FIELDS = ("method", "day", "step_id", "time", "kind", "task_id", "action",
                  "trigger_type", "cue_channel", "updated", "completed_before_choice",
                  "required_channel", "queried_required_channel_at_step", "queries",
                  "actor_fallback", "scene")
LIMITS = [
    "Single reused development scenario; no statistical significance or general-agent claim.",
    "F1 is set micro-F1, not exact-step accuracy. Interpret TP, FP, FN, recall and selection cardinality together.",
    "Helper tokens exclude the grammar probe and actor tokens. These are not total-system tokens or monetary costs.",
    "Logged ACT/CHECK/WAIT counts are adapter-delivered decisions, including code-generated WAIT/CHECK and cached ACT redelivery; they are not raw LLM outputs or distinct completed tasks.",
    "An ACT proposal does not establish actor uptake or task success. A correct hidden-task selection does not establish that its required source was observed.",
    "Required-channel queries at the due step are descriptive only: earlier observations may matter, and a query may be uninformative. No causal reminder-uptake claim is made.",
    "State-query totals already include clock queries; clock counts are a subset, not an extra cost to add.",
    "Manifest matching verifies recorded actor fields, scenario and simulator. Checkpoint, dtype, quantization, server seed, packages and grammar must also be checked in the host environment record.",
    "Policy/source hashes are verified against saved files. Snapshot restoration uses the matching current engine class; no frozen policy code or model is executed.",
]


def read_json(path):
    return json.loads(path.read_text())


def jsonl(path):
    with path.open() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def micro_metrics(tp, fp, fn):
    return {"set_tp": tp, "set_fp": fp, "set_fn": fn,
            "set_precision": tp / (tp + fp) if tp + fp else 0.0,
            "set_recall": tp / (tp + fn) if tp + fn else 0.0,
            "set_f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0}


def verify_sources(path, manifest):
    hashes = manifest.get("source_sha256", {})
    require(bool(hashes) and SIMULATOR in hashes, "Missing frozen simulator/source hashes")
    for name, expected in hashes.items():
        relative = Path(name)
        require(not relative.is_absolute() and ".." not in relative.parts,
                "Unsafe source snapshot path")
        require(digest(path / "source" / relative) == expected,
                "Source snapshot hash mismatch: " + name)
    require(digest(path / "scenario.json") == manifest.get("scenario_sha256"),
            "Scenario snapshot hash mismatch")
    require(digest(Path(pm_bench.__file__)) == hashes[SIMULATOR],
            "Current native scorer differs from the frozen simulator; do not silently rescore")


def restore_snapshot(path, manifest):
    policy = manifest.get("memory_policy", "legacy")
    classes = {"pis": PISEngine, "pis_verified": PISEngine,
               "pis_grounded": GroundedPISEngine, "sbpm_minimal": SourceBoundPISEngine,
               "sbpm_no_projection": SourceBoundV3Engine,
               "sbpm_no_arbiter": SourceBoundTriggerEngine,
               "sbpm": SourceBoundFairTriggerEngine}
    require(policy in classes, "Unsupported candidate snapshot policy: " + str(policy))
    cls = classes[policy]
    state = read_json(path / "memory_snapshot.json")
    expected_variant = getattr(cls, "POLICY", None)
    require(state.get("engine", {}).get("policy_variant") == expected_variant,
            "Snapshot policy variant does not match declared policy")
    if policy in SOURCE_BOUND_POLICIES:
        require(manifest.get("policy_variant") == expected_variant,
                "Manifest policy variant does not match source-bound implementation")
        required_sources = ["method/source_bound.py", "baselines/pis_registration.py"]
        if policy in {"sbpm_no_projection", *PROJECTED_POLICIES}:
            required_sources += ["method/source_bound_v3.py", "method/registration.py"]
        if policy in PROJECTED_POLICIES:
            required_sources += ["method/projection_cache.py", "method/trigger_engine.py", "method/calendar_guard.py"]
        if policy == "sbpm":
            required_sources += ["method/fair_checks.py", "method/fair_trigger.py"]
        for filename in required_sources:
            require("prospective_memory/" + filename in manifest["source_sha256"],
                    "Missing source-bound policy source snapshot")
    engine_options = {}
    if policy in PROJECTED_POLICIES:
        identity = manifest.get("memory_projector_id")
        batch_size = manifest.get("memory_projection_batch_size")
        require(isinstance(identity, str) and bool(identity.strip()), "Missing projector identity")
        require(type(batch_size) is int and 1 <= batch_size <= 32, "Invalid projection batch size")
        require(state.get("engine", {}).get("trigger_projection_cache", {}).get("batch_size") == batch_size,
                "Projection batch size disagrees with manifest")
        engine_options = {"projector_id": identity, "projection_batch_size": batch_size}
        # Restore recorded prompt/schema as data only. The offline subclass
        # preserves this configuration through adapter/engine fresh(), while
        # actual policy restore still validates every policy-specific field.
        definition = recorded_projection_definition(
            manifest, jsonl(path / "memory_calls.jsonl"), saved_states=(state,))
        cls = recorded_projection_engine_class(cls, definition)
    handoff = manifest.get("memory_query_handoff", "legacy")
    require(handoff in {"legacy", "explicit"}, "Invalid query handoff mode")
    require(state.get("query_handoff", "legacy") == handoff, "Query handoff mode disagrees with manifest")
    adapter = PMBenchAdapter(cls(None, **engine_options), query_handoff=handoff)
    adapter.restore(state)  # Pure deserialization: None forbids a model callback.
    for field, saved_field in (("memory_check_budget", "query_budget"),
                               ("pis_step_query_budget", "step_query_budget")):
        if field in manifest:
            value = manifest[field]
            require(type(value) is int and value >= 0 and state["engine"].get(saved_field) == value,
                    field + " disagrees with snapshot query budget")
    require(json.loads(json.dumps(adapter.snapshot())) == state,
            "Restored snapshot differs from persisted state")
    require(bool(state["engine"].get("verify_actions")) == (policy == "pis_verified"),
            "Unexpected verifier configuration")
    return state


def helper_diagnostics(path, manifest):
    usage, phases, decision_counts, engine_phases, engine_messages = (Counter() for _ in range(5))
    engine_error_pairs = Counter()
    raw_calls = errors = truncations = missing_usage = cycles = reminder_cycles = 0
    last_bank = None
    for call in jsonl(path / "memory_calls.jsonl"):
        raw_calls += 1
        phases[call.get("phase", "unknown")] += 1
        errors += int("error" in call)
        truncations += int(call.get("finish_reason") == "length")
        tokens = call.get("usage")
        missing_usage += int(not isinstance(tokens, dict))
        usage.update({k: (tokens or {}).get(k, 0) or 0 for k in
                      ("prompt_tokens", "completion_tokens", "total_tokens")})
    for cycle in jsonl(path / "memory.jsonl"):
        cycles += 1
        require(cycle.get("cycle") == cycles, "Memory cycle log is incomplete or out of order")
        reminder_cycles += int(bool(cycle.get("reminder")))
        decisions = cycle.get("decisions", [])
        require(all(d.get("kind") in {"WAIT", "CHECK", "ACT"} for d in decisions),
                "Unknown logged decision kind")
        decision_counts.update(d["kind"] for d in decisions)
        for error in cycle.get("errors", []):
            engine_phases[error.get("phase", "unknown")] += 1
            engine_messages[error.get("error", "unknown")] += 1
            engine_error_pairs[(error.get("phase", "unknown"), error.get("error", "unknown"))] += 1
        last_bank = cycle.get("bank")
    state = None
    if manifest["mode"] == "baseline":
        require(not raw_calls and not cycles and not (path / "memory_snapshot.json").exists(),
                "Plain baseline contains a memory intervention")
    else:
        state = restore_snapshot(path, manifest)
        require(state["cycles"] == cycles and cycles > 0, "Snapshot/cycle log count mismatch")
        require(state["engine"] == last_bank, "Last logged bank differs from final snapshot")
        # Per-cycle error slices must reconcile to the final complete error history.
        expected_errors = Counter((e.get("phase", "unknown"), e.get("error", "unknown"))
                                  for e in state["engine"].get("errors", []))
        require(engine_error_pairs == expected_errors,
                "Logged engine errors differ from final snapshot")
    bank = state["engine"] if state else {}
    return {"calls": raw_calls, "calls_by_phase": dict(phases),
            "tokens_excluding_probe": dict(usage), "calls_without_usage": missing_usage,
            "api_or_json_errors": errors, "length_finishes": truncations,
            "cycles": cycles, "cycles_with_reminders": reminder_cycles,
            "adapter_decision_counts": {kind: decision_counts[kind] for kind in ("WAIT", "CHECK", "ACT")},
            "engine_errors_by_phase": dict(engine_phases), "engine_error_messages": dict(engine_messages),
            "bank_entries": len(bank.get("intentions", [])),
            "bank_statuses": dict(Counter(i["status"] for i in bank.get("intentions", []))),
            "snapshot_restore_verified": state is not None,
            "snapshot_policy_variant": bank.get("policy_variant")}


def required_channel(task):
    current = task.get("current", {})
    if current.get("type") in {"time", "time_check"}:
        return "clock"
    channel = current.get("cue_channel")
    return channel if channel not in (None, "", "narrative") else ""


def trigger_class(task):
    task_type = task.get("current", {}).get("type")
    if task_type in {"time", "time_check"}:
        return "time"
    if task_type != "event":
        return "unknown"
    return "hidden_channel_event" if required_channel(task) else "visible_event"


def audit_run(directory):
    """Verify and independently rescore one complete portable-run artifact set."""
    path = Path(directory).resolve()
    manifest = read_json(path / "manifest.json")
    verify_sources(path, manifest)
    require(manifest.get("fallback") == "empty", "Only genuine empty-fallback runs are supported")
    scenario = pm_bench.load_scenario(str(path / "scenario.json"))
    expected_steps = [(d["name"], s["id"]) for d in scenario["days"] for s in d["steps"]]
    require(len(expected_steps) == 80 and len(set(expected_steps)) == 80,
            "Expected a complete 80-step scenario")
    entries, metadata = pm_bench.read_log_with_metadata(str(path / "trajectory.jsonl"))
    require([(e.get("day"), e.get("step_id")) for e in entries] == expected_steps,
            "Trajectory must contain every expected step exactly once and in order")
    require(metadata is not None and metadata.get("entry_count") == 80,
            "Missing completed-run metadata or inconsistent entry count")
    require(all(type(e.get("fallback_triggered")) is bool for e in entries),
            "Trajectory lacks explicit actor fallback instrumentation")
    fallback_steps = sum(e["fallback_triggered"] for e in entries)
    require(all(not e.get("task_ids") for e in entries if e["fallback_triggered"]),
            "An empty-fallback step contains selected tasks")
    result = score_with_rows(scenario, path / "trajectory.jsonl")
    native = metric_payload(result["summary"])
    recomputed = micro_metrics(*(sum(len(row[k]) for row in result["rows"]) for k in ("tp", "fp", "fn")))
    require(all(math.isclose(value, native[key], rel_tol=1e-12, abs_tol=1e-12)
                for key, value in recomputed.items()), "Native set counters disagree with state-aware rows")
    stored = read_json(path / "metrics.json")
    for key in ("metrics", "summary", "per_day", "steps"):
        require(stored.get(key) == result[key], "Stored native result disagrees with independent rescore: " + key)
    require(stored.get("fallback_steps") == fallback_steps, "Actor fallback count mismatch")
    counts = Counter()
    groups = {}
    for row, entry in zip(result["rows"], entries):
        row["actor_fallback"] = entry["fallback_triggered"]
        counts.update(row["queries"])
        for kind in ("tp", "fp", "fn"):
            for tid in row[kind]:
                task = row["tasks"].get(tid, {})
                group = groups.setdefault(trigger_class(task), Counter())
                group[kind] += 1
                if kind == "tp" and required_channel(task):
                    group["tp_with_required_channel_query_at_step"] += int(
                        row["queries"].get(required_channel(task), 0) > 0)
    require(sum(counts.values()) == native["state_query_calls"], "Query totals do not reconcile")
    require(counts["clock"] == native["check_time_calls"], "Clock query subset does not reconcile")
    return {"path": str(path), "manifest": manifest, "metrics": {**native, **recomputed},
            "summary": result["summary"], "per_day": result["per_day"], "steps": result["steps"],
            "rows": result["rows"], "fallback_steps": fallback_steps,
            "model_error_steps": sum(bool(e.get("model_error")) for e in entries),
            "actor_query_calls_including_clock": sum(counts.values()),
            "queries_by_channel": dict(counts), "duration_seconds": metadata.get("duration_seconds"),
            "selection_cardinality": result["selection_cardinality"],
            "selected_tasks": result["summary"]["chosen_tasks"],
            "trigger_breakdown": {name: dict(counts) for name, counts in groups.items()},
            "helper": helper_diagnostics(path, manifest),
            "verification": {"source_snapshot_hashes": True, "scenario_snapshot_hash": True,
                             "current_scorer_matches_snapshot": True, "independent_native_rescore": True,
                             "complete_ordered_80_step_trace": True},
            "artifact_sha256": {name: digest(path / name) for name in
                                ("manifest.json", "metrics.json", "trajectory.jsonl", "scenario.json",
                                 "memory.jsonl", "memory_calls.jsonl", "memory_snapshot.json")
                                if (path / name).exists()}}


def due_occurrences(run):
    return {(row["day"], row["step_id"], tid) for row in run["rows"] for tid in row["due"]}


def compare_runs(baseline, candidate):
    base, new = audit_run(baseline), audit_run(candidate)
    require(base["manifest"]["mode"] == "baseline", "First run must be the plain baseline")
    require(new["manifest"]["mode"] == "selective" and
            new["manifest"].get("memory_version") == "portable" and
            new["manifest"].get("memory_policy") in SOURCE_BOUND_POLICIES,
            "Candidate must be the source-bound portable method")
    matched = {field: base["manifest"].get(field) == new["manifest"].get(field) for field in COMMON_FIELDS}
    matched["simulator_source"] = (base["manifest"]["source_sha256"][SIMULATOR] ==
                                   new["manifest"]["source_sha256"][SIMULATOR])
    require(all(field in base["manifest"] and field in new["manifest"] for field in COMMON_FIELDS),
            "Missing actor comparability field")
    require(all(matched.values()), "Unmatched fresh pair: " + ", ".join(k for k, v in matched.items() if not v))
    return {"created_at": datetime.now(timezone.utc).isoformat(),
            "baseline": base, "candidate": new, "matched_actor_fields": matched,
            "identical_state_aware_due_occurrences": due_occurrences(base) == due_occurrences(new),
            "delta": {"tp": new["metrics"]["set_tp"] - base["metrics"]["set_tp"],
                      "fp": new["metrics"]["set_fp"] - base["metrics"]["set_fp"],
                      "fn": new["metrics"]["set_fn"] - base["metrics"]["set_fn"],
                      "f1_percentage_points": 100 * (new["metrics"]["set_f1"] - base["metrics"]["set_f1"])},
            "limits": LIMITS, "reporter_sha256": digest(Path(__file__))}


def failure_rows(report):
    for method in ("baseline", "candidate"):
        for row in report[method]["rows"]:
            for kind in ("fn", "fp"):
                for tid in row[kind]:
                    task = row["tasks"].get(tid, {})
                    channel = required_channel(task)
                    yield {"method": method, "day": row["day"], "step_id": row["step_id"],
                           "time": row["time"], "kind": kind.upper(), "task_id": tid,
                           "action": task.get("action_text") or task.get("label") or tid,
                           "trigger_type": trigger_class(task),
                           "cue_channel": task.get("current", {}).get("cue_channel", ""),
                           "updated": task.get("has_update", False),
                           "completed_before_choice": task.get("completed_before_choice", False),
                           "required_channel": channel,
                           "queried_required_channel_at_step": bool(channel and row["queries"].get(channel, 0)),
                           "queries": json.dumps(row["queries"], sort_keys=True),
                           "actor_fallback": row["actor_fallback"], "scene": row["text"]}


def markdown(report):
    lines = ["# Source-bound PIS: completed fresh PM-Bench pair", "",
             "80 environment steps per run. Baseline 1 is a fresh plain main agent; method 3 is",
             "the source-bound prospective-memory helper. Original archived comparisons are unchanged.", "",
             "| Method | TP | FN | FP | Precision | Recall | Set-F1 | Queries (clock included) | Actor fallbacks |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for key, name in (("baseline", "Fresh plain baseline"), ("candidate", "Method 3: source-bound PIS")):
        r, m = report[key], report[key]["metrics"]
        lines.append(f"| {name} | {m['set_tp']} | {m['set_fn']} | {m['set_fp']} | "
                     f"{m['set_precision']:.1%} | {m['set_recall']:.1%} | {m['set_f1']:.1%} | "
                     f"{r['actor_query_calls_including_clock']} | {r['fallback_steps']} |")
    lines += ["", "TP = correct on-time selection; FN = missed at the due step; FP = extra/wrong/not-due",
              "selection. A late selection can create FN at the due step and FP later.", "",
              f"Candidate minus fresh baseline: F1 {report['delta']['f1_percentage_points']:+.2f} percentage points, "
              f"TP {report['delta']['tp']:+d}, FP {report['delta']['fp']:+d}, FN {report['delta']['fn']:+d}.",
              f"Identical state-aware due occurrence sets: {report['identical_state_aware_due_occurrences']}.", "",
              "[All missed and wrong selections](failures.csv) | [Audited counters, traces and provenance](ANALYSIS.json)", "",
              "## Cost and memory diagnostics", "",
              "| Method | Runtime (min) | Selected tasks | Helper calls | Helper tokens* | ACT / CHECK / WAIT deliveries** | Helper API/JSON errors | Length finishes |",
              "|---|---:|---:|---:|---:|---|---:|---:|"]
    for key in ("baseline", "candidate"):
        r, h = report[key], report[key]["helper"]
        d = h["adapter_decision_counts"]
        duration = "unknown" if r["duration_seconds"] is None else f"{r['duration_seconds']/60:.1f}"
        lines.append(f"| {key} | {duration} | {r['selected_tasks']} | {h['calls']} | "
                     f"{h['tokens_excluding_probe'].get('total_tokens', 0):,} | "
                     f"{d['ACT']} / {d['CHECK']} / {d['WAIT']} | {h['api_or_json_errors']} | {h['length_finishes']} |")
    lines += ["", "*Helper tokens only, excluding grammar probe; actor tokens and total-system cost are not measured.",
              "**Adapter deliveries include code decisions and cached ACT redelivery. They are not counts of",
              "distinct reminders, raw model outputs, accepted actions or completed tasks.", ""]
    for key in ("baseline", "candidate"):
        r = report[key]
        lines += [f"### {key}", "", f"- Run: `{r['path']}`.",
                  f"- Selection count → number of steps: `{r['selection_cardinality']}`.",
                  f"- Helper phases: `{r['helper']['calls_by_phase']}`.",
                  f"- Engine errors by phase: `{r['helper']['engine_errors_by_phase']}`.",
                  f"- Missing helper usage records: {r['helper']['calls_without_usage']}.",
                  f"- Final bank statuses: `{r['helper']['bank_statuses']}`.", ""]
    lines += ["## Trigger breakdown", "",
              "| Method | Trigger | Due (TP+FN) | TP | FN | FP | TP with required-channel query at same step |",
              "|---|---|---:|---:|---:|---:|---:|"]
    for key in ("baseline", "candidate"):
        for trigger, values in sorted(report[key]["trigger_breakdown"].items()):
            tp, fn, fp = (values.get(k, 0) for k in ("tp", "fn", "fp"))
            queries = (str(values.get("tp_with_required_channel_query_at_step", 0))
                       if trigger in {"time", "hidden_channel_event"} else "n/a")
            lines.append(f"| {key} | {trigger} | {tp+fn} | {tp} | {fn} | {fp} | {queries} |")
    lines += ["", "## Interpretation limits", ""] + ["- " + limit for limit in report["limits"]]
    lines += ["", "No historical score is presented as a fresh matched arm. Prior PIS/author results",
              "remain separate archived references; this report does not overwrite them.", ""]
    return "\n".join(lines)


def write_report(report, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "ANALYSIS.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "README.md").write_text(markdown(report))
    with (output / "failures.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FAILURE_FIELDS)
        writer.writeheader()
        writer.writerows(failure_rows(report))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    require(not args.output.exists(), "Report output already exists; refusing overwrite")
    report = compare_runs(args.baseline, args.candidate)
    write_report(report, args.output)
    print(json.dumps({"output": str(args.output.resolve()), "baseline": report["baseline"]["metrics"],
                      "candidate": report["candidate"]["metrics"], "delta": report["delta"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
