#!/usr/bin/env python3
"""Generate a single PM-Bench v9 week."""

import argparse

from pm_bench import attach_groundtruth_labels, validate_scenario
from week_builder_v9 import generate_week_v9, summarize_v9_stats, write_json


def main():
    parser = argparse.ArgumentParser(description="Generate a PM-Bench v9 week.")
    parser.add_argument("--out", required=True, help="Path to the output JSON file.")
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible v9 generation.",
    )
    parser.add_argument(
        "--scenario-name",
        default="synthetic_week_v9",
        help="Scenario name to write into the generated file.",
    )
    args = parser.parse_args()

    week, stats = generate_week_v9(seed=args.seed, scenario_name=args.scenario_name)
    groundtruth_report = attach_groundtruth_labels(week)
    if not groundtruth_report["solvable"]:
        raise SystemExit(f"Solvability check failed: {groundtruth_report['issues']}")
    errors, warnings = validate_scenario(week)
    if errors:
        raise SystemExit(f"Validation failed: {errors}")
    for warning in warnings:
        print(f"warning: {warning}")
    write_json(args.out, week)
    print(summarize_v9_stats(stats))
    print(f"solvable: {groundtruth_report['solvable']}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
