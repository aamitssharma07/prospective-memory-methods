#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SIM_ROOT = Path(__file__).resolve().parent
for path in (str(PROJECT_ROOT), str(SIM_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import pm_bench as PM_BENCH
import run_hierarchical_agent as HIER_BASELINE
import run_hierarchical_agent_union_query as HIER_UNION
import run_todo_ledger as TODO_LEDGER
import analyze_run as ANALYZE


SETUP_CHOICES = [
    "single_baseline",
    "todo_ledger",
    "single_heartbeat",
    "multi_baseline",
    "multi_union_query",
    "multi_majority_vote",
]

HEARTBEAT_MODE_CHOICES = ["optional", "auto30", "auto60"]


def parse_agent_roles(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    roles = [item.strip() for item in raw.split(",") if item.strip()]
    return roles or None


def sanitize_model_label(model: str) -> str:
    safe = model.strip().lower()
    for src, dst in (
        ("openai/", ""),
        ("anthropic/", ""),
        ("google/", ""),
        ("mistralai/", ""),
        ("meta-llama/", ""),
        ("qwen/", ""),
        ("moonshotai/", ""),
        ("z-ai/", ""),
        ("deepseek/", ""),
        ("alibaba/", ""),
    ):
        if safe.startswith(src):
            safe = safe[len(src):]
            break
    safe = safe.replace("/", "-").replace(":", "-").replace(" ", "-").replace(".", "")
    return safe


def canonical_setup_label(args: argparse.Namespace) -> str:
    if args.setup == "single_baseline":
        return "single-baseline"
    if args.setup == "todo_ledger":
        return "single-todo-ledger"
    if args.setup == "single_heartbeat":
        if args.heartbeat_mode == "optional":
            return "heartbeat-proactive"
        if args.heartbeat_mode == "auto30":
            return "heartbeat-auto-30m"
        if args.heartbeat_mode == "auto60":
            return "heartbeat-auto-60m"
    if args.setup == "multi_baseline":
        return "hier-baseline"
    if args.setup == "multi_union_query":
        return "hier-union-query"
    if args.setup == "multi_majority_vote":
        return "hier-majority-vote"
    return args.setup.replace("_", "-")


def build_run_paths(args: argparse.Namespace) -> dict[str, str]:
    root_dir = Path(args.out_dir).expanduser()
    if not root_dir.is_absolute():
        root_dir = PROJECT_ROOT / root_dir
    root_dir = root_dir.resolve()
    root_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    model_dir = root_dir / sanitize_model_label(args.model)
    model_dir.mkdir(parents=True, exist_ok=True)
    run_name = f"{canonical_setup_label(args)}-{sanitize_model_label(args.model)}-v9-{timestamp}"
    run_dir = model_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "run_name": run_name,
        "model_dir": str(model_dir),
        "run_dir": str(run_dir),
        "log": str(run_dir / f"{run_name}.jsonl"),
        "score": str(run_dir / f"{run_name}.score.md"),
        "prompt": str(run_dir / f"{run_name}.prompt.txt"),
        "prompt_log": str(run_dir / f"{run_name}.prompt.log"),
        "debug": str(run_dir / f"{run_name}.debug.jsonl"),
        "ledger": str(run_dir / f"{run_name}.ledger.jsonl"),
        "checkpoint": str(run_dir / f"{run_name}.checkpoint.json"),
        "memory_dir": str(run_dir),
    }
    return paths


def resolve_hier_memory_dir(memory_dir: str | None, default_dir: str) -> str:
    candidate = Path(memory_dir).expanduser() if memory_dir else Path(default_dir)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return str(candidate.resolve())


def resolve_backend_args(args: argparse.Namespace) -> tuple[str, str | None, str | None]:
    if args.backend == "openrouter":
        return (
            "openrouter",
            args.base_url or "https://openrouter.ai/api/v1",
            args.api_key or PM_BENCH.load_openrouter_api_key(),
        )
    return (
        "sglang",
        args.base_url or "http://127.0.0.1:30002/v1",
        args.api_key,
    )


def score_and_write_report(
    scenario: dict,
    scenario_path: str,
    resolved_log_path: str,
    log_entries: list[dict] | None = None,
    run_metadata: dict | None = None,
) -> None:
    if log_entries is None or run_metadata is None:
        log_entries, run_metadata = PM_BENCH.read_log_with_metadata(resolved_log_path)
    summary, per_day, summary_steps = PM_BENCH.score_log(scenario, log_entries)
    PM_BENCH.print_report(summary, per_day, summary_steps, run_metadata=run_metadata)
    report_md = PM_BENCH.build_markdown_report(
        summary, per_day, summary_steps, run_metadata=run_metadata
    )
    report_path = str(Path(resolved_log_path).with_suffix(".score.md"))
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(report_md)
    ANALYZE.analyze(
        Path(scenario_path),
        Path(resolved_log_path),
        Path(resolved_log_path).parent,
    )
    print(f"Wrote score report: {report_path}")


def run_single_baseline(
    args: argparse.Namespace,
    scenario: dict,
    backend: str,
    base_url: str | None,
    api_key: str | None,
    paths: dict[str, str],
) -> tuple[list[dict], str, dict | None]:
    resolved_log_path = args.log or paths["log"]
    log_entries = PM_BENCH.run_llm(
        scenario,
        resolved_log_path,
        args.model,
        args.env,
        args.max_time_requests,
        backend,
        base_url,
        api_key,
        prompt_log_path=args.prompt_log or paths["prompt"],
        show_task_legend=args.task_legend,
        out_dir=None,
        enable_heartbeat=False,
        auto_heartbeat_minutes=None,
        heartbeat_message_mode=args.heartbeat_message_mode,
        max_tokens=args.max_tokens,
        checkpoint_path=args.checkpoint or paths["checkpoint"],
        resume=args.resume,
    )
    _, run_metadata = PM_BENCH.read_log_with_metadata(resolved_log_path)
    return log_entries, resolved_log_path, run_metadata


def run_single_heartbeat(
    args: argparse.Namespace,
    scenario: dict,
    backend: str,
    base_url: str | None,
    api_key: str | None,
    paths: dict[str, str],
) -> tuple[list[dict], str, dict | None]:
    resolved_log_path = args.log or paths["log"]
    auto_minutes = None
    enable_heartbeat = False
    if args.heartbeat_mode == "optional":
        enable_heartbeat = True
    elif args.heartbeat_mode == "auto30":
        auto_minutes = 30
    elif args.heartbeat_mode == "auto60":
        auto_minutes = 60
    else:
        raise SystemExit(f"Unsupported heartbeat mode: {args.heartbeat_mode}")
    log_entries = PM_BENCH.run_llm(
        scenario,
        resolved_log_path,
        args.model,
        args.env,
        args.max_time_requests,
        backend,
        base_url,
        api_key,
        prompt_log_path=args.prompt_log or paths["prompt"],
        show_task_legend=args.task_legend,
        out_dir=None,
        enable_heartbeat=enable_heartbeat,
        auto_heartbeat_minutes=auto_minutes,
        heartbeat_message_mode=args.heartbeat_message_mode,
        max_tokens=args.max_tokens,
        checkpoint_path=args.checkpoint or paths["checkpoint"],
        resume=args.resume,
    )
    _, run_metadata = PM_BENCH.read_log_with_metadata(resolved_log_path)
    return log_entries, resolved_log_path, run_metadata


def run_todo_ledger(
    args: argparse.Namespace,
    scenario: dict,
    backend: str,
    base_url: str | None,
    api_key: str | None,
    paths: dict[str, str],
) -> tuple[list[dict], str, dict]:
    return TODO_LEDGER.run_todo_ledger(
        scenario=scenario,
        log_path=args.log or paths["log"],
        model=args.model,
        backend=backend,
        base_url=base_url,
        api_key=api_key,
        max_time_requests=args.max_time_requests,
        prompt_log_path=args.prompt_log or paths["prompt"],
        ledger_log_path=args.ledger_log or paths["ledger"],
        show_task_legend=args.task_legend,
        max_invalid_retries=args.max_invalid_retries,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        max_context_tokens=args.max_context_tokens,
        out_dir=None,
        checkpoint_path=args.checkpoint or paths["checkpoint"],
        resume=args.resume,
    )


def run_multi_baseline(
    args: argparse.Namespace,
    scenario: dict,
    backend: str,
    base_url: str | None,
    api_key: str | None,
    paths: dict[str, str],
) -> tuple[list[dict], str, dict]:
    return HIER_BASELINE.run_hierarchical_agent(
        scenario=scenario,
        log_path=args.log or paths["log"],
        model=args.model,
        backend=backend,
        base_url=base_url,
        api_key=api_key,
        num_subagents=args.num_subagents,
        agent_roles=parse_agent_roles(args.agent_roles),
        memory_dir=resolve_hier_memory_dir(args.memory_dir, paths["run_dir"]),
        max_time_requests=args.max_time_requests,
        max_invalid_retries=args.max_invalid_retries,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        request_timeout_seconds=args.request_timeout_seconds,
        prompt_log_path=args.prompt_log or paths["prompt_log"],
        debug_log_path=args.debug_log or paths["debug"],
        verbose_subagents=args.verbose_subagents,
        debug_log_subagent_events=args.debug_log_subagent_events,
        score_each_day=args.score,
    )


def run_multi_union_query(
    args: argparse.Namespace,
    scenario: dict,
    backend: str,
    base_url: str | None,
    api_key: str | None,
    paths: dict[str, str],
) -> tuple[list[dict], str, dict]:
    return HIER_UNION.run_hierarchical_agent(
        scenario=scenario,
        log_path=args.log or paths["log"],
        model=args.model,
        backend=backend,
        base_url=base_url,
        api_key=api_key,
        num_subagents=args.num_subagents,
        agent_roles=parse_agent_roles(args.agent_roles),
        memory_dir=resolve_hier_memory_dir(args.memory_dir, paths["run_dir"]),
        max_time_requests=args.max_time_requests,
        max_invalid_retries=args.max_invalid_retries,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        request_timeout_seconds=args.request_timeout_seconds,
        prompt_log_path=args.prompt_log or paths["prompt_log"],
        debug_log_path=args.debug_log or paths["debug"],
        verbose_subagents=args.verbose_subagents,
        debug_log_subagent_events=args.debug_log_subagent_events,
        score_each_day=args.score,
        enable_tasks_should_not_select=not args.disable_tasks_should_not_select,
        decision_mode=args.decision_mode,
    )


def run_multi_majority_vote(
    args: argparse.Namespace,
    scenario: dict,
    backend: str,
    base_url: str | None,
    api_key: str | None,
    paths: dict[str, str],
) -> tuple[list[dict], str, dict]:
    return HIER_UNION.run_hierarchical_agent(
        scenario=scenario,
        log_path=args.log or paths["log"],
        model=args.model,
        backend=backend,
        base_url=base_url,
        api_key=api_key,
        num_subagents=args.num_subagents,
        agent_roles=parse_agent_roles(args.agent_roles),
        memory_dir=resolve_hier_memory_dir(args.memory_dir, paths["run_dir"]),
        max_time_requests=args.max_time_requests,
        max_invalid_retries=args.max_invalid_retries,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        prompt_log_path=args.prompt_log or paths["prompt_log"],
        debug_log_path=args.debug_log or paths["debug"],
        verbose_subagents=args.verbose_subagents,
        debug_log_subagent_events=args.debug_log_subagent_events,
        score_each_day=args.score,
        enable_tasks_should_not_select=not args.disable_tasks_should_not_select,
        decision_mode="task_vote_only",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified PM-Bench evaluation runner.")
    parser.add_argument("--setup", choices=SETUP_CHOICES, required=True)
    parser.add_argument(
        "--scenario",
        default=str(PROJECT_ROOT / "data" / "synthetic_week_v9.json"),
        help="Scenario JSON path.",
    )
    parser.add_argument("--model", required=True, help="Model ID to run.")
    parser.add_argument(
        "--backend",
        choices=["openrouter", "sglang"],
        required=True,
        help="Inference backend to use.",
    )
    parser.add_argument(
        "--log",
        default=None,
        help="Output action log path (.jsonl).",
    )
    parser.add_argument(
        "--out-dir",
        "--output-dir",
        dest="out_dir",
        default=str(PROJECT_ROOT / "runs" / "local"),
        help="Root directory for generated run folders.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override the backend base URL.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Override the backend API key.",
    )
    parser.add_argument("--env", default=".env", help="Env path for pm_bench.run_llm compatibility.")
    parser.add_argument("--prompt-log", default=None)
    parser.add_argument("--debug-log", default=None)
    parser.add_argument("--ledger-log", default=None)
    parser.add_argument("--checkpoint", default=None, help="Exact-resume checkpoint path.")
    parser.add_argument("--resume", action="store_true", help="Resume from --checkpoint.")
    parser.add_argument("--memory-dir", default=None)
    parser.add_argument("--task-legend", action="store_true", dest="task_legend", default=False)
    parser.add_argument("--score", action="store_true", help="Score the run and write <log>.score.md.")
    parser.add_argument("--max-time-requests", type=int, default=5)
    parser.add_argument("--max-invalid-retries", type=int, default=2)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=768)
    parser.add_argument("--request-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--max-context-tokens", type=int, default=32000)

    parser.add_argument(
        "--heartbeat-mode",
        choices=HEARTBEAT_MODE_CHOICES,
        default="optional",
        help="For --setup single_heartbeat: optional, auto30, or auto60.",
    )
    parser.add_argument(
        "--heartbeat-message-mode",
        choices=list(PM_BENCH.HEARTBEAT_MESSAGE_MODES),
        default="channel_query",
        help="Heartbeat prompt style for single_heartbeat runs.",
    )

    parser.add_argument("--num-subagents", type=int, default=3)
    parser.add_argument(
        "--agent-roles",
        default=None,
        help="Comma-separated subagent role names.",
    )
    parser.add_argument("--verbose-subagents", action="store_true")
    parser.add_argument("--debug-log-subagent-events", action="store_true")
    parser.add_argument(
        "--decision-mode",
        choices=["coordinator_only", "task_vote_only", "vote_plus_coordinator"],
        default="coordinator_only",
        help=(
            "Only used by --setup multi_union_query. "
            "--setup multi_majority_vote always uses task_vote_only."
        ),
    )
    parser.add_argument(
        "--disable-tasks-should-not-select",
        dest="disable_tasks_should_not_select",
        action="store_true",
        default=True,
        help=(
            "Only used by --setup multi_union_query and multi_majority_vote. "
            "Disable tasks_should_not_select (default: disabled)."
        ),
    )
    parser.add_argument(
        "--enable-tasks-should-not-select",
        dest="disable_tasks_should_not_select",
        action="store_false",
        help=(
            "Only used by --setup multi_union_query and multi_majority_vote. "
            "Enable tasks_should_not_select."
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    scenario = PM_BENCH.load_scenario(args.scenario)
    backend, base_url, api_key = resolve_backend_args(args)
    paths = build_run_paths(args)

    if args.setup == "single_baseline":
        log_entries, resolved_log_path, run_metadata = run_single_baseline(
            args, scenario, backend, base_url, api_key, paths
        )
    elif args.setup == "todo_ledger":
        log_entries, resolved_log_path, run_metadata = run_todo_ledger(
            args, scenario, backend, base_url, api_key, paths
        )
    elif args.setup == "single_heartbeat":
        log_entries, resolved_log_path, run_metadata = run_single_heartbeat(
            args, scenario, backend, base_url, api_key, paths
        )
    elif args.setup == "multi_baseline":
        log_entries, resolved_log_path, run_metadata = run_multi_baseline(
            args, scenario, backend, base_url, api_key, paths
        )
    elif args.setup == "multi_union_query":
        log_entries, resolved_log_path, run_metadata = run_multi_union_query(
            args, scenario, backend, base_url, api_key, paths
        )
    elif args.setup == "multi_majority_vote":
        log_entries, resolved_log_path, run_metadata = run_multi_majority_vote(
            args, scenario, backend, base_url, api_key, paths
        )
    else:
        raise SystemExit(f"Unsupported setup: {args.setup}")

    if args.score:
        score_and_write_report(
            scenario,
            args.scenario,
            resolved_log_path,
            log_entries=log_entries,
            run_metadata=run_metadata,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
