#!/usr/bin/env python3
"""Create durable machine-readable and human-readable analysis for one run."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim"))
import pm_bench as PM_BENCH  # noqa: E402


STEP_FIELDS = [
    "day", "step_id", "time", "text", "cues", "trajectory_present", "expected_task_ids",
    "selected_task_ids", "true_positives", "false_positives", "false_negatives",
    "exact_set_match", "invalid_response", "invalid_response_policy",
    "invalid_response_reason", "state_query_calls", "check_time_calls",
]


def csv_value(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    return value


def rates(summary: dict) -> dict:
    tp, fp, fn = summary["set_tp"], summary["set_fp"], summary["set_fn"]
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    return {"set_precision": precision, "set_recall": recall, "set_f1": f1}


def step_rows(scenario: dict, entries: list[dict]) -> list[dict]:
    by_key = {(entry["day"], entry["step_id"]): entry for entry in entries}
    rows = []
    for day in scenario["days"]:
        for step in day["steps"]:
            entry = by_key.get((day["name"], step["id"]), {})
            expected = sorted(
                action["id"] for action in step.get("groundtruth", {}).get("actions", [])
            )
            selected = sorted(PM_BENCH.normalize_task_ids(entry))
            expected_set, selected_set = set(expected), set(selected)
            query_counts = PM_BENCH.get_action_state_query_counts(entry)
            rows.append({
                "day": day["name"],
                "step_id": step["id"],
                "time": step.get("time"),
                "text": step.get("text"),
                "cues": step.get("cues", []),
                "trajectory_present": bool(entry),
                "expected_task_ids": expected,
                "selected_task_ids": selected,
                "true_positives": sorted(expected_set & selected_set),
                "false_positives": sorted(selected_set - expected_set),
                "false_negatives": sorted(expected_set - selected_set),
                "exact_set_match": bool(entry) and not entry.get("invalid_response", False)
                and selected_set == expected_set,
                "invalid_response": bool(entry.get("invalid_response", False)),
                "invalid_response_policy": entry.get("invalid_response_policy"),
                "invalid_response_reason": entry.get("invalid_response_reason"),
                "state_query_calls": sum(query_counts.values()),
                "check_time_calls": query_counts.get("clock", 0),
            })
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=STEP_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row[key]) for key in STEP_FIELDS})


def markdown(payload: dict, failures: list[dict]) -> str:
    summary, derived = payload["summary"], payload["rates"]
    metadata = payload.get("run_metadata") or {}
    pct = lambda value: "n/a" if value is None else f"{value * 100:.1f}%"
    tok = metadata.get("total_tokens")
    if tok is None and isinstance(metadata.get("token_usage"), dict):
        tok = metadata["token_usage"].get("total_tokens")
    dur = metadata.get("duration_seconds")
    tok_text = "n/a" if tok is None else f"{int(tok):,}"
    dur_text = "n/a" if dur is None else PM_BENCH.format_duration_seconds(dur)
    lines = [
        "# Run Analysis", "",
        f"- Status: `{payload['status']}`",
        f"- Completed steps: {payload['completed_steps']} / {payload['expected_steps']}",
        f"- Set F1: **{pct(derived['set_f1'])}**",
        f"- Set precision: {pct(derived['set_precision'])}",
        f"- Set recall: {pct(derived['set_recall'])}",
        f"- TOK: {tok_text}",
        f"- DUR: {dur_text}",
        f"- TP / FP / FN: {summary['set_tp']} / {summary['set_fp']} / {summary['set_fn']}",
        f"- Hit / late / miss: {summary['hit']} / {summary['late']} / {summary['miss']}",
        f"- Invalid response steps: {summary['invalid_response_steps']}",
        "", "## Per-Day", "",
        "| Day | Hit | Late | Miss | TP | FP | FN | Invalid |", 
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for day, details in payload["per_day"].items():
        metrics = details["metrics"]
        lines.append(
            f"| {day} | {metrics['hit']} | {metrics['late']} | {metrics['miss']} | "
            f"{metrics['set_tp']} | {metrics['set_fp']} | {metrics['set_fn']} | "
            f"{metrics['invalid_response_steps']} |"
        )
    lines.extend([
        "", "## Failure Inventory", "",
        f"{len(failures)} steps contain a false positive, false negative, invalid response, "
        "or are absent from an incomplete trajectory.", "",
        "See `failures.csv` for every affected step and `steps.csv` for the complete timeline.",
        "The full nested scorer output is preserved in `metrics.json`.", "",
    ])
    return "\n".join(lines)


def analyze(scenario_path: Path, log_path: Path, output_dir: Path) -> dict:
    scenario = PM_BENCH.load_scenario(str(scenario_path))
    entries, run_metadata = PM_BENCH.read_log_with_metadata(str(log_path))
    run_metadata = dict(run_metadata or {})
    token_usage = PM_BENCH.summarize_token_usage(entries)
    if token_usage is not None and "token_usage" not in run_metadata:
        run_metadata["token_usage"] = token_usage
    expected_steps = sum(len(day["steps"]) for day in scenario["days"])
    status = "complete" if len(entries) == expected_steps else "partial"
    rows = step_rows(scenario, entries)
    failures = [
        row for row in rows
        if row["false_positives"] or row["false_negatives"]
        or row["invalid_response"] or not row["trajectory_present"]
    ]
    payload = {
        "schema_version": 1,
        "status": status,
        "expected_steps": expected_steps,
        "completed_steps": len(entries),
        "run_metadata": run_metadata,
    }
    if status == "complete":
        summary, per_day, _ = PM_BENCH.score_log(scenario, entries)
        payload.update(summary=summary, rates=rates(summary), per_day=per_day)
    else:
        payload.update(summary=None, rates=None, per_day=None)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metrics.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_csv(output_dir / "steps.csv", rows)
    write_csv(output_dir / "failures.csv", failures)
    if status == "complete":
        (output_dir / "ANALYSIS.md").write_text(markdown(payload, failures), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    payload = analyze(args.scenario.resolve(), args.log.resolve(), args.output_dir.resolve())
    print(json.dumps({key: payload[key] for key in ("status", "completed_steps", "expected_steps")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
