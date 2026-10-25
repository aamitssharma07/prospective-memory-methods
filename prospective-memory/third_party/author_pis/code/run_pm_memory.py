#!/usr/bin/env python3
"""
CLI: run PM-Bench with baseline / A-Mem / Mem0 / intention / PMA /
official todo-ledger / heartbeat scaffolds.

API key / base_url / model are loaded from repo-root `.env` (see `.env.example`).
CLI flags override the file. Swap models without editing Python:

  python code/run_pm_memory.py --list-providers
  python code/run_pm_memory.py --provider deepseek --setup intention
  python code/run_pm_memory.py --provider qwen --model qwen3.5-397b --setup baseline
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "code"
PMBENCH = ROOT / "data" / "PMBench"
RUNS = PMBENCH / "runs"
THIRD = ROOT / "third_party"

for p in (str(CODE), str(THIRD / "mem0-main"), str(PMBENCH / "sim")):
    if p not in sys.path:
        sys.path.insert(0, p)

from llm_cost import format_summary, reset as reset_cost, write_summary
from llm_env import (
    format_provider_list,
    install_model_chat_extras,
    load_dotenv_files,
    resolve_llm,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PM-Bench × A-Mem / Mem0 runner")
    p.add_argument(
        "--provider",
        default=None,
        help="LLM vendor name (qwen, deepseek, or any NAME_* in .env). "
        "Falls back to DEFAULT_PROVIDER.",
    )
    p.add_argument(
        "--list-providers",
        action="store_true",
        help="Print configured providers from .env and exit.",
    )
    p.add_argument(
        "--setup",
        choices=[
            "baseline",
            "amem",
            "mem0",
            "intention",
            "pma",
            "todo_ledger",
            "heartbeat",
        ],
        default=None,
        help="intention = structured prospective intention store; "
        "pma = Proactive Memory Agent (Wu et al. 2026); "
        "todo_ledger / heartbeat = official PM-Bench scaffolds. "
        "Required unless --list-providers.",
    )
    p.add_argument("--model", default=None, help="Override <PROVIDER>_MODEL from .env")
    p.add_argument("--base-url", default=None, help="Override <PROVIDER>_BASE_URL from .env")
    p.add_argument("--api-key", default=None, help="Override <PROVIDER>_API_KEY from .env")
    p.add_argument(
        "--response-format",
        default=None,
        choices=["json_schema", "json_object", "none"],
        help="Override <PROVIDER>_RESPONSE_FORMAT (default: json_schema for qwen, "
        "json_object otherwise).",
    )
    p.add_argument("--out-dir", default=None)
    p.add_argument("--scenario", default=str(PMBENCH / "data" / "synthetic_week_v9.json"))
    p.add_argument("--max-tokens", type=int, default=1024)
    p.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Memory retrieve top-k (A-Mem: paper hits + ≤k link neighbors each)",
    )
    p.add_argument(
        "--max-inject-chars",
        type=int,
        default=8000,
        help="Safety cap on injected memory text (paper A-Mem includes context/keywords/tags)",
    )
    p.add_argument(
        "--amem-max-note-chars",
        type=int,
        default=280,
        help="Deprecated no-op (kept for CLI compat); paper recall no longer truncates per note",
    )
    p.add_argument("--evo-threshold", type=int, default=100, help="A-Mem consolidate threshold")
    p.add_argument("--no-amem-keyword-query", action="store_true")
    p.add_argument("--no-score", action="store_true")
    p.add_argument(
        "--use-qwen-embed",
        action="store_true",
        help="Mem0: use Aliyun Qwen embedding endpoint (env-overridable).",
    )
    p.add_argument(
        "--keep-full-history",
        action="store_true",
        help="Memory setups: also send full-week chat history (legacy). "
        "Default is current-step context + retrieved memories only.",
    )
    p.add_argument(
        "--no-intention-llm-update",
        action="store_true",
        help="Intention setup: disable the Update Judge (add / cancel / "
        "reschedule / override). There is no keyword fallback.",
    )
    p.add_argument(
        "--no-intention-llm-channel-expiry",
        action="store_true",
        help="Deprecated no-op; channel observations are no longer stored.",
    )
    p.add_argument(
        "--no-intention-llm-extract",
        action="store_true",
        help="Intention setup: alias of --no-intention-llm-update (extract is "
        "merged into the Update Judge). Day-plan bullets still use regex.",
    )
    p.add_argument(
        "--no-intention-llm-match",
        action="store_true",
        help="Intention setup: disable event-string similarity filter; inject "
        "all today pending (event/channel not filtered). Default is on.",
    )
    p.add_argument(
        "--no-force-check-time",
        action="store_true",
        help="Intention setup: do not override choose→check_time when clock is "
        "unknown but pending time intentions exist.",
    )
    p.add_argument(
        "--force-query-channels",
        action="store_true",
        help="Intention ablation: override choose to query_state CHECK channels "
        "that are still unqueried this step (cheating-adjacent).",
    )
    p.add_argument(
        "--gate-time-due",
        action="store_true",
        help="Intention ablation: drop menu task_ids that match TIME-WAIT, "
        "so clock tasks can only be performed when TIME-DUE.",
    )
    p.add_argument(
        "--intention-retrieval",
        choices=["due", "similarity", "source"],
        default="due",
        help="Intention recall path. due (default) = TIME-DUE / event / CHECK "
        "on typed fields (main experiment). similarity = Mem0-style "
        "embed+BM25 top-k (PIS-RAG). source = same due predicates on the "
        "planting/rewrite sentence, not due/event_cue/watch fields "
        "(NL-due ablation). Isolated from the main intention run tree.",
    )
    p.add_argument(
        "--no-intention-status",
        action="store_true",
        help="Intention ablation: do not write done/canceled. Due retrieval "
        "still filters by time and event. Seed/Update add+reschedule/"
        "override unchanged. Isolated from the main intention run tree.",
    )
    p.add_argument(
        "--heartbeat-mode",
        choices=["optional", "auto30", "auto60"],
        default="optional",
        help="For --setup heartbeat: optional (model may set_heartbeat), "
        "or auto30 / auto60 fixed-interval wakes.",
    )
    p.add_argument(
        "--pma-interval",
        type=int,
        default=1,
        help="PMA: run the two-phase memory agent every N decision requests "
        "(paper default: every turn).",
    )
    return p.parse_args()


def _safe_model(model: str) -> str:
    return model.replace("/", "-").replace(":", "-").replace(" ", "-")


def _isolate_intention_out_dir(out_dir: str, *, folder: str) -> str:
    """Keep ablation artifacts out of the main intention run tree."""
    p = Path(out_dir)
    if folder in p.parts:
        return str(p)
    parts = list(p.parts)
    for i, part in enumerate(parts):
        if part == "intention":
            parts[i] = folder
            return str(Path(*parts))
    return str(RUNS / folder / p.name)


def _isolate_rag_out_dir(out_dir: str) -> str:
    """Keep PIS-RAG artifacts out of the main intention run tree."""
    return _isolate_intention_out_dir(out_dir, folder="intention_rag")


def _prepare_qwen_embed_env() -> None:
    """Require MEM0_EMBED_API_KEY from .env; only fill non-secret defaults."""
    if not os.environ.get("MEM0_EMBED_API_KEY"):
        raise SystemExit(
            "Mem0 Qwen embedding needs MEM0_EMBED_API_KEY in .env "
            "(see .env.example; also MEM0_EMBED_BASE_URL / MEM0_EMBED_MODEL)."
        )
    os.environ.setdefault(
        "MEM0_EMBED_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    os.environ.setdefault("MEM0_EMBED_MODEL", "text-embedding-v3")
    os.environ.setdefault("MEM0_EMBED_DIMS", "1536")


def main() -> int:
    load_dotenv_files()
    args = parse_args()
    if args.list_providers:
        print(format_provider_list())
        return 0
    if not args.setup:
        raise SystemExit(
            "Missing --setup (baseline | amem | mem0 | intention | pma | "
            "todo_ledger | heartbeat)."
        )

    provider = args.provider or os.environ.get("DEFAULT_PROVIDER")
    cfg = resolve_llm(
        provider,
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
        response_format=args.response_format,
        out_dir=args.out_dir,
        runs_dir=RUNS,
    )
    model = cfg["model"]
    base_url = cfg["base_url"]
    api_key = cfg["api_key"]
    out_dir = cfg["out_dir"]
    response_format = cfg["response_format"]
    args.provider = cfg["name"]
    thinking_extra = install_model_chat_extras(model)

    import pm_bench as PM_BENCH

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_prefix = {
        "baseline": "single-baseline",
        "amem": "amem",
        "mem0": "mem0",
        "intention": "intention",
        "pma": "pma",
        "todo_ledger": "single-todo-ledger",
        "heartbeat": {
            "optional": "heartbeat-proactive",
            "auto30": "heartbeat-auto-30m",
            "auto60": "heartbeat-auto-60m",
        }[args.heartbeat_mode],
    }[args.setup]
    if args.setup == "intention" and args.intention_retrieval == "similarity":
        run_prefix = "intention-rag"
        out_dir = _isolate_rag_out_dir(out_dir)
    if args.setup == "intention" and args.intention_retrieval == "source":
        run_prefix = "intention-source"
        out_dir = _isolate_intention_out_dir(out_dir, folder="intention_source")
    if args.setup == "intention" and args.no_intention_status:
        run_prefix = "intention-nostatus"
        out_dir = _isolate_intention_out_dir(out_dir, folder="intention_nostatus")
    scenario_stem = Path(args.scenario).stem
    version_tag = "v10" if "month" in scenario_stem.lower() else "v9"
    run_name = f"{run_prefix}-{_safe_model(model)}-{version_tag}-{timestamp}"
    run_dir = Path(out_dir) / _safe_model(model) / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    reset_cost(run_dir / f"{run_name}.cost.jsonl")

    print(f"provider={cfg['label']} model={model} setup={args.setup}")
    print(f"out={run_dir}")
    if thinking_extra:
        print(f"chat extra_body={thinking_extra}")

    session_cm = None
    if args.setup == "amem":
        from pm_memory.amem import build_amem_backend
        from pm_memory.session import MemorySession, install_memory_session

        backend = build_amem_backend(
            model=model,
            api_key=api_key,
            base_url=base_url,
            top_k=args.top_k,
            evo_threshold=args.evo_threshold,
            use_keyword_query=not args.no_amem_keyword_query,
            max_inject_chars=args.max_inject_chars,
        )
        session = MemorySession(
            backend,
            top_k=args.top_k,
            log_path=str(run_dir / f"{run_name}.memory.jsonl"),
            keep_full_history=args.keep_full_history,
        )
        session_cm = install_memory_session(PM_BENCH, session)
    elif args.setup == "mem0":
        from pm_memory.mem0_backend import build_mem0_backend
        from pm_memory.session import MemorySession, install_memory_session

        # DeepSeek's OpenAI-compatible gateway is not a reliable embedder for
        # Mem0 (and fact extraction often returns []). Prefer the known-good
        # Qwen embedding endpoint unless the caller already set MEM0_EMBED_*.
        auto_qwen_embed = args.provider == "deepseek" and not os.environ.get("MEM0_EMBED_BASE_URL")
        if (
            args.use_qwen_embed
            or auto_qwen_embed
            or os.environ.get("MEM0_USE_QWEN_EMBED", "").lower() in ("1", "true", "yes")
        ):
            _prepare_qwen_embed_env()
        backend = build_mem0_backend(
            provider_key=args.provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            out_dir=out_dir,
            user_id=f"{args.provider}_mem0",
            top_k=args.top_k,
            max_inject_chars=args.max_inject_chars,
        )
        session = MemorySession(
            backend,
            top_k=args.top_k,
            log_path=str(run_dir / f"{run_name}.memory.jsonl"),
            keep_full_history=args.keep_full_history,
        )
        session_cm = install_memory_session(PM_BENCH, session)
    elif args.setup == "intention":
        from pm_memory.intention_store import build_intention_backend
        from pm_memory.session import MemorySession, install_memory_session

        rag_mode = args.intention_retrieval == "similarity"
        source_mode = args.intention_retrieval == "source"
        embed_fn = None
        if rag_mode:
            auto_qwen_embed = args.provider == "deepseek" and not os.environ.get(
                "MEM0_EMBED_BASE_URL"
            )
            if (
                args.use_qwen_embed
                or auto_qwen_embed
                or os.environ.get("MEM0_USE_QWEN_EMBED", "").lower()
                in ("1", "true", "yes")
            ):
                _prepare_qwen_embed_env()
            from pm_memory.intention_rag import embedder_from_mem0_env

            embed_fn = embedder_from_mem0_env()
            if embed_fn is None:
                print(
                    "intention_retrieval=similarity: no MEM0_EMBED_API_KEY/"
                    "BASE_URL; ranking with BM25 only"
                )
        backend = build_intention_backend(
            store_path=str(run_dir / f"{run_name}.intentions.json"),
            max_inject_chars=args.max_inject_chars,
            model=model,
            api_key=api_key,
            base_url=base_url,
            use_llm_update=not (
                args.no_intention_llm_update or args.no_intention_llm_extract
            ),
            use_llm_extract=not (
                args.no_intention_llm_update or args.no_intention_llm_extract
            ),
            use_llm_match=not args.no_intention_llm_match,
            use_llm_cadence=False,
            gate_time_due=False if rag_mode else args.gate_time_due,
            force_query_channels=False if rag_mode else args.force_query_channels,
            response_format=response_format,
            retrieval_mode=(
                "similarity" if rag_mode else "source" if source_mode else "due"
            ),
            embed_fn=embed_fn,
            ignore_status=args.no_intention_status,
            llm_timeout=float(os.environ.get("PM_LLM_TIMEOUT", "3600")),
        )
        print(
            "intention_retrieval="
            + getattr(backend, "retrieval_mode", "due")
            + " intention_llm_update="
            + ("on" if getattr(backend, "use_llm_update", False) else "off")
            + " intention_llm_extract="
            + ("on" if getattr(backend, "use_llm_extract", False) else "off")
            + " intention_llm_done="
            + ("on" if getattr(backend, "use_llm_done", False) else "off")
            + " intention_llm_match="
            + ("on" if getattr(backend, "use_llm_match", False) else "off")
            + " intention_llm_cadence="
            + ("on" if getattr(backend, "use_llm_cadence", False) else "off")
            + " intention_llm_rewrite="
            + ("on" if getattr(backend, "use_llm_rewrite", False) else "off")
            + " force_check_time="
            + (
                "off"
                if rag_mode or args.no_force_check_time
                else "on"
            )
            + " force_query_channels="
            + ("on" if (args.force_query_channels and not rag_mode) else "off")
            + " gate_time_due="
            + ("on" if (args.gate_time_due and not rag_mode) else "off")
            + " ignore_status="
            + ("on" if args.no_intention_status else "off")
            + " rag_embed="
            + ("on" if embed_fn is not None else "off")
            + " judge_format="
            + response_format
            + " extra_body="
            + (str(thinking_extra) if thinking_extra else "default")
        )
        session = MemorySession(
            backend,
            top_k=args.top_k,
            log_path=str(run_dir / f"{run_name}.memory.jsonl"),
            keep_full_history=args.keep_full_history,
            force_check_time=False if rag_mode else (not args.no_force_check_time),
            force_query_channels=False if rag_mode else args.force_query_channels,
            gate_time_due=False if rag_mode else args.gate_time_due,
        )
        session_cm = install_memory_session(PM_BENCH, session)
    elif args.setup == "pma":
        from pm_memory.pma import build_pma_backend
        from pm_memory.session import MemorySession, install_memory_session

        backend = build_pma_backend(
            model=model,
            api_key=api_key,
            base_url=base_url,
            max_inject_chars=args.max_inject_chars,
            interval=args.pma_interval,
        )
        print(f"pma_interval={args.pma_interval}")
        session = MemorySession(
            backend,
            top_k=args.top_k,
            log_path=str(run_dir / f"{run_name}.memory.jsonl"),
            keep_full_history=args.keep_full_history,
            force_check_time=False,
        )
        session_cm = install_memory_session(PM_BENCH, session)

    scenario = PM_BENCH.load_scenario(args.scenario)
    log_path = str(run_dir / f"{run_name}.jsonl")
    prompt_log = str(run_dir / f"{run_name}.prompt.txt")

    enable_heartbeat = False
    auto_heartbeat_minutes = None
    if args.setup == "heartbeat":
        if args.heartbeat_mode == "optional":
            enable_heartbeat = True
        elif args.heartbeat_mode == "auto30":
            auto_heartbeat_minutes = 30
        elif args.heartbeat_mode == "auto60":
            auto_heartbeat_minutes = 60
        print(
            f"heartbeat_mode={args.heartbeat_mode} "
            f"enable={enable_heartbeat} auto_minutes={auto_heartbeat_minutes}"
        )

    if args.setup == "todo_ledger":
        import run_todo_ledger as TODO_LEDGER

        # Official ledger runner hardcodes json_schema (sglang). DeepSeek etc.
        # only accept json_object — patch without editing PM-Bench sources.
        if response_format != "json_schema":
            _orig_todo_call = TODO_LEDGER._call_model

            def _todo_call_json_object(
                client,
                model,
                messages,
                backend,
                temperature,
                max_tokens,
                response_schema,
            ):
                if backend != "sglang":
                    return _orig_todo_call(
                        client,
                        model,
                        messages,
                        backend,
                        temperature,
                        max_tokens,
                        response_schema,
                    )
                kwargs = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "response_format": {"type": "json_object"},
                }
                response = client.chat.completions.create(**kwargs)
                raw = PM_BENCH.extract_chat_text(response)
                if raw is None or not str(raw).strip():
                    raise ValueError("Empty todo-ledger response")
                return raw

            TODO_LEDGER._call_model = _todo_call_json_object

        log_entries, log_path, _meta = TODO_LEDGER.run_todo_ledger(
            scenario=scenario,
            log_path=log_path,
            model=model,
            backend="sglang",
            base_url=base_url,
            api_key=api_key,
            max_time_requests=5,
            prompt_log_path=prompt_log,
            ledger_log_path=str(run_dir / f"{run_name}.ledger.jsonl"),
            show_task_legend=False,
            max_invalid_retries=2,
            temperature=0.0,
            max_tokens=args.max_tokens,
            max_context_tokens=32000,
            out_dir=None,
        )
    else:

        def _run():
            return PM_BENCH.run_llm(
                scenario,
                log_path=log_path,
                model=model,
                env_path=None,
                max_time_requests=5,
                backend="sglang",
                base_url=base_url,
                api_key=api_key,
                out_dir=None,
                max_tokens=args.max_tokens,
                response_format_mode=response_format,
                prompt_log_path=prompt_log,
                enable_heartbeat=enable_heartbeat,
                auto_heartbeat_minutes=auto_heartbeat_minutes,
            )

        if session_cm is not None:
            with session_cm:
                log_entries = _run()
        else:
            log_entries = _run()

    meta: dict = {}
    if not args.no_score:
        entries, meta = PM_BENCH.read_log_with_metadata(log_path)
        meta = meta or {}
        if not entries:
            entries = log_entries
        summary, per_day, summary_steps = PM_BENCH.score_log(scenario, entries)
        PM_BENCH.print_report(summary, per_day, summary_steps, run_metadata=meta)
        report = PM_BENCH.build_markdown_report(
            summary, per_day, summary_steps, run_metadata=meta
        )
        score_path = str(run_dir / f"{run_name}.score.md")
        Path(score_path).write_text(report, encoding="utf-8")
        print(f"Wrote score report: {score_path}")
    cost_path = run_dir / f"{run_name}.cost.json"
    cost = write_summary(
        cost_path,
        extra={
            "setup": args.setup,
            "provider": cfg["name"],
            "model": model,
            "run": run_name,
            "out": str(run_dir),
            "score_duration_seconds": meta.get("duration_seconds"),
        },
    )
    print(format_summary(cost))
    print(f"Wrote cost report: {cost_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
