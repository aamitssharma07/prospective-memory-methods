#!/usr/bin/env python3
"""
Run PM-Bench with a coordinator + subagents architecture.

Design goals for v1:
- Same model instance for coordinator and subagents.
- Structured outputs for coordinator and subagents.
- Subagent memory persisted as JSON files on disk (one latest version each).
- No rolling chat history.
- PM-Bench-compatible JSONL logs for existing scoring.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
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
PST_TZ = timezone(timedelta(hours=-8), name="PST")
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0


DEFAULT_AGENT_ROLES = ["event_watcher", "status_watcher", "update_watcher"]

SUBAGENT_ROLE_GUIDANCE: dict[str, str] = {
    "event_watcher": (
        "- Focus on event-driven opportunities from current cues and active handles.\n"
        "- Keep candidate handle suggestions conservative and specific to step evidence."
    ),
    "status_watcher": (
        "- Focus on proactive monitoring duties and hidden-state checks.\n"
        "- Suggest only high-value state queries that can change the current decision."
    ),
    "update_watcher": (
        "- Focus on cancels/overrides/reschedules/dependency risks.\n"
        "- Flag blockers that should prevent premature task completion choices."
    ),
}


def _build_subagent_system_prompt(
    agent_name: str,
    include_tasks_should_not_select: bool,
) -> str:
    role_guidance = SUBAGENT_ROLE_GUIDANCE.get(
        agent_name,
        (
            "- Focus on active PM signals relevant to your assigned role.\n"
            "- Keep notes compact, specific, and current-step grounded."
        ),
    )
    prompt = f"""You are a PM-Bench subagent.
Role identity: {agent_name}

Your role:
1) Analyze the current PM-Bench step using your role guidance.
2) Propose state queries BEFORE task selection.
3) Propose tasks that might be due.
"""
    if include_tasks_should_not_select:
        prompt += "4) Propose tasks that should NOT be selected now.\n\n"
    else:
        prompt += "\n"
    prompt += f"""Role guidance:
{role_guidance}

Output strict JSON only (no markdown, no code fences). Every required key must be present.
Return minimal compact JSON only (single object, no extra text).

Rules:
- Use task handles from the current step menu only (task_n).
- Use channels from available channels only.
- If no items exist for a list, return [].
- Keep evidence concise and step-grounded; avoid speculation.
"""
    return prompt

def _build_coordinator_system_prompt(
    include_tasks_should_not_select: bool,
    decision_mode: str,
) -> str:
    prompt = """You are the coordinator for PM-Bench.
You receive current step context and
structured subagent signals.
Return one valid PM-Bench action JSON.
Return minimal compact JSON only (single object, no extra text).

Rules:
- action is choose, query_state, or check_time.
- If action is choose: choice must be A/B/C and channel must be NONE.
- If action is query_state/check_time: choice must be NONE and task_ids must be [].
- check_time must use channel=clock.
- task_ids must use action handles from the current menu only.
- Use the JSON key task_ids (do not use task_handles).

Decision policy:
- Subagent structured signals provide evidence, not final decisions.
- State query phase has already run from the de-duplicated union of subagent query suggestions.
- When evidence indicates a task is due now, include its handle(s) in task_ids on your choose action.
- A choose action with task_ids=[] is only appropriate when no task has sufficient evidence of being due now.
- Prefer precise execution: avoid selecting tasks that are only \"later\" / \"not yet due\" / speculative.
- Make the final decision carefully; avoid majority-vote shortcuts.
"""
    if include_tasks_should_not_select:
        prompt = prompt.replace(
            "- Make the final decision carefully; avoid majority-vote shortcuts.\n",
            "- Treat tasks_should_not_select as strong caution unless state evidence clearly contradicts it.\n"
            "- Make the final decision carefully; avoid majority-vote shortcuts.\n",
        )
    if decision_mode == "task_vote_only":
        prompt += (
            "\nDecision mode override:\n"
            "- You decide choice only (A/B/C).\n"
            "- task_ids are resolved externally by majority task voting and any task_ids you return are ignored.\n"
            "- Still return valid choose JSON.\n"
        )
    elif decision_mode == "vote_plus_coordinator":
        prompt += (
            "\nDecision mode override:\n"
            "- A majority task-vote summary is provided as advisory evidence.\n"
            "- You may override the majority when evidence supports it.\n"
            "- When strong majority evidence exists, do not leave task_ids empty without clear contradictory evidence.\n"
        )
    return prompt


def _build_invalid_subagent_msg(include_tasks_should_not_select: bool) -> str:
    required = ["focus", "state_query_suggestions", "tasks_might_be_due"]
    if include_tasks_should_not_select:
        required.append("tasks_should_not_select")
    return (
        "Invalid subagent JSON. Return strict JSON with required keys: "
        + ", ".join(required)
        + ". Return minimal compact JSON only."
    )

INVALID_COORDINATOR_MSG = (
    "Invalid PM action JSON. Follow the required schema and action constraints. "
    "Return minimal compact JSON only."
)


def _build_coordinator_force_choose_msg(decision_mode: str) -> str:
    if decision_mode == "task_vote_only":
        return (
            "State-query phase for this step is complete. Do not query again now; "
            "return a choose action with choice A/B/C."
        )
    return (
        "State-query phase for this step is complete. Do not query again now; "
        "return a choose action (A/B/C) and include task_ids for tasks you judge due now."
    )


def _build_non_empty_task_retry_msg(majority_handles: list[str]) -> str:
    majority_text = ", ".join(majority_handles) if majority_handles else "(none)"
    return (
        "Your previous choose action used task_ids=[] despite strong majority vote evidence. "
        f"Majority-voted task handles this step: {majority_text}. "
        "Re-evaluate and return choose with non-empty task_ids unless you have explicit contradictory evidence."
    )


class StructuredModelResponseError(RuntimeError):
    def __init__(self, message: str, raw_text: str | None = None):
        super().__init__(message)
        self.raw_text = raw_text


def _sanitize_model_label(model: str) -> str:
    return model.replace("/", "-").replace(":", "-").replace(" ", "-")


def _resolve_runs_path(
    path_value: str | None,
    model_label: str,
    runs_dir: Path,
    prefix: str,
    suffix: str,
) -> str | None:
    if path_value is None:
        ts = datetime.now().strftime("%Y%m%d-%H%M")
        return str(runs_dir / f"{prefix}-{ts}-{_sanitize_model_label(model_label)}{suffix}")
    path = Path(path_value)
    if path.is_absolute():
        resolved = path
    else:
        # "runs/..." should map to project-root runs/, not runs/runs/.
        if path.parts and path.parts[0] == runs_dir.name:
            resolved = PROJECT_ROOT / path
        else:
            resolved = runs_dir / path
    if not str(resolved).endswith(suffix):
        resolved = resolved.with_suffix(suffix)
    return str(resolved)


def _ensure_parent_dir(path_value: str | None) -> None:
    if not path_value:
        return
    Path(path_value).parent.mkdir(parents=True, exist_ok=True)


def _chat_completion_with_retries(
    client,
    request_kwargs: dict[str, Any],
    backend: str,
    attempts: int,
    request_timeout_seconds: float,
) -> str:
    last_dump = None
    last_finish_reason = None
    for attempt_idx in range(1, attempts + 1):
        call_kwargs = dict(request_kwargs)
        call_kwargs.setdefault("timeout", request_timeout_seconds)
        response = client.chat.completions.create(**call_kwargs)
        raw_text = PM_BENCH.extract_chat_text(response)
        last_finish_reason = PM_BENCH.extract_chat_finish_reason(response)
        last_dump = response.model_dump()
        if raw_text is not None and raw_text.strip():
            return raw_text
        print(
            f"Empty chat response ({backend}) attempt {attempt_idx}/{attempts} "
            f"(finish_reason={last_finish_reason!r})."
        )
        if attempt_idx < attempts:
            time.sleep(0.25)
    raise StructuredModelResponseError(
        (
            f"Empty response from backend {backend} after {attempts} attempts "
            f"(finish_reason={last_finish_reason!r}): {last_dump}"
        ),
        raw_text=None,
    )


def _call_structured_model(
    client,
    model: str,
    messages: list[dict[str, str]],
    backend: str,
    schema_name: str,
    response_schema: dict[str, Any],
    temperature: float,
    max_tokens: int,
    return_raw_text: bool = False,
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    supports_temperature = backend in ("sglang", "openrouter") or not model.startswith("gpt-5")

    if backend == "openai":
        if not hasattr(client, "responses"):
            raise SystemExit(
                "OpenAI client does not support the Responses API. "
                "Upgrade openai (pip install -U openai) or use --backend sglang."
            )
        response = client.responses.create(
            model=model,
            input=messages,
            timeout=request_timeout_seconds,
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": response_schema,
                    "strict": True,
                }
            },
        )
        raw_text = response.output_text
        if raw_text is None or not raw_text.strip():
            raise StructuredModelResponseError(
                "OpenAI Responses API returned empty output_text.",
                raw_text=None,
            )
    elif backend == "sglang":
        kwargs = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        }
        # sglang schema enforcement can be inconsistent for local OSS models;
        # rely on prompt constraints + local schema validation/retry.
        if supports_temperature:
            kwargs["temperature"] = temperature
        raw_text = _chat_completion_with_retries(
            client,
            kwargs,
            backend,
            attempts=2,
            request_timeout_seconds=request_timeout_seconds,
        )
    else:
        kwargs = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "extra_body": {"reasoning": {"exclude": True}},
        }
        if supports_temperature:
            kwargs["temperature"] = temperature
        raw_text = _chat_completion_with_retries(
            client,
            kwargs,
            backend,
            attempts=4,
            request_timeout_seconds=request_timeout_seconds,
        )

    try:
        payload = PM_BENCH.parse_json_payload(raw_text)
    except Exception as exc:  # noqa: BLE001
        raise StructuredModelResponseError(
            f"Failed to parse JSON payload: {type(exc).__name__}",
            raw_text=raw_text,
        ) from exc
    if not isinstance(payload, dict):
        raise StructuredModelResponseError(
            "Structured response is not a JSON object.",
            raw_text=raw_text,
        )
    if return_raw_text:
        return {"payload": payload, "raw_text": raw_text}
    return payload


def _preflight_backend_model(client, backend: str, base_url: str | None, model: str) -> None:
    """Fail fast if the configured backend endpoint/model is not reachable."""
    if backend != "sglang":
        return
    endpoint = base_url or "http://127.0.0.1:30002/v1"
    try:
        models_response = client.models.list()
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "Failed to reach sglang endpoint for hierarchical run. "
            f"base_url={endpoint} model={model} error={type(exc).__name__}: {exc}"
        ) from exc

    available_ids: list[str] = []
    data = getattr(models_response, "data", None)
    if isinstance(data, list):
        for item in data:
            model_id = getattr(item, "id", None)
            if isinstance(model_id, str):
                available_ids.append(model_id)
    if available_ids and model not in available_ids:
        raise SystemExit(
            "Requested model is not served by the current sglang endpoint. "
            f"requested={model} base_url={endpoint} available={available_ids}"
        )


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _subagent_structured_path(memory_dir: Path, agent_name: str) -> Path:
    return memory_dir / f"{agent_name}.json"


def _clean_text(value: Any, *, default: str = "none", max_chars: int = 220) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    if len(text) > max_chars:
        return text[:max_chars].rstrip()
    return text


def _dedupe_keep_order(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


def _build_task_vote_summary(
    subagent_round_updates: list[dict[str, Any]],
    allowed_handles: list[str],
    menu_entries: list[dict[str, str]],
) -> tuple[dict[str, int], list[str], dict[str, list[str]]]:
    handle_set = set(allowed_handles)
    order_index = {entry["handle"]: idx for idx, entry in enumerate(menu_entries)}
    task_vote_counts: dict[str, int] = {}
    task_vote_by_agent: dict[str, list[str]] = {}

    for update in subagent_round_updates:
        agent = str(update.get("agent", "unknown"))
        votes_for_agent: list[str] = []
        seen_for_agent: set[str] = set()
        for item in update.get("tasks_might_be_due", []):
            if not isinstance(item, dict):
                continue
            handle = item.get("task_handle")
            if not isinstance(handle, str) or handle not in handle_set or handle in seen_for_agent:
                continue
            seen_for_agent.add(handle)
            votes_for_agent.append(handle)
            task_vote_counts[handle] = task_vote_counts.get(handle, 0) + 1
        task_vote_by_agent[agent] = votes_for_agent

    threshold = len(subagent_round_updates) / 2.0
    majority_handles = [
        handle
        for handle, count in task_vote_counts.items()
        if count > threshold
    ]
    majority_handles.sort(key=lambda handle: (order_index.get(handle, 10_000), handle))

    ordered_counts = {
        handle: task_vote_counts[handle]
        for handle in sorted(
            task_vote_counts.keys(),
            key=lambda handle: (
                -task_vote_counts[handle],
                order_index.get(handle, 10_000),
                handle,
            ),
        )
    }
    return ordered_counts, majority_handles, task_vote_by_agent


def _default_subagent_payload(
    include_tasks_should_not_select: bool,
) -> dict[str, Any]:
    payload = {
        "focus": "none",
        "state_query_suggestions": [],
        "tasks_might_be_due": [],
    }
    if include_tasks_should_not_select:
        payload["tasks_should_not_select"] = []
    return payload


def _build_subagent_response_schema(
    allowed_handles: list[str],
    allowed_channels: list[str],
    include_tasks_should_not_select: bool,
) -> dict[str, Any]:
    due_task_item_schema = {
        "type": "object",
        "properties": {
            "task_handle": {"type": "string", "enum": allowed_handles},
            "evidence": {"type": "string"},
            "pending_state_queries": {
                "type": "array",
                "items": {"type": "string", "enum": allowed_channels},
            },
        },
        "required": ["task_handle", "evidence", "pending_state_queries"],
        "additionalProperties": False,
    }
    blocked_task_item_schema = {
        "type": "object",
        "properties": {
            "task_handle": {"type": "string", "enum": allowed_handles},
            "evidence": {"type": "string"},
        },
        "required": ["task_handle", "evidence"],
        "additionalProperties": False,
    }
    properties: dict[str, Any] = {
        "focus": {"type": "string"},
        "state_query_suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "enum": allowed_channels},
                    "reason": {"type": "string"},
                },
                "required": ["channel", "reason"],
                "additionalProperties": False,
            },
        },
        "tasks_might_be_due": {"type": "array", "items": due_task_item_schema},
    }
    required = [
        "focus",
        "state_query_suggestions",
        "tasks_might_be_due",
    ]
    if include_tasks_should_not_select:
        properties["tasks_should_not_select"] = {
            "type": "array",
            "items": blocked_task_item_schema,
        }
        required.append("tasks_should_not_select")

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _normalize_subagent_payload(
    payload: Any,
    allowed_handles: list[str],
    allowed_channels: list[str],
    include_tasks_should_not_select: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(payload, dict):
        return None, "payload_not_object"
    focus = _clean_text(payload.get("focus"), default="none", max_chars=120)

    queries: list[dict[str, str]] = []
    raw_queries = payload.get("state_query_suggestions")
    if not isinstance(raw_queries, list):
        return None, "invalid_state_query_suggestions"
    for item in raw_queries:
        if not isinstance(item, dict):
            continue
        channel = item.get("channel")
        if not isinstance(channel, str) or channel not in allowed_channels:
            continue
        queries.append(
            {
                "channel": channel,
                "reason": _clean_text(item.get("reason"), default="none", max_chars=180),
            }
        )
    queries = queries[:6]

    def _normalize_due_task_items(raw_items: Any) -> list[dict[str, Any]] | None:
        if not isinstance(raw_items, list):
            return None
        normalized: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            handle = item.get("task_handle")
            if not isinstance(handle, str) or handle not in allowed_handles:
                continue
            pending_raw = item.get("pending_state_queries")
            if not isinstance(pending_raw, list):
                pending_raw = []
            pending_channels = [
                value
                for value in pending_raw
                if isinstance(value, str) and value in allowed_channels
            ]
            normalized.append(
                {
                    "task_handle": handle,
                    "evidence": _clean_text(item.get("evidence"), default="none", max_chars=220),
                    "pending_state_queries": _dedupe_keep_order(pending_channels)[:4],
                }
            )
        deduped: list[dict[str, Any]] = []
        seen_handles: set[str] = set()
        for item in normalized:
            handle = item["task_handle"]
            if handle in seen_handles:
                continue
            seen_handles.add(handle)
            deduped.append(item)
        return deduped[:8]

    def _normalize_blocked_task_items(raw_items: Any) -> list[dict[str, Any]] | None:
        if not isinstance(raw_items, list):
            return None
        normalized: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            handle = item.get("task_handle")
            if not isinstance(handle, str) or handle not in allowed_handles:
                continue
            normalized.append(
                {
                    "task_handle": handle,
                    "evidence": _clean_text(item.get("evidence"), default="none", max_chars=220),
                }
            )
        deduped: list[dict[str, Any]] = []
        seen_handles: set[str] = set()
        for item in normalized:
            handle = item["task_handle"]
            if handle in seen_handles:
                continue
            seen_handles.add(handle)
            deduped.append(item)
        return deduped[:8]

    due_items = _normalize_due_task_items(payload.get("tasks_might_be_due"))
    if due_items is None:
        return None, "invalid_tasks_might_be_due"
    normalized_payload: dict[str, Any] = {
        "focus": focus,
        "state_query_suggestions": queries,
        "tasks_might_be_due": due_items,
    }
    if include_tasks_should_not_select:
        not_select_items = _normalize_blocked_task_items(payload.get("tasks_should_not_select"))
        if not_select_items is None:
            return None, "invalid_tasks_should_not_select"
        normalized_payload["tasks_should_not_select"] = not_select_items

    return normalized_payload, None


def _normalize_saved_subagent_payload(
    payload: Any,
    include_tasks_should_not_select: bool,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    focus = _clean_text(payload.get("focus"), default="none", max_chars=120)
    raw_queries = payload.get("state_query_suggestions")
    raw_due = payload.get("tasks_might_be_due")
    raw_not_select = payload.get("tasks_should_not_select", [])
    if not isinstance(raw_queries, list) or not isinstance(raw_due, list):
        return None
    if include_tasks_should_not_select and not isinstance(raw_not_select, list):
        return None

    query_items: list[dict[str, str]] = []
    for item in raw_queries[:6]:
        if not isinstance(item, dict):
            continue
        channel = _clean_text(item.get("channel"), default="none", max_chars=64)
        query_items.append(
            {
                "channel": channel,
                "reason": _clean_text(item.get("reason"), default="none", max_chars=180),
            }
        )

    def _normalize_saved_task_list(raw_items: list[Any], *, include_pending_queries: bool) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw_items[:8]:
            if not isinstance(item, dict):
                continue
            task_handle = _clean_text(item.get("task_handle"), default="", max_chars=64)
            if not task_handle or task_handle in seen:
                continue
            seen.add(task_handle)
            payload_item: dict[str, Any] = {
                "task_handle": task_handle,
                "evidence": _clean_text(item.get("evidence"), default="none", max_chars=220),
            }
            if include_pending_queries:
                pending_raw = item.get("pending_state_queries")
                pending = []
                if isinstance(pending_raw, list):
                    pending = [
                        _clean_text(value, default="", max_chars=64)
                        for value in pending_raw
                        if str(value or "").strip()
                    ]
                payload_item["pending_state_queries"] = _dedupe_keep_order([v for v in pending if v])[:4]
            out.append(payload_item)
        return out

    normalized_payload: dict[str, Any] = {
        "focus": focus,
        "state_query_suggestions": query_items,
        "tasks_might_be_due": _normalize_saved_task_list(raw_due, include_pending_queries=True),
    }
    if include_tasks_should_not_select:
        normalized_payload["tasks_should_not_select"] = _normalize_saved_task_list(
            raw_not_select if isinstance(raw_not_select, list) else [],
            include_pending_queries=False,
        )
    return normalized_payload


def _build_persisted_subagent_payload(
    payload: dict[str, Any],
    *,
    agent_name: str,
    day_name: str,
    step_id: str,
    step_time: str,
) -> dict[str, Any]:
    persisted = dict(payload)
    persisted["_meta"] = {
        "agent": agent_name,
        "day": day_name,
        "step_id": step_id,
        "step_time": step_time,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    return persisted


def _summarize_subagent_payload(
    payload: dict[str, Any],
    include_tasks_should_not_select: bool,
) -> dict[str, Any]:
    blocked_items = payload.get("tasks_should_not_select", []) if include_tasks_should_not_select else []
    query_channels = _dedupe_keep_order(
        [item["channel"] for item in payload["state_query_suggestions"]]
    )[:3]
    candidate_handles = [item["task_handle"] for item in payload["tasks_might_be_due"]][:3]
    blocking_conditions = [
        f"{item['task_handle']}: {item['evidence']}"
        for item in blocked_items[:3]
    ]
    watchlist = [
        item["task_handle"]
        for item in payload["tasks_might_be_due"][:2]
    ]
    watchlist.extend(item["task_handle"] for item in blocked_items[:1])
    return {
        "focus": payload["focus"],
        "active_signal_count": (
            len(payload["state_query_suggestions"])
            + len(payload["tasks_might_be_due"])
            + len(blocked_items)
        ),
        "watchlist": watchlist[:3],
        "candidate_handles": candidate_handles,
        "query_suggestions": query_channels,
        "blocking_conditions": blocking_conditions,
    }


def _load_subagent_payload(
    memory_root: Path,
    agent_name: str,
    include_tasks_should_not_select: bool,
) -> dict[str, Any]:
    payload = _default_subagent_payload(include_tasks_should_not_select)
    structured_path = _subagent_structured_path(memory_root, agent_name)
    if not structured_path.exists():
        return payload
    try:
        raw_payload = json.loads(_read_text(structured_path))
    except Exception:  # noqa: BLE001
        return payload
    normalized_payload = _normalize_saved_subagent_payload(
        raw_payload,
        include_tasks_should_not_select=include_tasks_should_not_select,
    )
    return normalized_payload if normalized_payload is not None else payload


def _build_subagent_state_summaries(
    memory_root: Path,
    subagent_names: list[str],
    include_tasks_should_not_select: bool,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for agent_name in subagent_names:
        payload = _load_subagent_payload(
            memory_root,
            agent_name,
            include_tasks_should_not_select=include_tasks_should_not_select,
        )
        summary = _summarize_subagent_payload(
            payload,
            include_tasks_should_not_select=include_tasks_should_not_select,
        )
        summary_payload: dict[str, Any] = {
            "agent": agent_name,
            "focus": summary["focus"],
            "active_signal_count": summary["active_signal_count"],
            "watchlist": summary["watchlist"],
            "candidate_handles": summary["candidate_handles"],
            "query_suggestions": summary["query_suggestions"],
            "blocking_conditions": summary["blocking_conditions"],
            "state_query_suggestions": payload["state_query_suggestions"],
            "tasks_might_be_due": payload["tasks_might_be_due"],
        }
        if include_tasks_should_not_select:
            summary_payload["tasks_should_not_select"] = payload.get("tasks_should_not_select", [])
        summaries.append(summary_payload)
    return summaries


def _init_subagent_memories(
    memory_dir: Path,
    subagent_names: list[str],
    include_tasks_should_not_select: bool,
) -> list[str]:
    memory_dir.mkdir(parents=True, exist_ok=True)
    names = list(subagent_names)
    for name in names:
        structured_path = _subagent_structured_path(memory_dir, name)
        payload = _default_subagent_payload(include_tasks_should_not_select)
        if not structured_path.exists():
            _write_text(
                structured_path,
                json.dumps(
                    _build_persisted_subagent_payload(
                        payload,
                        agent_name=name,
                        day_name="unknown",
                        step_id="unknown",
                        step_time="unknown",
                    ),
                    ensure_ascii=True,
                    indent=2,
                ),
            )
    return names


def _format_step_menu(menu_entries: list[dict[str, str]]) -> str:
    if not menu_entries:
        return "(none)"
    lines = []
    for entry in menu_entries:
        lines.append(f"- {entry['handle']}: {entry['action_text']}")
    return "\n".join(lines)


def _resolve_subagent_names(num_subagents: int, agent_roles: list[str] | None) -> list[str]:
    if agent_roles:
        cleaned: list[str] = []
        for role in agent_roles:
            role_name = role.strip()
            if role_name and role_name not in cleaned:
                cleaned.append(role_name)
        if cleaned:
            return cleaned
    if num_subagents == len(DEFAULT_AGENT_ROLES):
        return list(DEFAULT_AGENT_ROLES)
    return [f"subagent_{idx}" for idx in range(1, num_subagents + 1)]


def _validate_coordinator_action(
    payload: Any,
    allowed_handles: list[str],
    allowed_channels: list[str],
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(payload, dict):
        return None, "payload_not_object"
    action = payload.get("action")
    choice = payload.get("choice")
    task_ids = payload.get("task_ids")
    # Backward-compatible alias: some models emit task_handles instead of task_ids.
    if task_ids is None and isinstance(payload.get("task_handles"), list):
        task_ids = payload.get("task_handles")
    channel = payload.get("channel")
    if action not in ("choose", "check_time", "query_state"):
        return None, "invalid_action"
    if not isinstance(task_ids, list):
        return None, "invalid_task_ids"
    if not isinstance(channel, str):
        return None, "invalid_channel"
    if channel not in set(allowed_channels + ["NONE"]):
        return None, "unknown_channel"

    deduped = []
    for handle in task_ids:
        if not isinstance(handle, str):
            return None, "task_id_not_string"
        if handle not in allowed_handles:
            return None, f"unknown_task_id:{handle}"
        if handle in deduped:
            return None, f"duplicate_task_id:{handle}"
        deduped.append(handle)

    if action == "choose":
        if choice not in ("A", "B", "C"):
            return None, "invalid_choice_for_choose"
        if channel != "NONE":
            return None, "choose_requires_channel_none"
    elif action == "check_time":
        if choice != "NONE":
            return None, "check_time_requires_choice_none"
        if deduped:
            return None, "check_time_requires_no_tasks"
        if channel != "clock":
            return None, "check_time_requires_clock"
    else:  # query_state
        if choice != "NONE":
            return None, "query_state_requires_choice_none"
        if deduped:
            return None, "query_state_requires_no_tasks"
        if channel in ("NONE",):
            return None, "query_state_requires_channel"

    return {
        "action": action,
        "choice": choice,
        "task_ids": deduped,
        "channel": channel,
    }, None


def _validate_coordinator_choice_only(payload: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(payload, dict):
        return None, "payload_not_object"
    action = payload.get("action")
    choice = payload.get("choice")
    channel = payload.get("channel")
    if action != "choose":
        return None, "force_choose_required"
    if choice not in ("A", "B", "C"):
        return None, "invalid_choice_for_choose"
    if channel != "NONE":
        return None, "choose_requires_channel_none"
    return {
        "action": "choose",
        "choice": choice,
        "task_ids": [],
        "channel": "NONE",
    }, None


def _build_coordinator_recovery_action(
    last_payload: Any,
    allowed_handles: list[str],
    allowed_channels: list[str],
    force_choose_reason: str | None,
) -> dict[str, Any]:
    default_choose = {
        "action": "choose",
        "choice": "C",
        "task_ids": [],
        "channel": "NONE",
    }
    if not isinstance(last_payload, dict):
        return default_choose

    action = last_payload.get("action")
    choice = last_payload.get("choice")
    channel = last_payload.get("channel")
    raw_task_ids = last_payload.get("task_ids")
    if raw_task_ids is None and isinstance(last_payload.get("task_handles"), list):
        raw_task_ids = last_payload.get("task_handles")
    deduped: list[str] = []
    if isinstance(raw_task_ids, list):
        for handle in raw_task_ids:
            if isinstance(handle, str) and handle in allowed_handles and handle not in deduped:
                deduped.append(handle)

    if action == "choose":
        return {
            "action": "choose",
            "choice": choice if choice in ("A", "B", "C") else "C",
            "task_ids": deduped,
            "channel": "NONE",
        }

    if force_choose_reason is not None:
        return default_choose

    if action == "check_time":
        return {
            "action": "check_time",
            "choice": "NONE",
            "task_ids": [],
            "channel": "clock",
        }

    if action == "query_state":
        recovered_channel: str | None = None
        if isinstance(channel, str) and channel in allowed_channels and channel != "NONE":
            recovered_channel = channel
        elif allowed_channels:
            recovered_channel = allowed_channels[0]
        if recovered_channel == "clock":
            return {
                "action": "check_time",
                "choice": "NONE",
                "task_ids": [],
                "channel": "clock",
            }
        if recovered_channel:
            return {
                "action": "query_state",
                "choice": "NONE",
                "task_ids": [],
                "channel": recovered_channel,
            }

    return default_choose


def _build_subagent_user_prompt(
    agent_name: str,
    day_name: str,
    step: dict[str, Any],
    menu_entries: list[dict[str, str]],
    allowed_channels: list[str],
    time_visible_by_default: bool,
    state_observations: list[str],
    memory_context: str,
    include_tasks_should_not_select: bool,
) -> str:
    observations = "\n".join(f"- {line}" for line in state_observations) if state_observations else "- (none)"
    channels_line = ", ".join(allowed_channels)
    schema_template: dict[str, Any] = {
        "focus": "one concise role-grounded line",
        "state_query_suggestions": [
            {
                "channel": allowed_channels[0] if allowed_channels else "clock",
                "reason": "why query now",
            }
        ],
        "tasks_might_be_due": [
            {
                "task_handle": "task_n",
                "evidence": "why this could be due now",
                "pending_state_queries": ["clock"],
            }
        ],
    }
    if include_tasks_should_not_select:
        schema_template["tasks_should_not_select"] = [
            {
                "task_handle": "task_n",
                "evidence": "why selecting now is risky/wrong",
            }
        ]
    task_lists_rule = (
        "- tasks_might_be_due and tasks_should_not_select may be empty.\n"
        if include_tasks_should_not_select
        else "- tasks_might_be_due may be empty.\n"
    )
    return (
        f"Agent: {agent_name}\n"
        f"Day: {day_name}\n"
        f"Step ID: {step['id']}\n"
        f"Step time: {step['time']} (visible_by_default={str(time_visible_by_default).lower()})\n\n"
        f"Step text:\n{step['text']}\n\n"
        f"Options:\n" + "\n".join(step["options"]) + "\n\n"
        f"Current action menu:\n{_format_step_menu(menu_entries)}\n\n"
        f"Observed state responses this step:\n{observations}\n\n"
        f"Available channels:\n{channels_line}\n\n"
        "Return strict JSON only with this shape and required keys:\n"
        + json.dumps(schema_template, indent=2)
        + "\n\n"
        "Additional rules:\n"
        "- Queries are proposed before task selection.\n"
        f"{task_lists_rule}"
        "- Use [] for empty lists.\n"
        "- Keep evidence short and tied to this step only.\n\n"
        "Output format reminder:\n"
        "- Return minimal compact JSON only (single object, no extra text).\n\n"
        "Current structured memory context:\n"
        f"{memory_context}\n"
    )


def _build_coordinator_user_prompt(
    day_name: str,
    step: dict[str, Any],
    menu_entries: list[dict[str, str]],
    allowed_channels: list[str],
    time_visible_by_default: bool,
    state_observations: list[str],
    subagent_round_updates: list[dict[str, Any]],
    subagent_failures: list[str],
    recent_decisions: list[str],
    union_query_channels: list[str],
    union_query_results: list[str],
    force_choose_reason: str | None,
    include_tasks_should_not_select: bool,
    decision_mode: str,
    task_vote_counts: dict[str, int],
    task_vote_majority_handles: list[str],
    task_vote_by_agent: dict[str, list[str]],
) -> str:
    observations = "\n".join(f"- {line}" for line in state_observations) if state_observations else "- (none)"
    updates_lines: list[str] = []
    due_support_lines: list[str] = []
    caution_lines: list[str] = []
    for update in subagent_round_updates:
        query_text = (
            ", ".join(item["channel"] for item in update["state_query_suggestions"])
            if update["state_query_suggestions"]
            else "(none)"
        )
        due_text = (
            ", ".join(item["task_handle"] for item in update["tasks_might_be_due"])
            if update["tasks_might_be_due"]
            else "(none)"
        )
        blocked_items = update.get("tasks_should_not_select", []) if include_tasks_should_not_select else []
        not_select_text = (
            ", ".join(item["task_handle"] for item in blocked_items)
            if blocked_items
            else "(none)"
        )
        line = (
            f"- {update['agent']}: focus={update['focus'] or '(empty)'} "
            f"query_channels={query_text} due_candidates={due_text}"
        )
        if include_tasks_should_not_select:
            line += f" forbidden={not_select_text}"
        updates_lines.append(line)
        for due in update["tasks_might_be_due"]:
            due_support_lines.append(
                f"- {update['agent']} supports {due['task_handle']}: {due['evidence']} "
                f"(pending_queries={','.join(due['pending_state_queries']) or 'none'})"
            )
        for blocked in blocked_items:
            caution_lines.append(
                f"- {update['agent']} cautions {blocked['task_handle']}: {blocked['evidence']}"
            )
    updates_text = "\n".join(updates_lines) if updates_lines else "- (none)"
    due_support_text = "\n".join(due_support_lines) if due_support_lines else "- (none)"
    caution_text = "\n".join(caution_lines) if caution_lines else "- (none)"
    union_query_text = ", ".join(union_query_channels) if union_query_channels else "(none)"
    union_results_text = "\n".join(f"- {line}" for line in union_query_results) if union_query_results else "- (none)"

    failures_text = "\n".join(f"- {line}" for line in subagent_failures) if subagent_failures else "- (none)"
    recent_text = "\n".join(f"- {line}" for line in recent_decisions[-8:]) if recent_decisions else "- (none)"
    channels_line = ", ".join(allowed_channels)
    vote_counts_text = (
        "\n".join(f"- {handle}: {count}" for handle, count in task_vote_counts.items())
        if task_vote_counts
        else "- (none)"
    )
    vote_majority_text = ", ".join(task_vote_majority_handles) if task_vote_majority_handles else "(none)"
    vote_by_agent_text = (
        "\n".join(
            f"- {agent}: {', '.join(handles) if handles else '(none)'}"
            for agent, handles in task_vote_by_agent.items()
        )
        if task_vote_by_agent
        else "- (none)"
    )
    force_choose_text = (
        f"\nCoordinator constraint:\n- {force_choose_reason}\n"
        if force_choose_reason
        else ""
    )
    caution_section = (
        f"Tasks that should not be selected (strong caution; overridable):\n{caution_text}\n\n"
        if include_tasks_should_not_select
        else ""
    )
    vote_mode_section = ""
    if decision_mode == "task_vote_only":
        vote_mode_section = (
            "Task-vote aggregation this round:\n"
            "- decision_mode=task_vote_only\n"
            f"- majority_threshold=>N/2 with N={len(task_vote_by_agent)}\n"
            f"- majority_handles={vote_majority_text}\n"
            f"- vote_counts:\n{vote_counts_text}\n"
            f"- per_agent_votes:\n{vote_by_agent_text}\n\n"
            "Coordinator mode constraint:\n"
            "- You decide only choice A/B/C.\n"
            "- task_ids are resolved externally from majority votes and your task_ids will be ignored.\n\n"
        )
    elif decision_mode == "vote_plus_coordinator":
        vote_mode_section = (
            "Task-vote aggregation this round (advisory evidence):\n"
            "- decision_mode=vote_plus_coordinator\n"
            f"- majority_threshold=>N/2 with N={len(task_vote_by_agent)}\n"
            f"- majority_handles={vote_majority_text}\n"
            f"- vote_counts:\n{vote_counts_text}\n"
            f"- per_agent_votes:\n{vote_by_agent_text}\n\n"
        )
    return (
        f"Day: {day_name}\n"
        f"Step ID: {step['id']}\n"
        f"Step time: {step['time']} (visible_by_default={str(time_visible_by_default).lower()})\n\n"
        f"Step text:\n{step['text']}\n\n"
        f"Options:\n" + "\n".join(step["options"]) + "\n\n"
        f"Current action menu:\n{_format_step_menu(menu_entries)}\n\n"
        f"Observed state responses this step:\n{observations}\n\n"
        f"Available channels:\n{channels_line}\n\n"
        f"Union state queries already executed this round:\n- {union_query_text}\n\n"
        f"State query results from the union run:\n{union_results_text}\n\n"
        f"Recent finalized coordinator decisions (same day):\n{recent_text}\n\n"
        f"Subagent failures this round:\n{failures_text}\n\n"
        f"Subagent update summaries this round:\n{updates_text}\n\n"
        f"Task candidates that might be due:\n{due_support_text}\n\n"
        f"{vote_mode_section}"
        f"{caution_section}"
        f"{force_choose_text}"
        "Output format reminder:\n"
        "- Return minimal compact JSON only (single object, no extra text).\n"
    )


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _now_iso_pst() -> str:
    return datetime.now(PST_TZ).strftime("%Y_%m_%d_%H_%M_%S")


def _emit_subagent_progress(
    verbose_subagents: bool,
    debug_log_handle,
    debug_log_subagent_events: bool,
    day_name: str,
    step_id: str,
    agent_name: str,
    phase: str,
    details: dict[str, Any] | None = None,
) -> None:
    details = details or {}
    if verbose_subagents:
        if phase == "start":
            print(f"[subagent] {day_name} {step_id} {agent_name} start")
        elif details.get("error"):
            elapsed_ms = details.get("elapsed_ms")
            elapsed_text = "n/a" if elapsed_ms is None else f"{float(elapsed_ms):.1f}ms"
            print(
                f"[subagent] {day_name} {step_id} {agent_name} failed "
                f"({elapsed_text}) error={details.get('error')}"
            )
        else:
            elapsed_ms = details.get("elapsed_ms")
            focus = details.get("focus")
            signals = details.get("signal_count")
            watchlist = details.get("watchlist")
            watchlist_text = ",".join(watchlist) if isinstance(watchlist, list) and watchlist else "-"
            elapsed_text = "n/a" if elapsed_ms is None else f"{float(elapsed_ms):.1f}ms"
            print(
                f"[subagent] {day_name} {step_id} {agent_name} done "
                f"({elapsed_text}) focus={focus} signals={signals} watch={watchlist_text}"
            )
    if debug_log_handle and debug_log_subagent_events:
        payload = {
            "event": "subagent_progress",
            "ts": _now_iso_utc(),
            "phase": phase,
            "day": day_name,
            "step_id": step_id,
            "agent": agent_name,
        }
        payload.update(details)
        debug_log_handle.write(json.dumps(payload) + "\n")
        debug_log_handle.flush()


def _format_channel_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "(none)"
    return " | ".join(f"{channel}={counts[channel]}" for channel in sorted(counts))


def _truncate_for_log(value: str | None, max_chars: int = 500) -> str:
    if value is None:
        return "null"
    text = value.replace("\n", "\\n")
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...[truncated]"


def _run_subagent_proposal(
    client,
    model: str,
    backend: str,
    temperature: float,
    max_tokens: int,
    max_invalid_retries: int,
    agent_name: str,
    memory_root: Path,
    day_name: str,
    step: dict[str, Any],
    menu_entries: list[dict[str, str]],
    allowed_channels: list[str],
    time_visible_by_default: bool,
    state_observations: list[str],
    include_tasks_should_not_select: bool,
    request_timeout_seconds: float,
) -> dict[str, Any]:
    started_at_perf = time.perf_counter()
    structured_path = _subagent_structured_path(memory_root, agent_name)
    memory_payload = _load_subagent_payload(
        memory_root,
        agent_name,
        include_tasks_should_not_select=include_tasks_should_not_select,
    )
    memory_context = json.dumps(memory_payload, ensure_ascii=True, indent=2)
    allowed_handles = [entry["handle"] for entry in menu_entries]
    subagent_schema = _build_subagent_response_schema(
        allowed_handles,
        allowed_channels,
        include_tasks_should_not_select=include_tasks_should_not_select,
    )
    sub_messages = [
        {
            "role": "system",
            "content": _build_subagent_system_prompt(
                agent_name,
                include_tasks_should_not_select=include_tasks_should_not_select,
            ),
        },
        {
            "role": "user",
            "content": _build_subagent_user_prompt(
                agent_name=agent_name,
                day_name=day_name,
                step=step,
                menu_entries=menu_entries,
                allowed_channels=allowed_channels,
                time_visible_by_default=time_visible_by_default,
                state_observations=state_observations,
                memory_context=memory_context,
                include_tasks_should_not_select=include_tasks_should_not_select,
            ),
        },
    ]

    normalized_payload = None
    error = None
    last_raw_response = "null"
    attempts = 0
    for _ in range(max_invalid_retries + 1):
        attempts += 1
        try:
            response_obj = _call_structured_model(
                client=client,
                model=model,
                messages=sub_messages,
                backend=backend,
                schema_name="subagent_proposal",
                response_schema=subagent_schema,
                temperature=temperature,
                max_tokens=max_tokens,
                return_raw_text=True,
                request_timeout_seconds=request_timeout_seconds,
            )
            payload = response_obj["payload"]
            raw_response = response_obj["raw_text"]
        except Exception as exc:  # noqa: BLE001
            error = f"model_error:{type(exc).__name__}"
            payload = None
            raw_response = getattr(exc, "raw_text", None)
        last_raw_response = _truncate_for_log(raw_response)
        normalized_payload, validation_error = _normalize_subagent_payload(
            payload=payload,
            allowed_handles=allowed_handles,
            allowed_channels=allowed_channels,
            include_tasks_should_not_select=include_tasks_should_not_select,
        )
        if normalized_payload is not None:
            error = None
            break
        error = validation_error or error or "invalid_payload"
        sub_messages.append(
            {
                "role": "assistant",
                "content": json.dumps(payload) if payload is not None else (raw_response or "null"),
            }
        )
        sub_messages.append(
            {
                "role": "user",
                "content": _build_invalid_subagent_msg(
                    include_tasks_should_not_select=include_tasks_should_not_select
                ),
            }
        )

    if normalized_payload is None:
        raise RuntimeError(
            "Subagent failed after retries "
            f"(agent={agent_name}, attempts={attempts}, error={error}, raw_response={last_raw_response})"
        )
    elapsed_ms = (time.perf_counter() - started_at_perf) * 1000.0
    _write_text(
        structured_path,
        json.dumps(
            _build_persisted_subagent_payload(
                normalized_payload,
                agent_name=agent_name,
                day_name=day_name,
                step_id=step["id"],
                step_time=step["time"],
            ),
            ensure_ascii=True,
            indent=2,
        ),
    )
    summary = _summarize_subagent_payload(
        normalized_payload,
        include_tasks_should_not_select=include_tasks_should_not_select,
    )
    parsed: dict[str, Any] = {
        "agent": agent_name,
        "focus": summary["focus"],
        "active_signal_count": summary["active_signal_count"],
        "watchlist": summary["watchlist"],
        "candidate_handles": summary["candidate_handles"],
        "query_suggestions": summary["query_suggestions"],
        "blocking_conditions": summary["blocking_conditions"],
        "state_query_suggestions": normalized_payload["state_query_suggestions"],
        "tasks_might_be_due": normalized_payload["tasks_might_be_due"],
    }
    if include_tasks_should_not_select:
        parsed["tasks_should_not_select"] = normalized_payload.get("tasks_should_not_select", [])
    return {
        "proposal": parsed,
        "runtime": {
            "agent": agent_name,
            "attempts": attempts,
            "elapsed_ms": round(elapsed_ms, 1),
            "fallback_reason": None,
        },
    }


def run_hierarchical_agent(
    scenario: dict[str, Any],
    log_path: str | None,
    model: str,
    backend: str,
    base_url: str | None,
    api_key: str | None,
    num_subagents: int,
    agent_roles: list[str] | None,
    memory_dir: str | None,
    max_time_requests: int,
    max_invalid_retries: int,
    temperature: float,
    max_tokens: int,
    prompt_log_path: str | None,
    debug_log_path: str | None,
    verbose_subagents: bool,
    debug_log_subagent_events: bool,
    score_each_day: bool,
    enable_tasks_should_not_select: bool,
    decision_mode: str = "coordinator_only",
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    run_started_at_utc = _now_iso_utc()
    run_started_perf = time.perf_counter()
    if backend == "sglang" and base_url is None:
        base_url = "http://127.0.0.1:30002/v1"
    client = PM_BENCH.build_llm_client(backend, api_key=api_key, base_url=base_url)
    _preflight_backend_model(client, backend=backend, base_url=base_url, model=model)
    log_entries: list[dict[str, Any]] = []

    runs_dir = PROJECT_ROOT / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    resolved_log_path = _resolve_runs_path(log_path, model, runs_dir, "hier-agent", ".jsonl")
    resolved_prompt_log = _resolve_runs_path(prompt_log_path, model, runs_dir, "hier-agent-prompt", ".log") if prompt_log_path else None
    resolved_debug_log = (
        _resolve_runs_path(debug_log_path, model, runs_dir, "hier-agent-debug", ".jsonl")
        if (debug_log_path or debug_log_subagent_events)
        else None
    )
    _ensure_parent_dir(resolved_log_path)
    _ensure_parent_dir(resolved_prompt_log)
    _ensure_parent_dir(resolved_debug_log)

    if memory_dir is None:
        # Keep subagent memory co-located with this run's log artifacts.
        log_stem = Path(resolved_log_path).stem if resolved_log_path else "hier-agent"
        memory_root = Path(resolved_log_path).parent / f"{log_stem}.memory"
    else:
        candidate = Path(memory_dir)
        memory_root = candidate if candidate.is_absolute() else runs_dir / candidate
    subagent_names = _resolve_subagent_names(num_subagents, agent_roles)
    subagent_names = _init_subagent_memories(
        memory_root,
        subagent_names,
        include_tasks_should_not_select=enable_tasks_should_not_select,
    )

    prompt_log_handle = open(resolved_prompt_log, "w", encoding="utf-8", buffering=1) if resolved_prompt_log else None
    debug_log_handle = open(resolved_debug_log, "w", encoding="utf-8", buffering=1) if resolved_debug_log else None

    state_visibility = PM_BENCH.normalize_state_visibility(scenario)
    state_channels = PM_BENCH.normalize_state_channels(scenario)
    allowed_channels = PM_BENCH.list_state_channels(scenario)
    time_visible_by_default = state_visibility.get("clock", False)
    updates_by_day = PM_BENCH.build_updates_by_day(scenario)
    state_query_counts_by_day: dict[str, dict[str, int]] = {}

    print("=== Hierarchical Agent Run ===")
    print(f"Model: {model} | Backend: {backend}")
    print(f"Subagents: {len(subagent_names)} ({', '.join(subagent_names)}) | Memory dir: {memory_root}")
    print(f"Decision mode: {decision_mode}")
    print(
        "Subagent caution list (tasks_should_not_select): "
        + ("enabled" if enable_tasks_should_not_select else "disabled")
    )
    if verbose_subagents:
        print("Verbose subagent progress: on")
    for line in PM_BENCH.DAILY_TASK_HEADER_LINES:
        print(line)

    for day in scenario["days"]:
        day_log_start_idx = len(log_entries)
        day_start_minutes = PM_BENCH.build_day_start_minutes(day)
        tasks = day["tasks"]
        lure_catalog = PM_BENCH.normalize_lure_catalog(day.get("lures", []))
        active_task_ids = set()
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
                    day_task_states[task_id], update, task_states=day_task_states
                )
        id_to_handle, _ = PM_BENCH.build_day_handle_maps(
            day_task_states,
            lure_catalog,
            seed_key=f"{day['name']}:handles",
        )

        print(f"\n=== {day['name']} ===")
        for line in day.get("start_instructions", []):
            print(line)

        last_query_step_by_channel: dict[str, int] = {}
        last_snapshot_item_by_channel: dict[str, dict[str, Any]] = {}
        coordinator_recent_decisions: list[str] = []

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
            allowed_handles = sorted(step_handle_to_id.keys())

            print(f"\n{step['text']}")
            for option in step["options"]:
                print(option)
            print(PM_BENCH.format_action_menu(menu_entries, header="Step action menu"))
            if time_visible_by_default:
                print(
                    f"Time: {step['time']} | Stopwatch: {step_minutes - day_start_minutes} min"
                )

            check_time_count = 0
            state_query_counts: dict[str, int] = {}
            state_observations: list[str] = []
            step_coordinator_recoveries: list[dict[str, Any]] = []
            force_choose_reason = (
                "State-query phase for this step already executed from de-duplicated subagent suggestions."
            )
            subagent_round_updates: list[dict[str, Any]] = []
            subagent_runtime_by_agent: dict[str, dict[str, Any]] = {}
            subagent_failures: list[str] = []
            selected_subagents = list(subagent_names)
            route_reason = "all_subagents_union_policy"
            proposal_by_agent: dict[str, dict[str, Any]] = {}
            submit_time_by_agent: dict[str, float] = {}

            if len(selected_subagents) <= 1:
                for agent_name in selected_subagents:
                    _emit_subagent_progress(
                        verbose_subagents=verbose_subagents,
                        debug_log_handle=debug_log_handle,
                        debug_log_subagent_events=debug_log_subagent_events,
                        day_name=day["name"],
                        step_id=step["id"],
                        agent_name=agent_name,
                        phase="start",
                    )
                    submit_time = time.perf_counter()
                    try:
                        result = _run_subagent_proposal(
                            client=client,
                            model=model,
                            backend=backend,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            max_invalid_retries=max_invalid_retries,
                            agent_name=agent_name,
                            memory_root=memory_root,
                            day_name=day["name"],
                            step=step,
                            menu_entries=menu_entries,
                            allowed_channels=allowed_channels,
                            time_visible_by_default=time_visible_by_default,
                            state_observations=state_observations,
                            include_tasks_should_not_select=enable_tasks_should_not_select,
                            request_timeout_seconds=request_timeout_seconds,
                        )
                        proposal = result["proposal"]
                        runtime = result["runtime"]
                        proposal_by_agent[agent_name] = proposal
                        subagent_runtime_by_agent[agent_name] = runtime
                        _emit_subagent_progress(
                            verbose_subagents=verbose_subagents,
                            debug_log_handle=debug_log_handle,
                            debug_log_subagent_events=debug_log_subagent_events,
                            day_name=day["name"],
                            step_id=step["id"],
                            agent_name=agent_name,
                            phase="finish",
                            details={
                                "elapsed_ms": runtime["elapsed_ms"],
                                "attempts": runtime["attempts"],
                                "fallback_reason": runtime["fallback_reason"],
                                "focus": proposal["focus"],
                                "signal_count": proposal["active_signal_count"],
                                "watchlist": proposal["watchlist"],
                            },
                        )
                    except Exception as exc:  # noqa: BLE001
                        elapsed_ms = (time.perf_counter() - submit_time) * 1000.0
                        error_text = f"worker_error:{type(exc).__name__}"
                        failure_detail = f"{agent_name}: {error_text}: {exc}"
                        subagent_failures.append(failure_detail)
                        _emit_subagent_progress(
                            verbose_subagents=verbose_subagents,
                            debug_log_handle=debug_log_handle,
                            debug_log_subagent_events=debug_log_subagent_events,
                            day_name=day["name"],
                            step_id=step["id"],
                            agent_name=agent_name,
                            phase="finish",
                            details={
                                "elapsed_ms": round(elapsed_ms, 1),
                                "attempts": 0,
                                "error": error_text,
                            },
                        )
            else:
                with ThreadPoolExecutor(max_workers=len(selected_subagents)) as executor:
                    future_to_agent = {}
                    for agent_name in selected_subagents:
                        _emit_subagent_progress(
                            verbose_subagents=verbose_subagents,
                            debug_log_handle=debug_log_handle,
                            debug_log_subagent_events=debug_log_subagent_events,
                            day_name=day["name"],
                            step_id=step["id"],
                            agent_name=agent_name,
                            phase="start",
                        )
                        submit_time_by_agent[agent_name] = time.perf_counter()
                        future = executor.submit(
                            _run_subagent_proposal,
                            client,
                            model,
                            backend,
                            temperature,
                            max_tokens,
                            max_invalid_retries,
                            agent_name,
                            memory_root,
                            day["name"],
                            step,
                            menu_entries,
                            allowed_channels,
                            time_visible_by_default,
                            state_observations,
                            enable_tasks_should_not_select,
                            request_timeout_seconds,
                        )
                        future_to_agent[future] = agent_name
                    for future in as_completed(future_to_agent):
                        agent_name = future_to_agent[future]
                        try:
                            result = future.result()
                            proposal = result["proposal"]
                            runtime = result["runtime"]
                        except Exception as exc:  # noqa: BLE001
                            elapsed_ms = (
                                time.perf_counter() - submit_time_by_agent[agent_name]
                            ) * 1000.0
                            error_text = f"worker_error:{type(exc).__name__}"
                            failure_detail = f"{agent_name}: {error_text}: {exc}"
                            subagent_failures.append(failure_detail)
                            _emit_subagent_progress(
                                verbose_subagents=verbose_subagents,
                                debug_log_handle=debug_log_handle,
                                debug_log_subagent_events=debug_log_subagent_events,
                                day_name=day["name"],
                                step_id=step["id"],
                                agent_name=agent_name,
                                phase="finish",
                                details={
                                    "elapsed_ms": round(elapsed_ms, 1),
                                    "attempts": 0,
                                    "error": error_text,
                                },
                            )
                            continue
                        proposal_by_agent[agent_name] = proposal
                        subagent_runtime_by_agent[agent_name] = runtime
                        _emit_subagent_progress(
                            verbose_subagents=verbose_subagents,
                            debug_log_handle=debug_log_handle,
                            debug_log_subagent_events=debug_log_subagent_events,
                            day_name=day["name"],
                            step_id=step["id"],
                            agent_name=agent_name,
                            phase="finish",
                            details={
                                "elapsed_ms": runtime["elapsed_ms"],
                                "attempts": runtime["attempts"],
                                "fallback_reason": runtime["fallback_reason"],
                                "focus": proposal["focus"],
                                "signal_count": proposal["active_signal_count"],
                                "watchlist": proposal["watchlist"],
                            },
                        )

            subagent_round_updates = [
                proposal_by_agent[name]
                for name in selected_subagents
                if name in proposal_by_agent
            ]
            if not subagent_round_updates:
                print(
                    f"[subagent] {day['name']} {step['id']} all subagents failed; "
                    "continuing with coordinator-only context."
                )
                for failure in subagent_failures:
                    print(f"[subagent] failure detail: {failure}")
            elif subagent_failures:
                print(
                    f"[subagent] {day['name']} {step['id']} partial failure: "
                    f"{len(subagent_failures)}/{len(selected_subagents)} failed; "
                    f"continuing with {len(subagent_round_updates)}."
                )
                for failure in subagent_failures:
                    print(f"[subagent] failure detail: {failure}")

            union_query_channels: list[str] = []
            for update in subagent_round_updates:
                for suggestion in update["state_query_suggestions"]:
                    channel = suggestion["channel"]
                    if channel in allowed_channels and channel not in union_query_channels:
                        union_query_channels.append(channel)

            union_query_results: list[str] = []
            for channel in union_query_channels:
                state_query_counts[channel] = state_query_counts.get(channel, 0) + 1
                day_state_query_counts[channel] = day_state_query_counts.get(channel, 0) + 1
                if channel == "clock":
                    check_time_count += 1
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
                    channel, items, day["name"], step["id"]
                )
                response_text = PM_BENCH.format_state_query_display(
                    response["channel"], response["items"]
                )
                print(f"Coordinator pre-query (union): {channel}")
                print(response_text)
                state_observations.append(response_text)
                union_query_results.append(response_text)
                coordinator_recent_decisions.append(
                    f"{step['id']}: query {channel} state_queries={_format_channel_counts(state_query_counts)}"
                )

            task_vote_counts, task_vote_majority_handles, task_vote_by_agent = _build_task_vote_summary(
                subagent_round_updates=subagent_round_updates,
                allowed_handles=allowed_handles,
                menu_entries=menu_entries,
            )
            subagent_state_summaries = _build_subagent_state_summaries(
                memory_root,
                subagent_names,
                include_tasks_should_not_select=enable_tasks_should_not_select,
            )
            coord_messages = [
                {
                    "role": "system",
                    "content": _build_coordinator_system_prompt(
                        include_tasks_should_not_select=enable_tasks_should_not_select,
                        decision_mode=decision_mode,
                    ),
                },
                {
                    "role": "user",
                    "content": _build_coordinator_user_prompt(
                        day_name=day["name"],
                        step=step,
                        menu_entries=menu_entries,
                        allowed_channels=allowed_channels,
                        time_visible_by_default=time_visible_by_default,
                        state_observations=state_observations,
                        subagent_round_updates=subagent_round_updates,
                        subagent_failures=subagent_failures,
                        recent_decisions=coordinator_recent_decisions,
                        union_query_channels=union_query_channels,
                        union_query_results=union_query_results,
                        force_choose_reason=force_choose_reason,
                        include_tasks_should_not_select=enable_tasks_should_not_select,
                        decision_mode=decision_mode,
                        task_vote_counts=task_vote_counts,
                        task_vote_majority_handles=task_vote_majority_handles,
                        task_vote_by_agent=task_vote_by_agent,
                    ),
                },
            ]
            if prompt_log_handle:
                prompt_log_handle.write(f"=== {day['name']} {step['id']} ===\n")
                prompt_log_handle.write(json.dumps(coord_messages, indent=2))
                prompt_log_handle.write("\n\n")
                prompt_log_handle.flush()

            coord_schema = PM_BENCH.build_action_schema(allowed_handles, allowed_channels)
            action = None
            action_error = None
            last_coord_payload: Any = None
            coordinator_validation_failures: list[dict[str, Any]] = []
            force_choose_msg = _build_coordinator_force_choose_msg(decision_mode)
            empty_majority_retry_used = False
            for _ in range(max_invalid_retries + 1):
                try:
                    payload = _call_structured_model(
                        client=client,
                        model=model,
                        messages=coord_messages,
                        backend=backend,
                        schema_name="coordinator_action",
                        response_schema=coord_schema,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        request_timeout_seconds=request_timeout_seconds,
                    )
                except Exception as exc:  # noqa: BLE001
                    payload = None
                    action_error = f"model_error:{type(exc).__name__}"
                last_coord_payload = payload
                if decision_mode == "task_vote_only":
                    action, validation_error = _validate_coordinator_choice_only(payload)
                else:
                    action, validation_error = _validate_coordinator_action(
                        payload, allowed_handles, allowed_channels
                    )
                    if action is not None and action["action"] != "choose":
                        action = None
                        validation_error = "force_choose_required"
                    elif (
                        decision_mode == "vote_plus_coordinator"
                        and action is not None
                        and action["action"] == "choose"
                        and not action["task_ids"]
                        and task_vote_majority_handles
                        and not empty_majority_retry_used
                    ):
                        action = None
                        validation_error = "empty_task_ids_with_majority_vote"
                        empty_majority_retry_used = True
                if action is not None:
                    action_error = None
                    break
                action_error = validation_error or action_error or "invalid_payload"
                coordinator_validation_failures.append(
                    {
                        "error": action_error,
                        "payload": payload,
                    }
                )
                coord_messages.append(
                    {
                        "role": "assistant",
                        "content": json.dumps(payload) if payload is not None else "null",
                    }
                )
                if validation_error == "force_choose_required":
                    coord_messages.append(
                        {"role": "user", "content": force_choose_msg}
                    )
                elif validation_error == "empty_task_ids_with_majority_vote":
                    coord_messages.append(
                        {
                            "role": "user",
                            "content": _build_non_empty_task_retry_msg(
                                task_vote_majority_handles
                            ),
                        }
                    )
                else:
                    coord_messages.append(
                        {"role": "user", "content": INVALID_COORDINATOR_MSG}
                    )

            if action is None:
                recovered_action = _build_coordinator_recovery_action(
                    last_payload=last_coord_payload,
                    allowed_handles=allowed_handles,
                    allowed_channels=allowed_channels,
                    force_choose_reason=force_choose_reason,
                )
                recovery_event = {
                    "error": action_error,
                    "last_payload": last_coord_payload,
                    "recovered_action": recovered_action,
                }
                step_coordinator_recoveries.append(recovery_event)
                print(
                    f"[coordinator] recovered invalid action at {day['name']} {step['id']}: "
                    f"{action_error} -> {json.dumps(recovered_action)}"
                )
                action = recovered_action

            raw_coordinator_action = action
            if decision_mode == "task_vote_only":
                # In task_vote_only mode, coordinator chooses only A/B/C.
                action = {
                    "action": "choose",
                    "choice": action["choice"],
                    "task_ids": list(task_vote_majority_handles),
                    "channel": "NONE",
                }
                task_ids_source = "majority_vote"
            else:
                task_ids_source = "coordinator"

            if debug_log_handle:
                debug_payload = {
                    "event": "step_decision",
                    "ts": _now_iso_utc(),
                    "day": day["name"],
                    "step_id": step["id"],
                    "coordinator_action": action,
                    "decision_mode": decision_mode,
                    "task_ids_source": task_ids_source,
                    "task_vote_counts": task_vote_counts,
                    "task_vote_majority_handles": task_vote_majority_handles,
                    "task_vote_by_agent": task_vote_by_agent,
                    "coordinator_raw_action": raw_coordinator_action,
                    "force_choose_reason": force_choose_reason,
                    "union_query_channels": union_query_channels,
                    "union_query_results": union_query_results,
                    "state_observations": state_observations,
                    "router_selected_subagents": selected_subagents,
                    "router_reason": route_reason,
                    # Detailed debug fields are intentionally kept near the end for readability.
                    "subagent_round_updates": subagent_round_updates,
                    "subagent_state_summaries": subagent_state_summaries,
                    "subagent_runtime": [
                        {
                            "agent": name,
                            "attempts": subagent_runtime_by_agent[name]["attempts"],
                            "elapsed_ms": subagent_runtime_by_agent[name]["elapsed_ms"],
                            "fallback_reason": subagent_runtime_by_agent[name]["fallback_reason"],
                        }
                        for name in selected_subagents
                        if name in subagent_runtime_by_agent
                    ],
                    "subagent_failures": subagent_failures,
                    "all_subagents_failed": len(subagent_round_updates) == 0,
                    "coordinator_validation_failures": coordinator_validation_failures,
                    "coordinator_recoveries": step_coordinator_recoveries,
                }
                debug_log_handle.write(
                    json.dumps(debug_payload)
                    + "\n"
                )
                debug_log_handle.flush()

            choice = action["choice"]
            task_ids = [step_handle_to_id[h] for h in action["task_ids"]]
            if task_ids:
                print(f"Coordinator action: choose {choice} + task(s) {', '.join(task_ids)}")
            else:
                print(f"Coordinator action: choose {choice}")

            PM_BENCH.apply_runtime_completions(
                day_task_states,
                task_ids,
                due_now,
                step,
                step_idx,
                step_minutes,
                day_start_minutes,
            )
            log_entries.append(
                {
                    "day": day["name"],
                    "step_id": step["id"],
                    "timestamp_pst": _now_iso_pst(),
                    "choice": choice,
                    "task_ids": task_ids,
                    "check_time": check_time_count,
                    "state_queries": state_query_counts,
                    "subagent_failures": subagent_failures,
                    "all_subagents_failed": len(subagent_round_updates) == 0,
                    "coordinator_recoveries": step_coordinator_recoveries,
                }
            )
            task_handles_text = ",".join(action["task_ids"]) if action["task_ids"] else "-"
            coordinator_recent_decisions.append(
                f"{step['id']}: choose {choice} task_handles={task_handles_text} "
                f"state_queries={_format_channel_counts(state_query_counts)}"
            )
        state_query_counts_by_day[day["name"]] = day_state_query_counts
        if score_each_day:
            day_log_entries = log_entries[day_log_start_idx:]
            day_metrics, day_by_type, _, _, _ = PM_BENCH.score_day(
                day,
                day_log_entries,
                day_updates.get("pre", []),
                day_updates.get("by_step", {}),
                state_visibility,
            )
            day_total_tasks = sum(counts["total"] for counts in day_by_type.values())
            print(f"\n--- Day Score: {day['name']} ---")
            print(
                f"Hit: {day_metrics['hit']} | Late: {day_metrics['late']} | Miss: {day_metrics['miss']} | "
                f"False alarms: {day_metrics['false_alarm']} | Commission: {day_metrics['commission']} | "
                f"Wrong-content: {day_metrics['wrong_content']} | Overkill steps: {day_metrics['overkill_steps']} | "
                f"Actions: {day_metrics['chosen_tasks']}"
            )
            print(
                f"Rates: hit {PM_BENCH.format_rate(day_metrics['hit'], day_total_tasks)} | "
                f"late {PM_BENCH.format_rate(day_metrics['late'], day_total_tasks)} | "
                f"miss {PM_BENCH.format_rate(day_metrics['miss'], day_total_tasks)} | "
                f"precision_hit {PM_BENCH.format_precision(day_metrics['hit'], day_metrics['chosen_tasks'])} | "
                f"precision_any {PM_BENCH.format_precision_any(day_metrics['hit'], day_metrics['late'], day_metrics['chosen_tasks'])}"
            )
            print(f"State queries by channel: {_format_channel_counts(day_state_query_counts)}")

    if prompt_log_handle:
        prompt_log_handle.close()
    if debug_log_handle:
        debug_log_handle.close()

    run_metadata = PM_BENCH.make_run_metadata(
        mode="run-hierarchical-agent",
        started_at_utc=run_started_at_utc,
        finished_at_utc=_now_iso_utc(),
        duration_seconds=time.perf_counter() - run_started_perf,
        entry_count=len(log_entries),
        model=model,
        backend=backend,
    )
    PM_BENCH.write_log(resolved_log_path, log_entries, run_metadata=run_metadata)
    print(f"\nWrote log: {resolved_log_path}")
    print(f"Memory dir: {memory_root}")
    print("State query calls by day/channel:")
    overall_state_query_counts: dict[str, int] = {}
    for day in scenario["days"]:
        day_name = day["name"]
        day_counts = state_query_counts_by_day.get(day_name, {})
        print(f"  {day_name}: {_format_channel_counts(day_counts)}")
        for channel, value in day_counts.items():
            overall_state_query_counts[channel] = overall_state_query_counts.get(channel, 0) + value
    print(f"  Overall: {_format_channel_counts(overall_state_query_counts)}")
    if resolved_debug_log:
        print(f"Debug log: {resolved_debug_log}")
    return log_entries, resolved_log_path, run_metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run PM-Bench with hierarchical subagents.")
    parser.add_argument(
        "--scenario",
        default=str(PROJECT_ROOT / "data" / "synthetic_week_v8.json"),
        help="Scenario JSON path.",
    )
    parser.add_argument("--log", default=None, help="Output action log path (.jsonl).")
    parser.add_argument("--model", default="gpt-5-mini")
    parser.add_argument("--backend", choices=["openai", "openrouter", "sglang"], default="openai")
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override OpenAI-compatible base URL (required for sglang if not default).",
    )
    parser.add_argument("--api-key", default=None, help="API key override.")
    parser.add_argument("--num-subagents", type=int, default=3)
    parser.add_argument(
        "--agent-roles",
        default=None,
        help="Comma-separated subagent role names. If omitted, role names come from --num-subagents.",
    )
    parser.add_argument(
        "--memory-dir",
        default=None,
        help="Directory for subagent JSON memory files. Defaults under runs/.",
    )
    parser.add_argument(
        "--max-time-requests",
        type=int,
        default=5,
        help="Deprecated no-op. State-query caps are disabled.",
    )
    parser.add_argument("--max-invalid-retries", type=int, default=2)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=768)
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        help="Per model API request timeout in seconds.",
    )
    parser.add_argument(
        "--decision-mode",
        choices=["coordinator_only", "task_vote_only", "vote_plus_coordinator"],
        default="coordinator_only",
        help="Decision policy mode.",
    )
    parser.add_argument("--prompt-log", default=None, help="Optional coordinator prompt log (.log).")
    parser.add_argument("--debug-log", default=None, help="Optional debug sidecar log (.jsonl).")
    parser.add_argument(
        "--verbose-subagents",
        action="store_true",
        help="Print per-subagent start/finish progress in terminal.",
    )
    parser.add_argument(
        "--debug-log-subagent-events",
        action="store_true",
        help="Write per-subagent start/finish events to debug log JSONL.",
    )
    parser.add_argument(
        "--score",
        action="store_true",
        help="Score run (prints per-day progress + final report) and write <log>.score.md.",
    )
    parser.add_argument(
        "--disable-tasks-should-not-select",
        dest="disable_tasks_should_not_select",
        action="store_true",
        default=True,
        help=(
            "Disable the subagent tasks_should_not_select channel. "
            "Subagents will only provide state_query_suggestions and tasks_might_be_due. "
            "(default: disabled)"
        ),
    )
    parser.add_argument(
        "--enable-tasks-should-not-select",
        dest="disable_tasks_should_not_select",
        action="store_false",
        help=(
            "Enable the subagent tasks_should_not_select channel."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scenario = PM_BENCH.load_scenario(args.scenario)
    agent_roles = [item.strip() for item in args.agent_roles.split(",")] if args.agent_roles else None
    log_entries, resolved_log_path, run_metadata = run_hierarchical_agent(
        scenario=scenario,
        log_path=args.log,
        model=args.model,
        backend=args.backend,
        base_url=args.base_url,
        api_key=args.api_key,
        num_subagents=args.num_subagents,
        agent_roles=agent_roles,
        memory_dir=args.memory_dir,
        max_time_requests=args.max_time_requests,
        max_invalid_retries=args.max_invalid_retries,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        request_timeout_seconds=args.request_timeout_seconds,
        prompt_log_path=args.prompt_log,
        debug_log_path=args.debug_log,
        verbose_subagents=args.verbose_subagents,
        debug_log_subagent_events=args.debug_log_subagent_events,
        score_each_day=args.score,
        enable_tasks_should_not_select=not args.disable_tasks_should_not_select,
        decision_mode=args.decision_mode,
    )
    if args.score:
        summary, per_day, summary_steps = PM_BENCH.score_log(scenario, log_entries)
        PM_BENCH.print_report(
            summary, per_day, summary_steps, run_metadata=run_metadata
        )
        report_md = PM_BENCH.build_markdown_report(
            summary, per_day, summary_steps, run_metadata=run_metadata
        )
        report_path = str(Path(resolved_log_path).with_suffix(".score.md"))
        with open(report_path, "w", encoding="utf-8") as handle:
            handle.write(report_md)
        print(f"Wrote score report: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
