"""
MemorySession: the only PM-Bench integration glue.

Hooks `pm_bench.request_model_action` for the duration of one run:

  1. Strip any prior memory injection from `messages`
  2. RECALL from backend using the current vignette
  3. Build a *compact* prompt (no full-week history by default)
  4. Append one `[Relevant_memories]` user message
  5. Call the original decision API
  6. Restore the full transcript for run_llm bookkeeping
  7. On choose → ENCODE the turn

Memory failures log and continue with empty memory so a bad judge
does not abort the whole week.
"""

from __future__ import annotations

import copy
import json
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from llm_cost import cost_role

from .common import (
    INTENTION_MEMORY_INJECT_HEADER,
    MEMORY_MARKER,
    PMA_MEMORY_INJECT_HEADER,
    MemoryBackend,
    build_compact_messages,
    extract_step_clock,
    format_memory_injection,
    strip_abc_options,
    strip_action_menu,
)

_CALENDAR_DAY_RE = re.compile(
    r"^(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{1,2}$",
    re.I,
)
# Isolated month track: leftover pending makes the model query forever.
# Weekday weeks never match _CALENDAR_DAY_RE, so the 7-day experiment is unchanged.
_CALENDAR_QUERY_CAP = 12


class MemorySession:
    def __init__(
        self,
        backend: MemoryBackend,
        *,
        top_k: int = 10,
        log_path: str | None = None,
        keep_full_history: bool = False,
        force_check_time: bool = True,
        force_query_channels: bool = False,
        gate_time_due: bool = False,
    ):
        self.backend = backend
        self.top_k = top_k
        self.log_path = log_path
        self.keep_full_history = keep_full_history
        # Intention: if no trusted clock but pending time tasks exist, override
        # non-clock actions to check_time (legitimate channel, not GT leak).
        self.force_check_time = force_check_time
        # Ablation (cheating-adjacent): force CHECK query_state; strip TIME-WAIT picks.
        self.force_query_channels = force_query_channels
        self.gate_time_due = gate_time_due
        self._log_handle = None
        self._day = ""
        self._step = ""
        self._time = ""
        self._observation = ""
        self._step_raw = ""  # vignette + menu (for resolving task_N → labels)
        self._step_seq = 0
        self._calendar_queries = 0
        self._last_vignette = ""
        # Exact payload sent to the model (for prompt.txt after restore).
        self.last_sent_messages: list[dict] | None = None

    def open(self) -> None:
        if self.log_path:
            Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = open(self.log_path, "a", encoding="utf-8", buffering=1)

    def close(self) -> None:
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def _log(self, event: dict[str, Any]) -> None:
        if self._log_handle is not None:
            self._log_handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            self._log_handle.flush()

    def wrap(self, original_request):
        session = self

        def request_model_action(
            client,
            model,
            messages,
            allowed_task_ids,
            allowed_channels,
            backend,
            allow_heartbeat=False,
            max_tokens=256,
            response_format_mode="json_schema",
        ):
            clean = [
                m
                for m in messages
                if not (
                    isinstance(m, dict)
                    and m.get("role") == "user"
                    and isinstance(m.get("content"), str)
                    and MEMORY_MARKER in m["content"]
                )
            ]
            day, step, time_str, observation, step_raw = _parse_context(clean)
            if day and day != session._day:
                session._day = day
                session._step_seq = 0
                session._calendar_queries = 0
                session._last_vignette = ""
                session._time = ""  # prior-day clock evidence must not leak
            # PM-Bench never puts step_id in the model-visible prompt (only in
            # prompt_log headers). Synthesize a stable per-day step key from
            # vignette changes so encode metadata is not blank.
            if observation and observation != session._last_vignette:
                session._last_vignette = observation
                session._step_seq += 1
                session._calendar_queries = 0
                # Previous step's check_time must not count as this step's clock.
                session._time = ""
            if not step and session._step_seq:
                step = f"s{session._step_seq}"
            # Only this-step Time: / State [clock] counts. Do not reuse a
            # prior-step session._time when the current vignette has no clock.
            session._time = time_str
            session._day = day or session._day
            session._step = step
            session._observation = observation
            session._step_raw = step_raw or observation

            # Retrieve with narrative-only query (no A/B/C noise).
            recall_query = strip_abc_options(observation) or _fallback_query(clean)
            memory_text = ""
            try:
                recall_kwargs = {"top_k": session.top_k}
                # Intention / PMA need clock, menu, and channel replies — not
                # just a semantic query string.
                if getattr(session.backend, "uses_step_context", False) or getattr(
                    session.backend, "name", ""
                ) in ("intention", "pma"):
                    recall_kwargs["context"] = {
                        "day": session._day,
                        "step": session._step,
                        "time": session._time,
                        "observation": observation,
                        "step_raw": session._step_raw,
                        "messages": clean,
                    }
                with cost_role("memory"):
                    memory_text = session.backend.recall(
                        recall_query, **recall_kwargs
                    )
                info = getattr(session.backend, "last_recall_info", None) or {}
                session._log(
                    {
                        "event": "recall",
                        "backend": session.backend.name,
                        "day": session._day,
                        "step": session._step,
                        "time": session._time,
                        "query_chars": len(recall_query or ""),
                        "memory_chars": len(memory_text or ""),
                        "memory_preview": (memory_text or "")[:240],
                        "memory_text": memory_text or "",
                        "compact_prompt": not session.keep_full_history,
                        **{f"recall_{k}": v for k, v in info.items()},
                    }
                )
            except Exception as exc:
                session._log(
                    {
                        "event": "recall_error",
                        "backend": session.backend.name,
                        "day": session._day,
                        "step": session._step,
                        "time": session._time,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                memory_text = ""

            # Full transcript must keep growing for encode/day tracking, but the
            # model should see a compact window + memories (unless opted out).
            full_snapshot = copy.deepcopy(clean)
            if session.keep_full_history:
                api_messages = copy.deepcopy(clean)
            else:
                # Intention already seeded the morning list; keep === Day ===
                # so weekday is known, drop stale when-clauses. Other backends
                # still need the plan in the prompt.
                api_messages = build_compact_messages(
                    clean,
                    include_day_plan=getattr(session.backend, "name", "")
                    != "intention",
                )
            backend_name = getattr(session.backend, "name", "")
            custom_header = getattr(session.backend, "memory_inject_header", None)
            if custom_header:
                inject_header = custom_header
            elif backend_name == "intention":
                inject_header = INTENTION_MEMORY_INJECT_HEADER
            elif backend_name == "pma":
                inject_header = PMA_MEMORY_INJECT_HEADER
            else:
                inject_header = None
            api_messages.append(
                {
                    "role": "user",
                    "content": format_memory_injection(
                        memory_text, header=inject_header
                    ),
                }
            )
            session.last_sent_messages = copy.deepcopy(api_messages)

            # Temporarily expose API payload on the shared list so any in-call
            # logging sees what was sent; restore full history afterwards.
            messages[:] = api_messages
            try:
                with cost_role("choose"):
                    action = original_request(
                        client,
                        model,
                        messages,
                        allowed_task_ids,
                        allowed_channels,
                        backend,
                        allow_heartbeat=allow_heartbeat,
                        max_tokens=max_tokens,
                        response_format_mode=response_format_mode,
                    )
            finally:
                messages[:] = full_snapshot

            # Hard gate: unknown clock + pending time intentions ⇒ must check_time
            # before choose / other channels (still a normal PM-Bench action).
            info = getattr(session.backend, "last_recall_info", None) or {}
            if (
                session.force_check_time
                and getattr(session.backend, "name", "") == "intention"
                and info.get("force_check_time")
                and isinstance(action, dict)
                and not _is_clock_query(action)
            ):
                forced = {
                    "action": "check_time",
                    "choice": "NONE",
                    "task_ids": [],
                    "channel": "clock",
                }
                session._log(
                    {
                        "event": "force_check_time",
                        "backend": session.backend.name,
                        "day": session._day,
                        "step": session._step,
                        "time": session._time,
                        "pending_time": info.get("pending_time"),
                        "model_action": action.get("action"),
                        "model_channel": action.get("channel"),
                    }
                )
                action = forced

            # CHECK: prompt lists union of watch; only --force-query-channels
            # rewrites choose (cadence rewrite removed).
            needed = [
                str(c).strip()
                for c in (info.get("channel_needed") or [])
                if str(c).strip() and str(c).strip().lower() != "clock"
            ]
            if allowed_channels:
                allow = {str(c).strip().lower() for c in allowed_channels}
                needed = [c for c in needed if c.lower() in allow]
            if (
                session.force_query_channels
                and getattr(session.backend, "name", "") == "intention"
                and needed
                and isinstance(action, dict)
                and not info.get("force_check_time")
                and not _is_needed_channel_query(action, needed)
            ):
                forced_ch = {
                    "action": "query_state",
                    "choice": "NONE",
                    "task_ids": [],
                    "channel": needed[0],
                }
                session._log(
                    {
                        "event": "force_query_channel",
                        "backend": session.backend.name,
                        "day": session._day,
                        "step": session._step,
                        "time": session._time,
                        "channel": needed[0],
                        "needed": needed,
                        "model_action": action.get("action"),
                        "model_channel": action.get("channel"),
                    }
                )
                action = forced_ch

            # Ablation-only: after CHECK is empty, do not re-query a channel
            # already seen this step (PM-Bench has no per-channel cap).
            if (
                getattr(session.backend, "ignore_status", False)
                and getattr(session.backend, "name", "") == "intention"
                and isinstance(action, dict)
                and action.get("action") == "query_state"
                and not info.get("force_check_time")
            ):
                ch = str(action.get("channel") or "").strip().lower()
                queried = {
                    str(x).strip().lower()
                    for x in (info.get("match_queried") or [])
                    if str(x).strip()
                }
                needed_l = {c.lower() for c in needed}
                if ch and ch != "clock" and ch in queried and ch not in needed_l:
                    session._log(
                        {
                            "event": "block_repeat_query",
                            "backend": session.backend.name,
                            "day": session._day,
                            "step": session._step,
                            "time": session._time,
                            "channel": ch,
                            "queried": sorted(queried),
                            "needed": needed,
                        }
                    )
                    action = {
                        "action": "choose",
                        "choice": "A",
                        "task_ids": [],
                    }

            if (
                _CALENDAR_DAY_RE.match((session._day or "").strip())
                and isinstance(action, dict)
                and action.get("action") in ("check_time", "query_state")
            ):
                session._calendar_queries += 1
                queried = {
                    str(x).strip().lower()
                    for x in (info.get("match_queried") or [])
                    if str(x).strip()
                }
                channel = str(action.get("channel") or "").strip().lower()
                if action.get("action") == "check_time":
                    channel = "clock"
                hit_cap = session._calendar_queries >= _CALENDAR_QUERY_CAP
                repeat = bool(channel and channel in queried)
                if hit_cap or repeat:
                    session._log(
                        {
                            "event": "cap_calendar_query",
                            "backend": session.backend.name,
                            "day": session._day,
                            "step": session._step,
                            "time": session._time,
                            "channel": channel,
                            "queries": session._calendar_queries,
                            "repeat": repeat,
                            "queried": sorted(queried),
                        }
                    )
                    action = {
                        "action": "choose",
                        "choice": "A",
                        "task_ids": [],
                    }

            # Ablation: clock tasks only when TIME-DUE (store due.time vs clock).
            if (
                session.gate_time_due
                and getattr(session.backend, "name", "") == "intention"
                and isinstance(action, dict)
                and action.get("action") not in ("check_time", "query_state")
                and hasattr(session.backend, "gate_undue_clock_tasks")
            ):
                kept, dropped = session.backend.gate_undue_clock_tasks(
                    action, session._step_raw
                )
                if dropped:
                    session._log(
                        {
                            "event": "gate_time_due",
                            "backend": session.backend.name,
                            "day": session._day,
                            "step": session._step,
                            "time": session._time,
                            "dropped": dropped,
                            "kept": kept,
                        }
                    )
                    action = {**action, "task_ids": kept}

            if isinstance(action, dict) and action.get("action") not in ("check_time", "query_state"):
                turn = {
                    "day": session._day,
                    "step": session._step,
                    "time": session._time,
                    "observation": session._observation,
                    "step_raw": session._step_raw,
                    "action": action,
                }
                try:
                    with cost_role("memory"):
                        session.backend.encode(turn)
                    info = getattr(session.backend, "last_encode_info", None) or {}
                    session._log(
                        {
                            "event": "encode",
                            "backend": session.backend.name,
                            "day": session._day,
                            "step": session._step,
                            "time": session._time,
                            "choice": action.get("choice"),
                            "n_tasks": len(action.get("task_ids") or []),
                            **{f"encode_{k}": v for k, v in info.items()},
                        }
                    )
                except Exception as exc:
                    session._log(
                        {
                            "event": "encode_error",
                            "backend": session.backend.name,
                            "day": session._day,
                            "step": session._step,
                            "time": session._time,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    )
            return action

        return request_model_action


def _is_clock_query(action: dict) -> bool:
    act = action.get("action")
    if act == "check_time":
        return True
    if act == "query_state" and str(action.get("channel") or "").lower() == "clock":
        return True
    return False


def _is_needed_channel_query(action: dict, needed: list[str]) -> bool:
    if action.get("action") != "query_state":
        return False
    ch = str(action.get("channel") or "").strip().lower()
    return bool(ch) and ch in {c.lower() for c in needed}


def _parse_context(messages: list[dict]) -> tuple[str, str, str, str, str]:
    day = ""
    step = ""
    time_str = ""
    observation = ""
    step_raw = ""

    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        if content.startswith("=== ") and " ===" in content:
            day = content.splitlines()[0].strip("= ").strip() or day

    # Current clock: this step's Time: / State [clock] only.
    # Prior steps' dumps stay in the full transcript for run_llm bookkeeping
    # and must not leak into TIME-DUE / force_check_time.
    time_str = extract_step_clock(messages)

    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        if content.startswith("Heartbeat") or content.startswith("==="):
            continue
        if MEMORY_MARKER in content:
            continue
        # State query replies are short channel dumps — not the vignette.
        if content.startswith("State [") or content.startswith("Time:"):
            continue
        step_raw = content
        observation = strip_action_menu(content)
        m_step = re.search(r"\b(d\d+_s\d+)\b", content)
        if m_step:
            step = m_step.group(1)
        break

    return day, step, time_str, observation, step_raw


def _fallback_query(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user" and isinstance(msg.get("content"), str):
            return strip_abc_options(strip_action_menu(msg["content"]))[:1000]
    return ""


@contextmanager
def install_memory_session(pm_bench_module, session: MemorySession) -> Iterator[MemorySession]:
    """Temporarily replace pm_bench.request_model_action for one run."""
    original = pm_bench_module.request_model_action
    session.open()
    pm_bench_module.request_model_action = session.wrap(original)
    pm_bench_module._active_memory_session = session  # type: ignore[attr-defined]
    try:
        yield session
    finally:
        pm_bench_module.request_model_action = original
        if getattr(pm_bench_module, "_active_memory_session", None) is session:
            pm_bench_module._active_memory_session = None  # type: ignore[attr-defined]
        session.close()
