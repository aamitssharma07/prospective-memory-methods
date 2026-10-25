#!/usr/bin/env python3
"""Per-category and per-task failure analysis for PM-Bench runs.

PM-Bench's scorer reports category splits only for modality, regularity and
monitoring, and records false alarms as a single scalar with no task identity.
This adds the missing breakdowns -- update subtype, channel-triggered, lures,
and per-task outcomes -- without reimplementing the scoring semantics.

Exactness: `score_day` is recompiled from its own source with one line added
that publishes its per-task state dict. Every number here therefore comes from
the benchmark's own state machine, and `--validate` re-checks the aggregate
totals against the untouched `score_log`.
"""
import argparse
import csv
import inspect
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmark" / "sim"))
import pm_bench  # noqa: E402

CAPTURED = []


def _instrumented_score_day():
    """Recompile score_day so it publishes task_states, leaving logic untouched."""
    src = inspect.getsource(pm_bench.score_day)
    anchor = '    task_states = {task["id"]: init_task_state(task) for task in tasks}'
    if anchor not in src:
        raise SystemExit("score_day changed shape; update the anchor in analyze_categories.py")
    src = src.replace(anchor, anchor + "\n    _CAPTURED.append((day, task_states))", 1)
    src = re.sub(r"^def score_day", "def _score_day_capturing", src)
    namespace = dict(vars(pm_bench))
    namespace["_CAPTURED"] = CAPTURED
    exec(compile(src, "<instrumented score_day>", "exec"), namespace)
    return namespace["_score_day_capturing"]


def task_metadata(scenario):
    """Category labels per task, plus the lure ids and update subtypes."""
    meta, updates = {}, {}
    for day in scenario["days"]:
        for task in day["tasks"]:
            meta[(day["name"], task["id"])] = {
                "day": day["name"],
                "label": task.get("label", ""),
                "modality": task.get("type"),
                "regular": bool(task.get("regular")),
                "cross_day": bool(task.get("cross_day")),
                "cross_day_offset": task.get("cross_day_offset"),
                "cue_channel": task.get("cue_channel") or "",
                "channel_triggered": bool(task.get("cue_channel")),
                "target_time": task.get("target_time") or "",
            }
        for step in day.get("steps", []):
            for update in step.get("updates", []):
                updates[update["task_id"]] = {"action": update["action"], "at": step["id"]}
    lures = {lure["id"] for day in scenario["days"] for lure in day.get("lures", [])}
    return meta, updates, lures


def selections(log_entries):
    """Task ids the agent selected, per step, in order."""
    out = []
    for entry in log_entries:
        if entry.get("record_type"):
            continue
        out.append((entry.get("step_id"), list(entry.get("task_ids") or [])))
    return out


def analyse(scenario_path, log_path):
    scenario = pm_bench.load_scenario(str(scenario_path))
    entries, run_metadata = pm_bench.read_log_with_metadata(str(log_path))
    meta, updates, lures = task_metadata(scenario)

    CAPTURED.clear()
    capturing = _instrumented_score_day()
    original = pm_bench.score_day
    pm_bench.score_day = capturing
    try:
        summary, per_day, steps = pm_bench.score_log(scenario, entries)
    finally:
        pm_bench.score_day = original

    # One task_states dict per day. Four recurring tasks share an id across
    # days, so an occurrence is keyed by (day, task_id), not by id alone.
    states = {}
    for day, day_states in CAPTURED:
        for task_id, state in day_states.items():
            states[(day["name"], task_id)] = state

    rows = []
    for (day_name, task_id), state in states.items():
        info = dict(meta.get((day_name, task_id), {}))
        scored = not state.get("canceled")
        outcome = state.get("result") or ("canceled" if state.get("canceled") else "miss")
        info.update(
            task_id=task_id,
            scored=scored,
            outcome=outcome,
            completed_at=state.get("completed_at") or "",
            updated=bool(state.get("updated")),
            update_action=updates.get(task_id, {}).get("action", ""),
            update_at=updates.get(task_id, {}).get("at", ""),
        )
        rows.append(info)

    # False alarms: every selection of a task that was not credited at that step.
    credited = {(r["task_id"], r["completed_at"]) for r in rows if r["completed_at"]}
    known = {task_id for _day, task_id in meta}
    by_id = {}
    for row in rows:
        by_id.setdefault(row["task_id"], row)
    false_alarms = []
    for step_id, chosen in selections(entries):
        for task_id in chosen:
            if (task_id, step_id) in credited:
                continue
            if task_id in lures or task_id not in known:
                kind = "lure"
            else:
                state_row = by_id.get(task_id, {})
                if state_row.get("outcome") in ("hit", "late") and state_row.get("completed_at") != step_id:
                    kind = "already_credited"
                elif state_row.get("cross_day"):
                    kind = "cross_day_wrong_step"
                else:
                    kind = "real_task_wrong_step"
            false_alarms.append({"step_id": step_id, "task_id": task_id, "kind": kind,
                                 "modality": by_id.get(task_id, {}).get("modality", ""),
                                 "cue_channel": by_id.get(task_id, {}).get("cue_channel", "")})
    return summary, rows, false_alarms, run_metadata


def bucket(rows, predicate, label):
    chosen = [r for r in rows if r["scored"] and predicate(r)]
    counts = Counter(r["outcome"] for r in chosen)
    total = len(chosen)
    hit, late, miss = counts.get("hit", 0), counts.get("late", 0), total - counts.get("hit", 0) - counts.get("late", 0)
    return {"category": label, "total": total, "hit": hit, "late": late, "miss": miss,
            "hit_rate": (100.0 * hit / total) if total else 0.0}


def category_table(rows, updates_present):
    out = [bucket(rows, lambda r: True, "ALL scored tasks")]
    for value in ("event", "time"):
        out.append(bucket(rows, lambda r, v=value: r["modality"] == v, f"modality: {value}"))
    out.append(bucket(rows, lambda r: r["regular"], "regular"))
    out.append(bucket(rows, lambda r: not r["regular"], "non-regular"))
    out.append(bucket(rows, lambda r: r["channel_triggered"], "channel-triggered"))
    out.append(bucket(rows, lambda r: not r["channel_triggered"], "not channel-triggered"))
    out.append(bucket(rows, lambda r: r["cross_day"], "cross-day"))
    out.append(bucket(rows, lambda r: r["update_action"] != "", "update-sensitive (any)"))
    for action in ("cancel", "override", "reschedule"):
        out.append(bucket(rows, lambda r, a=action: r["update_action"] == a, f"update: {action}"))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default=str(ROOT / "benchmark/data/synthetic_week_v9.json"))
    parser.add_argument("--log", required=True, help="trajectory.jsonl from a run")
    parser.add_argument("--label", default="", help="model/setup name for the report")
    parser.add_argument("--out-dir", type=Path, default=None, help="write per-task CSVs here")
    parser.add_argument("--validate", action="store_true",
                        help="check the per-task totals against the untouched scorer")
    args = parser.parse_args()

    summary, rows, false_alarms, run_metadata = analyse(args.scenario, args.log)
    label = args.label or run_metadata.get("model", Path(args.log).stem)

    if args.validate:
        hit = sum(1 for r in rows if r["outcome"] == "hit")
        late = sum(1 for r in rows if r["outcome"] == "late")
        problems = []
        if hit != summary["hit"]:
            problems.append(f"hit {hit} != scorer {summary['hit']}")
        if late != summary["late"]:
            problems.append(f"late {late} != scorer {summary['late']}")
        print("VALIDATION:", "; ".join(problems) if problems else
              f"per-task totals agree with the scorer (hit {hit}, late {late})")

    print(f"\n=== {label} — per-category outcomes ===")
    print(f"{'category':26s}{'total':>6}{'hit':>5}{'late':>5}{'miss':>6}{'hit rate':>10}")
    for row in category_table(rows, bool(false_alarms)):
        print(f"{row['category']:26s}{row['total']:>6}{row['hit']:>5}{row['late']:>5}"
              f"{row['miss']:>6}{row['hit_rate']:>9.1f}%")

    kinds = Counter(f["kind"] for f in false_alarms)
    print(f"\n=== false-alarm attribution ({len(false_alarms)} selections not credited) ===")
    for kind, count in kinds.most_common():
        print(f"  {kind:24s}{count:>5}")

    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        tasks_csv = args.out_dir / "per_task_outcomes.csv"
        with tasks_csv.open("w", newline="") as handle:
            fields = ["task_id", "label", "day", "modality", "regular", "cross_day",
                      "cue_channel", "channel_triggered", "target_time", "update_action",
                      "update_at", "updated", "scored", "outcome", "completed_at"]
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(sorted(rows, key=lambda r: (r["day"], r["task_id"])))
        fa_csv = args.out_dir / "false_alarms.csv"
        with fa_csv.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["step_id", "task_id", "kind",
                                                        "modality", "cue_channel"])
            writer.writeheader()
            writer.writerows(false_alarms)
        print(f"\nwrote {tasks_csv}\nwrote {fa_csv}")


if __name__ == "__main__":
    main()
