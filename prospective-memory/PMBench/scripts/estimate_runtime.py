#!/usr/bin/env python3
"""Estimate the core-four runtime from saved PM-Bench run metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics


ROOT = Path(__file__).resolve().parents[1]
SETUP_MARKERS = {
    "single_baseline": "single-baseline-",
    "optional_heartbeat": "heartbeat-proactive-",
    "todo_ledger": "single-todo-ledger-",
    "auto_heartbeat_30m": "heartbeat-auto-30m-",
}


def format_duration(seconds: float) -> str:
    minutes, sec = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def load_durations(results_dir: Path) -> dict[str, list[float]]:
    durations = {name: [] for name in SETUP_MARKERS}
    for path in results_dir.rglob("*.jsonl"):
        path_text = str(path)
        setup = next(
            (name for name, marker in SETUP_MARKERS.items() if marker in path_text),
            None,
        )
        if setup is None or ".ledger.jsonl" in path.name:
            continue
        try:
            first = path.open("r", encoding="utf-8").readline()
            metadata = json.loads(first)
            duration = float(metadata["duration_seconds"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
        if metadata.get("entry_count") == 80 and duration > 0:
            durations[setup].append(duration)
    return durations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "runs" / "all_results_v9")
    parser.add_argument("--models", type=int, default=11)
    parser.add_argument("--parallel-workers", type=int, default=1)
    args = parser.parse_args()
    if args.models < 1 or args.parallel_workers < 1:
        parser.error("--models and --parallel-workers must be positive")

    durations = load_durations(args.results_dir)
    medians: dict[str, float] = {}
    print("Historical 80-step run durations:")
    for setup in SETUP_MARKERS:
        values = durations[setup]
        if not values:
            raise SystemExit(f"No usable historical durations for {setup}")
        median = statistics.median(values)
        medians[setup] = median
        print(
            f"  {setup:24} median={format_duration(median):>8} "
            f"range={format_duration(min(values))}..{format_duration(max(values))} "
            f"n={len(values)}"
        )

    serial_seconds = args.models * sum(medians.values())
    effective_seconds = serial_seconds / args.parallel_workers
    print(f"\nPlanned runs: {args.models} models x {len(SETUP_MARKERS)} setups")
    print(f"Historical-median serial estimate: {format_duration(serial_seconds)}")
    if args.parallel_workers > 1:
        print(
            f"Idealized {args.parallel_workers}-worker lower bound: "
            f"{format_duration(effective_seconds)}"
        )
    print(
        "Planning estimate only: model speed, provider latency, retries, and GPU "
        "scheduling can materially change wall time. Server startup, model swaps, "
        "and Slurm queue time are excluded. Live execution uses tqdm ETA."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
