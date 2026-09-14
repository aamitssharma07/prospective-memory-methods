#!/usr/bin/env python3
"""
Run PM-Bench with a coordinator + subagents architecture.

Design goals for v1:
- Same model instance for coordinator and subagents.
- Structured output for coordinator; markdown notebooks for subagents.
- Subagent memory persisted as markdown files on disk (one latest version each).
- No rolling chat history that accumulates old notebook snapshots.
- PM-Bench-compatible JSONL logs for existing scoring.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
import json
import re
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


def _build_subagent_system_prompt(agent_name: str) -> str:
    role_guidance = SUBAGENT_ROLE_GUIDANCE.get(
        agent_name,
        (
            "- Focus on active PM signals relevant to your assigned role.\n"
            "- Keep notes compact, specific, and current-step grounded."
        ),
    )
    return f"""You are a PM-Bench subagent.
Role identity: {agent_name}

Your role:
1) Keep a compact markdown notebook as persistent memory.
2) Track currently active signals and high-value watch items.
3) Provide structured suggestions for handles/queries/blockers.

Role guidance:
{role_guidance}

Important:
- Do NOT rely on previous chat turns; use the notebook as memory.
- Prefer precision over guessing when uncertain.
- Rewrite the full notebook every step (do not append-only).
- Remove stale items:
  - completed/canceled tasks,
  - cues/windows that already passed,
  - outdated low-value notes.
- Keep only active/relevant signals.

Output markdown only (no JSON, no code fences) with this exact structure:

# Subagent Notebook
## Focus
- one short line
## Active Signals
- up to 5 bullets, each <= 140 chars
## Watchlist
- up to 3 bullets
## Candidate Handles
- up to 3 menu handles like task_1 (or "none")
## Query Suggestions
- up to 3 channels from current step (or "none")
## Blocking Conditions
- up to 3 blockers (or "none")
## Removed This Step
- optional bullets for what was pruned
## Last Updated
- day: <day name>
- step_id: <step id>
- time: <step time>
"""


COORDINATOR_SYSTEM_PROMPT = """You are the coordinator for PM-Bench.
You receive current step context, full subagent notebook snapshots, and
structured subagent signals.
Return one valid PM-Bench action JSON.

Rules:
- action is choose, query_state, or check_time.
- If action is choose: choice must be A/B/C and channel must be NONE.
- If action is query_state/check_time: choice must be NONE and task_ids must be [].
- check_time must use channel=clock.
- task_ids must use action handles from the current menu only.
- Use the JSON key task_ids (do not use task_handles).

Decision policy:
- Subagent notebooks and structured signals provide evidence, not final decisions.
- Use evidence quality and context fit, not majority vote.
- If evidence supports acting on a task and no blocker is present, include that task handle.
- If evidence is weak/conflicting, query targeted state only when it can change the decision.
- If repeated queries give no new information, choose and move forward.
"""


ROUTER_SYSTEM_PROMPT = """You route PM-Bench subagents for the current step.
Select only the subagents likely to add information for this step.
Do not select agents that are unlikely to contribute.

Output strict JSON only with:
- selected_agents: list of agent names
- reason: short rationale
"""


INVALID_SUBAGENT_MSG = (
    "Invalid notebook markdown. Return markdown only with required sections: "
    "Focus, Active Signals, Watchlist, Candidate Handles, Query Suggestions, "
    "Blocking Conditions, Removed This Step, Last Updated."
)

INVALID_COORDINATOR_MSG = (
    "Invalid PM action JSON. Follow the required schema and action constraints."
)

COORDINATOR_FORCE_CHOOSE_MSG = (
    "Repeated state queries produced no new information for this step. "
    "Do not query again now; choose A/B/C to advance."
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


def _call_text_model(
    client,
    model: str,
    messages: list[dict[str, str]],
    backend: str,
    temperature: float,
    max_tokens: int,
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> str:
    supports_temperature = backend in ("sglang", "openrouter") or not model.startswith("gpt-5")
    if backend == "openai":
        if hasattr(client, "responses"):
            response = client.responses.create(
                model=model,
                input=messages,
                timeout=request_timeout_seconds,
            )
            raw_text = response.output_text
            if raw_text is None or not raw_text.strip():
                raise StructuredModelResponseError(
                    "OpenAI Responses API returned empty output_text.",
                    raw_text=None,
                )
        else:
            kwargs = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
            }
            if supports_temperature:
                kwargs["temperature"] = temperature
            raw_text = _chat_completion_with_retries(
                client,
                kwargs,
                backend,
                attempts=2,
                request_timeout_seconds=request_timeout_seconds,
            )
    elif backend == "sglang":
        kwargs = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        }
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
    return raw_text


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


def _subagent_memory_path(memory_dir: Path, agent_name: str) -> Path:
    return memory_dir / f"{agent_name}.md"


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


MAX_SUBAGENT_NOTEBOOK_CHARS = 1800
MAX_SUBAGENT_NOTEBOOK_LINES = 70
REQUIRED_NOTEBOOK_HEADERS = [
    "# Subagent Notebook",
    "## Focus",
    "## Active Signals",
    "## Watchlist",
    "## Candidate Handles",
    "## Query Suggestions",
    "## Blocking Conditions",
    "## Removed This Step",
    "## Last Updated",
]


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _truncate_multiline(text: str, max_chars: int, max_lines: int) -> str:
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    trimmed = "\n".join(lines)
    if len(trimmed) > max_chars:
        trimmed = trimmed[:max_chars]
        if "\n" in trimmed:
            trimmed = trimmed.rsplit("\n", 1)[0]
    return trimmed.strip()


def _extract_section_lines(markdown: str, header: str) -> list[str]:
    lines = markdown.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.strip() == header:
            start = idx + 1
            break
    if start is None:
        return []
    section: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        section.append(line.rstrip())
    return section


def _normalize_subagent_markdown(markdown: str) -> str:
    clean = _strip_code_fence(markdown)
    clean = _truncate_multiline(
        clean,
        max_chars=MAX_SUBAGENT_NOTEBOOK_CHARS,
        max_lines=MAX_SUBAGENT_NOTEBOOK_LINES,
    )
    if not clean:
        clean = "# Subagent Notebook\n"
    return clean + ("\n" if not clean.endswith("\n") else "")


def _clip_bullets(section_lines: list[str], max_items: int, max_chars: int) -> list[str]:
    items: list[str] = []
    for line in section_lines:
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        text = stripped[1:].strip()
        if not text:
            continue
        if len(text) > max_chars:
            text = text[:max_chars].rstrip()
        items.append(f"- {text}")
        if len(items) >= max_items:
            break
    return items


def _compact_subagent_notebook(markdown: str, day_name: str, step_id: str, step_time: str) -> str:
    focus = _clip_bullets(_extract_section_lines(markdown, "## Focus"), max_items=1, max_chars=120)
    active = _clip_bullets(_extract_section_lines(markdown, "## Active Signals"), max_items=5, max_chars=140)
    watch = _clip_bullets(_extract_section_lines(markdown, "## Watchlist"), max_items=3, max_chars=60)
    candidate_handles = _clip_bullets(
        _extract_section_lines(markdown, "## Candidate Handles"), max_items=3, max_chars=50
    )
    query_suggestions = _clip_bullets(
        _extract_section_lines(markdown, "## Query Suggestions"), max_items=3, max_chars=60
    )
    blocking_conditions = _clip_bullets(
        _extract_section_lines(markdown, "## Blocking Conditions"), max_items=3, max_chars=140
    )
    removed = _clip_bullets(_extract_section_lines(markdown, "## Removed This Step"), max_items=5, max_chars=140)

    if not focus:
        focus = ["- keep active PM cues and prune stale notes"]
    if not active:
        active = ["- none"]
    if not watch:
        watch = ["- none"]
    if not candidate_handles:
        candidate_handles = ["- none"]
    if not query_suggestions:
        query_suggestions = ["- none"]
    if not blocking_conditions:
        blocking_conditions = ["- none"]
    if not removed:
        removed = ["- none"]

    compact = (
        "# Subagent Notebook\n"
        "## Focus\n"
        + "\n".join(focus)
        + "\n## Active Signals\n"
        + "\n".join(active)
        + "\n## Watchlist\n"
        + "\n".join(watch)
        + "\n## Candidate Handles\n"
        + "\n".join(candidate_handles)
        + "\n## Query Suggestions\n"
        + "\n".join(query_suggestions)
        + "\n## Blocking Conditions\n"
        + "\n".join(blocking_conditions)
        + "\n## Removed This Step\n"
        + "\n".join(removed)
        + "\n## Last Updated\n"
        + f"- day: {day_name}\n"
        + f"- step_id: {step_id}\n"
        + f"- time: {step_time}\n"
    )
    return _normalize_subagent_markdown(compact)


def _validate_subagent_markdown(markdown: str) -> tuple[bool, str | None]:
    for header in REQUIRED_NOTEBOOK_HEADERS:
        if header not in markdown:
            return False, f"missing_header:{header}"
    return True, None


def _summarize_subagent_markdown(markdown: str) -> dict[str, Any]:
    focus_lines = [ln for ln in _extract_section_lines(markdown, "## Focus") if ln.strip().startswith("-")]
    active_lines = [ln for ln in _extract_section_lines(markdown, "## Active Signals") if ln.strip().startswith("-")]
    watch_lines = [ln for ln in _extract_section_lines(markdown, "## Watchlist") if ln.strip().startswith("-")]
    handle_lines = [
        ln for ln in _extract_section_lines(markdown, "## Candidate Handles") if ln.strip().startswith("-")
    ]
    query_lines = [
        ln for ln in _extract_section_lines(markdown, "## Query Suggestions") if ln.strip().startswith("-")
    ]
    blocker_lines = [
        ln for ln in _extract_section_lines(markdown, "## Blocking Conditions") if ln.strip().startswith("-")
    ]
    watchlist = []
    for line in watch_lines[:3]:
        value = line[1:].strip()
        if value.lower() in ("none", "(none)"):
            continue
        watchlist.append(value)
    candidate_handles: list[str] = []
    for line in handle_lines[:3]:
        for token in re.findall(r"\btask_\d+\b", line):
            if token not in candidate_handles:
                candidate_handles.append(token)
    query_suggestions: list[str] = []
    for line in query_lines[:3]:
        value = line[1:].strip()
        if not value or value.lower() in ("none", "(none)"):
            continue
        query_suggestions.append(value.split()[0].strip(",.;:"))
    blocking_conditions: list[str] = []
    for line in blocker_lines[:3]:
        value = line[1:].strip()
        if not value or value.lower() in ("none", "(none)"):
            continue
        blocking_conditions.append(value)
    return {
        "focus": focus_lines[0][1:].strip() if focus_lines else "",
        "active_signal_count": len([ln for ln in active_lines if ln[1:].strip().lower() != "none"]),
        "watchlist": watchlist,
        "candidate_handles": candidate_handles[:3],
        "query_suggestions": query_suggestions[:3],
        "blocking_conditions": blocking_conditions[:3],
    }


def _load_subagent_notebooks(memory_root: Path, subagent_names: list[str]) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for agent_name in subagent_names:
        markdown = _read_text(_subagent_memory_path(memory_root, agent_name))
        normalized = _normalize_subagent_markdown(markdown)
        summary = _summarize_subagent_markdown(normalized)
        docs.append(
            {
                "agent": agent_name,
                "memory_markdown": normalized,
                "focus": summary["focus"],
                "active_signal_count": summary["active_signal_count"],
                "watchlist": summary["watchlist"],
                "candidate_handles": summary["candidate_handles"],
                "query_suggestions": summary["query_suggestions"],
                "blocking_conditions": summary["blocking_conditions"],
            }
        )
    return docs


def _init_subagent_memories(memory_dir: Path, subagent_names: list[str]) -> list[str]:
    memory_dir.mkdir(parents=True, exist_ok=True)
    names = list(subagent_names)
    for name in names:
        path = _subagent_memory_path(memory_dir, name)
        if not path.exists():
            template = (
                "# Subagent Notebook\n"
                "## Focus\n"
                "- initialize focus\n"
                "## Active Signals\n"
                "- none\n"
                "## Watchlist\n"
                "- none\n"
                "## Candidate Handles\n"
                "- none\n"
                "## Query Suggestions\n"
                "- none\n"
                "## Blocking Conditions\n"
                "- none\n"
                "## Removed This Step\n"
                "- none\n"
                "## Last Updated\n"
                "- day: unknown\n"
                "- step_id: unknown\n"
                "- time: unknown\n"
            )
            _write_text(path, template)
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


def _build_router_user_prompt(
    day_name: str,
    step: dict[str, Any],
    menu_entries: list[dict[str, str]],
    allowed_channels: list[str],
    state_observations: list[str],
    subagent_docs: list[dict[str, Any]],
    recent_decisions: list[str],
) -> str:
    observations = "\n".join(f"- {line}" for line in state_observations) if state_observations else "- (none)"
    agent_lines = []
    for doc in subagent_docs:
        focus = doc["focus"] or "(empty)"
        agent_lines.append(f"- {doc['agent']}: focus={focus} active_signals={doc['active_signal_count']}")
    agents_text = "\n".join(agent_lines) if agent_lines else "- (none)"
    recent_text = "\n".join(f"- {line}" for line in recent_decisions[-6:]) if recent_decisions else "- (none)"
    channels_line = ", ".join(allowed_channels) if allowed_channels else "(none)"
    return (
        f"Day: {day_name}\n"
        f"Step ID: {step['id']}\n"
        f"Step time: {step['time']}\n\n"
        f"Step text:\n{step['text']}\n\n"
        f"Options:\n" + "\n".join(step["options"]) + "\n\n"
        f"Current action menu:\n{_format_step_menu(menu_entries)}\n\n"
        f"Observed state responses this step:\n{observations}\n\n"
        f"Available channels:\n{channels_line}\n\n"
        f"Recent coordinator decisions:\n{recent_text}\n\n"
        f"Subagents and latest notebook summaries:\n{agents_text}\n\n"
        "Select only subagents likely to add new information for this step."
    )


def _select_subagents_for_step(
    client,
    model: str,
    backend: str,
    temperature: float,
    max_tokens: int,
    request_timeout_seconds: float,
    max_invalid_retries: int,
    day_name: str,
    step: dict[str, Any],
    menu_entries: list[dict[str, str]],
    allowed_channels: list[str],
    state_observations: list[str],
    subagent_docs: list[dict[str, Any]],
    recent_decisions: list[str],
    subagent_names: list[str],
) -> tuple[list[str], str]:
    if not subagent_names:
        return [], "no_subagents_configured"
    schema = {
        "type": "object",
        "properties": {
            "selected_agents": {
                "type": "array",
                "items": {"type": "string", "enum": subagent_names},
                "minItems": 1,
            },
            "reason": {"type": "string"},
        },
        "required": ["selected_agents", "reason"],
        "additionalProperties": False,
    }
    messages = [
        {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _build_router_user_prompt(
                day_name=day_name,
                step=step,
                menu_entries=menu_entries,
                allowed_channels=allowed_channels,
                state_observations=state_observations,
                subagent_docs=subagent_docs,
                recent_decisions=recent_decisions,
            ),
        },
    ]
    for _ in range(max_invalid_retries + 1):
        try:
            payload = _call_structured_model(
                client=client,
                model=model,
                messages=messages,
                backend=backend,
                schema_name="subagent_router",
                response_schema=schema,
                temperature=temperature,
                max_tokens=max_tokens,
                request_timeout_seconds=request_timeout_seconds,
            )
        except Exception:
            payload = {}
        selected = payload.get("selected_agents")
        reason = payload.get("reason")
        if isinstance(selected, list) and isinstance(reason, str):
            deduped = [name for name in subagent_names if name in selected]
            if deduped:
                return deduped, reason.strip() or "selected_by_router"
        messages.append({"role": "assistant", "content": json.dumps(payload) if payload else "null"})
        messages.append(
            {
                "role": "user",
                "content": "Invalid router output. Return JSON with non-empty selected_agents and reason.",
            }
        )
    return list(subagent_names), "router_fallback_all"


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
    notebook_markdown: str,
) -> str:
    observations = "\n".join(f"- {line}" for line in state_observations) if state_observations else "- (none)"
    channels_line = ", ".join(allowed_channels)
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
        "Update instruction:\n"
        "- Rewrite the full notebook markdown for this step.\n"
        "- Keep only active signals; remove stale/past/completed items.\n"
        "- Be concise (max 5 active signals, max 3 watchlist items).\n"
        "- Fill Candidate Handles with task_n handles only when supported by evidence.\n"
        "- Fill Query Suggestions with channels only when a query can change a decision.\n"
        "- Fill Blocking Conditions when dependency/cancel/override risk is present.\n"
        "- Output markdown only (no JSON, no code fences).\n\n"
        "Current notebook markdown:\n"
        f"{notebook_markdown}\n"
    )


def _build_coordinator_user_prompt(
    day_name: str,
    step: dict[str, Any],
    menu_entries: list[dict[str, str]],
    allowed_channels: list[str],
    time_visible_by_default: bool,
    state_observations: list[str],
    subagent_docs: list[dict[str, Any]],
    subagent_round_updates: list[dict[str, Any]],
    subagent_failures: list[str],
    recent_decisions: list[str],
    force_choose_reason: str | None,
) -> str:
    observations = "\n".join(f"- {line}" for line in state_observations) if state_observations else "- (none)"
    recommended_query_channels: list[str] = []
    updates_lines = []
    for update in subagent_round_updates:
        watchlist_text = ", ".join(update["watchlist"]) if update["watchlist"] else "(none)"
        handle_text = ", ".join(update["candidate_handles"]) if update["candidate_handles"] else "(none)"
        query_text = ", ".join(update["query_suggestions"]) if update["query_suggestions"] else "(none)"
        blocker_text = " | ".join(update["blocking_conditions"]) if update["blocking_conditions"] else "(none)"
        for channel in update["query_suggestions"]:
            if channel not in recommended_query_channels:
                recommended_query_channels.append(channel)
        updates_lines.append(
            f"- {update['agent']}: focus={update['focus'] or '(empty)'} "
            f"active_signals={update['active_signal_count']} watchlist={watchlist_text} "
            f"candidate_handles={handle_text} query_suggestions={query_text} blockers={blocker_text}"
        )
    updates_text = "\n".join(updates_lines) if updates_lines else "- (none)"
    preferred_channels_text = (
        ", ".join(recommended_query_channels) if recommended_query_channels else "(none)"
    )

    notebook_lines = []
    for doc in subagent_docs:
        prompt_markdown = _truncate_multiline(doc["memory_markdown"], max_chars=1200, max_lines=45)
        notebook_lines.append(f"### {doc['agent']}\n{prompt_markdown}")
    notebooks_text = "\n\n".join(notebook_lines) if notebook_lines else "(none)"
    failures_text = "\n".join(f"- {line}" for line in subagent_failures) if subagent_failures else "- (none)"
    recent_text = "\n".join(f"- {line}" for line in recent_decisions[-8:]) if recent_decisions else "- (none)"
    channels_line = ", ".join(allowed_channels)
    force_choose_text = (
        f"\nCoordinator constraint:\n- {force_choose_reason}\n"
        if force_choose_reason
        else ""
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
        f"Preferred query channels from subagents this round:\n- {preferred_channels_text}\n\n"
        f"Recent finalized coordinator decisions (same day):\n{recent_text}\n\n"
        f"Subagent failures this round:\n{failures_text}\n\n"
        f"Subagent update summaries this round:\n{updates_text}\n\n"
        f"Subagent notebook snapshots (latest from disk):\n{notebooks_text}\n\n"
        f"{force_choose_text}"
    )


def _now_iso_utc() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


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
    request_timeout_seconds: float,
    max_invalid_retries: int,
    agent_name: str,
    memory_root: Path,
    day_name: str,
    step: dict[str, Any],
    menu_entries: list[dict[str, str]],
    allowed_channels: list[str],
    time_visible_by_default: bool,
    state_observations: list[str],
) -> dict[str, Any]:
    started_at_perf = time.perf_counter()
    notebook_path = _subagent_memory_path(memory_root, agent_name)
    notebook_markdown = _normalize_subagent_markdown(_read_text(notebook_path))
    sub_messages = [
        {"role": "system", "content": _build_subagent_system_prompt(agent_name)},
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
                notebook_markdown=notebook_markdown,
            ),
        },
    ]

    normalized_markdown = None
    error = None
    last_raw_response = "null"
    attempts = 0
    for _ in range(max_invalid_retries + 1):
        attempts += 1
        try:
            raw_response = _call_text_model(
                client=client,
                model=model,
                messages=sub_messages,
                backend=backend,
                temperature=temperature,
                max_tokens=max_tokens,
                request_timeout_seconds=request_timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            error = f"model_error:{type(exc).__name__}"
            raw_response = getattr(exc, "raw_text", None)
        last_raw_response = _truncate_for_log(raw_response)
        candidate = _normalize_subagent_markdown(raw_response or "")
        valid, validation_error = _validate_subagent_markdown(candidate)
        if valid:
            error = None
            normalized_markdown = _compact_subagent_notebook(
                candidate,
                day_name=day_name,
                step_id=step["id"],
                step_time=step["time"],
            )
            break
        error = validation_error or error or "invalid_payload"
        sub_messages.append(
            {
                "role": "assistant",
                "content": raw_response or "",
            }
        )
        sub_messages.append({"role": "user", "content": INVALID_SUBAGENT_MSG})

    if normalized_markdown is None:
        raise RuntimeError(
            "Subagent failed after retries "
            f"(agent={agent_name}, attempts={attempts}, error={error}, raw_response={last_raw_response})"
        )
    elapsed_ms = (time.perf_counter() - started_at_perf) * 1000.0
    _write_text(notebook_path, normalized_markdown)
    summary = _summarize_subagent_markdown(normalized_markdown)
    parsed = {
        "agent": agent_name,
        "memory_markdown": normalized_markdown,
        "focus": summary["focus"],
        "active_signal_count": summary["active_signal_count"],
        "watchlist": summary["watchlist"],
        "candidate_handles": summary["candidate_handles"],
        "query_suggestions": summary["query_suggestions"],
        "blocking_conditions": summary["blocking_conditions"],
    }
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
        ts = datetime.now().strftime("%Y%m%d-%H%M")
        memory_root = runs_dir / f"hier-memory-{ts}-{_sanitize_model_label(model)}"
    else:
        candidate = Path(memory_dir)
        memory_root = candidate if candidate.is_absolute() else runs_dir / candidate
    subagent_names = _resolve_subagent_names(num_subagents, agent_roles)
    subagent_names = _init_subagent_memories(memory_root, subagent_names)

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
            force_choose_reason: str | None = None
            last_query_response_by_channel: dict[str, str] = {}
            repeated_identical_query_count_by_channel: dict[str, int] = {}
            no_new_info_query_streak = 0
            step_coordinator_recoveries: list[dict[str, Any]] = []

            while True:
                subagent_round_updates: list[dict[str, Any]] = []
                subagent_runtime_by_agent: dict[str, dict[str, Any]] = {}
                subagent_failures: list[str] = []
                pre_route_docs = _load_subagent_notebooks(memory_root, subagent_names)
                selected_subagents, route_reason = _select_subagents_for_step(
                    client=client,
                    model=model,
                    backend=backend,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    request_timeout_seconds=request_timeout_seconds,
                    max_invalid_retries=max_invalid_retries,
                    day_name=day["name"],
                    step=step,
                    menu_entries=menu_entries,
                    allowed_channels=allowed_channels,
                    state_observations=state_observations,
                    subagent_docs=pre_route_docs,
                    recent_decisions=coordinator_recent_decisions,
                    subagent_names=subagent_names,
                )
                if verbose_subagents:
                    print(
                        f"[router] {day['name']} {step['id']} selected="
                        f"{','.join(selected_subagents)} reason={route_reason}"
                    )

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
                                request_timeout_seconds=request_timeout_seconds,
                                max_invalid_retries=max_invalid_retries,
                                agent_name=agent_name,
                                memory_root=memory_root,
                                day_name=day["name"],
                                step=step,
                                menu_entries=menu_entries,
                                allowed_channels=allowed_channels,
                                time_visible_by_default=time_visible_by_default,
                                state_observations=state_observations,
                            )
                            proposal = result["proposal"]
                            runtime = result["runtime"]
                            subagent_round_updates.append(proposal)
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
                    proposal_by_agent: dict[str, dict[str, Any]] = {}
                    submit_time_by_agent: dict[str, float] = {}
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
                                request_timeout_seconds,
                                max_invalid_retries,
                                agent_name,
                                memory_root,
                                day["name"],
                                step,
                                menu_entries,
                                allowed_channels,
                                time_visible_by_default,
                                state_observations,
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
                subagent_docs = _load_subagent_notebooks(memory_root, subagent_names)

                coord_messages = [
                    {"role": "system", "content": COORDINATOR_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": _build_coordinator_user_prompt(
                            day_name=day["name"],
                            step=step,
                            menu_entries=menu_entries,
                            allowed_channels=allowed_channels,
                            time_visible_by_default=time_visible_by_default,
                            state_observations=state_observations,
                            subagent_docs=subagent_docs,
                            subagent_round_updates=subagent_round_updates,
                            subagent_failures=subagent_failures,
                            recent_decisions=coordinator_recent_decisions,
                            force_choose_reason=force_choose_reason,
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
                    action, validation_error = _validate_coordinator_action(
                        payload, allowed_handles, allowed_channels
                    )
                    if (
                        action is not None
                        and force_choose_reason is not None
                        and action["action"] != "choose"
                    ):
                        action = None
                        validation_error = "force_choose_required"
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
                            {"role": "user", "content": COORDINATOR_FORCE_CHOOSE_MSG}
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

                if debug_log_handle:
                    debug_log_handle.write(
                        json.dumps(
                            {
                                "event": "step_decision",
                                "ts": _now_iso_utc(),
                                "day": day["name"],
                                "step_id": step["id"],
                                "router_selected_subagents": selected_subagents,
                                "router_reason": route_reason,
                                "subagent_round_updates": [
                                    {
                                        "agent": update["agent"],
                                        "focus": update["focus"],
                                        "active_signal_count": update["active_signal_count"],
                                        "watchlist": update["watchlist"],
                                        "candidate_handles": update["candidate_handles"],
                                        "query_suggestions": update["query_suggestions"],
                                        "blocking_conditions": update["blocking_conditions"],
                                    }
                                    for update in subagent_round_updates
                                ],
                                "subagent_notebook_summaries": [
                                    {
                                        "agent": doc["agent"],
                                        "focus": doc["focus"],
                                        "active_signal_count": doc["active_signal_count"],
                                        "watchlist": doc["watchlist"],
                                        "candidate_handles": doc["candidate_handles"],
                                        "query_suggestions": doc["query_suggestions"],
                                        "blocking_conditions": doc["blocking_conditions"],
                                        "chars": len(doc["memory_markdown"]),
                                    }
                                    for doc in subagent_docs
                                ],
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
                                "coordinator_action": action,
                                "state_observations": state_observations,
                                "force_choose_reason": force_choose_reason,
                            }
                        )
                        + "\n"
                    )
                    debug_log_handle.flush()

                if action["action"] in ("check_time", "query_state"):
                    channel = "clock" if action["action"] == "check_time" else action["channel"]
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
                    print(f"Coordinator action: query_state {channel}")
                    print(response_text)
                    prev_text = last_query_response_by_channel.get(channel)
                    if prev_text == response_text:
                        repeat_count = repeated_identical_query_count_by_channel.get(channel, 0) + 1
                        repeated_identical_query_count_by_channel[channel] = repeat_count
                        no_new_info_query_streak += 1
                        if repeat_count >= 1 or no_new_info_query_streak >= 2:
                            force_choose_reason = (
                                f"Channel '{channel}' returned identical responses repeatedly "
                                f"({repeat_count + 1} times) in this step."
                            )
                            state_observations.append(
                                f"No-new-info warning for {channel}: repeated identical responses."
                            )
                    else:
                        last_query_response_by_channel[channel] = response_text
                        repeated_identical_query_count_by_channel[channel] = 0
                        no_new_info_query_streak = 0
                        force_choose_reason = None
                        state_observations.append(response_text)
                    coordinator_recent_decisions.append(
                        f"{step['id']}: query {channel} "
                        f"state_queries={_format_channel_counts(state_query_counts)} "
                        f"force_choose={'yes' if force_choose_reason else 'no'}"
                    )
                    continue

                choice = action["choice"]
                force_choose_reason = None
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
                break
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
        help="Directory for subagent markdown memory files. Defaults under runs/.",
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
