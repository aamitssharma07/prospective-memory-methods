#!/usr/bin/env python3
"""Validate the Qwen3-8B gate before submitting the remaining model matrix."""

from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "data" / "PMBench" / "runs" / "exp2_anchor_qwen3_8b"
MODEL_DIR = Path("Qwen-Qwen3-8B")

RUN_SPECS = {
    "mem0": (RUN_ROOT / "results" / MODEL_DIR, "mem0-Qwen-Qwen3-8B-v9-*"),
    "amem": (RUN_ROOT / "results" / MODEL_DIR, "amem-Qwen-Qwen3-8B-v9-*"),
    "pis_rag": (
        RUN_ROOT / "intention_rag" / "results" / MODEL_DIR,
        "intention-rag-Qwen-Qwen3-8B-v9-*",
    ),
    "pis": (RUN_ROOT / "results" / MODEL_DIR, "intention-Qwen-Qwen3-8B-v9-*"),
}


def newest_run(parent: Path, pattern: str) -> Path:
    candidates = sorted(path for path in parent.glob(pattern) if path.is_dir())
    if not candidates:
        raise AssertionError(f"missing run directory: {parent / pattern}")
    return candidates[-1]


def validate_run(name: str, run_dir: Path) -> None:
    stem = run_dir.name
    required = [
        run_dir / f"{stem}.jsonl",
        run_dir / f"{stem}.score.md",
        run_dir / f"{stem}.cost.json",
        run_dir / f"{stem}.cost.jsonl",
        run_dir / f"{stem}.memory.jsonl",
        run_dir / f"{stem}.prompt.txt",
    ]
    for path in required:
        assert path.is_file() and path.stat().st_size > 0, f"missing/empty: {path}"

    rows = [json.loads(line) for line in required[0].read_text().splitlines()]
    assert len(rows) == 81, f"{name}: expected header + 80 steps, got {len(rows)}"
    steps = rows[1:]
    assert len({row.get("step_id") for row in steps}) == 80, (
        f"{name}: duplicate or missing step IDs"
    )
    for row in steps:
        if row.get("model_error"):
            assert not row.get("task_ids"), f"{name}: model error received task credit"

    score = required[1].read_text()
    assert "| Set F1 |" in score, f"{name}: score report lacks Set F1"
    json.loads(required[2].read_text())
    print(f"PASS {name}: 80 steps, complete artifacts ({run_dir})")


def validate_logs() -> None:
    job_id = os.environ.get("ANCHOR_JOB_ID", "1502585")
    logs = [RUN_ROOT / f"sglang-{job_id}.log", RUN_ROOT / f"slurm-{job_id}.log"]
    logs.extend(RUN_ROOT / f"{name}-{job_id}.log" for name in RUN_SPECS)
    forbidden = (
        "OpenRouter",
        "RateLimitError",
        "APIConnectionError",
        "CUDA out of memory",
        "Scheduler hit an exception",
    )
    for path in logs:
        assert path.is_file(), f"missing active-job log: {path}"
        text = path.read_text(errors="replace")
        found = [token for token in forbidden if token in text]
        assert not found, f"{path}: infrastructure/provider errors: {found}"
    print(f"PASS active-job logs for {job_id}")


def main() -> None:
    for marker in RUN_SPECS:
        path = RUN_ROOT / "status" / f"{marker}.complete"
        assert path.is_file(), f"missing completion marker: {path}"
    for name, (parent, pattern) in RUN_SPECS.items():
        validate_run(name, newest_run(parent, pattern))
    validate_logs()
    print("ANCHOR VALIDATION PASSED")


if __name__ == "__main__":
    main()
