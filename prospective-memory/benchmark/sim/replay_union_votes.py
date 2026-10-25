#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_pm_bench_module():
    pm_bench_path = PROJECT_ROOT / "sim" / "pm_bench.py"
    spec = importlib.util.spec_from_file_location("pm_bench", pm_bench_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load pm_bench module from {pm_bench_path}")
    pm_bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pm_bench)
    return pm_bench


PM_BENCH = _load_pm_bench_module()


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _find_union_paths(source_run_dir: Path) -> tuple[Path, Path]:
    jsonl_candidates = sorted(source_run_dir.glob("*.jsonl"))
    log_path = None
    debug_path = None
    for candidate in jsonl_candidates:
        if candidate.name.endswith(".debug.jsonl"):
            debug_path = candidate
        else:
            log_path = candidate
    if log_path is None:
        raise SystemExit(f"Could not find union log .jsonl in {source_run_dir}")
    if debug_path is None:
        raise SystemExit(f"Could not find union debug .debug.jsonl in {source_run_dir}")
    return log_path, debug_path


def _build_day_handle_maps(scenario: dict[str, Any]) -> dict[str, dict[str, str]]:
    day_handle_to_id: dict[str, dict[str, str]] = {}
    for day in scenario.get("days", []):
        tasks = day.get("tasks", [])
        lure_catalog = PM_BENCH.normalize_lure_catalog(day.get("lures", []))
        task_states = {task["id"]: PM_BENCH.init_task_state(task) for task in tasks}
        _, handle_to_id = PM_BENCH.build_day_handle_maps(
            task_states,
            lure_catalog,
            seed_key=f"{day['name']}:handles",
        )
        day_handle_to_id[day["name"]] = handle_to_id
    return day_handle_to_id


def _read_debug_step_votes(
    debug_path: Path,
) -> dict[tuple[str, str], dict[str, Any]]:
    by_step: dict[tuple[str, str], dict[str, Any]] = {}
    with debug_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if payload.get("event") != "step_decision":
                continue
            day = payload.get("day")
            step_id = payload.get("step_id")
            if not isinstance(day, str) or not isinstance(step_id, str):
                continue
            by_step[(day, step_id)] = payload
    return by_step


def _compute_majority_handles(
    vote_counts: dict[str, int],
    vote_by_agent: dict[str, list[str]],
) -> list[str]:
    if not vote_counts:
        return []
    n = len(vote_by_agent)
    if n <= 0:
        return []
    threshold = n / 2.0
    winners = [handle for handle, count in vote_counts.items() if count > threshold]
    winners.sort()
    return winners


def _compute_unanimous_handles(
    vote_counts: dict[str, int],
    vote_by_agent: dict[str, list[str]],
) -> list[str]:
    if not vote_counts:
        return []
    n = len(vote_by_agent)
    if n <= 0:
        return []
    winners = [handle for handle, count in vote_counts.items() if count == n]
    winners.sort()
    return winners


def _map_handles_to_ids(
    handles: list[str],
    day: str,
    day_handle_to_id: dict[str, dict[str, str]],
) -> list[str]:
    handle_to_id = day_handle_to_id.get(day, {})
    mapped: list[str] = []
    for handle in handles:
        task_id = handle_to_id.get(handle)
        if task_id is None:
            continue
        if task_id in mapped:
            continue
        mapped.append(task_id)
    return mapped


def _replay_entries(
    union_entries: list[dict[str, Any]],
    vote_by_step: dict[tuple[str, str], dict[str, Any]],
    day_handle_to_id: dict[str, dict[str, str]],
    rule: str,
) -> list[dict[str, Any]]:
    if rule not in {"majority", "unanimous"}:
        raise ValueError(f"Unsupported rule: {rule}")

    replayed: list[dict[str, Any]] = []
    for entry in union_entries:
        if not isinstance(entry, dict):
            replayed.append(entry)
            continue
        day = entry.get("day")
        step_id = entry.get("step_id")
        if not isinstance(day, str) or not isinstance(step_id, str):
            replayed.append(dict(entry))
            continue
        step_vote = vote_by_step.get((day, step_id))
        if step_vote is None:
            replayed.append(dict(entry))
            continue

        vote_counts = step_vote.get("task_vote_counts")
        vote_by_agent = step_vote.get("task_vote_by_agent")
        majority_from_debug = step_vote.get("task_vote_majority_handles")
        if not isinstance(vote_counts, dict) or not isinstance(vote_by_agent, dict):
            replayed.append(dict(entry))
            continue

        if rule == "majority":
            if isinstance(majority_from_debug, list) and all(
                isinstance(item, str) for item in majority_from_debug
            ):
                handles = list(majority_from_debug)
            else:
                handles = _compute_majority_handles(vote_counts, vote_by_agent)
        else:
            if isinstance(majority_from_debug, list) and all(
                isinstance(item, str) for item in majority_from_debug
            ):
                n = len(vote_by_agent)
                handles = [h for h in majority_from_debug if vote_counts.get(h) == n]
                extras = [
                    h
                    for h, count in vote_counts.items()
                    if count == n and h not in handles
                ]
                extras.sort()
                handles.extend(extras)
            else:
                handles = _compute_unanimous_handles(vote_counts, vote_by_agent)
        mapped_task_ids = _map_handles_to_ids(handles, day, day_handle_to_id)
        next_entry = dict(entry)
        next_entry["task_ids"] = mapped_task_ids
        replayed.append(next_entry)
    return replayed


def _replace_run_name(path: Path, from_prefix: str, to_prefix: str) -> Path:
    if not path.name.startswith(from_prefix):
        raise SystemExit(f"Expected {path.name} to start with {from_prefix}")
    return path.with_name(path.name.replace(from_prefix, to_prefix, 1))


def _score_and_write_report(
    scenario: dict[str, Any],
    log_path: Path,
    entries: list[dict[str, Any]],
    run_metadata: dict[str, Any],
) -> Path:
    summary, per_day, summary_steps = PM_BENCH.score_log(scenario, entries)
    report_md = PM_BENCH.build_markdown_report(
        summary,
        per_day,
        summary_steps,
        run_metadata=run_metadata,
    )
    report_path = log_path.with_suffix(".score.md")
    with report_path.open("w", encoding="utf-8") as handle:
        handle.write(report_md)
    return report_path


def _write_replay(
    scenario: dict[str, Any],
    union_entries: list[dict[str, Any]],
    union_metadata: dict[str, Any] | None,
    source_run_dir: Path,
    target_run_dir: Path,
    mode_name: str,
    replay_mode_label: str,
    rule: str,
    vote_by_step: dict[tuple[str, str], dict[str, Any]],
    day_handle_to_id: dict[str, dict[str, str]],
    overwrite: bool,
) -> tuple[Path, Path]:
    target_run_dir.mkdir(parents=True, exist_ok=True)
    log_path = target_run_dir / f"{target_run_dir.name}.jsonl"
    score_path = target_run_dir / f"{target_run_dir.name}.score.md"

    if score_path.exists() and not overwrite:
        print(f"[skip] {mode_name}: score already exists at {score_path}")
        return log_path, score_path

    replay_entries = _replay_entries(
        union_entries=union_entries,
        vote_by_step=vote_by_step,
        day_handle_to_id=day_handle_to_id,
        rule=rule,
    )
    now = _now_iso_utc()
    replay_metadata = PM_BENCH.make_run_metadata(
        mode=replay_mode_label,
        started_at_utc=now,
        finished_at_utc=now,
        duration_seconds=0.0,
        entry_count=len(replay_entries),
        model=(union_metadata or {}).get("model"),
        backend=(union_metadata or {}).get("backend"),
    )
    replay_metadata["source_union_run_dir"] = str(source_run_dir)
    PM_BENCH.write_log(str(log_path), replay_entries, run_metadata=replay_metadata)
    written_score = _score_and_write_report(
        scenario=scenario,
        log_path=log_path,
        entries=replay_entries,
        run_metadata=replay_metadata,
    )
    print(f"[ok] {mode_name}: wrote {log_path}")
    print(f"[ok] {mode_name}: wrote {written_score}")
    return log_path, written_score


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay union-query debug votes to emit majority-vote and unanimous-vote "
            "scored run artifacts without rerunning inference."
        )
    )
    parser.add_argument(
        "--scenario",
        default=str(PROJECT_ROOT / "data" / "synthetic_week_v9.json"),
        help="Scenario JSON path.",
    )
    parser.add_argument(
        "--source-run-dir",
        required=True,
        help="Path to the source hier-union-query run directory.",
    )
    parser.add_argument(
        "--out-model-dir",
        default=None,
        help=(
            "Directory where replay run directories will be written. "
            "Defaults to the parent of --source-run-dir."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing replay score artifacts.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    scenario = PM_BENCH.load_scenario(args.scenario)
    source_run_dir = Path(args.source_run_dir).expanduser().resolve()
    if not source_run_dir.exists():
        raise SystemExit(f"Source run dir not found: {source_run_dir}")
    if not source_run_dir.is_dir():
        raise SystemExit(f"Source run dir is not a directory: {source_run_dir}")

    out_model_dir = (
        Path(args.out_model_dir).expanduser().resolve()
        if args.out_model_dir
        else source_run_dir.parent
    )
    out_model_dir.mkdir(parents=True, exist_ok=True)

    union_log_path, union_debug_path = _find_union_paths(source_run_dir)
    union_entries, union_metadata = PM_BENCH.read_log_with_metadata(str(union_log_path))
    vote_by_step = _read_debug_step_votes(union_debug_path)
    day_handle_to_id = _build_day_handle_maps(scenario)

    source_name = source_run_dir.name
    majority_name = _replace_run_name(
        Path(source_name),
        "hier-union-query-",
        "hier-majority-vote-replay-",
    ).name
    unanimous_name = _replace_run_name(
        Path(source_name),
        "hier-union-query-",
        "hier-unanimous-vote-replay-",
    ).name

    _write_replay(
        scenario=scenario,
        union_entries=union_entries,
        union_metadata=union_metadata,
        source_run_dir=source_run_dir,
        target_run_dir=out_model_dir / majority_name,
        mode_name="majority",
        replay_mode_label="replay-multi-majority-vote-from-union-debug",
        rule="majority",
        vote_by_step=vote_by_step,
        day_handle_to_id=day_handle_to_id,
        overwrite=args.overwrite,
    )
    _write_replay(
        scenario=scenario,
        union_entries=union_entries,
        union_metadata=union_metadata,
        source_run_dir=source_run_dir,
        target_run_dir=out_model_dir / unanimous_name,
        mode_name="unanimous",
        replay_mode_label="replay-multi-unanimous-vote-from-union-debug",
        rule="unanimous",
        vote_by_step=vote_by_step,
        day_handle_to_id=day_handle_to_id,
        overwrite=args.overwrite,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
