#!/usr/bin/env python3
"""Rebuild a paper-style Computation Cost table from cost run artifacts."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "code"
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))

from llm_cost import load_events, summary as summary_from_events  # noqa: E402


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _score_fields(score_path: Path) -> dict:
    text = score_path.read_text(encoding="utf-8") if score_path.is_file() else ""
    out = {
        "duration_s": None,
        "state_queries": None,
        "check_time": None,
        "set_f1": None,
        "hit": None,
    }

    def grab(pat: str, cast=float):
        m = re.search(pat, text, re.I)
        return cast(m.group(1)) if m else None

    out["duration_s"] = grab(r"\|\s*Duration\s*\|\s*([0-9.]+)s")
    if out["duration_s"] is None:
        # "47.882s" in table
        out["duration_s"] = grab(r"\|\s*Duration\s*\|\s*([0-9.]+)")
    out["state_queries"] = grab(r"state query calls:\s*(\d+)", int)
    if out["state_queries"] is None:
        out["state_queries"] = grab(r"\|\s*State query calls\s*\|\s*(\d+)", int)
    out["check_time"] = grab(r"check_time calls:\s*(\d+)", int)
    if out["check_time"] is None:
        out["check_time"] = grab(r"\|\s*Check_time calls\s*\|\s*(\d+)", int)
    out["set_f1"] = grab(r"set_f1\s+([0-9.]+)%")
    if out["set_f1"] is None:
        out["set_f1"] = grab(r"\|\s*Set F1\s*\|\s*([0-9.]+)%")
    return out


def _store_size(run_dir: Path, stem: str) -> dict:
    out = {"memories": None, "store_bytes": None}
    intent = run_dir / f"{stem}.intentions.json"
    if intent.is_file():
        data = json.loads(intent.read_text(encoding="utf-8"))
        items = data.get("intentions") if isinstance(data, dict) else data
        if isinstance(items, dict):
            out["memories"] = len(items)
        elif isinstance(items, list):
            out["memories"] = len(items)
        out["store_bytes"] = intent.stat().st_size
        return out
    mem_jsonl = run_dir / f"{stem}.memory.jsonl"
    if mem_jsonl.is_file():
        out["store_bytes"] = mem_jsonl.stat().st_size
    return out


def _step_count(run_dir: Path, stem: str) -> int:
    path = run_dir / f"{stem}.jsonl"
    n = 0
    for row in _load_jsonl(path):
        if row.get("action") or row.get("choice") or row.get("task_ids") is not None:
            n += 1
    return n


def summarize_run(run_dir: Path) -> dict:
    stem = run_dir.name
    jsonl = run_dir / f"{stem}.cost.jsonl"
    events = _load_jsonl(jsonl)
    load_events(events)
    data = summary_from_events(wall_seconds=0.0)
    score = _score_fields(run_dir / f"{stem}.score.md")
    store = _store_size(run_dir, stem)
    steps = _step_count(run_dir, stem) or None
    wall = score["duration_s"] or data.get("wall_seconds")
    billed = data.get("chat_billed") or {}
    chat = data.get("chat") or {}
    if steps and billed.get("total_tokens"):
        data["tokens_per_step"] = round(billed["total_tokens"] / steps, 1)
        data["calls_per_step"] = round((billed.get("calls") or 0) / steps, 2)
    if steps and wall:
        data["seconds_per_step"] = round(float(wall) / steps, 2)
    data["pm_steps"] = steps
    data["state_queries"] = score["state_queries"]
    data["check_time"] = score["check_time"]
    data["set_f1"] = score["set_f1"]
    data["score_duration_s"] = score["duration_s"]
    data["memory_items"] = store["memories"]
    data["store_bytes"] = store["store_bytes"]
    data["peak_prompt_tokens"] = chat.get("prompt_tokens_peak")
    return data


def markdown_table(rows: list[dict]) -> str:
    headers = [
        "Setup",
        "LLM calls",
        "Prompt tok",
        "Completion tok",
        "Total tok (API)",
        "Choose tok",
        "Memory tok",
        "Local tok",
        "Embed tok",
        "Peak ctx",
        "Tok/step",
        "Calls/step",
        "Wall (s)",
        "s/step",
        "p50 / p95 (ms)",
        "state / clock",
        "Mem items",
        "USD off-peak",
        "Set-F1",
    ]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        billed = r.get("chat_billed") or {}
        choose = r.get("choose") or {}
        mem = r.get("memory_chat") or {}
        local = r.get("chat_local") or {}
        embed = r.get("embed") or {}
        chat = r.get("chat") or {}
        lat = f"{chat.get('latency_ms_p50', 0):.0f} / {chat.get('latency_ms_p95', 0):.0f}"
        mon = f"{r.get('state_queries') if r.get('state_queries') is not None else '—'} / {r.get('check_time') if r.get('check_time') is not None else '—'}"
        f1 = f"{r.get('set_f1'):.1f}%" if r.get("set_f1") is not None else "—"
        wall = r.get("score_duration_s") or r.get("wall_seconds")
        lines.append(
            "| "
            + " | ".join(
                [
                    str(r.get("setup") or r.get("run") or ""),
                    str(billed.get("calls") or 0),
                    f"{billed.get('prompt_tokens') or 0:,}",
                    f"{billed.get('completion_tokens') or 0:,}",
                    f"{billed.get('total_tokens') or 0:,}",
                    f"{choose.get('total_tokens') or 0:,}",
                    f"{mem.get('total_tokens') or 0:,}",
                    f"{local.get('total_tokens') or 0:,}",
                    f"{embed.get('total_tokens') or 0:,}",
                    f"{r.get('peak_prompt_tokens') or 0:,}",
                    str(r.get("tokens_per_step") or "—"),
                    str(r.get("calls_per_step") or "—"),
                    f"{wall:.1f}" if wall else "—",
                    str(r.get("seconds_per_step") or "—"),
                    lat,
                    mon,
                    str(r.get("memory_items") if r.get("memory_items") is not None else "—"),
                    f"${r.get('usd_flash_offpeak'):.3f}"
                    if r.get("usd_flash_offpeak") is not None
                    else "—",
                    f1,
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/PMBench/runs/cost"
    runs = sorted(p for p in root.rglob("*.cost.jsonl") if p.is_file())
    if not runs:
        print(f"no *.cost.jsonl under {root}", file=sys.stderr)
        return 1
    rows = []
    for path in runs:
        data = summarize_run(path.parent)
        data["setup"] = path.parent.name.split("-")[0] if "-" in path.parent.name else path.parent.name
        # run dir: single-baseline-... / mem0-... / amem-... / intention-...
        name = path.parent.name
        if name.startswith("single-baseline"):
            data["setup"] = "baseline"
        elif name.startswith("mem0"):
            data["setup"] = "Mem0"
        elif name.startswith("amem"):
            data["setup"] = "A-Mem"
        elif name.startswith("intention"):
            data["setup"] = "PIS v6.2"
        data["run"] = name
        rows.append(data)
    print(markdown_table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
