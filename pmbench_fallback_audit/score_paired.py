#!/usr/bin/env python3
"""Score one instrumented PM-Bench trace under both fallback policies.

The original score uses the logged actions. The corrected counterfactual replaces
task_ids with [] only on entries marked fallback_triggered. This is an exact
same-trace comparison, but not a replacement for a separate corrected run when
runtime completions change future model context.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "PMBench" / "sim"
sys.path.insert(0, str(SIM))

import pm_bench  # noqa: E402


def metric_payload(summary: dict) -> dict:
    tp = summary["set_tp"]
    fp = summary["set_fp"]
    fn = summary["set_fn"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "set_precision": precision,
        "set_recall": recall,
        "set_f1": f1,
        "set_tp": tp,
        "set_fp": fp,
        "set_fn": fn,
        "hit": summary["hit"],
        "late": summary["late"],
        "miss": summary["miss"],
        "false_alarm": summary["false_alarm"],
        "check_time_calls": summary["check_time_calls"],
        "state_query_calls": summary["state_query_calls"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    scenario = pm_bench.load_scenario(args.scenario)
    original_entries, metadata = pm_bench.read_log_with_metadata(args.log)
    if original_entries and not all(
        "fallback_triggered" in entry for entry in original_entries
    ):
        raise SystemExit(
            "This is a legacy, uninstrumented log. It cannot establish which "
            "actions were substituted; generate a new trace first."
        )
    fallback_entries = [
        entry for entry in original_entries if entry.get("fallback_triggered")
    ]

    corrected_entries = copy.deepcopy(original_entries)
    credited_task_selections = 0
    for entry in corrected_entries:
        if entry.get("fallback_triggered"):
            credited_task_selections += len(entry.get("task_ids", []))
            entry["task_ids"] = []
            entry["fallback_policy"] = "empty_counterfactual"

    original_summary, original_per_day, steps = pm_bench.score_log(
        scenario, original_entries
    )
    corrected_summary, corrected_per_day, _ = pm_bench.score_log(
        scenario, corrected_entries
    )
    original = metric_payload(original_summary)
    corrected = metric_payload(corrected_summary)

    result = {
        "source_log": str(Path(args.log).resolve()),
        "run_metadata": metadata,
        "steps": steps,
        "fallback_steps": len(fallback_entries),
        "fallback_rate": len(fallback_entries) / steps if steps else 0.0,
        "ground_truth_task_selections_inserted": credited_task_selections,
        "original_protocol": original,
        "empty_fallback_counterfactual": corrected,
        "original_pmbench_summary": original_summary,
        "corrected_pmbench_summary": corrected_summary,
        "original_pmbench_per_day": original_per_day,
        "corrected_pmbench_per_day": corrected_per_day,
        "set_f1_absolute_difference": original["set_f1"] - corrected["set_f1"],
        "interpretation_warning": (
            "This paired score holds the generated trace fixed. Run the empty "
            "fallback protocol separately for end-to-end results if fallback "
            "completions alter later state or prompts."
        ),
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "steps": steps,
                "fallback_steps": len(fallback_entries),
                "fallback_rate": result["fallback_rate"],
                "original_set_f1": original["set_f1"],
                "corrected_set_f1": corrected["set_f1"],
                "set_f1_absolute_difference": result["set_f1_absolute_difference"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
