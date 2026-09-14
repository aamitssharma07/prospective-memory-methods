#!/usr/bin/env python3
"""Aggregate paired audit outputs into one publication-friendly CSV."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    rows = []
    for path in sorted(Path(args.results).glob("*/*/paired_metrics.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        manifest = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))
        original = payload["original_protocol"]
        corrected = payload["empty_fallback_counterfactual"]
        rows.append({
            "model": manifest["model"]["id"],
            "family": manifest["model"]["family"],
            "category": manifest["model"]["category"],
            "total_parameters_b": manifest["model"]["total_parameters_b"],
            "active_parameters_b": manifest["model"]["active_parameters_b"],
            "pmbench_anchor": manifest["model"]["pmbench_anchor"],
            "setup": manifest["setup"].get("label", manifest["setup"]["name"]),
            "steps": payload["steps"], "fallback_steps": payload["fallback_steps"],
            "fallback_rate": payload["fallback_rate"],
            "inserted_task_selections": payload["ground_truth_task_selections_inserted"],
            "original_set_f1": original["set_f1"],
            "corrected_set_f1": corrected["set_f1"],
            "set_f1_difference": payload["set_f1_absolute_difference"],
            "original_tp": original["set_tp"], "corrected_tp": corrected["set_tp"],
            "original_fp": original["set_fp"], "corrected_fp": corrected["set_fp"],
            "original_fn": original["set_fn"], "corrected_fn": corrected["set_fn"],
            "state_query_calls": original["state_query_calls"],
            "check_time_calls": original["check_time_calls"],
        })
    if not rows:
        raise SystemExit("No paired_metrics.json files found")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
