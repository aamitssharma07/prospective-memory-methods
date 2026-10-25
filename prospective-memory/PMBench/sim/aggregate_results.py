#!/usr/bin/env python3
"""Aggregate completed run bundles into JSON, CSV, and Markdown tables."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


FIELDS = [
    "model", "setup", "status", "completed_steps", "set_f1", "set_precision",
    "set_recall", "set_tp", "set_fp", "set_fn", "hit", "late", "miss",
    "false_alarm", "invalid_response_steps", "state_query_calls", "TOK", "DUR",
    "duration_seconds",
]


def _as_number(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def token_count(metadata: dict, run_dir: Path) -> int | float | None:
    """Return total token count from saved metadata/cost artifacts when present."""
    token_usage = metadata.get("token_usage") if isinstance(metadata, dict) else None
    if isinstance(token_usage, dict):
        for key in ("total_tokens", "TOK", "tokens"):
            value = _as_number(token_usage.get(key))
            if value is not None:
                return value
    for key in ("total_tokens", "TOK", "tokens"):
        value = _as_number(metadata.get(key)) if isinstance(metadata, dict) else None
        if value is not None:
            return value

    cost_candidates = sorted(run_dir.glob("*.cost.json"))
    for path in cost_candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for section_name in ("chat_billed", "chat", "usage"):
            section = payload.get(section_name)
            if isinstance(section, dict):
                value = _as_number(section.get("total_tokens"))
                if value is not None:
                    return value
        value = _as_number(payload.get("total_tokens"))
        if value is not None:
            return value
    return None


def collect(root: Path) -> list[dict]:
    rows = []
    for path in sorted(root.glob("*/*/metrics.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        manifest_path = path.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        summary = payload.get("summary") or {}
        rates = payload.get("rates") or {}
        metadata = payload.get("run_metadata") or {}
        rows.append({
            "model": manifest.get("model", {}).get("name", metadata.get("model", path.parents[1].name)),
            "setup": manifest.get("setup", {}).get("name", path.parent.name),
            "status": payload["status"],
            "completed_steps": payload["completed_steps"],
            "set_f1": rates.get("set_f1"),
            "set_precision": rates.get("set_precision"),
            "set_recall": rates.get("set_recall"),
            "set_tp": summary.get("set_tp"), "set_fp": summary.get("set_fp"),
            "set_fn": summary.get("set_fn"), "hit": summary.get("hit"),
            "late": summary.get("late"), "miss": summary.get("miss"),
            "false_alarm": summary.get("false_alarm"),
            "invalid_response_steps": summary.get("invalid_response_steps"),
            "state_query_calls": summary.get("state_query_calls"),
            "TOK": token_count(metadata, path.parent),
            "DUR": metadata.get("duration_seconds"),
            "duration_seconds": metadata.get("duration_seconds"),
        })
    return rows


def percent(value):
    return "n/a" if value is None else f"{value * 100:.1f}%"


def number(value):
    if value is None:
        return "n/a"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.3f}"
    return f"{int(value):,}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    root = args.results.resolve()
    output = (args.output_dir or root).resolve()
    rows = collect(root)
    if not rows:
        raise SystemExit(f"No metrics.json files found under {root}")
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    with (output / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# PM-Bench Core-Four Results", "",
        "| Model | Setup | Status | Set F1 | Precision | Recall | TOK | DUR | TP | FP | FN | Invalid |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['model']} | {row['setup']} | {row['status']} | {percent(row['set_f1'])} | "
            f"{percent(row['set_precision'])} | {percent(row['set_recall'])} | "
            f"{number(row['TOK'])} | {number(row['DUR'])} | "
            f"{row['set_tp'] if row['set_tp'] is not None else 'n/a'} | "
            f"{row['set_fp'] if row['set_fp'] is not None else 'n/a'} | "
            f"{row['set_fn'] if row['set_fn'] is not None else 'n/a'} | "
            f"{row['invalid_response_steps'] if row['invalid_response_steps'] is not None else 'n/a'} |"
        )
    (output / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} result rows to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
