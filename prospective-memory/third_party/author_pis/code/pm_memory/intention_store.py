"""
Prospective Intention Store (PIS) — structured external memory for PM-Bench.

Unlike Mem0 / A-Mem (semantic episode recall), this store keeps *condition
intentions* with an explicit lifecycle:

  write   → LLM style rewrite, regex day-plan plant, then Update Judge add
  update  → one LLM judge: add / cancel / reschedule / override, plus
             scene_cues (vignette facts rewritten in event_cue style)
  check   → union of watch on today pending, injected as MUST query
  match   → after each State reply: event vs vignette + queried State so far
             (do not wait for every CHECK name); TIME-DUE is code vs due.time
  encode  → chosen menu line, same strip as plant, exact action match
             (ignore periods); clock slots still split by at HH:MM / TIME-DUE

No scenario ground-truth is read. Everything is derived from model-visible
text (day plan, vignette, action menu, State [channel] replies).
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from llm_cost import cost_role
from llm_env import chat_extra_body

from .common import (
    INTENTION_MEMORY_INJECT_HEADER,
    INTENTION_RAG_MEMORY_INJECT_HEADER,
    INTENTION_REWRITE_PROMPT,
    INTENTION_UPDATE_JUDGE_PROMPT,
    current_step_start_index,
    parse_action_menu_map,
    resolve_action_labels,
    scrub_task_handles,
    truncate,
)

_HHMM_RE = re.compile(r"\b(\d{1,2}:\d{2})\b")


def _fail(where: str, detail: str) -> None:
    """Hard-fail so a bad judge step is visible instead of silently recovering."""
    raise RuntimeError(f"[intention:{where}] {detail}")


CHANNEL_HINTS: dict[str, tuple[str, ...]] = {
    "appointment_portal": ("appointment portal", "portal posts", "portal", "better slot"),
    "library_hold": ("library hold", "library notice", "hold is ready", "reserve reading"),
    "email": ("email", "confirmation email", "vendor reply"),
    "calendar": ("calendar", "calendar update", "room shift", "new block"),
    "course_portal": ("course portal", "grade", "grades released"),
    "bank_balance": ("balance", "bank", "below $"),
    "shipment_status": ("shipment", "out for delivery", "delivery"),
    "laundry_status": ("laundry", "laundry room"),
    "reservation_waitlist": ("waitlist", "reservation"),
    "price_tracker": ("price tracker", "price drop"),
    "clock": ("clock",),
}

_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_SCHEDULE_CHANGE_RE = re.compile(
    r"\b(move[sd]?|shift(?:s|ed)?|nudge[sd]?|reschedule(?:d|s)?|better|puts?|latest update)\b",
    re.I,
)
_PLAN_BULLET_RE = re.compile(r"^\s*[-•]\s+(.+?)\s*$")
_MONTH_DAY_RE = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})\b",
    re.I,
)
_CROSS_DAY_RE = re.compile(
    r"\bOn\s+("
    r"Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|"
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2}"
    r")\b[,:]?\s*(.+?)(?:\.(?:\s|$)|$)",
    re.I,
)
_WHEN_RE = re.compile(r"\bwhen\b\s+(.+?)(?:\.(?:\s|$)|$)", re.I)
_AT_TIME_RE = re.compile(r"\bat\s+(\d{1,2}:\d{2})\b", re.I)
_AND_TIMES_RE = re.compile(
    r"\bat\s+(\d{1,2}:\d{2})\s+and\s+(?:at\s+)?(\d{1,2}:\d{2})\b",
    re.I,
)
_MEAL_NAMES = "breakfast|lunch|dinner|brunch|bedtime"
_AND_MEALS_RE = re.compile(
    rf"\bat\s+({_MEAL_NAMES})\s+and\s+(?:at\s+)?({_MEAL_NAMES})\b",
    re.I,
)
_MEAL_AT_RE = re.compile(rf"\bat\s+({_MEAL_NAMES})\b", re.I)
_WATCH_ALLOWED = tuple(name for name in CHANNEL_HINTS if name != "clock")
_EMPTY_DUE_DAY = frozenset({"", "null", "none", "-", "unknown", "today", "todays"})
_STATE_REPLY_RE = re.compile(
    r"^State\s*\[([^\]]+)\]\s*:\s*(.+)$",
    re.I | re.M,
)
_CUE_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Dropped before comparing stored event_cue strings (not vignette scan).
_CUE_STOP = frozenset(
    {
        "a",
        "an",
        "and",
        "appear",
        "appears",
        "arrive",
        "arrives",
        "at",
        "before",
        "comes",
        "come",
        "for",
        "free",
        "from",
        "in",
        "inside",
        "is",
        "it",
        "its",
        "land",
        "lands",
        "later",
        "notice",
        "now",
        "of",
        "on",
        "once",
        "open",
        "reach",
        "reaches",
        "show",
        "shows",
        "the",
        "this",
        "to",
        "tucked",
        "unlocked",
        "up",
        "waiting",
        "when",
        "with",
        "you",
        "your",
    }
)
_THINK_RE = re.compile(r"<think>.*?</think>", re.I | re.DOTALL)
_THINK_UNCLOSED_RE = re.compile(r"<think>.*", re.I | re.DOTALL)


@dataclass
class DueSlot:
    """When the commitment should be carried out.

    `day` is optional: only a named calendar weekday, never the planting day
    just because the reminder appeared then. `time` is optional HH:MM.
    """

    day: str = ""
    time: str = ""


@dataclass
class Intention:
    intent_id: str
    action: str
    status: str = "pending"  # pending | done | canceled
    due: DueSlot = field(default_factory=DueSlot)
    event_cue: str = ""
    watch: list[str] = field(default_factory=list)
    # Ablation-only: planting / rewrite sentence. Main recall never reads this.
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if not (data.get("source") or "").strip():
            data.pop("source", None)
        return data


class IntentionStoreBackend:
    """Structured prospective-memory backend."""

    name = "intention"

    def __init__(
        self,
        *,
        store_path: str | None = None,
        max_inject_chars: int = 6000,
        time_tolerance_minutes: int = 0,
        llm_client: Any | None = None,
        llm_model: str | None = None,
        use_llm_update: bool = False,
        use_llm_extract: bool = False,
        use_llm_done: bool = False,
        use_llm_match: bool = False,
        use_llm_cadence: bool = False,
        gate_time_due: bool = False,
        force_query_channels: bool = False,
        llm_response_format: str | None = None,
        retrieval_mode: str = "due",
        embed_fn: Any | None = None,
        ignore_status: bool = False,
    ):
        self.store_path = Path(store_path) if store_path else None
        self.max_inject_chars = max_inject_chars
        self.time_tolerance_minutes = time_tolerance_minutes
        self.llm_client = llm_client
        self.llm_model = llm_model or ""
        # One Update Judge covers add + cancel/reschedule/override.
        self.use_llm_update = bool(use_llm_update and llm_client and llm_model)
        self.use_llm_extract = bool(
            (use_llm_extract or use_llm_update) and llm_client and llm_model
        )
        self.use_llm_done = False
        self.use_llm_rewrite = bool(llm_client and self.llm_model)
        # Event filter is code similarity; flag still means "filter unmatched events".
        self.use_llm_match = bool(use_llm_match)
        self.use_llm_cadence = False
        # Ablation: clock tasks only when TIME-DUE; CHECK channels forced in session.
        self.gate_time_due = bool(gate_time_due)
        self.force_query_channels = bool(force_query_channels)
        mode = (retrieval_mode or "due").strip().lower()
        if mode not in ("due", "similarity", "source"):
            raise ValueError(
                f"retrieval_mode must be 'due', 'similarity', or 'source', "
                f"got {retrieval_mode!r}"
            )
        self.retrieval_mode = mode
        self.ignore_status = bool(ignore_status)
        self.embed_fn = embed_fn
        self._rag_vec_cache: dict[str, tuple[str, list[float]]] = {}
        self._recall_tick: int = 0
        self._last_tick_key: str = ""
        self._channel_interval_steps: dict[str, int] = {}
        self._channel_last_query_tick: dict[str, int] = {}
        self.last_cadence_info: dict[str, Any] = {}
        self._event_sim_threshold = 0.62
        fmt = (llm_response_format or "").strip().lower()
        if fmt not in ("json_schema", "json_object", "none"):
            model_l = (self.llm_model or "").lower()
            fmt = "json_schema" if "qwen" in model_l else "json_object"
        self.llm_response_format = fmt
        self._last_time_hits: list[Intention] = []
        self._last_time_waits: list[Intention] = []
        self.intentions: dict[str, Intention] = {}
        self._seeded_days: set[str] = set()
        self._daily_day: str = ""
        self._daily_specs: list[dict[str, str]] = []
        self._last_update_obs_key: str = ""
        self._last_update_hits: int = 0
        self._patched_ids: list[str] = []
        self._judge_index_to_id: dict[int, str] = {}
        self._update_skipped: list[dict[str, Any]] = []
        self._last_extract_obs_key: str = ""
        self._last_extract_added: int = 0
        self._last_extract_items: list[dict[str, Any]] = []
        self.last_encode_info: dict[str, Any] = {}
        self.last_recall_info: dict[str, Any] = {}
        self.last_update_info: dict[str, Any] = {}
        self.last_extract_info: dict[str, Any] = {}
        self.last_done_info: dict[str, Any] = {}
        self.last_match_info: dict[str, Any] = {}
        self.last_rewrite_info: dict[str, Any] = {}
        self._rewrite_cache: dict[str, str] = {}
        self._last_scene_cues: list[str] = []
        self._last_scene_key: str = ""
        self._last_match_labels: dict[str, Any] = {}
        self._last_due_union_key: str = ""
        self._last_cue_key: str = ""
        self._cue_index_to_id: dict[int, str] = {}
        self._step_log_path = (
            self.store_path.with_name(self.store_path.stem + ".steps.jsonl")
            if self.store_path
            else None
        )
        self._filter_log_path = (
            self.store_path.with_name(self.store_path.stem + ".filters.md")
            if self.store_path
            else None
        )
        if self.store_path and self.store_path.exists():
            self._load()

    @property
    def memory_inject_header(self) -> str:
        if self.retrieval_mode == "similarity":
            return INTENTION_RAG_MEMORY_INJECT_HEADER
        return INTENTION_MEMORY_INJECT_HEADER

    def _use_source_phi(self) -> bool:
        """Ablation: sat(φ,V) reads the source sentence, not typed fields."""
        return self.retrieval_mode == "source"

    def _source_span(self, text: str, action: str) -> str:
        """Shortest line/sentence in text that mentions the action. Never the whole scene."""
        blob = (text or "").strip()
        act = (action or "").strip()
        if not blob:
            return ""
        chunks: list[str] = []
        for raw in blob.splitlines():
            line = raw.strip().lstrip("-• ").strip()
            if len(line) >= 6:
                chunks.append(line)
        for raw in re.split(r"[.!?\n]+", blob):
            sent = raw.strip().lstrip("-• ").strip()
            if len(sent) >= 6 and sent not in chunks:
                chunks.append(sent)
        if not chunks:
            return ""
        act_l = act.lower()
        tokens = [
            t
            for t in re.findall(r"[a-z0-9]+", act_l)
            if len(t) > 2
            and t
            not in {
                "the",
                "and",
                "for",
                "with",
                "when",
                "take",
                "your",
                "you",
            }
        ]
        scored: list[tuple[int, str]] = []
        for chunk in chunks:
            if len(chunk) > 280:
                continue
            low = chunk.lower()
            if act_l and len(act_l) >= 6 and act_l in low:
                scored.append((len(chunk), chunk))
            elif tokens and sum(1 for t in tokens if t in low) >= min(2, len(tokens)):
                scored.append((len(chunk), chunk))
        if not scored:
            return ""
        scored.sort(key=lambda x: x[0])
        return scored[0][1]

    def _set_source_from_text(
        self, intent: Intention, text: str, *, extra: str = ""
    ) -> None:
        if not self._use_source_phi():
            return
        span = self._source_span(text, intent.action)
        if span:
            intent.source = span
            return
        extra = (extra or "").strip()
        if extra:
            intent.source = extra

    def _weekday_in_text(self, text: str) -> str:
        low = (text or "").lower()
        for name in _WEEKDAYS:
            if re.search(rf"\b{name}\b", low):
                return name.capitalize()
        found = _MONTH_DAY_RE.search(text or "")
        if found:
            return self._normalize_weekday(found.group(0))
        return ""

    def _phi_times(self, intent: Intention) -> list[str]:
        if self._use_source_phi():
            found = _HHMM_RE.findall(intent.source or "")
            out: list[str] = []
            for raw in found:
                norm = self._first_time(raw)
                if norm and norm not in out:
                    out.append(norm)
            return out
        t = (intent.due.time or "").strip()
        return [t] if t else []

    def _phi_event(self, intent: Intention) -> str:
        if self._use_source_phi():
            return (intent.source or "").strip()
        return (intent.event_cue or "").strip()

    def _phi_watch(self, intent: Intention) -> list[str]:
        if self._use_source_phi():
            return self._infer_channels(intent.source or "")
        return [
            (w or "").strip().lower()
            for w in (intent.watch or [])
            if (w or "").strip()
        ]

    # ------------------------------------------------------------------ API
    def recall(self, query: str, *, top_k: int | None = None, context: dict | None = None) -> str:
        ctx = context or {}
        day = str(ctx.get("day") or "")
        time_str = str(ctx.get("time") or "")
        observation = str(ctx.get("observation") or query or "")
        messages = ctx.get("messages") or []

        self._maybe_seed_daily(messages, day=day)
        self._maybe_seed_day_plan(messages, day=day, time_str=time_str)
        self._advance_recall_tick(day=day, step=str(ctx.get("step") or ""))
        update_hits = self.apply_observation_updates(
            observation, day=day, time_str=time_str, messages=messages
        )
        extract_added = int((self.last_extract_info or {}).get("added") or 0)

        if self.retrieval_mode == "similarity":
            return self._recall_similarity(
                query,
                top_k=top_k,
                day=day,
                time_str=time_str,
                observation=observation,
                messages=messages,
                step=str(ctx.get("step") or ""),
                update_hits=update_hits,
                extract_added=extract_added,
            )

        pending = self._recall_pool()
        today_pending = [i for i in pending if self._is_active_on_day(i, day)]
        self._note_queried_channels(messages)
        # Meet order: TIME-DUE → CHECK union → event similarity (one pass on
        # current vignette + whatever State this step already has).
        time_hits = self._filter_time_due(today_pending, time_str)
        channel_needed = self._watch_needed(today_pending, messages)
        match = self._match_event_channel(
            today_pending,
            observation=observation,
            day=day,
            time_str=time_str,
            messages=messages,
        )
        event_hits = match["event_due"]
        channel_hits = match["channel_due"]
        due_ids = (
            {i.intent_id for i in time_hits}
            | {i.intent_id for i in event_hits}
            | {i.intent_id for i in channel_hits}
        )
        # Label, do not rewrite choose: unmatched clocks are TIME-WAIT.
        # Event/channel due this step still injects as DUE even if the clock
        # has not matched (the scene, not the clock, is the trigger).
        time_waits = [
            i
            for i in today_pending
            if time_str
            and self._phi_times(i)
            and i.intent_id not in due_ids
        ]
        self._last_time_hits = list(time_hits)
        self._last_time_waits = list(time_waits)
        hide_ids = {i.intent_id for i in time_waits}
        hide_ids.update(i.intent_id for i in (match.get("channel_wait") or []))
        if not time_str:
            hide_ids.update(
                i.intent_id
                for i in today_pending
                if self._phi_times(i) and i.intent_id not in due_ids
            )
        choose_pool = [i for i in match["kept"] if i.intent_id not in hide_ids]
        pending_time = [i for i in today_pending if self._phi_times(i)]
        # No trusted clock ⇒ cannot score TIME-DUE; ask session to force check_time.
        force_check_time = (not time_str) and bool(pending_time)
        step = str(ctx.get("step") or "")
        filter_trace = self._build_filter_trace(
            pending=pending,
            today_pending=today_pending,
            time_hits=time_hits,
            channel_needed=channel_needed,
            day=day,
            step=step,
            time_str=time_str,
            messages=messages,
            extracted=(
                (self.last_extract_info or {}).get("extracted") or []
                if extract_added
                else []
            ),
            extract_added=extract_added,
            match=match,
        )
        filter_trace_text = self._format_filter_trace(filter_trace)

        text = self._format_injection(
            time_hits=time_hits,
            time_waits=self._last_time_waits,
            event_hits=event_hits,
            channel_hits=channel_hits,
            channel_needed=channel_needed,
            today_pending=choose_pool,
            day=day,
            time_str=time_str,
            force_check_time=force_check_time,
            pending_time_n=len(pending_time),
            match_filtered=match.get("mode") in ("similarity", "llm"),
        )
        self.last_recall_info = {
            "retrieval_mode": self.retrieval_mode,
            "ignore_status": self.ignore_status,
            "pending": len(pending),
            "pending_time": len(pending_time),
            "clock_known": bool(time_str),
            "force_check_time": force_check_time,
            "force_query_channels": bool(self.force_query_channels and channel_needed),
            "time_hits": len(time_hits),
            "time_waits": len(self._last_time_waits),
            "event_hits": len(event_hits),
            "channel_hits": len(channel_hits),
            "channel_needed": channel_needed,
            "channel_intervals": {},
            "cadence_query": False,
            "today_pending": len(today_pending),
            "choose_pool": len(choose_pool),
            "aligned": len(choose_pool),
            "updates": update_hits,
            "extract_added": extract_added,
            "filter_dropped_future": len(filter_trace.get("drop_future_due_day") or []),
            "filter_time_not_due": len(filter_trace.get("time_not_due") or []),
            "filter_trace_text": filter_trace_text,
            **{f"update_{k}": v for k, v in (self.last_update_info or {}).items()},
            **{
                f"extract_{k}": v
                for k, v in (self.last_extract_info or {}).items()
                if k != "extracted"
            },
            **{f"match_{k}": v for k, v in (self.last_match_info or {}).items()},
            **{f"cadence_{k}": v for k, v in (self.last_cadence_info or {}).items()},
            **{
                f"rewrite_{k}": v
                for k, v in (self.last_rewrite_info or {}).items()
                if k != "text"
            },
        }
        injected = truncate(text, self.max_inject_chars) if text else ""
        self._save()
        self._append_filter_log(filter_trace_text)
        self._save_step(
            event="recall",
            day=day,
            step=step,
            time_str=time_str,
            extra={
                "injected": injected,
                "recall": dict(self.last_recall_info),
                "filter_trace": filter_trace,
            },
        )
        return injected

    def _recall_similarity(
        self,
        query: str,
        *,
        top_k: int | None,
        day: str,
        time_str: str,
        observation: str,
        messages: list,
        step: str,
        update_hits: int,
        extract_added: int,
    ) -> str:
        """Ablation: Mem0-style top-k over flattened intention records.

        Write path (seed / Update Judge) already ran. Does not TIME-DUE, event
        filter, CHECK, or force_check_time.
        """
        from .intention_rag import format_rag_injection, retrieve_intentions

        states = self._state_replies_this_step(messages)
        q = (query or observation or "").strip()
        if states:
            extra = "\n".join(
                f"State [{name}]: {body}" for name, body in sorted(states.items())
            )
            q = f"{q}\n{extra}".strip() if q else extra
        k = int(top_k) if top_k is not None else 5
        hits = retrieve_intentions(
            q,
            list(self.intentions.values()),
            top_k=k,
            embed_fn=self.embed_fn,
            vec_cache=self._rag_vec_cache,
        )
        text = format_rag_injection(hits, day=day, query=q)
        pending_n = sum(1 for i in self.intentions.values() if i.status == "pending")
        rag_rows = [
            {
                "id": hit["intent"].intent_id,
                "status": hit["intent"].status,
                "action": hit["intent"].action,
                "score": hit["score"],
                "semantic": hit["semantic"],
                "bm25": hit["bm25"],
                "mode": hit["mode"],
            }
            for hit in hits
        ]
        trace_text = self._format_rag_trace(
            day=day, step=step, query=q, rows=rag_rows
        )
        self.last_match_info = {"mode": "rag"}
        self.last_recall_info = {
            "retrieval_mode": "similarity",
            "pending": pending_n,
            "pending_time": 0,
            "clock_known": bool(time_str),
            "force_check_time": False,
            "force_query_channels": False,
            "time_hits": 0,
            "time_waits": 0,
            "event_hits": 0,
            "channel_hits": 0,
            "channel_needed": [],
            "channel_intervals": {},
            "cadence_query": False,
            "today_pending": pending_n,
            "choose_pool": len(hits),
            "aligned": len(hits),
            "updates": update_hits,
            "extract_added": extract_added,
            "rag_k": k,
            "rag_hits": len(hits),
            "rag_mode": hits[0]["mode"] if hits else "empty",
            "rag_query_chars": len(q),
            "filter_dropped_future": 0,
            "filter_time_not_due": 0,
            "filter_trace_text": trace_text,
        }
        injected = truncate(text, self.max_inject_chars) if text else ""
        self._save()
        self._append_filter_log(trace_text)
        self._save_step(
            event="recall",
            day=day,
            step=step,
            time_str=time_str,
            extra={
                "injected": injected,
                "recall": dict(self.last_recall_info),
                "rag_hits": rag_rows,
            },
        )
        return injected

    def _format_rag_trace(
        self, *, day: str, step: str, query: str, rows: list[dict[str, Any]]
    ) -> str:
        heading = f"## {day or '?'} {step or ''}".strip()
        lines = [
            heading + "  retrieval=similarity (PIS-RAG)",
            "",
            "Ablation: semantic + BM25 top-k over flattened intention records.",
            "No due stamps / event-due / CHECK. Candidate pool includes done/canceled.",
            "",
            f"query_chars={len(query or '')}",
            f"### top-{len(rows)}",
        ]
        if not rows:
            lines.append("- （无）")
        else:
            for r in rows:
                lines.append(
                    f"- {r.get('score')} {r.get('status')} | {r.get('action')} "
                    f"| sem={r.get('semantic')} bm25={r.get('bm25')} | {r.get('id')}"
                )
        return "\n".join(lines)

    def encode(self, turn: dict[str, Any]) -> None:
        day = str(turn.get("day") or "")
        time_str = str(turn.get("time") or "")
        observation = str(turn.get("observation") or "")
        self.apply_observation_updates(observation, day=day, time_str=time_str)

        labels = resolve_action_labels(turn)
        done_n = self._mark_done_by_choice(labels, day=day, time_str=time_str)
        added = int((self.last_extract_info or {}).get("added") or 0)
        self.last_encode_info = {
            "mode": "intention",
            "ignore_status": self.ignore_status,
            "marked_done": done_n,
            "added": added,
            "store_size": len(self.intentions),
            "pending": sum(1 for i in self.intentions.values() if i.status == "pending"),
            **{f"update_{k}": v for k, v in (self.last_update_info or {}).items()},
            **{f"extract_{k}": v for k, v in (self.last_extract_info or {}).items()},
            **{f"done_{k}": v for k, v in (self.last_done_info or {}).items()},
        }
        self._save()
        self._save_step(
            event="encode",
            day=day,
            step=str(turn.get("step") or ""),
            time_str=time_str,
            extra={"encode": dict(self.last_encode_info)},
        )

    def apply_observation_updates(
        self,
        observation: str,
        *,
        day: str = "",
        time_str: str = "",
        messages: list | None = None,
    ) -> int:
        """One Update Judge: cancel / reschedule / override AND plant new rows.

        LLM only. Empty scene → no-op. Cue matching is code similarity.
        """
        text = (observation or "").strip()
        if not text:
            self._patched_ids = []
            self._last_scene_cues = []
            self.last_update_info = {
                "mode": "empty",
                "patched_ids": [],
                "scene_cues": [],
            }
            if not self.last_extract_info:
                self.last_extract_info = {"mode": "empty", "extracted": [], "added": 0}
            return 0

        pending = self._recall_pool()
        if not self.use_llm_update:
            _fail(
                "scene",
                "改任务和种新任务必须开着同一个 Update Judge，没有关键词后手。"
                "不要加 --no-intention-llm-update。",
            )

        return self._ensure_scene_judge(
            text,
            pending,
            day=day,
            time_str=time_str,
            messages=messages or [],
            apply_updates=True,
        )

    def _ensure_scene_judge(
        self,
        observation: str,
        pending: list[Intention],
        *,
        day: str,
        time_str: str,
        messages: list,
        apply_updates: bool,
    ) -> int:
        """One LLM call: store patches + new intentions. Cue matching is code."""
        text = (observation or "").strip()
        obs_key = f"{day}|{text}"
        states = self._state_replies_this_step(messages)
        state_fp = "|".join(f"{k}={states[k]}" for k in sorted(states))
        scene_key = f"{obs_key}|{state_fp}"
        if scene_key == self._last_scene_key:
            return self._last_update_hits
        if apply_updates and obs_key == self._last_update_obs_key:
            # encode / check_time / extra State: do not re-ask or re-plant.
            return self._last_update_hits

        data = self._call_scene_judge(
            text,
            pending,
            day=day,
            time_str=time_str,
            states=states,
        )
        patches = list(data.get("updates") or [])
        new_items = list(data.get("intentions") or [])
        scene_cues = list(data.get("scene_cues") or [])
        self._last_scene_cues = scene_cues

        if apply_updates and obs_key != self._last_update_obs_key:
            self._patched_ids = []
            hits = self._apply_update_patches(
                patches,
                day=day,
                time_str=time_str,
                observation=text,
                due_ids=set(),
            )
            added = self._plant_extracted_items(
                new_items, day=day, observation=text
            )
            self._last_update_obs_key = obs_key
            self._last_extract_obs_key = obs_key
            self._last_update_hits = hits
            self.last_update_info = {
                "mode": "llm",
                "hits": hits,
                "patches": len(patches),
                "added": added,
                "candidates": len(self._judge_index_to_id),
                "skipped": list(self._update_skipped),
                "patched_ids": list(self._patched_ids),
                "scene_cues": list(scene_cues),
                "raw_patches": list(patches),
                "raw_new": list(new_items),
                "judge_index": {
                    str(n): iid for n, iid in self._judge_index_to_id.items()
                },
            }
            if hits or added:
                self._save()
        elif apply_updates:
            hits = self._last_update_hits
        else:
            hits = self._last_update_hits

        self._last_scene_key = scene_key
        return hits

    def _call_scene_judge(
        self,
        observation: str,
        pending: list[Intention],
        *,
        day: str,
        time_str: str,
        states: dict[str, str],
    ) -> dict[str, Any]:
        """Ask the LLM for patches AND new intentions in one call."""
        ordered = self._pending_for_judge(pending, day=day)
        self._judge_index_to_id = {}
        lines = []
        for n, i in enumerate(ordered, start=1):
            self._judge_index_to_id[n] = i.intent_id
            lines.append(f"{n}. " + " | ".join(self._intent_field_bits(i)))
        state_block = (
            "\n".join(f"State [{name}]: {text}" for name, text in sorted(states.items()))
            if states
            else "(none yet)"
        )
        watch_list = ", ".join(_WATCH_ALLOWED)
        prompt = (
            f"{INTENTION_UPDATE_JUDGE_PROMPT}\n\n"
            f"Day: {day}  Observed clock (may be empty): {time_str or 'unknown'}\n"
            f"TODAY: {day or 'unknown'}\n"
            f"Allowed watch names: {watch_list}\n\n"
            f"CURRENT SCENE:\n{observation[:2500]}\n\n"
            f"THIS STEP STATE REPLIES:\n{state_block}\n\n"
            "PENDING INTENTIONS (point to a row by n only):\n"
            + ("\n".join(lines) if lines else "(none)")
        )
        n_max = max(len(ordered), 1)
        data = self._complete_judge_json(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an intention-store update judge. Output valid "
                        "JSON only. Patch PENDING rows the scene is about "
                        "(n = list number: cancel / reschedule / override), "
                        "plant NEW deferred intentions, and split the scene "
                        "into scene_cues in event_cue style. Do not mark due."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=4096,
            schema_name="intention_update",
            schema=self._update_judge_schema(n_max),
            where="scene",
        )
        updates = data.get("updates")
        if updates is None:
            updates = []
        if not isinstance(updates, list):
            _fail("scene", f"updates 不是列表: {type(updates).__name__}")
        bad = [u for u in updates if not isinstance(u, dict)]
        if bad:
            _fail("scene", f"updates 里有不是对象的项: {bad[:3]!r}")
        intentions = data.get("intentions")
        if intentions is None:
            intentions = []
        if not isinstance(intentions, list):
            _fail("extract", f"intentions 不是列表: {type(intentions).__name__}")
        bad_i = [u for u in intentions if not isinstance(u, dict)]
        if bad_i:
            _fail("extract", f"intentions 里有不是对象的项: {bad_i[:3]!r}")
        return {
            "updates": updates,
            "intentions": intentions,
            "scene_cues": self._normalize_scene_cues(data.get("scene_cues")),
        }

    @staticmethod
    def _normalize_scene_cues(raw: Any) -> list[str]:
        """Keep non-empty strings; skip junk so a bad extra field is not fatal."""
        if raw is None:
            return []
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str):
                continue
            cue = item.strip().rstrip(".")
            if not cue or cue.lower() in ("null", "none", "-"):
                continue
            key = " ".join(cue.lower().split())
            if key in seen:
                continue
            seen.add(key)
            out.append(cue)
        return out

    @staticmethod
    def _update_judge_schema(n_max: int) -> dict[str, Any]:
        n_item = {
            "type": "integer",
            "minimum": 1,
            "maximum": n_max,
        }
        return {
            "type": "object",
            "properties": {
                "updates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "n": n_item,
                            "action": {
                                "type": "string",
                                "enum": ["cancel", "reschedule", "override"],
                            },
                            "new_time": {"type": ["string", "null"]},
                            "new_day": {"type": ["string", "null"]},
                            "new_trigger": {"type": ["string", "null"]},
                            "new_action": {"type": ["string", "null"]},
                            "rationale": {"type": "string"},
                        },
                        "required": [
                            "n",
                            "action",
                            "new_time",
                            "new_day",
                            "new_trigger",
                            "new_action",
                            "rationale",
                        ],
                        "additionalProperties": False,
                    },
                },
                "intentions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string"},
                            "due_day": {"type": ["string", "null"]},
                            "due_time": {"type": ["string", "null"]},
                            "event_cue": {"type": ["string", "null"]},
                            "watch": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "action",
                            "due_day",
                            "due_time",
                            "event_cue",
                            "watch",
                        ],
                        "additionalProperties": False,
                    },
                },
                "scene_cues": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["updates", "intentions", "scene_cues"],
            "additionalProperties": False,
        }

    @staticmethod
    def _scene_judge_schema(n_max: int) -> dict[str, Any]:
        return IntentionStoreBackend._update_judge_schema(n_max)

    def _complete_judge_json(
        self,
        *,
        messages: list[dict[str, Any]],
        max_tokens: int,
        schema_name: str,
        schema: dict[str, Any],
        where: str,
        client: Any | None = None,
        model: str | None = None,
        response_format: str | None = None,
    ) -> dict[str, Any]:
        """Follow provider JSON mode. Skip json_schema when the API rejects it."""
        client = client if client is not None else self.llm_client
        model_name = (model or self.llm_model or "").strip()
        fmt_mode = (response_format or self.llm_response_format or "").strip().lower()
        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        extra = chat_extra_body(model_name)
        if extra:
            kwargs["extra_body"] = extra
        formats: list[dict[str, Any] | None] = []
        if fmt_mode == "json_schema":
            formats.append(
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "strict": True,
                        "schema": schema,
                    },
                }
            )
        if fmt_mode in ("json_schema", "json_object"):
            formats.append({"type": "json_object"})
        formats.append(None)
        errors: list[str] = []
        for fmt in formats:
            try:
                call = dict(kwargs)
                if fmt is not None:
                    call["response_format"] = fmt
                role = (
                    "rewrite"
                    if where == "rewrite"
                    else "update_judge"
                    if where in ("update", "scene", "extract")
                    else where or "memory"
                )
                with cost_role(role):
                    resp = client.chat.completions.create(**call)
            except Exception as exc:
                errors.append(f"http:{type(exc).__name__}: {exc}")
                continue
            try:
                content = self._completion_text(resp)
            except Exception as exc:
                errors.append(f"read:{type(exc).__name__}: {exc}")
                continue
            data = self._try_parse_judge_json(content)
            if data is not None:
                return data
            preview = content.replace("\n", " ")[:80]
            errors.append(f"parse:{preview!r}")
        _fail(where, "模型没给出能解析的 JSON: " + " | ".join(errors)[:500])
        raise AssertionError("unreachable")

    @staticmethod
    def _completion_text(resp: Any) -> str:
        """Prefer content; flash may park JSON in reasoning_content if thinking is on."""
        try:
            msg = resp.choices[0].message
        except Exception:
            return ""
        content = str(getattr(msg, "content", "") or "").strip()
        if content:
            return content
        # Thinking models may park the JSON only in reasoning_*.
        # Do not concatenate: thinking often quotes prompt examples.
        for attr in ("reasoning_content", "reasoning"):
            val = getattr(msg, attr, None)
            text = str(val).strip() if val else ""
            if text:
                return text
        return ""

    @staticmethod
    def _extract_json_object(text: str) -> str | None:
        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        in_str = False
        esc = False
        for i, ch in enumerate(text[start:], start=start):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    @staticmethod
    def _try_parse_judge_json(content: str) -> dict[str, Any] | None:
        raw = (content or "").strip()
        if not raw:
            return None
        stripped = _THINK_RE.sub("", raw).strip()
        stripped = _THINK_UNCLOSED_RE.sub("", stripped).strip()
        blobs = [raw, stripped]
        candidates: list[str] = []
        for blob in blobs:
            if not blob:
                continue
            text = blob
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text).strip()
            if text and text not in candidates:
                candidates.append(text)
            extracted = IntentionStoreBackend._extract_json_object(text)
            if extracted and extracted not in candidates:
                candidates.append(extracted)
        for cand in candidates:
            try:
                data = json.loads(cand)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
        return None

    @staticmethod
    def _parse_judge_json(content: str, *, where: str) -> dict[str, Any]:
        data = IntentionStoreBackend._try_parse_judge_json(content)
        if data is None:
            preview = (content or "").replace("\n", " ")[:240]
            _fail(where, f"返回的不是 JSON; 原文前 240 字: {preview!r}")
        return data

    def _pending_for_judge(self, pending: list[Intention], *, day: str) -> list[Intention]:
        """All pending, today first. No word-overlap ranking."""
        today = (day or "").strip().lower()

        def sort_key(i: Intention) -> tuple:
            due = (i.due.day or "").strip().lower()
            today_first = 0 if (not due or due == today) else 1
            di = self._weekday_index(i.due.day)
            return (today_first, di if di is not None else 99, (i.action or "").lower())

        return sorted(pending, key=sort_key)

    def _resolve_patch_intent(self, patch: dict[str, Any]) -> Intention | None:
        """Map a judge patch to a pending row by list number n only."""
        raw_n = patch.get("n", patch.get("index", patch.get("item")))
        if raw_n is None:
            raw_id = str(patch.get("intent_id") or "").strip()
            if raw_id.isdigit():
                raw_n = raw_id
        try:
            if raw_n is None or str(raw_n).strip() == "":
                return None
            idx = int(raw_n)
        except (TypeError, ValueError):
            return None
        iid = self._judge_index_to_id.get(idx)
        if not iid:
            return None
        cand = self.intentions.get(iid)
        if cand is None:
            return None
        if not self.ignore_status and cand.status != "pending":
            return None
        return cand

    @staticmethod
    def _clock_token(text: str) -> str:
        m = _TIME_RE.search(text or "")
        return m.group(0) if m else ""

    @staticmethod
    def _trigger_without_clock(trig: str) -> str:
        leftover = _TIME_RE.sub("", trig or "")
        leftover = re.sub(r"[^a-z0-9]+", " ", leftover.lower()).strip()
        return leftover

    @classmethod
    def _normalize_update_verb(
        cls,
        patch: dict[str, Any],
        *,
        verb: str,
        intent: Intention | None = None,
    ) -> tuple[str, str]:
        """Repair inconsistent JSON. Does not read the vignette.

        cancel + new_trigger → override (cue rewrite, not void).
        override + HH:MM (or a clock row whose trigger is a time) → reschedule.
        """
        trig = str(patch.get("new_trigger") or "").strip()
        if trig.lower() in ("null", "none", "-"):
            trig = ""
        new_time = str(patch.get("new_time") or "").strip()
        if new_time.lower() in ("null", "none", "-"):
            new_time = ""
        clock = cls._clock_token(new_time) or cls._clock_token(trig)
        leftover = cls._trigger_without_clock(trig) if trig else ""
        has_clock_slot = bool(intent and (intent.due.time or "").strip())
        if verb == "cancel" and trig:
            if clock and not leftover:
                return "reschedule", ""
            return "override", trig
        if verb == "override":
            if clock and (not leftover or has_clock_slot):
                return "reschedule", ""
            if new_time and not trig:
                return "reschedule", ""
        return verb, trig

    def _reschedule_time_from_scene(self, observation: str, now: str) -> str:
        """HH:MM this scene is moving a clock task to, or empty.

        Needs a schedule-change verb so a vignette that only mentions a clock
        does not rewrite due.time. Prefers "to HH:MM"; else the last HH:MM
        that is not the trusted now.
        """
        text = observation or ""
        if not _SCHEDULE_CHANGE_RE.search(text):
            return ""
        now_n = self._first_time(now) if now else ""
        after_to = re.findall(r"\bto\s+(\d{1,2}:\d{2})\b", text, re.I)
        if after_to:
            picked = self._first_time(after_to[-1])
            if picked and picked != now_n:
                return picked
        found = [self._first_time(m.group(0)) for m in _TIME_RE.finditer(text)]
        found = [t for t in found if t and t != now_n]
        return found[-1] if found else ""

    def _clock_intents_named_in_scene(self, observation: str) -> list[Intention]:
        obs = " ".join((observation or "").lower().split())
        if not obs:
            return []
        out: list[Intention] = []
        for intent in self._recall_pool():
            if not (intent.due.time or "").strip():
                continue
            act = " ".join((intent.action or "").lower().split())
            if act and act in obs:
                out.append(intent)
        return out

    @staticmethod
    def _trigger_copies_scene(trigger: str, observation: str) -> bool:
        """True when new_trigger is the current vignette, not a later condition."""
        t = " ".join((trigger or "").lower().split())
        o = " ".join((observation or "").lower().split())
        if not t or not o:
            return False
        if t == o:
            return True
        need = max(40, int(0.55 * max(len(t), len(o))))
        if t in o and len(t) >= need:
            return True
        if o in t and len(o) >= need:
            return True
        return False

    def _apply_update_patches(
        self,
        patches: list[dict[str, Any]],
        *,
        day: str,
        time_str: str,
        observation: str = "",
        event_due_ids: set[str] | None = None,
        due_ids: set[str] | None = None,
    ) -> int:
        hits = 0
        self._update_skipped = []
        due_now = set(due_ids or event_due_ids or set())
        named_clocks = self._clock_intents_named_in_scene(observation)
        named_clock_ids = {i.intent_id for i in named_clocks}
        scene_time = self._reschedule_time_from_scene(observation, time_str)
        rescheduled: set[str] = set()
        for patch in patches:
            verb = str(patch.get("action") or "").strip().lower()
            if verb in ("", "none", "null"):
                continue
            if verb not in ("cancel", "reschedule", "override"):
                continue
            intent = self._resolve_patch_intent(patch)
            if intent is None:
                _fail(
                    "scene",
                    "点名的序号对不上待做列表，没有用词去猜。"
                    f" patch={patch!r} 有效序号={sorted(self._judge_index_to_id)}",
                )

            verb, new_trigger = self._normalize_update_verb(
                patch, verb=verb, intent=intent
            )
            patch = dict(patch)
            if new_trigger:
                patch["new_trigger"] = new_trigger
            elif verb == "reschedule":
                clock = self._first_time(
                    str(patch.get("new_time") or "")
                ) or self._first_time(str(patch.get("new_trigger") or ""))
                if clock:
                    patch["new_time"] = clock
                patch["new_trigger"] = ""

            if (
                verb == "override"
                and scene_time
                and named_clock_ids
                and intent.intent_id not in named_clock_ids
            ):
                self._update_skipped.append(
                    {
                        "intent_id": intent.intent_id,
                        "reason": "clock_change_wrong_row",
                    }
                )
                continue

            if (
                verb == "override"
                and scene_time
                and intent.intent_id in named_clock_ids
            ):
                verb = "reschedule"
                patch["new_time"] = scene_time
                patch["new_trigger"] = ""

            if verb == "cancel" and intent.intent_id in due_now:
                self._update_skipped.append(
                    {
                        "intent_id": intent.intent_id,
                        "reason": "cue_firing_not_cancel",
                    }
                )
                continue

            old_cue = (intent.event_cue or "").strip()
            new_trig = str(patch.get("new_trigger") or "").strip()
            if verb == "override" and self._trigger_copies_scene(
                new_trig, observation
            ):
                self._update_skipped.append(
                    {
                        "intent_id": intent.intent_id,
                        "reason": "cue_firing_not_override",
                    }
                )
                continue
            if (
                verb == "override"
                and old_cue
                and observation
                and self._event_similarity(
                    old_cue, self._vignette_for_event_match(observation)
                )
                >= self._event_sim_threshold
            ):
                self._update_skipped.append(
                    {
                        "intent_id": intent.intent_id,
                        "reason": "cue_firing_not_override",
                    }
                )
                continue

            if verb == "cancel":
                if not self._set_status(intent, "canceled"):
                    self._update_skipped.append(
                        {
                            "intent_id": intent.intent_id,
                            "reason": "ignore_status",
                        }
                    )
                    continue
            elif verb == "reschedule":
                new_time = str(patch.get("new_time") or "").strip()
                if not new_time:
                    new_time = self._first_time(
                        str(patch.get("new_summary") or patch.get("new_action") or "")
                    )
                if not new_time:
                    new_time = self._first_time(str(patch.get("new_trigger") or ""))
                if not new_time:
                    new_time = scene_time
                new_action = str(
                    patch.get("new_action") or patch.get("new_summary") or ""
                ).strip()
                new_day = str(patch.get("new_day") or "").strip() or day
                self._rewrite_due_world(intent, day=new_day, new_time=new_time)
                if new_action:
                    intent.action = self._action_phrase(new_action)
                cue = (intent.event_cue or "").strip()
                if cue and (_TIME_RE.fullmatch(cue) or cue.lower() in ("null", "none")):
                    intent.event_cue = ""
                self._set_source_from_text(
                    intent, observation, extra=new_time or new_action
                )
                rescheduled.add(intent.intent_id)
            elif verb == "override":
                new_trigger = str(patch.get("new_trigger") or "").strip()
                if new_trigger:
                    intent.event_cue = new_trigger
                    if not intent.due.time:
                        intent.due.time = ""
                new_action = str(
                    patch.get("new_action") or patch.get("new_summary") or ""
                ).strip()
                if new_action:
                    intent.action = self._action_phrase(new_action)
                    ch = self._infer_channels(new_action)
                    if ch:
                        intent.watch = ch
                elif new_trigger:
                    ch = self._infer_channels(new_trigger)
                    if ch:
                        intent.watch = ch
                self._set_source_from_text(
                    intent, observation, extra=new_trigger or new_action
                )
            self._patched_ids.append(intent.intent_id)
            hits += 1
        if scene_time:
            for intent in named_clocks:
                if (
                    (not self.ignore_status and intent.status != "pending")
                    or intent.intent_id in rescheduled
                ):
                    continue
                if (intent.due.time or "").strip() == scene_time:
                    continue
                self._rewrite_due_world(intent, day=day, new_time=scene_time)
                self._set_source_from_text(intent, observation, extra=scene_time)
                self._patched_ids.append(intent.intent_id)
                rescheduled.add(intent.intent_id)
                hits += 1
        return hits

    def _mark_done_by_choice(
        self, labels: list[str], *, day: str, time_str: str = ""
    ) -> int:
        """Map chosen menu labels onto pending rows in code. No LLM."""
        if not labels:
            self.last_done_info = {"mode": "no_labels"}
            return 0
        pending = self._recall_pool()
        if not pending:
            self.last_done_info = {"mode": "no_pending"}
            return 0
        hits_ids = self._done_ids_from_labels(
            labels, pending, day=day, time_str=time_str
        )
        if self.ignore_status:
            self.last_done_info = {
                "mode": "ignore_status",
                "labels": list(labels),
                "ids": list(hits_ids),
                "hits": 0,
            }
            return 0
        hits = 0
        for iid in hits_ids:
            intent = self.intentions.get(iid)
            if intent is None or intent.status != "pending":
                continue
            intent.status = "done"
            hits += 1
        self.last_done_info = {
            "mode": "code",
            "labels": list(labels),
            "ids": list(hits_ids),
            "hits": hits,
        }
        return hits

    def _done_ids_from_labels(
        self,
        labels: list[str],
        pending: list[Intention],
        *,
        day: str,
        time_str: str,
    ) -> list[str]:
        """One chosen menu line → pending rows: stripped equality ∪ substring.

        Menu text is run through ``_action_phrase`` (drop when / at HH:MM), then
        compared equal ignoring periods. Fallback: stored action is a
        space-bounded substring of that stripped key or of the raw menu line
        (covers leftover ``at breakfast`` on the menu). Same-action clock slots
        (11:00 vs 21:00) stay distinct via the HH:MM still on the menu line,
        or TIME-DUE. Same-action event slots (breakfast vs dinner) bind by
        event_cue tokens still on the menu line.
        """
        del day
        out: list[str] = []
        seen: set[str] = set()
        for lab in labels:
            matches = [i for i in pending if self._action_matches_menu(lab, i)]
            if not matches:
                continue
            chosen = matches
            clocked = [i for i in matches if (i.due.time or "").strip()]
            if len(clocked) >= 2:
                timed = [
                    i
                    for i in clocked
                    if self._menu_matches_clock_intent(lab, i)
                    and _HHMM_RE.search(lab or "")
                ]
                if len(timed) == 1:
                    chosen = timed
                else:
                    due_now = self._filter_time_due(clocked, time_str)
                    if len(due_now) == 1:
                        chosen = due_now
                    else:
                        continue
            elif len(matches) > 1 and clocked:
                due_now = self._filter_time_due(clocked, time_str)
                if len(due_now) == 1:
                    chosen = due_now
            if len(chosen) > 1:
                evented = [
                    i
                    for i in chosen
                    if (i.event_cue or "").strip() and not (i.due.time or "").strip()
                ]
                if len(evented) >= 2:
                    keyed = [
                        i for i in evented if self._menu_matches_event_intent(lab, i)
                    ]
                    if len(keyed) == 1:
                        chosen = keyed
                    elif keyed:
                        chosen = keyed
                    else:
                        continue
            for intent in chosen:
                if intent.intent_id in seen:
                    continue
                seen.add(intent.intent_id)
                out.append(intent.intent_id)
        return out

    def _menu_matches_event_intent(self, label: str, intent: Intention) -> bool:
        """Menu line binds to an event slot by cue tokens still on the label."""
        cue = (intent.event_cue or "").strip().lower()
        if not cue:
            return False
        raw = re.sub(r"\s+", " ", re.sub(r"\.", "", (label or "").strip()).lower()).strip()
        if not raw:
            return False
        if cue in raw:
            return True
        padded = f" {raw} "
        return any(f" {tok} " in padded for tok in self._event_cue_tokens(cue))

    def _action_matches_menu(self, label: str, intent: Intention) -> bool:
        lab = self._action_key(label)
        act = self._action_key(intent.action)
        if not act:
            return False
        if lab and lab == act:
            return True
        if len(act) < 6:
            return False
        raw = re.sub(r"\s+", " ", re.sub(r"\.", "", (label or "").strip()).lower()).strip()
        return self._action_is_menu_substring(act, lab) or self._action_is_menu_substring(
            act, raw
        )

    @staticmethod
    def _action_is_menu_substring(act: str, haystack: str) -> bool:
        """Stored action is a whole-phrase substring of the menu (not mid-word)."""
        if not act or not haystack:
            return False
        return f" {act} " in f" {haystack} "

    def _recall_pool(self) -> list[Intention]:
        """Due-path candidates. Ablation ignores status; Full uses pending only."""
        if self.ignore_status:
            return list(self.intentions.values())
        return [i for i in self.intentions.values() if i.status == "pending"]

    def _set_status(self, intent: Intention, status: str) -> bool:
        """Write pending/done/canceled. Ablation ``ignore_status`` is a no-op."""
        if self.ignore_status:
            return False
        intent.status = status
        return True

    def _apply_done_ns(self, ns: list[int]) -> int:
        if self.ignore_status:
            return 0
        hits = 0
        seen: set[str] = set()
        for n in ns:
            intent = self._resolve_patch_intent({"n": n})
            if intent is None:
                _fail(
                    "done",
                    "点名的序号对不上待做列表，没有用词去猜。"
                    f" n={n!r} 有效序号={sorted(self._judge_index_to_id)}",
                )
            if intent.intent_id in seen:
                continue
            seen.add(intent.intent_id)
            intent.status = "done"
            hits += 1
        return hits

    # ------------------------------------------------------------- seeding
    def _maybe_seed_daily(self, messages: list | None = None, *, day: str = "") -> None:
        """Re-open standing daily slots when the calendar day changes.

        Slot list comes from style rewrite + regex on the visible
        ``Regular tasks for every day`` block — not hardcoded drug names.
        """
        if day and day == self._daily_day:
            return
        self._ensure_daily_specs(messages or [], day=day)
        if not self._daily_specs:
            return
        for spec in self._daily_specs:
            action = str(spec.get("action") or "").strip()
            due_time = str(spec.get("due_time") or "").strip()
            event = str(spec.get("event_cue") or "").strip()
            if not action:
                continue
            existing = self._find_daily(action, due_time=due_time, event_cue=event)
            slot_day = day if due_time else ""
            if existing is not None:
                existing.status = "pending"
                existing.due.day = slot_day
                existing.due.time = due_time
                existing.event_cue = event or existing.event_cue
                existing.action = action
                if self._use_source_phi() and spec.get("source") and not existing.source:
                    existing.source = str(spec.get("source") or "")
                continue
            source = ""
            if self._use_source_phi():
                source = str(spec.get("source") or "").strip()
            self._insert(
                Intention(
                    intent_id=self._new_id(),
                    action=action,
                    status="pending",
                    due=DueSlot(day=slot_day, time=due_time),
                    event_cue=event,
                    source=source,
                )
            )
        self._daily_day = day

    def _ensure_daily_specs(self, messages: list, *, day: str) -> None:
        if self._daily_specs:
            return
        text = self._regular_tasks_text(messages)
        if not text:
            return
        before = set(self.intentions)
        self._extract_from_text(text, day=day)
        specs: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for iid, intent in list(self.intentions.items()):
            if iid not in before:
                if intent.status != "pending":
                    continue
            key = (
                (intent.action or "").strip().lower(),
                intent.due.time or "",
                (intent.event_cue or "").strip().lower(),
            )
            if iid not in before:
                if not key[0] or key in seen:
                    continue
                seen.add(key)
                specs.append(
                    {
                        "action": intent.action,
                        "due_time": intent.due.time or "",
                        "event_cue": intent.event_cue or "",
                        "source": intent.source or "",
                    }
                )
        self._daily_specs = specs

    @staticmethod
    def _regular_tasks_text(messages: list) -> str:
        for msg in messages:
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            content = msg.get("content")
            if not isinstance(content, str):
                continue
            low = content.lower()
            idx = low.find("regular tasks for every day")
            if idx < 0:
                continue
            chunk = content[idx:]
            cut = re.search(r"\n=== ", chunk)
            if cut:
                chunk = chunk[: cut.start()]
            return chunk.strip()
        return ""

    def _find_daily(
        self, action: str, *, due_time: str, event_cue: str
    ) -> Intention | None:
        """Re-open the standing daily slot. Exact action + time/cue, not extract-merge."""
        want = (action or "").strip().lower()
        for intent in self.intentions.values():
            if (intent.action or "").strip().lower() != want:
                continue
            if due_time:
                if intent.due.time == due_time:
                    return intent
            elif (intent.event_cue or "").lower() == event_cue.lower():
                return intent
        return None

    def _maybe_seed_day_plan(
        self, messages: list[dict], *, day: str, time_str: str
    ) -> None:
        if not day or day in self._seeded_days:
            return
        plan_text = ""
        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if not isinstance(content, str):
                continue
            if content.startswith(f"=== {day}") or (
                content.startswith("=== ") and day in content.splitlines()[0]
            ):
                plan_text = content
                break
        if not plan_text:
            return
        self._seeded_days.add(day)
        self._extract_from_text(plan_text, day=day)
        self._save()

    def _extract_observation(self, text: str, *, day: str, time_str: str = "") -> int:
        """Vignette planting now lives in the Update Judge. Cached no-op here."""
        del time_str
        scene = (text or "").strip()
        if not scene:
            if not self.last_extract_info:
                self.last_extract_info = {"mode": "empty", "extracted": [], "added": 0}
            return 0
        obs_key = f"{day}|{scene}"
        if obs_key == self._last_extract_obs_key or obs_key == self._last_update_obs_key:
            return int(self._last_extract_added or 0)
        return int((self.last_extract_info or {}).get("added") or 0)

    def _plant_extracted_items(
        self,
        raw: list[dict[str, Any]],
        *,
        day: str,
        observation: str = "",
    ) -> int:
        """Insert Update-Judge `intentions` rows. Always `_insert`, never merge."""
        added = 0
        traces: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                _fail("extract", f"intentions 里有不是对象的项: {item!r}")
            intent = self._intention_from_extract_item(
                item, today=day, source_text=observation
            )
            traces.append(
                {
                    "raw": {
                        "action": item.get("action"),
                        "due_day": item.get("due_day"),
                        "due_time": item.get("due_time"),
                        "event_cue": item.get("event_cue") or item.get("event"),
                        "watch": item.get("watch"),
                    },
                    "stored": self._brief_intent(intent),
                }
            )
            self._insert(intent)
            added += 1
        self._last_extract_items = traces
        self._last_extract_added = added
        self.last_extract_info = {
            "mode": "llm",
            "proposed": len(raw),
            "added": added,
            "extracted": list(traces),
        }
        return added

    def _intention_from_extract_item(
        self,
        item: dict[str, Any],
        *,
        today: str,
        strict_watch: bool = True,
        source_text: str = "",
    ) -> Intention:
        action = self._action_phrase(str(item.get("action") or "").strip())
        if len(action) < 6:
            _fail("extract", f"抽到的任务名称太短或空: {item!r}")
        due_raw = item.get("due") if isinstance(item.get("due"), dict) else {}
        due_time = str(item.get("due_time") or due_raw.get("time") or "").strip()
        if due_time.lower() in ("null", "none", "-"):
            due_time = ""
        m_time = _TIME_RE.search(due_time)
        due_time = m_time.group(0) if m_time else ""
        event_cue = str(item.get("event_cue") or item.get("event") or "").strip()
        event_cue = event_cue.rstrip(".")
        if event_cue.lower() in ("null", "none"):
            event_cue = ""
        due_day = self._resolve_due_day(
            str(item.get("due_day") or due_raw.get("day") or ""),
            today=today,
            due_time=due_time,
            event_cue=event_cue,
        )
        watch = self._normalize_watch(item.get("watch") or [], strict=strict_watch)
        source = ""
        if self._use_source_phi():
            source = self._source_span(source_text, action)
        return Intention(
            intent_id=self._new_id(),
            action=action,
            status="pending",
            due=DueSlot(day=due_day, time=due_time),
            event_cue=event_cue,
            watch=watch,
            source=source,
        )

    @staticmethod
    def _normalize_weekday(day: str) -> str:
        raw = (day or "").strip()
        found = _MONTH_DAY_RE.fullmatch(raw)
        if found:
            return f"{found.group(1).capitalize()} {int(found.group(2)):02d}"
        low = raw.lower()
        for name in _WEEKDAYS:
            if name == low:
                return name.capitalize()
        return raw

    @staticmethod
    def _month_day_key(day: str) -> tuple[int, int] | None:
        raw = (day or "").strip()
        found = _MONTH_DAY_RE.fullmatch(raw)
        if not found:
            return None
        month = found.group(1).lower()
        if month not in _MONTHS:
            return None
        return (_MONTHS.index(month), int(found.group(2)))

    def _resolve_due_day(
        self,
        raw_day: str,
        *,
        today: str = "",
        due_time: str = "",
        event_cue: str = "",
        named_day: bool = False,
    ) -> str:
        """Calendar due only. Planting day is not a due.

        Clock tasks may fall back to today. Event-only keeps a weekday only
        when it is an explicit named day other than the planting day (or
        `named_day` from an `On <Day>` clause).
        """
        token = (raw_day or "").strip()
        low = token.lower()
        if low in _EMPTY_DUE_DAY:
            weekday = ""
        else:
            weekday = self._normalize_weekday(token)
            if weekday.lower() in _EMPTY_DUE_DAY:
                weekday = ""

        today_norm = self._normalize_weekday(today) if today else ""
        if named_day:
            return weekday or today_norm
        if due_time:
            return weekday or today_norm
        if event_cue:
            if not weekday:
                return ""
            if today_norm and weekday.lower() == today_norm.lower():
                return ""
            return weekday
        return weekday or today_norm

    @staticmethod
    def _normalize_watch(names: Any, *, strict: bool = True) -> list[str]:
        allowed = set(_WATCH_ALLOWED)
        if names in (None, "", []):
            return []
        if isinstance(names, str):
            names = [names]
        if not isinstance(names, list):
            if strict:
                _fail("extract", f"watch 必须是名单或空: {names!r}")
            return []
        found: list[str] = []
        unknown: list[str] = []
        for raw in names:
            if not isinstance(raw, str) or not raw.strip():
                continue
            key = raw.strip().lower().replace(" ", "_")
            if key in ("null", "none"):
                continue
            if key not in allowed:
                unknown.append(raw)
                continue
            if key not in found:
                found.append(key)
        if unknown and strict:
            _fail(
                "extract",
                f"watch 里有不在名单中的名字: {unknown}；允许: {sorted(allowed)}",
            )
        return found

    def _extract_from_text(self, text: str, *, day: str) -> int:
        if not text:
            return 0
        text = self._rewrite_plan_source(text, day=day)
        before = set(self.intentions)
        added = 0
        for m in _CROSS_DAY_RE.finditer(text):
            target_day = self._normalize_weekday(m.group(1))
            rest = m.group(2).strip().rstrip(".")
            if len(rest) < 8:
                continue
            for piece in self._expand_plan_bullet(rest):
                intent = self._parse_intention_line(
                    piece, day=target_day, named_day=True
                )
                if intent is None:
                    continue
                self._insert(intent)
                added += 1

        for raw_line in text.splitlines():
            line = raw_line.strip()
            m = _PLAN_BULLET_RE.match(line)
            body = m.group(1).strip() if m else ""
            if not body:
                continue
            if body.lower().startswith("today's loose plan"):
                continue
            for piece in self._expand_plan_bullet(body):
                intent = self._parse_intention_line(piece, day=day)
                if intent is None:
                    continue
                self._insert(intent)
                added += 1
        return added

    def _rewrite_plan_source(self, text: str, *, day: str) -> str:
        """Normalize diverse plan wording so regex can plant. Fail-open."""
        source = (text or "").strip()
        if not source:
            self.last_rewrite_info = {"mode": "empty"}
            return text
        if not self.use_llm_rewrite:
            self.last_rewrite_info = {"mode": "off"}
            return text
        if self._month_day_key(day) is not None:
            # 7-day rewrite prompt is weekday-only; leave month text for regex.
            self.last_rewrite_info = {"mode": "calendar_passthrough"}
            return text
        cached = self._rewrite_cache.get(source)
        if cached is not None:
            self.last_rewrite_info = {"mode": "cache", "chars": len(cached)}
            return cached
        try:
            data = self._call_rewrite_judge(source, day=day)
            rewritten = str(data.get("text") or data.get("rewritten") or "").strip()
            if not rewritten:
                self.last_rewrite_info = {"mode": "empty_json"}
                return text
            self._rewrite_cache[source] = rewritten
            self.last_rewrite_info = {
                "mode": "llm",
                "source_chars": len(source),
                "rewritten_chars": len(rewritten),
            }
            return rewritten
        except Exception as exc:
            self.last_rewrite_info = {
                "mode": "fail_open",
                "error": f"{type(exc).__name__}: {exc}",
            }
            return text

    def _call_rewrite_judge(self, source: str, *, day: str) -> dict[str, Any]:
        prompt = (
            f"{INTENTION_REWRITE_PROMPT}\n\n"
            f"TODAY (planting day, not a due): {day or 'unknown'}\n\n"
            f"SOURCE:\n{source}"
        )
        return self._complete_judge_json(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You rewrite a to-do list into dash-bullet / On-Day "
                        "style so a regex can parse it. JSON only. "
                        "Do not invent commitments."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=2048,
            schema_name="intention_rewrite",
            schema=self._rewrite_schema(),
            where="rewrite",
        )

    @staticmethod
    def _rewrite_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        }

    def _parse_intention_line(
        self, body: str, *, day: str, named_day: bool = False
    ) -> Intention | None:
        body = body.strip().rstrip(".")
        if len(body) < 6:
            return None
        low = body.lower()
        if low.startswith("regular tasks"):
            return None

        due_time = ""
        m_at = _AT_TIME_RE.search(body)
        if m_at:
            due_time = m_at.group(1)

        when = ""
        m_when = _WHEN_RE.search(body)
        if m_when:
            when = m_when.group(1).strip().rstrip(".")
        if not when and not due_time:
            m_meal = _MEAL_AT_RE.search(body)
            if m_meal:
                when = m_meal.group(1).lower()

        return Intention(
            intent_id=self._new_id(),
            action=self._action_phrase(body),
            status="pending",
            due=DueSlot(
                day=self._resolve_due_day(
                    day,
                    today=day,
                    due_time=due_time,
                    event_cue=when,
                    named_day=named_day,
                ),
                time=due_time,
            ),
            event_cue=when,
            watch=self._infer_channels(when or body),
            source=body if self._use_source_phi() else "",
        )

    @staticmethod
    def _action_phrase(body: str) -> str:
        """What to do, without when-clause, at HH:MM, or at <meal>."""
        text = (body or "").strip().rstrip(".")
        m_when = _WHEN_RE.search(text)
        if m_when:
            text = text[: m_when.start()].strip().rstrip(",")
        text = _AT_TIME_RE.sub("", text)
        text = _MEAL_AT_RE.sub("", text)
        text = re.sub(r"\s+", " ", text).strip(" ,.")
        if not text:
            return (body or "").strip().rstrip(".")
        return text[0].upper() + text[1:]

    @staticmethod
    def _expand_plan_bullet(body: str) -> list[str]:
        """Split 'at 11:00 and 21:00' / 'at breakfast and dinner' into two lines."""
        text = (body or "").strip()
        if not text:
            return []
        m_times = _AND_TIMES_RE.search(text)
        if m_times:
            stem = (text[: m_times.start()] + text[m_times.end() :]).strip(" ,")
            return [
                f"{stem} at {m_times.group(1)}".strip(),
                f"{stem} at {m_times.group(2)}".strip(),
            ]
        m_meals = _AND_MEALS_RE.search(text)
        if m_meals:
            stem = (text[: m_meals.start()] + text[m_meals.end() :]).strip(" ,")
            return [
                f"{stem} at {m_meals.group(1)}".strip(),
                f"{stem} at {m_meals.group(2)}".strip(),
            ]
        return [text]

    @classmethod
    def _action_key(cls, text: str) -> str:
        """Compare menu lines to stored action: same strip, ignore periods."""
        phrase = cls._action_phrase(text)
        return re.sub(r"\.", "", (phrase or "").strip()).lower()

    @staticmethod
    def _weekday_index(day: str) -> int | None:
        if not day:
            return None
        try:
            return _WEEKDAYS.index(day.strip().lower())
        except ValueError:
            return None

    def _due_day(self, intent: Intention) -> str:
        if self._use_source_phi():
            return self._weekday_in_text(intent.source or "")
        return (intent.due.day or "").strip()

    def _is_active_on_day(self, intent: Intention, day: str) -> bool:
        """Hide only commitments whose due.day is still in the future.

        Empty due.day, today's due.day, and leftover earlier due.days stay
        visible. Day change must not cancel them.
        """
        return not self._due_day_is_future(intent, day)

    def _due_day_is_future(self, intent: Intention, today: str) -> bool:
        due = self._due_day(intent)
        if not due or not today:
            return False
        due_n = self._normalize_weekday(due)
        today_n = self._normalize_weekday(today)
        if due_n.lower() == today_n.lower():
            return False
        di, ti = self._weekday_index(due_n), self._weekday_index(today_n)
        if di is not None and ti is not None:
            return di > ti
        due_key, today_key = self._month_day_key(due_n), self._month_day_key(today_n)
        if due_key is not None and today_key is not None:
            return due_key > today_key
        return False

    def _brief_intent(self, i: Intention) -> dict[str, Any]:
        return {
            "id": i.intent_id,
            "action": i.action,
            "due_day": i.due.day or "",
            "due_time": i.due.time or "",
            "event": i.event_cue or "",
            "watch": list(i.watch or []),
        }

    def _build_filter_trace(
        self,
        *,
        pending: list[Intention],
        today_pending: list[Intention],
        time_hits: list[Intention],
        channel_needed: list[str],
        day: str,
        step: str,
        time_str: str,
        messages: list[dict],
        extracted: list[dict[str, Any]],
        extract_added: int,
        match: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        today_ids = {i.intent_id for i in today_pending}
        time_hit_ids = {i.intent_id for i in time_hits}
        clock_tasks = [i for i in today_pending if self._phi_times(i)]
        event_group = [
            i for i in today_pending if self._phi_event(i)
        ]
        no_event = [
            i for i in today_pending if not self._phi_event(i)
        ]
        match = match or {}
        if match.get("mode") in ("similarity", "llm"):
            kept_src = match.get("kept") or []
        else:
            kept_src = today_pending
        return {
            "day": day,
            "step": step,
            "clock": time_str or "",
            "extract_added": extract_added,
            "extracted": list(extracted or []),
            "pending": [self._brief_intent(i) for i in pending],
            "drop_future_due_day": [
                self._brief_intent(i) for i in pending if i.intent_id not in today_ids
            ],
            "kept_today": [self._brief_intent(i) for i in today_pending],
            "time_due": [self._brief_intent(i) for i in time_hits],
            "time_not_due": [
                self._brief_intent(i)
                for i in clock_tasks
                if i.intent_id not in time_hit_ids
            ],
            "event_group": [self._brief_intent(i) for i in event_group],
            "no_event_group": [self._brief_intent(i) for i in no_event],
            "check_channels": list(channel_needed),
            "queried_this_step": sorted(self._queried_channels_this_step(messages)),
            "match_mode": match.get("mode") or "off",
            "match_event_due": [
                self._brief_intent(i) for i in (match.get("event_due") or [])
            ],
            "match_event_drop": [
                self._brief_intent(i) for i in (match.get("event_drop") or [])
            ],
            "match_channel_due": [
                self._brief_intent(i) for i in (match.get("channel_due") or [])
            ],
            "match_channel_drop": [
                self._brief_intent(i) for i in (match.get("channel_drop") or [])
            ],
            "match_channel_wait": [
                self._brief_intent(i) for i in (match.get("channel_wait") or [])
            ],
            "match_kept": [self._brief_intent(i) for i in kept_src],
        }

    def _format_filter_trace(self, trace: dict[str, Any]) -> str:
        def rows(items: list[dict[str, Any]]) -> list[str]:
            if not items:
                return ["- （无）"]
            lines = []
            for r in items:
                bits = [r.get("action") or r.get("id")]
                due = self._due_display(
                    str(r.get("due_day") or ""), str(r.get("due_time") or "")
                )
                if due:
                    bits.append(f"due={due}")
                if r.get("event"):
                    bits.append(f"event={r['event']}")
                watch = r.get("watch") or []
                if watch:
                    bits.append("watch=" + ",".join(str(w) for w in watch))
                bits.append(r.get("id") or "")
                lines.append("- " + " | ".join(str(b) for b in bits if b))
            return lines

        clock = trace.get("clock") or "（无可信钟）"
        heading = f"## {trace.get('day') or '?'} {trace.get('step') or ''}".strip()
        lines = [
            heading + f"  clock={clock}",
            "",
            "代码筛选：隐藏未来 due.day，给时钟命中打 TIME-DUE。",
            "event / channel：相似度检索筛掉未发生的 cue / 已查未命中的 watch"
            "（不是子串 EVENT-CUED）。匹配只看 event 字符串与 scene_cues/State 子串，"
            "看不见 action。TIME-DUE 只比本步时钟和 due.time。命中后注入完整 intention 行。"
            "同线索库存 fan-out 补齐漏标的 due。关过滤时全部注入。"
            "无 State 的 watch 不筛掉、不盖 DUE。CHECK 是 today pending 的 watch 并集；"
            "不必等全部 CHECK 查完，每条 State 之后用 vignette+已查内容比一次 event。"
            "有内容的 event_cue 也可对 vignette 打分；仅频道名的 cue 等 State。"
            "未命中时钟不注入、不进 TODAY pending；`--gate-time-due` 才丢掉对应点选。",
            "",
            f"### 库存 pending（{len(trace.get('pending') or [])}）提取字段 time / event / watch",
            *rows(trace.get("pending") or []),
            "",
            f"### 1. 日历 — 筛掉未来 due.day（{len(trace.get('drop_future_due_day') or [])}）",
            *rows(trace.get("drop_future_due_day") or []),
            "",
            f"留下 today pending {len(trace.get('kept_today') or [])}",
            "",
            (
                f"### 2. 时钟 TIME-DUE — 打标签 {len(trace.get('time_due') or [])}；"
                f"有 due.time 未命中 {len(trace.get('time_not_due') or [])}"
                + (
                    "（不注入、不进 TODAY pending"
                    + ("；`--gate-time-due` 丢掉点选" if self.gate_time_due else "")
                    + "）"
                )
            ),
            "命中:",
            *rows(trace.get("time_due") or []),
            "未命中:",
            *rows(trace.get("time_not_due") or []),
            "",
            "### 3. CHECK — today pending 的 watch 并集（已查的去掉）",
            "CHECK: "
            + (", ".join(trace.get("check_channels") or []) or "（无）"),
            "queried: "
            + (", ".join(trace.get("queried_this_step") or []) or "（无）"),
            "",
            (
                f"### 4. 事件相似度 — 只看 event 字符串"
                + (
                    "；本步 CHECK 未查完，先不匹配"
                    if (trace.get("match_mode") or "") == "wait_channels"
                    else "，已有 State 时用 vignette+已查内容比一次"
                )
                + (
                    f"（mode={trace.get('match_mode') or 'off'}；"
                    f"due {len(trace.get('match_event_due') or [])}，"
                    f"筛掉 {len(trace.get('match_event_drop') or [])}）"
                )
            ),
            "到期:",
            *rows(trace.get("match_event_due") or []),
            "筛掉:",
            *rows(trace.get("match_event_drop") or []),
            "",
            (
                "### 5. channel — 该行任意 watch 有 State 即可打分；"
                "全查完且未命中才筛掉；无 State 的 wait 留给 CHECK"
            ),
            "watch 到期:",
            *rows(trace.get("match_channel_due") or []),
            "筛掉（已查过、未到期）:",
            *rows(trace.get("match_channel_drop") or []),
            "仍 wait（未查）:",
            *rows(trace.get("match_channel_wait") or []),
            "",
            f"### 6. 交给 choose 的剩余（{len(trace.get('match_kept') or [])}）",
            *rows(trace.get("match_kept") or []),
        ]
        extracted = trace.get("extracted") or []
        lines.append("")
        if extracted:
            lines.append(
                f"### 本步 extract 新种（{len(extracted)}，含模型原始字段）"
            )
            for ex in extracted:
                raw = ex.get("raw") if isinstance(ex, dict) else {}
                st = ex.get("stored") if isinstance(ex, dict) else {}
                raw = raw or {}
                st = st or {}
                lines.append(
                    "- raw "
                    f"due_day={raw.get('due_day')!r} due_time={raw.get('due_time')!r} "
                    f"event={raw.get('event_cue')!r} watch={raw.get('watch')!r} "
                    f"→ stored {st.get('action') or '-'} "
                    f"due={st.get('due_day') or '-'} {st.get('due_time') or ''} "
                    f"event={st.get('event') or '-'} watch={st.get('watch') or []}"
                )
        else:
            lines.append("### 本步 extract 新种：无（空场景 / 缓存 / 日计划正则另走）")
        return "\n".join(lines) + "\n"

    def _append_filter_log(self, text: str) -> None:
        if not self._filter_log_path or not text:
            return
        self._filter_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._filter_log_path.open("a", encoding="utf-8") as handle:
            handle.write(text)
            handle.write("\n")

    @staticmethod
    def _rewrite_due_world(intent: Intention, *, day: str, new_time: str = "") -> None:
        """Treat a reschedule as rewriting the world's due slot."""
        if day:
            intent.due.day = day
        if new_time:
            intent.due.time = new_time

    # ------------------------------------------------------------- filters
    def _filter_time_due(self, pending: list[Intention], time_str: str) -> list[Intention]:
        if not time_str:
            return []
        cur = self._to_minutes(time_str)
        if cur is None:
            return []
        hits = []
        for intent in pending:
            for raw in self._phi_times(intent):
                tgt = self._to_minutes(raw)
                if tgt is None:
                    continue
                if abs(cur - tgt) <= self.time_tolerance_minutes:
                    hits.append(intent)
                    break
        return hits

    def _menu_matches_clock_intent(self, label: str, intent: Intention) -> bool:
        """Menu line binds to a clock slot by stripped action + HH:MM."""
        if not self._action_matches_menu(label, intent):
            return False
        due_times = self._phi_times(intent)
        found = _HHMM_RE.findall(label or "")
        if due_times and found:
            return any(
                self._clocks_equal(t, due_t) for t in found for due_t in due_times
            )
        return True

    @staticmethod
    def _clocks_equal(a: str, b: str) -> bool:
        def parts(s: str) -> tuple[int, int] | None:
            m = re.match(r"^(\d{1,2}):(\d{2})$", (s or "").strip())
            if not m:
                return None
            return int(m.group(1)), int(m.group(2))

        pa, pb = parts(a), parts(b)
        return pa is not None and pa == pb

    def gate_undue_clock_tasks(
        self, action: dict[str, Any], step_raw: str
    ) -> tuple[list[Any], list[Any]]:
        """Drop menu picks that match TIME-WAIT and not TIME-DUE. Event/channel stay."""
        ids = list(action.get("task_ids") or [])
        if not self.gate_time_due:
            return ids, []
        menu = parse_action_menu_map(step_raw or "")
        hits = list(self._last_time_hits or [])
        waits = list(self._last_time_waits or [])
        kept: list[Any] = []
        dropped: list[Any] = []
        for tid in ids:
            key = str(tid).strip()
            label = menu.get(key.lower(), "") or menu.get(key, "")
            if not label:
                kept.append(tid)
                continue
            due_hit = any(self._menu_matches_clock_intent(label, i) for i in hits)
            wait_hit = any(self._menu_matches_clock_intent(label, i) for i in waits)
            if wait_hit and not due_hit:
                dropped.append(tid)
            else:
                kept.append(tid)
        return kept, dropped

    def _watch_needed(self, pending: list[Intention], messages: list[dict]) -> list[str]:
        """Union of watch names on today pending, minus already queried."""
        queried = self._queried_channels_this_step(messages)
        names: list[str] = []
        for intent in pending:
            for name in self._phi_watch(intent):
                name = (name or "").strip().lower()
                if not name or name == "clock" or name in queried:
                    continue
                if name not in names:
                    names.append(name)
        return names

    def _advance_recall_tick(self, *, day: str, step: str) -> None:
        key = f"{day}|{step}"
        prev = getattr(self, "_last_tick_key", "")
        if key and key != prev:
            self._recall_tick += 1
            self._last_tick_key = key

    def _note_queried_channels(self, messages: list[dict]) -> None:
        for name in self._queried_channels_this_step(messages):
            if name == "clock":
                continue
            self._channel_last_query_tick[name] = self._recall_tick

    def _channel_cadence_due(self, name: str) -> bool:
        interval = int(self._channel_interval_steps.get(name) or 2)
        last = self._channel_last_query_tick.get(name)
        if last is None:
            return True
        return (self._recall_tick - last) >= interval

    def _ensure_channel_cadence(self, pending: list[Intention]) -> None:
        """Cadence judge removed; intervals are unused."""
        del pending
        self.last_cadence_info = {
            "mode": "off",
            "intervals": {},
        }

    @staticmethod
    def _queried_channels_this_step(messages: list[dict]) -> set[str]:
        if not messages:
            return set()
        found: set[str] = set()
        for msg in messages[current_step_start_index(messages) :]:
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            content = msg.get("content")
            if not isinstance(content, str):
                continue
            if content.startswith("Time:"):
                found.add("clock")
            for m in _STATE_REPLY_RE.finditer(content):
                found.add(m.group(1).strip().lower())
        return found

    def _state_replies_this_step(self, messages: list[dict]) -> dict[str, str]:
        found: dict[str, str] = {}
        if not messages:
            return found
        for msg in messages[current_step_start_index(messages) :]:
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            content = msg.get("content")
            if not isinstance(content, str):
                continue
            for m in _STATE_REPLY_RE.finditer(content):
                found[m.group(1).strip().lower()] = m.group(2).strip()
        return found

    def _will_query_channels(self, channel_needed: list[str]) -> bool:
        """Session will rewrite choose to query_state these names this step."""
        return bool(channel_needed) and self.force_query_channels

    def _match_event_channel(
        self,
        today_pending: list[Intention],
        *,
        observation: str,
        day: str,
        time_str: str,
        messages: list[dict],
        channel_needed: list[str] | None = None,
    ) -> dict[str, Any]:
        """Event-string similarity vs vignette / State. Does not use action."""
        del channel_needed
        empty = {
            "mode": "off",
            "kept": list(today_pending),
            "event_due": [],
            "channel_due": [],
            "event_drop": [],
            "channel_drop": [],
            "channel_wait": [],
        }
        if not self.use_llm_match:
            self.last_match_info = {"mode": "off"}
            return empty
        needs = [
            i
            for i in today_pending
            if (i.event_cue or "").strip() or list(i.watch or [])
        ]
        if not needs:
            self.last_match_info = {"mode": "skip", "reason": "no_event_or_watch"}
            empty["mode"] = "skip"
            return empty

        states = self._state_replies_this_step(messages)
        queried = set(states) | self._queried_channels_this_step(messages)
        labels = self._ensure_cue_match(
            observation,
            today_pending,
            day=day,
            time_str=time_str,
            messages=messages,
        )
        raw_due = set(labels.get("due_ids") or [])
        due_ids = self._expand_event_due_ids(today_pending, raw_due)
        due_ids -= self._event_skip_ids(day, observation)
        labels["due_ids"] = list(due_ids)

        split = self._apply_match_labels(
            today_pending,
            due_ids=due_ids,
            queried=queried,
            states=states,
        )
        split["mode"] = "similarity"
        self.last_match_info = {
            "mode": "similarity",
            "due_ids": list(due_ids),
            "due_fanout_ids": sorted(due_ids - raw_due),
            "event_due_ids": [i.intent_id for i in split["event_due"]],
            "event_wait_ids": [i.intent_id for i in split["event_drop"]],
            "channel_due_ids": [i.intent_id for i in split["channel_due"]],
            "channel_wait_ids": [i.intent_id for i in split["channel_wait"]],
            "channel_drop_ids": [i.intent_id for i in split["channel_drop"]],
            "kept": [i.intent_id for i in split["kept"]],
            "queried": sorted(queried),
            "cue_listing": labels.get("listing") or [],
            "scores": labels.get("scores") or {},
        }
        return split

    def _ns_to_ids(self, raw: Any, index: dict[int, str]) -> list[str]:
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        for item in raw:
            try:
                n = int(item)
            except (TypeError, ValueError):
                continue
            iid = index.get(n)
            if iid and iid not in out:
                out.append(iid)
        return out

    def _ensure_cue_match(
        self,
        observation: str,
        today_pending: list[Intention],
        *,
        day: str,
        time_str: str,
        messages: list,
    ) -> dict[str, Any]:
        """One similarity pass on current vignette + State already in this step."""
        text = (observation or "").strip()
        states = self._state_replies_this_step(messages)
        state_fp = "|".join(f"{k}={states[k]}" for k in sorted(states))
        # Clock is not an event-match input; do not re-ask just because check_time ran.
        _ = time_str
        cue_key = f"{day}|{text}|{state_fp}"
        if cue_key == self._last_cue_key and self._last_match_labels:
            return dict(self._last_match_labels)
        data = self._call_cue_match_judge(
            text,
            today_pending,
            day=day,
            states=states,
        )
        labels = {
            "due_ids": list(data.get("due_ids") or []),
            "time_due_ids": list(data.get("time_due_ids") or []),
            "listing": list(data.get("listing") or []),
            "scores": dict(data.get("scores") or {}),
        }
        self._last_due_union_key = f"{day}|{text}"
        self._last_cue_key = cue_key
        self._last_match_labels = labels
        return dict(labels)

    def _cue_match_line(
        self, n: int, intent: Intention, *, field: str
    ) -> str | None:
        """One cue type per line. Never include action or the other field."""
        if field == "time":
            if not intent.due.time:
                return None
            bits = [f"time={intent.due.time}"]
            if intent.due.day:
                bits.append(f"day={intent.due.day}")
            return f"{n}. " + " | ".join(bits)
        if field == "event":
            event = self._phi_event(intent)
            if not event:
                return None
            return f"{n}. event={event}"
        raise ValueError(f"unknown cue field {field!r}")

    def _call_cue_match_judge(
        self,
        observation: str,
        today_pending: list[Intention],
        *,
        day: str,
        states: dict[str, str],
    ) -> dict[str, Any]:
        """Event-only similarity. TIME-DUE is code `_filter_time_due`, not this call.

        The matcher sees event strings vs vignette plus any State already
        retrieved this step — never action. Does not wait for every CHECK name.
        """
        ordered = self._pending_for_judge(today_pending, day=day)
        self._cue_index_to_id = {}
        listing: list[str] = []
        due_ids: list[str] = []
        scores: dict[str, float] = {}
        for n, intent in enumerate(ordered, start=1):
            self._cue_index_to_id[n] = intent.intent_id
            line = self._cue_match_line(n, intent, field="event")
            if not line:
                continue
            if "action=" in line.lower() or "time=" in line.lower():
                _fail("match", "event listing leaked action or time")
            listing.append(line)
            hay = self._event_haystack(intent, observation, states)
            if hay is None:
                continue
            score = self._event_similarity(self._phi_event(intent), hay)
            scores[intent.intent_id] = round(score, 3)
            if score >= self._event_sim_threshold:
                due_ids.append(intent.intent_id)
        return {
            "due_ids": due_ids,
            "time_due_ids": [],
            "listing": listing,
            "scores": scores,
        }

    def _watch_names(self, intent: Intention) -> list[str]:
        return [
            (w or "").strip().lower()
            for w in self._phi_watch(intent)
            if (w or "").strip() and (w or "").strip().lower() != "clock"
        ]

    def _cue_is_watch_name_only(self, intent: Intention) -> bool:
        """True when the cue has no content beyond the watched channel name.

        "the email lands" → {email}; matching that against a vignette that
        only says "check email" would false-due. Richer cues
        ("confirmation email arrives") may match the vignette itself.
        """
        watches = self._watch_names(intent)
        if not watches:
            return False
        names = set()
        for w in watches:
            names.add(w)
            names.update(p for p in w.split("_") if p)
        toks = set(self._event_cue_tokens(self._phi_event(intent)))
        return not toks or toks <= names

    def _event_haystack(
        self,
        intent: Intention,
        observation: str,
        states: dict[str, str],
    ) -> str | None:
        """Text the matcher may see. No action leak.

        Meet: event_cue vs scene_cues (event_cue style) and/or this-step
        State. Watch rows whose cue is only the channel name wait for State
        (otherwise "check email" would due "the email lands"). Cues with extra
        content may match the rewritten vignette without a query.
        """
        watches = self._watch_names(intent)
        vignette = self._vignette_for_event_match(observation)
        seen = [w for w in watches if w in states]
        state_parts = [self._state_body(states.get(w, "")) for w in seen]
        state_parts = [p for p in state_parts if p]
        if watches and self._cue_is_watch_name_only(intent):
            if not state_parts:
                return None
            return " ".join(state_parts)
        parts = [vignette, *state_parts]
        hay = " ".join(p for p in parts if p)
        return hay or None

    def _vignette_for_event_match(self, observation: str) -> str:
        """Prefer Update-Judge scene_cues (event_cue style); else raw vignette."""
        raw = (observation or "").strip()
        cues = [c.strip() for c in (self._last_scene_cues or []) if str(c).strip()]
        if not cues:
            return raw
        block = "\n".join(cues)
        if raw and raw not in block:
            return f"{block}\n{raw}"
        return block

    def _event_skip_ids(self, day: str, observation: str) -> set[str]:
        """Rows patched this scene: the notice rewrites the cue, it does not fire."""
        text = (observation or "").strip()
        obs_key = f"{day}|{text}"
        if obs_key and obs_key == getattr(self, "_last_update_obs_key", None):
            return set(self._patched_ids or [])
        return set()

    def _event_similarity(self, cue: str, text: str) -> float:
        """Best similarity of the event string against haystack substrings.

        Content tokens of the cue must appear in the haystack; shared boilerplate
        like "you notice the …" must not match a different object.
        """
        cue_n = " ".join((cue or "").lower().split())
        hay = " ".join((text or "").lower().split())
        if not cue_n or not hay:
            return 0.0
        if cue_n in hay:
            return 1.0
        cue_toks = list(self._event_cue_tokens(cue_n))
        hay_toks = list(_CUE_TOKEN_RE.findall(hay))
        hay_set = set(hay_toks)
        if cue_toks and not all(t in hay_set for t in cue_toks):
            return 0.0
        hay_content = [t for t in hay_toks if t not in _CUE_STOP and len(t) > 1]
        if cue_toks and self._tokens_in_order(cue_toks, hay_content):
            return 1.0
        if len(cue_toks) >= 2:
            n = len(cue_toks)
            for i in range(0, len(hay_toks) - n + 1):
                if hay_toks[i : i + n] == cue_toks:
                    return 1.0
            ba = {tuple(cue_toks[i : i + 2]) for i in range(n - 1)}
            bb = {tuple(hay_toks[i : i + 2]) for i in range(max(len(hay_toks) - 1, 0))}
            if ba and ba <= bb:
                return 0.85
        best = 0.0
        for window in self._event_windows(hay, len(cue_n)):
            if cue_toks:
                wset = set(_CUE_TOKEN_RE.findall(window))
                if not all(t in wset for t in cue_toks):
                    continue
            best = max(best, SequenceMatcher(None, cue_n, window).ratio())
        return best

    @staticmethod
    def _tokens_in_order(needle: list[str], hay: list[str]) -> bool:
        """True if needle tokens appear in order in hay (not necessarily adjacent)."""
        if not needle:
            return False
        i = 0
        for tok in hay:
            if i < len(needle) and tok == needle[i]:
                i += 1
        return i == len(needle)

    @staticmethod
    def _event_windows(text: str, cue_len: int) -> list[str]:
        if not text:
            return []
        windows = [text]
        for part in re.split(r"[.!?\n;]+", text):
            part = part.strip()
            if part:
                windows.append(part)
        span = max(int(cue_len), 8)
        pad = max(8, span // 4)
        step = max(4, span // 4)
        n = len(text)
        for i in range(0, max(n - span + 1, 1), step):
            windows.append(text[i : i + span + pad])
        return windows

    @staticmethod
    def _cue_match_schema(n_max: int) -> dict[str, Any]:
        n_item = {
            "type": "integer",
            "minimum": 1,
            "maximum": n_max,
        }
        return {
            "type": "object",
            "properties": {
                "event_due": {"type": "array", "items": n_item},
            },
            "required": ["event_due"],
            "additionalProperties": False,
        }

    def _apply_match_labels(
        self,
        today_pending: list[Intention],
        *,
        queried: set[str],
        states: dict[str, str] | None = None,
        due_ids: set[str] | None = None,
        event_due_ids: set[str] | None = None,
        channel_due_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        """Drop unmatched narrative events; keep unqueried watch rows for CHECK.

        A watch row may due from State, or from a vignette hit when the cue
        has content beyond the channel name. Remaining CHECK names are not a
        gate. No hit and still unqueried → wait. All watches queried and no
        hit → drop. Clock rows keep TIME-DUE even if an incidental cue missed.
        """
        event_marked = set(due_ids or []) | set(event_due_ids or [])
        channel_marked = set(channel_due_ids or [])
        marked = event_marked | channel_marked
        event_due: list[Intention] = []
        event_drop: list[Intention] = []
        channel_due: list[Intention] = []
        channel_drop: list[Intention] = []
        channel_wait: list[Intention] = []
        kept: list[Intention] = []
        states = {str(k).strip().lower(): str(v) for k, v in (states or {}).items()}
        for intent in today_pending:
            has_event = bool(self._phi_event(intent))
            watches = [
                (w or "").strip().lower()
                for w in self._phi_watch(intent)
                if (w or "").strip() and (w or "").strip().lower() != "clock"
            ]
            any_seen = bool(watches) and any(w in queried for w in watches)
            all_seen = bool(watches) and all(w in queried for w in watches)
            state_hit = any_seen and any(
                w in queried
                and self._state_matches_intent(states.get(w, ""), intent)
                for w in watches
            )
            event_hit = intent.intent_id in event_marked
            drop = False
            if watches and state_hit:
                channel_due.append(intent)
            elif watches and any_seen and (
                event_hit or intent.intent_id in channel_marked
            ):
                channel_due.append(intent)
            elif watches and event_hit:
                event_due.append(intent)
            elif watches and not all_seen:
                channel_wait.append(intent)
            elif watches and all_seen:
                if self._phi_times(intent):
                    # Clock row with an incidental watch: State must not erase TIME-DUE.
                    pass
                else:
                    channel_drop.append(intent)
                    drop = True
            if has_event and intent.intent_id not in marked:
                if watches:
                    pass
                elif self._phi_times(intent):
                    event_drop.append(intent)
                else:
                    event_drop.append(intent)
                    drop = True
            elif has_event:
                if watches:
                    pass
                else:
                    event_due.append(intent)
            if not drop:
                kept.append(intent)
        kept_ids = {i.intent_id for i in kept}
        return {
            "kept": kept,
            "event_due": [i for i in event_due if i.intent_id in kept_ids],
            "event_drop": event_drop,
            "channel_due": [i for i in channel_due if i.intent_id in kept_ids],
            "channel_drop": channel_drop,
            "channel_wait": channel_wait,
        }

    _STATE_EMPTY = frozenset({"", "(no updates)", "(none yet)"})
    _STATE_GENERIC = frozenset(
        {
            "active",
            "added",
            "afternoon",
            "appointment",
            "available",
            "balance",
            "calendar",
            "channel",
            "check",
            "delivery",
            "email",
            "hold",
            "later",
            "library",
            "new",
            "no",
            "notice",
            "portal",
            "shipment",
            "state",
            "status",
            "today",
            "update",
        }
    )
    _STATE_PREFIX_RE = re.compile(
        r"^(appointment portal|calendar update|library notice|"
        r"balance check|delivery status|course portal)\s*:\s*",
        re.I,
    )

    @classmethod
    def _state_body(cls, text: str) -> str:
        raw = (text or "").strip()
        if raw.lower() in cls._STATE_EMPTY:
            return ""
        return cls._STATE_PREFIX_RE.sub("", raw).strip()

    @staticmethod
    def _stem_token(tok: str) -> str:
        for suf in ("ing", "ed", "es", "s"):
            if tok.endswith(suf) and len(tok) - len(suf) >= 3:
                return tok[: -len(suf)]
        return tok

    def _state_matches_intent(self, state_text: str, intent: Intention) -> bool:
        """Non-empty State vs this row's event_cue, not the channel title."""
        body = self._state_body(state_text)
        if not body:
            return False
        cue = self._phi_event(intent)
        if cue and self._event_cues_share(body, cue):
            return True
        cue_toks = {
            self._stem_token(t)
            for t in self._event_cue_tokens(cue)
            if t not in self._STATE_GENERIC
        }
        state_toks = {
            self._stem_token(t)
            for t in self._event_cue_tokens(body)
            if t not in self._STATE_GENERIC
        }
        return bool(cue_toks and state_toks and (cue_toks & state_toks))

    @staticmethod
    def _event_cue_tokens(cue: str) -> tuple[str, ...]:
        raw = _CUE_TOKEN_RE.findall((cue or "").lower())
        return tuple(t for t in raw if t not in _CUE_STOP and len(t) > 1)

    @classmethod
    def _event_cues_share(cls, left: str, right: str) -> bool:
        """Same stored condition, not vignette substring EVENT-CUED."""
        a, b = cls._event_cue_tokens(left), cls._event_cue_tokens(right)
        if not a or not b:
            return False
        if a == b:
            return True
        if len(a) < 2 or len(b) < 2:
            return False
        ba = {a[i : i + 2] for i in range(len(a) - 1)}
        bb = {b[i : i + 2] for i in range(len(b) - 1)}
        if ba & bb:
            return True
        short, long_ = (a, b) if len(a) <= len(b) else (b, a)
        n = len(short)
        return any(long_[i : i + n] == short for i in range(len(long_) - n + 1))

    def _expand_event_due_ids(
        self, pending: list[Intention], event_due_ids: set[str]
    ) -> set[str]:
        """If the judge hits one row, also due pending rows with the same cue."""
        if not event_due_ids:
            return set()
        by_id = {i.intent_id: i for i in pending}
        extra = set(event_due_ids)
        if not any(
            iid in by_id and self._phi_event(by_id[iid])
            for iid in extra
        ):
            return extra
        changed = True
        while changed:
            changed = False
            seeds = [
                by_id[iid]
                for iid in extra
                if iid in by_id and self._phi_event(by_id[iid])
            ]
            for intent in pending:
                if intent.intent_id in extra:
                    continue
                cue = self._phi_event(intent)
                if not cue:
                    continue
                if any(
                    self._event_cues_share(cue, self._phi_event(seed))
                    for seed in seeds
                ):
                    extra.add(intent.intent_id)
                    changed = True
        return extra

    def _cluster_by_shared_cue(
        self, items: list[Intention]
    ) -> list[list[Intention]]:
        remaining = list(items)
        clusters: list[list[Intention]] = []
        while remaining:
            cluster = [remaining.pop(0)]
            changed = True
            while changed:
                changed = False
                keep: list[Intention] = []
                for other in remaining:
                    if any(
                        self._event_cues_share(
                            self._phi_event(other), self._phi_event(member)
                        )
                        for member in cluster
                    ):
                        cluster.append(other)
                        changed = True
                    else:
                        keep.append(other)
                remaining = keep
            clusters.append(cluster)
        return clusters

    def _shared_cue_label(self, items: list[Intention]) -> str:
        seqs = [self._event_cue_tokens(self._phi_event(i)) for i in items]
        seqs = [s for s in seqs if s]
        if not seqs:
            return ((items[0].event_cue if items else "") or "cue").strip()
        first = seqs[0]
        for n in range(len(first), 1, -1):
            for i in range(len(first) - n + 1):
                span = first[i : i + n]
                if all(
                    any(s[j : j + n] == span for j in range(len(s) - n + 1))
                    for s in seqs[1:]
                ):
                    return " ".join(span)
        if all(s == first for s in seqs):
            return " ".join(first)
        return " ".join(first)

    def _append_event_inject_section(
        self,
        sections: list[str],
        items: list[Intention],
        render_lines,
        *,
        due: bool,
        match_filtered: bool,
    ) -> None:
        if due and match_filtered:
            sections.append(
                "DUE (event similarity vs this vignette and/or this-step State; "
                "matcher saw event text only. After any of a row's CHECK "
                "channels replies, matching uses that State plus the vignette "
                "(does not wait for every CHECK name). "
                "One cue can due several rows — include ALL matching menu handles "
                "in this choose; the vignette may name only one action):"
            )
        else:
            sections.append(
                "EVENT pending (not a due stamp; if THIS vignette shows "
                "event=..., do ALL rows that share that cue, not just the "
                "action named in the scene; otherwise leave them):"
            )
        for cluster in self._cluster_by_shared_cue(items):
            if len(cluster) >= 2:
                sections.append(f"  [{self._shared_cue_label(cluster)}]")
            sections.extend(render_lines(cluster, "DUE" if due and match_filtered else "EVENT"))

    # ----------------------------------------------------------- formatting
    def _format_injection(
        self,
        *,
        time_hits: list[Intention],
        event_hits: list[Intention],
        channel_hits: list[Intention],
        channel_needed: list[str],
        today_pending: list[Intention],
        day: str,
        time_str: str,
        force_check_time: bool = False,
        pending_time_n: int = 0,
        match_filtered: bool = False,
        time_waits: list[Intention] | None = None,
    ) -> str:
        sections: list[str] = []
        header = f"Prospective intention store @ {day} {time_str or '(clock unknown)'}"
        sections.append(header)
        if force_check_time:
            sections.append(
                f"MUST check_time (or query_state channel=clock) BEFORE choose: "
                f"no trusted current clock, but {pending_time_n} pending time "
                f"intention(s) need a real now to decide TIME-DUE."
            )

        def _lines(items: list[Intention], tag: str) -> list[str]:
            out = []
            seen = set()
            for i in items:
                if i.intent_id in seen:
                    continue
                seen.add(i.intent_id)
                out.append(f"- [{tag}] {self._render_intent(i)}")
            return out

        due_stamp_ids = (
            {i.intent_id for i in time_hits}
            | {i.intent_id for i in event_hits}
            | {i.intent_id for i in channel_hits}
        )
        waits = list(time_waits or [])
        wait_ids = {i.intent_id for i in waits}
        clock_known = bool((time_str or "").strip())
        if clock_known:
            for item in today_pending:
                if (
                    self._phi_times(item)
                    and item.intent_id not in due_stamp_ids
                    and item.intent_id not in wait_ids
                ):
                    waits.append(item)
                    wait_ids.add(item.intent_id)

        block = _lines(time_hits, "TIME-DUE")
        if block:
            if self.gate_time_due:
                sections.append(
                    "TIME-DUE (clock matches now — include ALL of these in "
                    "task_ids if they are on the menu; do not pick only a DUE "
                    "event row):"
                )
            else:
                sections.append(
                    "TIME-DUE (clock matches now — include ALL of these in "
                    "task_ids if they are on the menu; do not skip them because "
                    "another DUE row is also listed):"
                )
            sections.extend(block)

        if channel_needed:
            sections.append(
                "MUST query_state these CHECK channels BEFORE choose "
                "(union of watch on today pending): "
                + ", ".join(channel_needed)
            )

        due_hits: list[Intention] = []
        due_seen: set[str] = set()
        for item in list(event_hits or []) + list(channel_hits or []):
            if item.intent_id in due_seen:
                continue
            due_seen.add(item.intent_id)
            due_hits.append(item)

        shown = set(due_stamp_ids) | wait_ids
        if due_hits:
            self._append_event_inject_section(
                sections,
                due_hits,
                _lines,
                due=True,
                match_filtered=match_filtered,
            )
            shown.update(i.intent_id for i in due_hits)

        # Unknown clock: clock rows are not do-now (MUST check_time covers them).
        if not clock_known:
            shown.update(
                i.intent_id
                for i in today_pending
                if self._phi_times(i) and i.intent_id not in due_stamp_ids
            )
        # Unqueried watch: CHECK names only; do not list the action as PENDING.
        shown.update(
            i.intent_id
            for i in today_pending
            if i.intent_id not in shown and self._watch_names(i)
        )

        event_pending = [
            i
            for i in today_pending
            if i.intent_id not in shown
            and self._phi_event(i)
            and not self._watch_names(i)
        ]
        rest = [
            i
            for i in today_pending
            if i.intent_id not in shown
            and not (self._phi_event(i) and not self._watch_names(i))
        ]
        if event_pending:
            self._append_event_inject_section(
                sections,
                event_pending,
                _lines,
                due=False,
                match_filtered=False,
            )
            shown.update(i.intent_id for i in event_pending)
        if rest:
            sections.append(
                "TODAY pending (not a due stamp; match current menu by meaning):"
            )
            sections.extend(_lines(rest, "PENDING"))

        # If everything empty, say so explicitly.
        body = "\n".join(sections)
        if body.strip() == header.strip():
            return header + "\n(No pending intentions.)"
        return scrub_task_handles(body)

    @staticmethod
    def _due_display(day: str = "", time: str = "") -> str:
        d = (day or "").strip()
        t = (time or "").strip()
        if not d and not t:
            return ""
        return f"{d} {t}".strip()

    def _intent_field_bits(self, i: Intention) -> list[str]:
        bits = [f"action={i.action}"]
        due = self._due_display(i.due.day, i.due.time)
        if due:
            bits.append(f"due={due}")
        if i.event_cue:
            bits.append(f"event={i.event_cue}")
        if i.watch:
            bits.append("watch=" + ",".join(i.watch))
        return bits

    def _render_intent(self, i: Intention) -> str:
        if self._use_source_phi() and (i.source or "").strip():
            return (i.source or "").strip()
        parts = [i.action]
        due = self._due_display(i.due.day, i.due.time)
        if due:
            parts.append(f"due={due}")
        if i.event_cue:
            parts.append(f"event={i.event_cue}")
        if i.watch:
            parts.append("watch=" + ",".join(i.watch))
        parts.append(f"status={i.status}")
        return " | ".join(parts)

    def _insert(self, intent: Intention) -> None:
        """Always add a new row. No action-overlap merge."""
        if not intent.intent_id:
            intent.intent_id = self._new_id()
        self.intentions[intent.intent_id] = intent

    def _infer_channels(self, text: str) -> list[str]:
        low = (text or "").lower()
        found: list[str] = []
        for name, hints in CHANNEL_HINTS.items():
            if name == "clock":
                continue
            if any(h in low for h in hints) and name not in found:
                found.append(name)
        return found

    @staticmethod
    def _first_time(text: str) -> str:
        m = _TIME_RE.search(text or "")
        return m.group(0) if m else ""

    @staticmethod
    def _to_minutes(t: str) -> int | None:
        m = _TIME_RE.search(t or "")
        if not m:
            return None
        return int(m.group(1)) * 60 + int(m.group(2))

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {
            t
            for t in re.findall(r"[a-z0-9$]+", (text or "").lower())
            if t not in {
                "a", "an", "the", "to", "of", "and", "or", "for", "on", "in",
                "at", "when", "your", "you", "with", "is", "it", "be", "do",
            }
            and len(t) > 1
        }

    def _overlap_score(self, a: Any, b: Any) -> float:
        if isinstance(a, Intention):
            a = f"{a.action} {a.event_cue}"
        if isinstance(b, Intention):
            b = f"{b.action} {b.event_cue}"
        ta, tb = self._tokens(str(a)), self._tokens(str(b))
        if not ta or not tb:
            return 0.0
        inter = len(ta & tb)
        return inter / float(min(len(ta), len(tb)))

    @staticmethod
    def _new_id() -> str:
        return "int_" + uuid.uuid4().hex[:10]

    def _export_payload(self) -> dict[str, Any]:
        return {
            "intentions": [i.to_dict() for i in self.intentions.values()],
            "seeded_days": sorted(self._seeded_days),
            "daily_day": self._daily_day,
            "recall_tick": self._recall_tick,
            "channel_interval_steps": dict(self._channel_interval_steps),
            "channel_last_query_tick": dict(self._channel_last_query_tick),
        }

    def _status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for intent in self.intentions.values():
            counts[intent.status] = counts.get(intent.status, 0) + 1
        return counts

    def _save(self) -> None:
        if not self.store_path:
            return
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._export_payload()
        self.store_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        md_path = self.store_path.with_suffix(".md")
        md_path.write_text(self._render_readable(payload), encoding="utf-8")

    def _save_step(
        self,
        *,
        event: str,
        day: str = "",
        step: str = "",
        time_str: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Append one inspectable snapshot so a bad step can be grepped later."""
        if not self._step_log_path:
            return
        self._step_log_path.parent.mkdir(parents=True, exist_ok=True)
        rec: dict[str, Any] = {
            "event": event,
            "day": day,
            "step": step,
            "time": time_str,
            "n_intentions": len(self.intentions),
            "status_counts": self._status_counts(),
            "intentions": [i.to_dict() for i in self.intentions.values()],
        }
        if extra:
            rec.update(extra)
        with self._step_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _render_readable(self, payload: dict[str, Any]) -> str:
        """Human-readable current-board dump (overwritten; history is steps.jsonl)."""
        lines = [
            f"# Intention store  (daily_day={payload.get('daily_day') or '-'})",
            "",
        ]
        by_status: dict[str, list[dict[str, Any]]] = {
            "pending": [],
            "done": [],
            "canceled": [],
        }
        for item in payload.get("intentions") or []:
            by_status.setdefault(item.get("status") or "?", []).append(item)
        for status in ("pending", "done", "canceled"):
            items = by_status.get(status) or []
            lines.append(f"## {status} ({len(items)})")
            if not items:
                lines.append("- (none)")
                lines.append("")
                continue
            for item in items:
                due = item.get("due") if isinstance(item.get("due"), dict) else {}
                bits = [item.get("action") or item.get("intent_id")]
                due_label = self._due_display(
                    str(due.get("day") or ""), str(due.get("time") or "")
                )
                if due_label:
                    bits.append(f"due={due_label}")
                if item.get("event_cue"):
                    bits.append(f"event={item['event_cue']}")
                watch = item.get("watch") or []
                if watch:
                    bits.append("watch=" + ",".join(str(w) for w in watch))
                bits.append(item.get("intent_id") or "")
                lines.append("- " + " | ".join(str(b) for b in bits if b))
            lines.append("")
        return "\n".join(lines) + "\n"

    def _load(self) -> None:
        raw = json.loads(self.store_path.read_text(encoding="utf-8"))
        self.intentions = {}
        for item in raw.get("intentions") or []:
            if not isinstance(item, dict):
                continue
            intent = self._intention_from_raw(item)
            self.intentions[intent.intent_id] = intent
        self._seeded_days = set(raw.get("seeded_days") or [])
        self._daily_day = str(raw.get("daily_day") or "")
        try:
            self._recall_tick = int(raw.get("recall_tick") or 0)
        except (TypeError, ValueError):
            self._recall_tick = 0
        intervals = raw.get("channel_interval_steps") or {}
        if isinstance(intervals, dict):
            self._channel_interval_steps = {
                str(k).strip().lower(): max(1, min(6, int(v)))
                for k, v in intervals.items()
                if str(k).strip()
            }
        last = raw.get("channel_last_query_tick") or {}
        if isinstance(last, dict):
            self._channel_last_query_tick = {
                str(k).strip().lower(): int(v)
                for k, v in last.items()
                if str(k).strip()
            }

    @classmethod
    def _intention_from_raw(cls, item: dict[str, Any]) -> Intention:
        due_raw = item.get("due")
        if isinstance(due_raw, dict):
            due = DueSlot(
                day=str(due_raw.get("day") or ""),
                time=str(due_raw.get("time") or ""),
            )
        else:
            due = DueSlot(
                day=str(item.get("target_day") or item.get("created_day") or ""),
                time=str(item.get("target_time") or ""),
            )
        watch: list[str] = []
        for name in item.get("watch") or []:
            if isinstance(name, str) and name:
                watch.append(name)
        if not watch:
            for c in item.get("channels") or []:
                if isinstance(c, dict) and c.get("name"):
                    watch.append(str(c["name"]))
                elif isinstance(c, str) and c:
                    watch.append(c)
        action = str(item.get("action") or "").strip()
        if not action:
            action = str(item.get("action_text") or item.get("summary") or "").strip().rstrip(".")
            action = cls._action_phrase(action)
        return Intention(
            intent_id=str(item.get("intent_id") or cls._new_id()),
            action=action,
            status=str(item.get("status") or "pending"),
            due=due,
            event_cue=str(item.get("event_cue") or item.get("trigger_event") or ""),
            watch=watch,
            source=str(item.get("source") or ""),
        )


def build_intention_backend(
    *,
    store_path: str | None = None,
    max_inject_chars: int = 6000,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    use_llm_update: bool = True,
    use_llm_extract: bool = True,
    use_llm_done: bool = False,
    use_llm_match: bool = True,
    use_llm_cadence: bool = False,
    gate_time_due: bool = False,
    force_query_channels: bool = False,
    llm_timeout: float = 120.0,
    response_format: str | None = None,
    retrieval_mode: str = "due",
    embed_fn: Any | None = None,
    ignore_status: bool = False,
):
    """Build intention store; enable LLM judges when credentials are given."""
    client = None
    want_llm = use_llm_update or use_llm_extract
    if want_llm and api_key and model:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise SystemExit(
                "intention LLM features require openai: pip install openai"
            ) from exc
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=llm_timeout)
    return IntentionStoreBackend(
        store_path=store_path,
        max_inject_chars=max_inject_chars,
        llm_client=client,
        llm_model=model,
        use_llm_update=bool(client and model and (use_llm_update or use_llm_extract)),
        use_llm_extract=bool(client and model and (use_llm_update or use_llm_extract)),
        use_llm_done=False,
        use_llm_match=bool(use_llm_match),
        use_llm_cadence=False,
        gate_time_due=gate_time_due,
        force_query_channels=force_query_channels,
        llm_response_format=response_format,
        retrieval_mode=retrieval_mode,
        embed_fn=embed_fn,
        ignore_status=ignore_status,
    )
