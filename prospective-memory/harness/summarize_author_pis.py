#!/usr/bin/env python3
"""Offline, state-aware scoring and failure comparison; never called by agents."""
import argparse
from collections import Counter
import csv
import hashlib
import inspect
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmark/sim"))
import pm_bench
from score_paired import metric_payload


def jsonl(path):
    with path.open() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def score_with_rows(scenario, path):
    entries, metadata = pm_bench.read_log_with_metadata(str(path))
    source, start = inspect.getsourcelines(pm_bench.score_day)
    target = start + next(i for i, line in enumerate(source) if "if chosen_set == due_now:" in line)
    rows = []

    def tracer(frame, event, arg):
        if frame.f_code != pm_bench.score_day.__code__:
            return None
        if event == "line" and frame.f_lineno == target:
            state = frame.f_locals
            due, chosen = state["due_now"], state["chosen_set"]
            rows.append({
                "day": state["day"]["name"], "step_id": state["step"]["id"],
                "time": state["step"].get("time"), "step_index": state["step_idx"],
                "text": state["step"].get("text"),
                "due": sorted(due), "chosen": sorted(chosen),
                "tp": sorted(chosen & due), "fp": sorted(chosen - due),
                "fn": sorted(due - chosen), "queries": dict(state["query_counts"]),
                "tasks": {tid: {"label": s["current"].get("label") or s["task"].get("label"),
                                  "action_text": s["current"].get("action_text") or s["task"].get("action_text"),
                                  "current": dict(s["current"]),
                                  "completed_before_choice": s["completed"],
                                  "active": s["active"], "has_update": s.get("has_update", False)}
                          for tid, s in state["task_states"].items()},
            })
        return tracer

    previous = sys.gettrace()
    sys.settrace(tracer)
    try:
        summary, per_day, steps = pm_bench.score_log(scenario, entries)
    finally:
        sys.settrace(previous)
    assert len(rows) == steps == len(entries)
    for key in ("tp", "fp", "fn"):
        assert sum(len(row[key]) for row in rows) == summary["set_" + key]
    return {"metrics": metric_payload(summary), "summary": summary,
            "per_day": per_day, "steps": steps, "rows": rows,
            "metadata": metadata, "trajectory": str(path),
            "fallback_steps": sum(bool(e.get("model_error") or e.get("fallback_triggered")) for e in entries),
            "selection_cardinality": dict(Counter(len(r["chosen"]) for r in rows))}


def api_stats(path):
    counts, tokens, finishes, formats = Counter(), Counter(), Counter(), Counter()
    truncated, limits = Counter(), {}
    errors = []
    for call in jsonl(path):
        role = call["role"]
        counts[role] += 1
        tokens[role] += call.get("usage", {}).get("total_tokens", 0)
        finishes[str(call.get("finish_reason"))] += 1
        if call.get("finish_reason") == "length":
            truncated[role] += 1
        limits.setdefault(role, set()).add(call["request"].get("max_tokens"))
        formats[call["request"].get("response_format", {}).get("type", "none")] += 1
        if "error" in call:
            errors.append({k: call[k] for k in ("call", "role", "error")})
    return {"calls_by_role": dict(counts), "tokens_by_role": dict(tokens),
            "finish_reasons": dict(finishes), "formats": dict(formats), "errors": errors,
            "truncations_by_role": dict(truncated),
            "max_tokens_by_role": {role: sorted(values) for role, values in limits.items()}}


def occurrences(result, field):
    return {(r["day"], r["step_id"], tid) for r in result["rows"] for tid in r[field]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--ours", type=Path, default=ROOT / "harness/memory_results/qwen3-8b-pis-triplet-20260922-03")
    args = parser.parse_args()
    root = args.directory.resolve()
    if json.loads((root / "status.json").read_text())["status"] != "completed":
        raise ValueError("Author pair not completed; do not report partial scores")
    manifest = json.loads((root / "manifest.json").read_text())
    for relative, sha in manifest["source_sha256"].items():
        assert hashlib.sha256((root / "author_source" / relative).read_bytes()).hexdigest() == sha
    assert hashlib.sha256((root / "scenario.json").read_bytes()).hexdigest() == manifest["scenario_sha256"]
    scenario = json.loads((root / "scenario.json").read_text())
    results = {}
    for arm in ("baseline", "intention"):
        folder = root / arm
        assert (folder / "completion.json").is_file()
        trajectories = [p for p in folder.glob("*/*/*.jsonl") if p.name.count(".") == 1]
        assert len(trajectories) == 1, trajectories
        results["author_" + arm] = score_with_rows(scenario, trajectories[0])
        native_report = trajectories[0].with_suffix(".score.md").read_text()
        native = re.search(r"Set micro: TP (\d+) \| FP (\d+) \| FN (\d+)", native_report)
        assert native is not None
        assert tuple(map(int, native.groups())) == tuple(results["author_" + arm]["metrics"]["set_" + k] for k in ("tp", "fp", "fn"))
        results["author_" + arm]["native_report_rescore_matches"] = True
        results["author_" + arm]["api"] = api_stats(folder / "api_calls.jsonl")
        results["author_" + arm]["duration_seconds"] = json.loads((folder / "completion.json").read_text())["duration_seconds"]
    for arm in ("baseline", "pis", "pis_verified"):
        folder = args.ours / arm
        assert json.loads((folder / "scenario.json").read_text()) == scenario
        results["ours_" + arm] = score_with_rows(scenario, folder / "trajectory.jsonl")
    author, ours = results["author_intention"], results["ours_pis"]
    for result in results.values():
        result["misses_by_trigger_type"] = dict(Counter(row["tasks"][tid]["current"]["type"] for row in result["rows"] for tid in row["fn"]))
        result["updated_task_misses"] = sum(row["tasks"][tid]["has_update"] for row in result["rows"] for tid in row["fn"])
    baseline_diff = {
        "selected_set_differences": sum(a["chosen"] != b["chosen"] for a, b in zip(results["author_baseline"]["rows"], results["ours_baseline"]["rows"])),
        "query_differences": sum(a["queries"] != b["queries"] for a, b in zip(results["author_baseline"]["rows"], results["ours_baseline"]["rows"])),
    }
    memory_path = next((root / "intention").glob("*/*/*.memory.jsonl"))
    memory_events = list(jsonl(memory_path))
    author["memory_events"] = dict(Counter(e["event"] for e in memory_events))
    author["memory_errors"] = [{k: v for k, v in e.items() if k in ("event", "day", "step", "error")} for e in memory_events if "error" in e.get("event", "")]
    author["memory_error_steps"] = sorted({(e["day"], e["step"]) for e in author["memory_errors"]})
    store_path = next((root / "intention").glob("*/*/*.intentions.json"))
    bank = json.loads(store_path.read_text())["intentions"]
    signatures = Counter(json.dumps({k: v for k, v in item.items() if k != "intent_id"}, sort_keys=True) for item in bank)
    author["final_bank"] = {"records": len(bank), "status_counts": dict(Counter(i["status"] for i in bank)),
                            "exact_duplicate_excess": sum(n - 1 for n in signatures.values()),
                            "largest_duplicate_groups": [{"copies": n, "record": json.loads(key)} for key, n in signatures.most_common(10) if n > 1]}
    left, right = occurrences(author, "fn"), occurrences(ours, "fn")
    overlap = {"missed_by_both": sorted(left & right),
               "author_miss_ours_hit": sorted(left & occurrences(ours, "tp")),
               "ours_miss_author_hit": sorted(right & occurrences(author, "tp")),
               "due_sets_identical": occurrences(author, "due") == occurrences(ours, "due")}
    payload = {"source_hashes_verified": True, "results": results, "miss_overlap": overlap,
               "baseline_trace_differences": baseline_diff}
    (root / "FAILURE_ANALYSIS.json").write_text(json.dumps(payload, indent=2) + "\n")
    fields = ["method", "day", "step_id", "time", "type", "task_id", "action", "trigger_type", "updated", "completed_before_choice", "queries"]
    with (root / "failures.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for method, result in results.items():
            for row in result["rows"]:
                for kind in ("fn", "fp"):
                    for tid in row[kind]:
                        task = row["tasks"].get(tid, {})
                        writer.writerow(dict(method=method, day=row["day"], step_id=row["step_id"], time=row["time"], type=kind.upper(), task_id=tid,
                                             action=task.get("action_text"), trigger_type=task.get("current", {}).get("type"), updated=task.get("has_update"),
                                             completed_before_choice=task.get("completed_before_choice"), queries=json.dumps(row["queries"])))
    names = {"author_baseline": "Author runner: baseline (fresh)", "author_intention": "Author GitHub PIS (fresh)",
             "ours_baseline": "Our previous baseline", "ours_pis": "Our PIS-inspired", "ours_pis_verified": "Our verifier-enabled*"}
    lines = ["# Author-code PIS versus our independent PIS — Qwen3-8B", "",
             "Completed single-run comparison on the same 80-step PM-Bench synthetic week.",
             f"Author revision: `{manifest['author_commit']}`. Unchanged memory logic; local transport/nonthinking instrumentation only.", "",
             "See [trace-backed failure examples](FAILURE_CASES.md), including expected versus actual JSON, and [all FP/FN rows](failures.csv).", "",
             "| Method | Correct/on-time TP | Wrong/not-due FP | Missed FN | Precision | Recall | Set-F1 | Queries | Invalid-output steps |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, result in results.items():
        m = result["metrics"]
        lines.append(f"| {names[name]} | {m['set_tp']} | {m['set_fp']} | {m['set_fn']} | {m['set_precision']:.1%} | {m['set_recall']:.1%} | {m['set_f1']:.1%} | {m['state_query_calls']} | {result['fallback_steps']} |")
    lines += ["", "TP/FN count due task occurrences; FP counts extra selections. F1 is not step accuracy.",
              "Invalid-output steps count actor failure, not internal helper parsing retries.",
              "*Previous verifier-enabled run produced no ACT proposals and invoked no verifier; not a tested verification benefit.",
              f"Baseline trace differences despite identical aggregate scores: {baseline_diff['selected_set_differences']} selected sets and {baseline_diff['query_differences']} query-count rows. Temperature 0 did not yield identical traces.", "",
              "## Where misses differ", "",
              f"- Identical state-aware due sets: {overlap['due_sets_identical']}.",
              f"- Missed by both: {len(overlap['missed_by_both'])}.",
              f"- Authors missed, ours hit: {len(overlap['author_miss_ours_hit'])}.",
              f"- Ours missed, authors hit: {len(overlap['ours_miss_author_hit'])}.", "",
              "| Day / step | Due action | Author PIS | Our PIS |",
              "|---|---|---|---|"]
    ours_rows = {(r["day"], r["step_id"]): r for r in ours["rows"]}
    for row in author["rows"]:
        other = ours_rows[(row["day"], row["step_id"])]
        for tid in sorted(set(row["fn"]) | set(other["fn"])):
            task = row["tasks"].get(tid, other["tasks"].get(tid, {}))
            action = (task.get("action_text") or tid).replace("|", "/")
            verdict = lambda r: "missed" if tid in r["fn"] else "hit" if tid in r["tp"] else "not due in this trace"
            lines.append(f"| {row['day']} / {row['step_id']} | {action} | {verdict(row)} | {verdict(other)} |")
    lines += ["", "## API reliability and cost", ""]
    for name in ("author_baseline", "author_intention"):
        result = results[name]
        lines += [f"- {names[name]}: {result['duration_seconds']/60:.1f} minutes; calls by role `{result['api']['calls_by_role']}`; tokens by role `{result['api']['tokens_by_role']}`; finish reasons `{result['api']['finish_reasons']}`; API errors {len(result['api']['errors'])}."]
    lines += [f"- Author PIS memory events: `{author['memory_events']}`; recorded memory errors: {len(author['memory_errors'])} across {len(author['memory_error_steps'])} distinct steps.",
              f"- Author PIS length-truncated replies by role: `{author['api']['truncations_by_role']}`; output limits: `{author['api']['max_tokens_by_role']}`. Retried calls are included in token and runtime costs.",
              f"- Final author store: {author['final_bank']['records']} records, statuses `{author['final_bank']['status_counts']}`, {author['final_bank']['exact_duplicate_excess']} excess exact copies (all exported fields except UUID identical). This measures duplication, not the number of causally explained misses.",
              "- Token counts above include actor and helper calls. Any upstream dollar estimates assume an unrelated hosted vendor tariff; they are not actual charges for these local runs."]
    lines += ["", "## Miss categories (task attributes, not inferred causes)", "",
              "| Method | Misses by trigger type | Missed occurrences on updated tasks |",
              "|---|---|---:|"]
    for name in ("author_intention", "ours_pis"):
        result = results[name]
        lines.append(f"| {names[name]} | `{result['misses_by_trigger_type']}` | {result['updated_task_misses']} |")
    lines += ["", "## Interpretation limits", "",
              "- This runs the current pinned GitHub implementation, not necessarily the exact paper revision/configuration.",
              "- Same Qwen3-8B BF16 model snapshot, temperature 0, nonthinking, 768 actor tokens, scenario and scoring. No ground-truth fallback.",
              "- Authors retain compact actor history, forced clock checks, channel-specific hints and done-on-selection. Ours retains independent actor choice, attempted-not-completed records and a two-query budget. Prompts, policies, budgets and costs are not matched.",
              "- Prior independent PIS outputs are reused, not silently relabeled as fresh runs. Single runs cannot establish significance or general plug-and-play benefits.",
              "- Raw calls, author memory snapshots, full scored rows and failures.csv support further causal diagnosis; an observed miss alone does not identify its cause.",
              "- Ground truth is used only in this offline analysis, never passed to the runtime memory module."]
    (root / "RESULTS.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:16]))


if __name__ == "__main__":
    main()
