#!/usr/bin/env python3
"""
Run a PM-Bench scenario with an in-context TODO ledger for prospective memory.

This script asks the model to maintain a TODO ledger in its JSON responses.
The ledger is re-injected into the prompt each step to provide a stable
notebook-style memory. Actions are logged in the standard JSONL format so
they can be scored by pm_bench.py.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from datetime import datetime
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
MAX_LEDGER_ITEMS = 5

LEDGER_INSTRUCTIONS = """You must maintain a compact TODO ledger that tracks tasks to do later.
Always return exactly one raw JSON object with keys: action, choice, task_ids, channel, ledger.
The ledger is a list of objects with keys:
- task_id: string (use current action handle like "task_7", not natural-language text)
- when: string (exact time like "11:00", a cue like "cue: breakfast", or "unknown")
- status: "pending", "done", or "canceled"
- notes: short string (optional)

Keep the ledger concise and up to date.
- Hard limit: ledger must contain at most 5 items.
- If there are more than 5 possible reminders, keep the 5 most urgent/likely.
- Keep notes very short (<= 8 words).
- Keep only tasks that still matter; remove completed items immediately.
If a task's exact time is known but the current time is not visible,
use action=check_time to query the current time before deciding.
When you choose actions, task_ids must be action handles from the current step menu.

Do not add extra keys outside the required JSON fields.
Do not include explanations, markdown, or code fences."""

INVALID_RESPONSE_MSG = (
    "Invalid response. Return one raw JSON object only with keys action, choice, task_ids, channel, ledger. "
    "Ledger must contain at most 5 items. "
    "When action=query_state/check_time, choice must be NONE and task_ids must be []. "
    "When action=choose, channel must be NONE."
)

LEDGER_RESET_MSG = (
    "Too many invalid responses. Reset ledger to an empty list [] and continue. "
    "Return a single raw JSON object only with keys action, choice, task_ids, channel, ledger."
)


def _format_ledger(ledger: list[dict[str, Any]]) -> str:
    visible_entries = [entry for entry in ledger if entry.get("status") != "done"][:MAX_LEDGER_ITEMS]
    compact_entries = []
    for entry in visible_entries:
        compact_entries.append(
            {
                "task_id": str(entry.get("task_id", "")),
                "when": str(entry.get("when", "")),
                "status": str(entry.get("status", "pending")),
                "notes": str(entry.get("notes", "")),
            }
        )
    return (
        "TODO Ledger (compact JSON array; edit in-place):\n"
        + json.dumps(compact_entries, ensure_ascii=False, separators=(",", ":"))
    )


def _sanitize_model_label(model: str) -> str:
    return model.replace("/", "-").replace(":", "-").replace(" ", "-")


def _resolve_output_path(
    path: str | None,
    out_dir: str | None,
    default_filename: str | None = None,
    required_suffix: str | None = None,
) -> str | None:
    return PM_BENCH.resolve_output_path(
        path,
        out_dir=out_dir,
        default_filename=default_filename,
        required_suffix=required_suffix,
    )


def _build_response_schema(allowed_ids: list[str], allowed_channels: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["choose", "check_time", "query_state"]},
            "choice": {"type": "string", "enum": ["A", "B", "C", "NONE"]},
            "task_ids": {"type": "array", "items": {"type": "string", "enum": allowed_ids}},
            "channel": {"type": "string", "enum": sorted(set(allowed_channels + ["NONE"]))},
            "ledger": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "when": {"type": "string"},
                        "status": {"type": "string", "enum": ["pending", "done", "canceled"]},
                        "notes": {"type": "string"},
                    },
                    "required": ["task_id", "when", "status", "notes"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["action", "choice", "task_ids", "channel", "ledger"],
        "additionalProperties": False,
    }


def _normalize_ledger(raw_ledger: Any) -> list[dict[str, str]] | None:
    if not isinstance(raw_ledger, list):
        return None
    normalized = []
    for item in raw_ledger:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("task_id", "")).strip()
        if not task_id:
            continue
        when = str(item.get("when", "")).strip()
        status = str(item.get("status", "pending")).strip().lower()
        if status not in ("pending", "done", "canceled"):
            status = "pending"
        notes = " ".join(str(item.get("notes", "")).strip().split())
        if len(notes) > 80:
            notes = notes[:80].rstrip()
        normalized.append(
            {
                "task_id": task_id,
                "when": when,
                "status": status,
                "notes": notes,
            }
        )
    return normalized


def _prune_completed_ledger(ledger: list[dict[str, str]]) -> list[dict[str, str]]:
    return [entry for entry in ledger if entry.get("status") != "done"]


def _validate_payload(
    payload: Any,
    allowed_channels: list[str],
) -> tuple[dict[str, Any] | None, list[dict[str, str]] | None, str | None]:
    if not isinstance(payload, dict):
        return None, None, "payload_not_object"
    action = payload.get("action")
    choice = payload.get("choice")
    task_ids = payload.get("task_ids")
    channel = payload.get("channel")
    raw_ledger = payload.get("ledger")

    if action not in ("choose", "check_time", "query_state"):
        return None, None, "invalid_action"
    if action in ("check_time", "query_state") and choice != "NONE":
        return None, None, "invalid_choice_for_check_time"
    if action == "choose" and choice not in ("A", "B", "C"):
        return None, None, "invalid_choice"
    if not isinstance(task_ids, list):
        return None, None, "invalid_task_ids"
    if action in ("check_time", "query_state") and task_ids:
        return None, None, "invalid_task_ids_for_query"
    if not isinstance(channel, str):
        return None, None, "invalid_channel"
    if action in ("check_time", "query_state") and channel not in allowed_channels:
        return None, None, "invalid_channel_for_query"
    if action == "check_time" and channel != "clock":
        return None, None, "invalid_channel_for_check_time"
    if action == "choose" and channel != "NONE":
        return None, None, "invalid_channel_for_choose"
    if not isinstance(raw_ledger, list):
        return None, None, "invalid_ledger"
    if len(raw_ledger) > MAX_LEDGER_ITEMS:
        return None, None, "ledger_too_large"

    normalized_task_ids = []
    for task_id in task_ids:
        if isinstance(task_id, str) and task_id not in normalized_task_ids:
            normalized_task_ids.append(task_id)

    ledger = _normalize_ledger(raw_ledger)
    if ledger is None:
        return None, None, "invalid_ledger"
    action_payload = {
        "action": action,
        "choice": choice,
        "task_ids": normalized_task_ids,
        "channel": channel,
    }
    return action_payload, ledger, None


def _call_model(
    client,
    model: str,
    messages: list[dict[str, str]],
    backend: str,
    temperature: float,
    max_tokens: int,
    response_schema: dict[str, Any] | None,
):
    def _chat_completion_with_retries(
        request_kwargs: dict[str, Any],
        attempts: int,
    ) -> str:
        last_dump = None
        last_finish_reason = None
        for attempt_idx in range(1, attempts + 1):
            response = client.chat.completions.create(**request_kwargs)
            raw_value = PM_BENCH.extract_chat_text(response)
            last_finish_reason = PM_BENCH.extract_chat_finish_reason(response)
            last_dump = response.model_dump()
            if raw_value is not None and raw_value.strip():
                return raw_value
            print(
                f"Empty chat response ({backend}) attempt {attempt_idx}/{attempts} "
                f"(finish_reason={last_finish_reason!r})."
            )
            if attempt_idx < attempts:
                time.sleep(0.25)
        raise ValueError(
            f"Empty response from backend {backend} after {attempts} attempts "
            f"(finish_reason={last_finish_reason!r}): {last_dump}"
        )

    kwargs = {
        "model": model,
        "messages": messages,
    }
    supports_temperature = backend in ("sglang", "openrouter") or not model.startswith("gpt-5")
    if supports_temperature:
        kwargs["temperature"] = temperature
    if backend == "openai":
        if not hasattr(client, "responses"):
            raise SystemExit(
                "OpenAI client does not support the Responses API. "
                "Upgrade the openai package (pip install -U openai) "
                "or use --backend sglang."
            )
        text_config = None
        if response_schema is not None:
            text_config = {
                "format": {
                    "type": "json_schema",
                    "name": "pm_todo_ledger",
                    "schema": response_schema,
                    "strict": True,
                }
            }
        response = client.responses.create(
            model=model,
            input=messages,
            text=text_config,
        )
        raw_text = response.output_text
        if raw_text is None or not raw_text.strip():
            raise ValueError(f"Empty response from backend {backend}: {response.model_dump()}")
        return raw_text
    if backend == "sglang":
        kwargs["max_tokens"] = max_tokens
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        if response_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "pm_todo_ledger", "schema": response_schema},
            }
    elif backend == "openrouter":
        kwargs["max_tokens"] = max_tokens
        kwargs["extra_body"] = {"reasoning": {"exclude": True}}
    attempts = 4 if backend == "openrouter" else 2
    return _chat_completion_with_retries(kwargs, attempts=attempts)


def _write_prompt_log(handle, day_name: str, step_id: str, messages: list[dict[str, str]]) -> None:
    estimated_tokens = PM_BENCH.estimate_input_tokens(messages)
    handle.write(f"=== {day_name} {step_id} ===\n")
    handle.write(json.dumps(messages, indent=2))
    handle.write(f"\nEST_INPUT_TOKENS: {estimated_tokens}\n\n")
    handle.flush()


def _format_channel_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "(none)"
    items = [f"{channel}:{counts[channel]}" for channel in sorted(counts.keys())]
    return ", ".join(items)


def _prune_messages(
    messages: list[dict[str, str]],
    pinned: set[int],
    max_context_tokens: int,
) -> None:
    if max_context_tokens <= 0:
        return
    while PM_BENCH.estimate_input_tokens(messages) > max_context_tokens:
        removed = False
        for idx, message in enumerate(messages):
            if id(message) in pinned:
                continue
            if idx == 0 and message.get("role") == "system":
                continue
            messages.pop(idx)
            removed = True
            break
        if not removed:
            break


def run_todo_ledger(
    scenario: dict[str, Any],
    log_path: str | None,
    model: str,
    backend: str,
    base_url: str | None,
    api_key: str | None,
    max_time_requests: int,
    prompt_log_path: str | None,
    ledger_log_path: str | None,
    show_task_legend: bool,
    max_invalid_retries: int,
    temperature: float,
    max_tokens: int,
    max_context_tokens: int,
    out_dir: str | None,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    _ = max_time_requests  # deprecated no-op; kept for CLI compatibility
    run_started_at_utc = PM_BENCH.now_utc_iso()
    run_started_perf = time.perf_counter()
    effective_out_dir = out_dir or "runs"
    if backend == "sglang" and base_url is None:
        base_url = "http://127.0.0.1:30002/v1"
    client = PM_BENCH.build_llm_client(backend, api_key=api_key, base_url=base_url)
    log_entries: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    state_query_counts_by_day: dict[str, dict[str, int]] = {}

    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    run_prefix = f"todo-ledger-{timestamp}-{_sanitize_model_label(model)}"
    default_log_name = f"{run_prefix}/{run_prefix}.jsonl"
    resolved_log_path = _resolve_output_path(
        log_path,
        out_dir=effective_out_dir,
        default_filename=default_log_name,
        required_suffix=".jsonl",
    )
    if resolved_log_path is None:
        raise SystemExit("Failed to resolve output log path.")
    if prompt_log_path is None:
        resolved_prompt_log = str(Path(resolved_log_path).with_suffix(".prompt.txt"))
    else:
        resolved_prompt_log = _resolve_output_path(prompt_log_path, out_dir=effective_out_dir)
    resolved_ledger_log = (
        _resolve_output_path(
            ledger_log_path,
            out_dir=effective_out_dir,
            required_suffix=".jsonl",
        )
        if ledger_log_path
        else None
    )
    prompt_log_handle = (
        open(resolved_prompt_log, "w", encoding="utf-8", buffering=1)
        if resolved_prompt_log
        else None
    )
    ledger_log_handle = (
        open(resolved_ledger_log, "w", encoding="utf-8", buffering=1)
        if resolved_ledger_log
        else None
    )

    state_visibility = PM_BENCH.normalize_state_visibility(scenario)
    state_channels = PM_BENCH.normalize_state_channels(scenario)
    allowed_channels = PM_BENCH.list_state_channels(scenario)
    time_visible_by_default = state_visibility.get("clock", False)
    PM_BENCH.print_llm_instructions(
        time_visible_by_default,
        show_task_legend,
        allowed_channels,
    )
    system_prompt = PM_BENCH.build_llm_system_prompt(show_task_legend, allowed_channels)
    system_prompt = system_prompt + "\n\n" + LEDGER_INSTRUCTIONS
    messages = [{"role": "system", "content": system_prompt}]
    system_message = messages[0]

    daily_header = "\n".join(PM_BENCH.DAILY_TASK_HEADER_LINES)
    print(daily_header)
    daily_header_message = {"role": "user", "content": daily_header}
    messages.append(daily_header_message)

    ledger_message = {"role": "user", "content": _format_ledger(ledger)}
    messages.append(ledger_message)

    updates_by_day = PM_BENCH.build_updates_by_day(scenario)
    try:
        for day in scenario["days"]:
            day_start_minutes = PM_BENCH.build_day_start_minutes(day)
            tasks = day["tasks"]
            lure_catalog = PM_BENCH.normalize_lure_catalog(day.get("lures", []))
            active_task_ids: set[str] = set()
            for task in tasks:
                enc_type, _ = PM_BENCH.normalize_encoding(task["encoding"])
                if enc_type == "start":
                    active_task_ids.add(task["id"])

            day_updates = updates_by_day.get(day["name"], {"pre": [], "by_step": {}})
            day_state_query_counts: dict[str, int] = {}
            day_task_states = {task["id"]: PM_BENCH.init_task_state(task) for task in tasks}
            for task in tasks:
                enc_type, _ = PM_BENCH.normalize_encoding(task["encoding"])
                if enc_type == "start":
                    day_task_states[task["id"]]["active"] = True
            for update in day_updates.get("pre", []):
                task_id = update.get("task_id")
                if task_id in day_task_states:
                    PM_BENCH.apply_task_update(
                        day_task_states[task_id],
                        update,
                        task_states=day_task_states,
                    )
            id_to_handle, _ = PM_BENCH.build_day_handle_maps(
                day_task_states,
                lure_catalog,
                seed_key=f"{day['name']}:handles",
            )

            day_header = "\n".join([f"=== {day['name']} ==="] + day.get("start_instructions", []))
            print(f"\n{day_header}")
            day_header_message = {"role": "user", "content": day_header}
            messages.append(day_header_message)

            day_legend_message = None
            if show_task_legend:
                legend_entries = []
                for task_id, state in sorted(day_task_states.items()):
                    if not state["active"]:
                        continue
                    legend_entries.append(
                        {
                            "id": task_id,
                            "handle": id_to_handle[task_id],
                            "action_text": PM_BENCH.runtime_task_action_text(state),
                        }
                    )
                for lure in lure_catalog:
                    legend_entries.append(
                        {
                            "id": lure["id"],
                            "handle": id_to_handle[lure["id"]],
                            "action_text": lure["action_text"],
                        }
                    )
                legend_text = PM_BENCH.format_action_menu(
                    legend_entries,
                    header="Daily action-handle legend",
                )
                print(legend_text)
                day_legend_message = {"role": "user", "content": legend_text}
                messages.append(day_legend_message)

            last_query_step_by_channel: dict[str, int] = {}
            last_snapshot_item_by_channel: dict[str, dict[str, Any]] = {}

            for step_idx, step in enumerate(day["steps"]):
                for update in day_updates.get("by_step", {}).get(step["id"], []):
                    task_id = update.get("task_id")
                    if task_id in day_task_states:
                        PM_BENCH.apply_task_update(
                            day_task_states[task_id],
                            update,
                            task_states=day_task_states,
                        )
                for task in tasks:
                    enc_type, enc_step = PM_BENCH.normalize_encoding(task["encoding"])
                    if enc_type == "step" and enc_step == step["id"]:
                        active_task_ids.add(task["id"])
                        day_task_states[task["id"]]["active"] = True

                step_minutes = PM_BENCH.time_to_minutes(step["time"])
                due_now = PM_BENCH.compute_due_now(
                    day_task_states,
                    active_task_ids,
                    step,
                    step_idx,
                    step_minutes,
                    day_start_minutes,
                )
                menu_entries, step_handle_to_id = PM_BENCH.build_step_action_menu(
                    day_task_states,
                    active_task_ids,
                    lure_catalog,
                    id_to_handle,
                    day["name"],
                    step["id"],
                )
                menu_text = PM_BENCH.format_action_menu(menu_entries, header="Step action menu")
                allowed_handles = sorted(step_handle_to_id.keys())
                time_line = ""
                if time_visible_by_default:
                    time_line = f"\nTime: {step['time']} | Stopwatch: {step_minutes - day_start_minutes} min"
                step_prompt = (
                    f"{step['text']}\n"
                    + "\n".join(step["options"])
                    + "\n"
                    + menu_text
                    + "\n"
                    + time_line
                )

                print(f"\n{step['text']}")
                for option in step["options"]:
                    print(option)
                print(menu_text)
                if time_visible_by_default:
                    print(f"Time: {step['time']} | Stopwatch: {step_minutes - day_start_minutes} min")

                step_message = {"role": "user", "content": step_prompt}
                messages.append(step_message)

                check_time_count = 0
                state_query_counts: dict[str, int] = {}
                invalid_attempts = 0
                ledger_reset_used = False
                while True:
                    ledger_message["content"] = _format_ledger(ledger)
                    pinned_messages = {
                        id(system_message),
                        id(daily_header_message),
                        id(day_header_message),
                        id(ledger_message),
                        id(step_message),
                    }
                    if day_legend_message is not None:
                        pinned_messages.add(id(day_legend_message))
                    _prune_messages(messages, pinned_messages, max_context_tokens)
                    if prompt_log_handle:
                        _write_prompt_log(prompt_log_handle, day["name"], step["id"], messages)
                    response_schema = _build_response_schema(allowed_handles, allowed_channels)
                    raw_text = _call_model(
                        client,
                        model,
                        messages,
                        backend,
                        temperature,
                        max_tokens,
                        response_schema=response_schema,
                    )
                    messages.append({"role": "assistant", "content": raw_text})

                    try:
                        payload = PM_BENCH.parse_json_payload(raw_text)
                    except Exception:  # noqa: BLE001
                        payload = None

                    action, new_ledger, error = _validate_payload(payload, allowed_channels)
                    if error:
                        invalid_attempts += 1
                        if invalid_attempts > max_invalid_retries:
                            if (not ledger_reset_used) and ledger:
                                print(
                                    "Exceeded max invalid response retries. "
                                    "Resetting TODO ledger to [] and retrying step."
                                )
                                ledger = []
                                ledger_reset_used = True
                                invalid_attempts = 0
                                messages.append({"role": "user", "content": LEDGER_RESET_MSG})
                                continue
                            raise SystemExit("Exceeded max invalid response retries.")
                        print(f"Invalid response ({error}): {raw_text!r}")
                        messages.append({"role": "user", "content": INVALID_RESPONSE_MSG})
                        continue

                    if new_ledger is not None:
                        ledger = _prune_completed_ledger(new_ledger)

                    if action["action"] in ("check_time", "query_state"):
                        channel = action["channel"]
                        if action["action"] == "check_time":
                            channel = "clock"
                        print(f"Model action: query_state {channel}")
                        if channel == "clock":
                            check_time_count += 1
                        state_query_counts[channel] = state_query_counts.get(channel, 0) + 1
                        day_state_query_counts[channel] = day_state_query_counts.get(channel, 0) + 1
                        items = PM_BENCH.resolve_state_query_items(
                            channel,
                            day["steps"],
                            step_idx,
                            day["name"],
                            day_start_minutes,
                            state_channels,
                            last_query_step_by_channel,
                            last_snapshot_item_by_channel,
                        )
                        response = PM_BENCH.build_state_query_response(
                            channel,
                            items,
                            day["name"],
                            step["id"],
                        )
                        response_text = PM_BENCH.format_state_query_display(
                            response["channel"],
                            response["items"],
                        )
                        print(response_text)
                        messages.append({"role": "user", "content": response_text})
                        continue

                    choice = action["choice"]
                    task_handles: list[str] = []
                    for handle in action["task_ids"]:
                        if handle in step_handle_to_id and handle not in task_handles:
                            task_handles.append(handle)
                    task_ids = [step_handle_to_id[handle] for handle in task_handles]
                    if task_ids:
                        print(f"Model action: choose {choice} + task(s) {', '.join(task_ids)}")
                    else:
                        print(f"Model action: choose {choice}")

                    PM_BENCH.apply_runtime_completions(
                        day_task_states,
                        task_ids,
                        due_now,
                        step,
                        step_idx,
                        step_minutes,
                        day_start_minutes,
                    )
                    entry = {
                        "day": day["name"],
                        "step_id": step["id"],
                        "choice": choice,
                        "task_ids": task_ids,
                        "task_handles": task_handles,
                        "check_time": check_time_count,
                        "state_queries": state_query_counts,
                        "ledger": ledger,
                    }
                    log_entries.append(entry)
                    if ledger_log_handle:
                        ledger_log_handle.write(json.dumps(entry) + "\n")
                    break
            state_query_counts_by_day[day["name"]] = day_state_query_counts
    finally:
        if prompt_log_handle:
            prompt_log_handle.close()
        if ledger_log_handle:
            ledger_log_handle.close()

    run_metadata = PM_BENCH.make_run_metadata(
        mode="run-todo-ledger-agent",
        started_at_utc=run_started_at_utc,
        finished_at_utc=PM_BENCH.now_utc_iso(),
        duration_seconds=time.perf_counter() - run_started_perf,
        entry_count=len(log_entries),
        model=model,
        backend=backend,
    )
    PM_BENCH.write_log(resolved_log_path, log_entries, run_metadata=run_metadata)
    print(f"\nWrote log: {resolved_log_path}")
    print("State query calls by day/channel:")
    overall_state_query_counts: dict[str, int] = {}
    for day in scenario["days"]:
        day_name = day["name"]
        day_counts = state_query_counts_by_day.get(day_name, {})
        print(f"  {day_name}: {_format_channel_counts(day_counts)}")
        for channel, value in day_counts.items():
            overall_state_query_counts[channel] = overall_state_query_counts.get(channel, 0) + value
    print(f"  Overall: {_format_channel_counts(overall_state_query_counts)}")
    return log_entries, resolved_log_path, run_metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run PM-Bench with a TODO ledger agent.")
    parser.add_argument(
        "--scenario",
        default=str(PROJECT_ROOT / "data" / "synthetic_week_v8.json"),
        help="Scenario JSON path.",
    )
    parser.add_argument("--log", default=None, help="Output action log path (.jsonl).")
    parser.add_argument(
        "--out-dir",
        "--output-dir",
        dest="out_dir",
        default=str(PROJECT_ROOT / "runs"),
        help=(
            "Output directory for generated artifacts (logs, sidecars). "
            "Defaults to the repository's runs directory; each run creates "
            "a subfolder with a shared filename prefix."
        ),
    )
    parser.add_argument("--model", default="gpt-5-mini")
    parser.add_argument(
        "--backend",
        choices=["openai", "openrouter", "sglang"],
        default="openai",
        help="Select which API backend to use for inference.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override the OpenAI-compatible base URL (useful for sglang).",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key override; for sglang use any string (default: None).",
    )
    parser.add_argument(
        "--max-time-requests",
        type=int,
        default=5,
        help="Deprecated no-op. State-query caps are disabled.",
    )
    parser.add_argument("--prompt-log", default=None, help="Optional prompt log file.")
    parser.add_argument("--ledger-log", default=None, help="Optional ledger trajectory log (.jsonl).")
    parser.add_argument(
        "--task-legend",
        action="store_true",
        dest="task_legend",
        default=False,
        help="Show a daily action-handle legend (active tasks + lures).",
    )
    parser.add_argument(
        "--score",
        action="store_true",
        help="Score run and write <log>.score.md report.",
    )
    parser.add_argument("--max-invalid-retries", type=int, default=2)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=768)
    parser.add_argument(
        "--max-context-tokens",
        type=int,
        default=32000,
        help="Trim message history to stay under this approximate token budget.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scenario = PM_BENCH.load_scenario(args.scenario)
    log_entries, resolved_log_path, run_metadata = run_todo_ledger(
        scenario=scenario,
        log_path=args.log,
        model=args.model,
        backend=args.backend,
        base_url=args.base_url,
        api_key=args.api_key,
        max_time_requests=args.max_time_requests,
        prompt_log_path=args.prompt_log,
        ledger_log_path=args.ledger_log,
        show_task_legend=args.task_legend,
        max_invalid_retries=args.max_invalid_retries,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        max_context_tokens=args.max_context_tokens,
        out_dir=args.out_dir,
    )
    if args.score:
        summary, per_day, summary_steps = PM_BENCH.score_log(scenario, log_entries)
        PM_BENCH.print_report(
            summary,
            per_day,
            summary_steps,
            run_metadata=run_metadata,
        )
        report_md = PM_BENCH.build_markdown_report(
            summary,
            per_day,
            summary_steps,
            run_metadata=run_metadata,
        )
        report_path = str(Path(resolved_log_path).with_suffix(".score.md"))
        with open(report_path, "w", encoding="utf-8") as handle:
            handle.write(report_md)
        print(f"Wrote score report: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
