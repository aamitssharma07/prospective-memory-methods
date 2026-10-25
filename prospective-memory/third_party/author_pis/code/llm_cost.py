"""In-process LLM / embedding cost log for Computation Cost tables.

Patched onto OpenAI ``chat.completions.create`` and ``embeddings.create``.
Role comes from ``cost_role(...)`` (choose / memory / update_judge / rewrite).
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator

_role: ContextVar[str] = ContextVar("llm_cost_role", default="choose")
_lock = threading.Lock()
_EVENTS: list[dict[str, Any]] = []
_STARTED: float | None = None
_JSONL: Path | None = None


@contextmanager
def cost_role(role: str) -> Iterator[None]:
    token = _role.set(role)
    try:
        yield
    finally:
        _role.reset(token)


def current_role() -> str:
    return _role.get()


def load_events(events: list[dict[str, Any]], *, wall_seconds: float | None = None) -> None:
    """Replace the in-memory log (used when rebuilding a table from jsonl)."""
    global _EVENTS, _STARTED
    with _lock:
        _EVENTS = list(events)
        _STARTED = None if wall_seconds is None else time.perf_counter() - float(wall_seconds)


def reset(jsonl_path: str | Path | None = None) -> None:
    global _EVENTS, _STARTED, _JSONL
    with _lock:
        _EVENTS = []
        _STARTED = time.perf_counter()
        _JSONL = Path(jsonl_path) if jsonl_path else None
        if _JSONL:
            _JSONL.parent.mkdir(parents=True, exist_ok=True)
            _JSONL.write_text("", encoding="utf-8")


def _usage_int(usage: Any, *names: str) -> int:
    if usage is None:
        return 0
    for name in names:
        val = getattr(usage, name, None)
        if val is None and isinstance(usage, dict):
            val = usage.get(name)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                continue
    return 0


def _cached_tokens(usage: Any) -> int:
    if usage is None:
        return 0
    details = getattr(usage, "prompt_tokens_details", None)
    if details is None and isinstance(usage, dict):
        details = usage.get("prompt_tokens_details")
    if details is None:
        return 0
    return _usage_int(details, "cached_tokens")


def _estimate_prompt_tokens(messages: Any) -> int:
    if not isinstance(messages, list):
        return 0
    chars = 0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, list):
            chars += sum(len(str(part)) for part in content)
    return max(1, chars // 4) if chars else 0


def record_chat(resp: Any, kwargs: dict[str, Any], elapsed_ms: float) -> None:
    usage = getattr(resp, "usage", None)
    prompt = _usage_int(usage, "prompt_tokens", "input_tokens")
    completion = _usage_int(usage, "completion_tokens", "output_tokens")
    total = _usage_int(usage, "total_tokens")
    estimated = False
    if prompt == 0 and completion == 0:
        prompt = _estimate_prompt_tokens(kwargs.get("messages"))
        content = ""
        try:
            content = str(resp.choices[0].message.content or "")
        except Exception:
            content = ""
        completion = max(1, len(content) // 4) if content else 0
        total = prompt + completion
        estimated = True
    elif total == 0:
        total = prompt + completion
    event = {
        "kind": "chat",
        "role": current_role(),
        "model": str(kwargs.get("model") or getattr(resp, "model", "") or ""),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cached_tokens": _cached_tokens(usage),
        "elapsed_ms": round(float(elapsed_ms), 1),
        "estimated": estimated,
    }
    _append(event)


def record_embed(resp: Any, kwargs: dict[str, Any], elapsed_ms: float) -> None:
    usage = getattr(resp, "usage", None)
    prompt = _usage_int(usage, "prompt_tokens", "total_tokens")
    estimated = False
    if prompt == 0:
        raw = kwargs.get("input")
        if isinstance(raw, str):
            chars = len(raw)
        elif isinstance(raw, list):
            chars = sum(len(str(x)) for x in raw)
        else:
            chars = 0
        prompt = max(1, chars // 4) if chars else 0
        estimated = True
    event = {
        "kind": "embed",
        "role": current_role() if current_role() != "choose" else "memory",
        "model": str(kwargs.get("model") or getattr(resp, "model", "") or ""),
        "prompt_tokens": prompt,
        "completion_tokens": 0,
        "total_tokens": prompt,
        "cached_tokens": 0,
        "elapsed_ms": round(float(elapsed_ms), 1),
        "estimated": estimated,
    }
    _append(event)


def _append(event: dict[str, Any]) -> None:
    with _lock:
        _EVENTS.append(event)
        path = _JSONL
    if path is not None:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * q))))
    return ordered[idx]


def _bucket(events: list[dict[str, Any]]) -> dict[str, Any]:
    calls = len(events)
    prompt = sum(int(e.get("prompt_tokens") or 0) for e in events)
    completion = sum(int(e.get("completion_tokens") or 0) for e in events)
    total = sum(int(e.get("total_tokens") or 0) for e in events)
    cached = sum(int(e.get("cached_tokens") or 0) for e in events)
    lat = [float(e.get("elapsed_ms") or 0) for e in events]
    prompts = [int(e.get("prompt_tokens") or 0) for e in events]
    estimated = sum(1 for e in events if e.get("estimated"))
    return {
        "calls": calls,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cached_tokens": cached,
        "elapsed_ms": round(sum(lat), 1),
        "latency_ms_mean": round(sum(lat) / calls, 1) if calls else 0.0,
        "latency_ms_p50": round(_pct(lat, 0.50), 1),
        "latency_ms_p95": round(_pct(lat, 0.95), 1),
        "prompt_tokens_mean": round(sum(prompts) / calls, 1) if calls else 0.0,
        "prompt_tokens_p50": round(_pct([float(x) for x in prompts], 0.50), 1),
        "prompt_tokens_peak": max(prompts) if prompts else 0,
        "tokens_per_call": round(total / calls, 1) if calls else 0.0,
        "estimated_calls": estimated,
    }


def summary(*, wall_seconds: float | None = None) -> dict[str, Any]:
    with _lock:
        events = list(_EVENTS)
        started = _STARTED
    if wall_seconds is None and started is not None:
        wall_seconds = time.perf_counter() - started
    chat = [e for e in events if e.get("kind") == "chat"]
    embed = [e for e in events if e.get("kind") == "embed"]
    by_role: dict[str, dict[str, Any]] = {}
    for role in sorted({str(e.get("role") or "choose") for e in chat}):
        by_role[role] = _bucket([e for e in chat if e.get("role") == role])
    by_model: dict[str, dict[str, Any]] = {}
    for model in sorted({str(e.get("model") or "") for e in chat}):
        by_model[model or "(unknown)"] = _bucket(
            [e for e in chat if str(e.get("model") or "") == model]
        )
    decision_roles = {"choose"}
    memory_chat = [e for e in chat if e.get("role") not in decision_roles]
    local_chat = [
        e
        for e in chat
        if "mlx" in str(e.get("model") or "").lower()
        or "qwen2.5-3b" in str(e.get("model") or "").lower()
        or e.get("role") == "calibrate"
    ]
    local_ids = {id(e) for e in local_chat}
    billed_chat = [e for e in chat if id(e) not in local_ids]
    billed = _bucket(billed_chat)
    # DeepSeek V4 Flash official card, off-peak (weekend / non-peak UTC).
    # Peak is 2×. Cache-hit input is billed separately when the API reports it.
    miss = max(0, billed["prompt_tokens"] - billed["cached_tokens"])
    usd_offpeak = (
        miss * 0.22e-6
        + billed["cached_tokens"] * 0.007e-6
        + billed["completion_tokens"] * 0.66e-6
    )
    usd_peak = (
        miss * 0.44e-6
        + billed["cached_tokens"] * 0.014e-6
        + billed["completion_tokens"] * 1.32e-6
    )
    return {
        "wall_seconds": round(float(wall_seconds or 0.0), 3),
        "chat": _bucket(chat),
        "chat_billed": billed,
        "chat_local": _bucket(local_chat),
        "choose": _bucket([e for e in chat if e.get("role") == "choose"]),
        "memory_chat": _bucket(memory_chat),
        "embed": _bucket(embed),
        "by_role": by_role,
        "by_model": by_model,
        "n_events": len(events),
        "usd_flash_offpeak": round(usd_offpeak, 4),
        "usd_flash_peak": round(usd_peak, 4),
        "usd_note": (
            "deepseek-v4-flash official $/1M: off-peak in 0.22 / cache 0.007 / "
            "out 0.66; peak 2×. Local calibrator and embeddings excluded."
        ),
    }


def write_summary(path: str | Path, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    data = summary()
    if extra:
        data = {**extra, **data}
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return data


def format_summary(data: dict[str, Any] | None = None) -> str:
    data = data or summary()
    chat = data.get("chat") or {}
    billed = data.get("chat_billed") or {}
    local = data.get("chat_local") or {}
    choose = data.get("choose") or {}
    memory = data.get("memory_chat") or {}
    embed = data.get("embed") or {}
    lines = [
        "=== Computation cost ===",
        f"wall={data.get('wall_seconds')}s",
        (
            f"chat calls={chat.get('calls')}  "
            f"in={chat.get('prompt_tokens')}  "
            f"out={chat.get('completion_tokens')}  "
            f"total={chat.get('total_tokens')}  "
            f"p50={chat.get('latency_ms_p50')}ms  "
            f"p95={chat.get('latency_ms_p95')}ms"
        ),
        (
            f"  billed  calls={billed.get('calls')}  "
            f"total={billed.get('total_tokens')}"
        ),
        (
            f"  local   calls={local.get('calls')}  "
            f"total={local.get('total_tokens')}  (calibrator, not API)"
        ),
        (
            f"  choose  calls={choose.get('calls')}  "
            f"total={choose.get('total_tokens')}"
        ),
        (
            f"  memory  calls={memory.get('calls')}  "
            f"total={memory.get('total_tokens')}"
        ),
        (
            f"embed calls={embed.get('calls')}  "
            f"tokens={embed.get('total_tokens')}  "
            f"p50={embed.get('latency_ms_p50')}ms"
        ),
        (
            f"context peak={chat.get('prompt_tokens_peak')}  "
            f"mean={chat.get('prompt_tokens_mean')}  "
            f"tok/call={chat.get('tokens_per_call')}"
        ),
        (
            f"usd_flash off-peak=${data.get('usd_flash_offpeak')}  "
            f"peak=${data.get('usd_flash_peak')}  "
            "(API chat only)"
        ),
    ]
    return "\n".join(lines)
