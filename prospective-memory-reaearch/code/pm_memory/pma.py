"""Proactive Memory Agent backend (Wu et al., arXiv:2607.08716).

Paper loop, prompted (no SFT/GRPO):
  Phase 1 — tool calls edit a Status / Knowledge / Procedural bank
  Phase 2 — emit <context_for_action> or <no_intervention/>

This file reimplements the paper's memory core against an OpenAI-compatible
client so we do not pull Harbor / Terminal-Bench / litellm. Prompts keep the
two-phase protocol; wording is adapted from coding-agent to PM-Bench's week
of deferred commitments (no GT leak, no forced channel queries).
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .common import (
    format_turn_note,
    scrub_task_handles,
    strip_abc_options,
    strip_action_menu,
    truncate,
)

logger = logging.getLogger(__name__)

BANK_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "memory_save_knowledge",
            "description": (
                "Save an important fact to the knowledge bank. Use for: "
                "deferred commitments, clock times, event cues, cancellations "
                "or reschedules, and facts learned from queried channels."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The fact to save. Be precise and specific.",
                    }
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_save_procedural",
            "description": (
                "Record an experience: an action already taken, a failed "
                "attempt, or a query that did or did not help."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "What was tried and what happened.",
                    }
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_update_status",
            "description": (
                "Update internal progress tracking. Private to the memory "
                "agent; not shown to the action agent."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Current progress / open risks summary.",
                    }
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_delete",
            "description": "Delete an outdated or incorrect memory entry by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "The ID of the memory to delete.",
                    }
                },
                "required": ["memory_id"],
            },
        },
    },
]

PHASE1_SYSTEM = """You are a Memory Bank Manager. Your job is to maintain a lean, accurate knowledge bank for an agent living a simulated week of ongoing activity plus deferred commitments.

## Your Tools
- memory_save_knowledge: Save important FACTS (deferred tasks, due times, event cues, cancel/reschedule, channel facts)
- memory_save_procedural: Record EXPERIENCES (already-done actions, failed attempts, useful or useless queries)
- memory_update_status: Track progress internally (not shown to the action agent)
- memory_delete: Remove outdated/incorrect entries

## Guidelines
1. **Be selective**: Only save information that would be LOST if the action agent's context window scrolls past it
2. **Prioritize commitments**: what to do later, when/under what cue, and later updates that void or move a commitment
3. **Record what was already done** so it is not repeated
4. **Keep it lean**: Delete entries superseded by newer information (a cancel beats the original reminder)
5. **Don't save obvious things**: the current vignette the agent just saw, routine A/B/C activity choices, or general knowledge

## What to save at the start of a day:
- Morning-list commitments and their cues or times
- Cross-day leftovers that are still in force

## What to save at later steps:
- Cancellations, reschedules, overrides
- Channel facts after a query_state / check_time reply
- Actions that fulfilled a commitment
"""

PHASE2_SYSTEM = """You are a Selective Attention module for an Action Agent in a seven-day prospective-memory week.

Your role is like selective attention — when the agent's working memory has scrolled past an open commitment, a cancel, or a due cue, you can restore that context. You also know when things are fine and the agent does not need help.

## PROCESS:
1. Review the memory bank contents
2. Review the agent's recent trajectory (what it is doing now)
3. DECIDE: Does the agent need a context reminder right now?

## WHEN TO INTERVENE (output <context_for_action>):
- An open commitment may be due given the current scene, clock, or channel reply
- The agent is about to repeat an already-done action
- The agent may fire a canceled or rescheduled (stale) commitment
- A hidden channel still needs a query before a watch-dependent commitment can be judged

## WHEN NOT TO INTERVENE (output <no_intervention/>):
- The agent's actions are consistent with the memory bank
- You are not confident that a specific fact is being forgotten
- The information you would provide is already visible in the recent trajectory
- You would only be restating what the agent already knows

## OUTPUT FORMAT:
If intervention needed, write:
<context_for_action>
Your synthesized context note here. Frame as observations, not commands.
Match tasks by meaning; do not invent menu handles like task_N.
</context_for_action>

If no intervention needed, write:
<no_intervention/>

## GUIDELINES:
- Your DEFAULT is <no_intervention/> — only intervene when you see a real gap
- When you do intervene, be thoughtful: synthesize, don't dump the whole bank
- Frame as observations: "There is still a pending pickup when the shelf cue appears" not "You MUST pick task_7"
- Don't include information already visible in the recent trajectory
- The action agent is a strong model — help it remember, don't try to control it
"""


@dataclass
class MemoryEntry:
    id: str
    content: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class UniversalMemory:
    """Paper bank: private status + knowledge + procedural lists."""

    def __init__(self, max_status_length: int = 2000):
        self._status = ""
        self._knowledge: list[MemoryEntry] = []
        self._procedural: list[MemoryEntry] = []
        self._max_status_length = max_status_length

    @property
    def status(self) -> str:
        return self._status

    @property
    def knowledge(self) -> list[MemoryEntry]:
        return self._knowledge

    @property
    def procedural(self) -> list[MemoryEntry]:
        return self._procedural

    def update_status(self, content: str) -> None:
        value = content or ""
        if len(value) > self._max_status_length:
            value = value[: self._max_status_length] + "..."
        self._status = value

    def save_knowledge(self, content: str) -> str:
        entry = MemoryEntry(id=uuid.uuid4().hex[:8], content=content)
        self._knowledge.append(entry)
        return entry.id

    def save_procedural(self, content: str) -> str:
        entry = MemoryEntry(id=uuid.uuid4().hex[:8], content=content)
        self._procedural.append(entry)
        return entry.id

    def delete(self, memory_id: str) -> bool:
        for store in (self._knowledge, self._procedural):
            for i, entry in enumerate(store):
                if entry.id == memory_id:
                    store.pop(i)
                    return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "knowledge": [
                {"id": e.id, "content": e.content, "created_at": e.created_at}
                for e in self._knowledge
            ],
            "procedural": [
                {"id": e.id, "content": e.content, "created_at": e.created_at}
                for e in self._procedural
            ],
        }


@dataclass
class MemoryOperation:
    action: str
    memory_id: str | None = None
    content: str | None = None
    success: bool = True
    error: str | None = None


@dataclass
class MemoryAgentResult:
    operations: list[MemoryOperation]
    should_inject: bool
    context_for_action: str | None = None
    raw_response_phase1: str | None = None
    raw_response_phase2: str | None = None


class PmaMemoryAgent:
    """Synchronous OpenAI-compatible port of the paper MemoryAgent."""

    def __init__(self, llm_client: Any, llm_model: str, *, max_memory_in_prompt: int = 50):
        self.llm_client = llm_client
        self.llm_model = llm_model
        self.memory = UniversalMemory()
        self.max_memory_in_prompt = max_memory_in_prompt

    def _format_memory_list(self, entries: list[MemoryEntry]) -> str:
        if not entries:
            return "(empty)"
        shown = entries[: self.max_memory_in_prompt]
        lines = [f"[{e.id}] {e.content}" for e in shown]
        if len(entries) > len(shown):
            lines.append(f"(showing {len(shown)} of {len(entries)})")
        return "\n".join(lines)

    def _format_memory_bank(self) -> str:
        return (
            "<memory_bank>\n"
            f"<status>\n{self.memory.status or '(no status)'}\n</status>\n"
            f"<knowledge>\n{self._format_memory_list(self.memory.knowledge)}\n</knowledge>\n"
            f"<procedural>\n{self._format_memory_list(self.memory.procedural)}\n</procedural>\n"
            "</memory_bank>"
        )

    def _build_phase1_prompt(self, observation: str, step_count: int) -> str:
        return (
            f"## Step {step_count}\n\n"
            f"## Current Memory Bank\n{self._format_memory_bank()}\n\n"
            f"## Context (Task Description + Recent Trajectory)\n{observation}\n\n"
            "## Your Task\n"
            "Analyze the trajectory and update the memory bank. Save important "
            "facts, record experiences, delete outdated entries. Be selective.\n"
        )

    def _build_phase2_prompt(self, observation: str, step_count: int) -> str:
        return (
            f"## Step {step_count}\n\n"
            f"## Memory Bank (just updated)\n{self._format_memory_bank()}\n\n"
            f"## Context (Task Description + Recent Trajectory)\n{observation}\n\n"
            "## Your Task\n"
            "Review the memory bank and the agent's recent trajectory. Decide:\n"
            "- Is the agent missing or forgetting something important from the memory bank?\n"
            "- Is the agent heading toward a canceled, already-done, or not-yet-due action?\n\n"
            "If yes, write a <context_for_action> note with the relevant context.\n"
            "If no, write <no_intervention/>.\n"
        )

    def _complete(
        self,
        *,
        system: str,
        user: str,
        tools: list[dict] | None = None,
        max_tokens: int = 700,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return self.llm_client.chat.completions.create(**kwargs)

    def process(self, observation: str, step_count: int = 0) -> MemoryAgentResult:
        operations: list[MemoryOperation] = []
        raw1 = None
        try:
            resp1 = self._complete(
                system=PHASE1_SYSTEM,
                user=self._build_phase1_prompt(observation, step_count),
                tools=BANK_TOOLS,
            )
            msg1 = resp1.choices[0].message
            raw1 = msg1.content
            operations = self._execute_tool_calls(msg1)
        except Exception as exc:
            logger.error("PMA Phase 1 error: %s", exc, exc_info=True)
            operations.append(
                MemoryOperation(action="phase1", success=False, error=str(exc)[:200])
            )

        should_inject = False
        context_for_action = None
        raw2 = None
        try:
            resp2 = self._complete(
                system=PHASE2_SYSTEM,
                user=self._build_phase2_prompt(observation, step_count),
            )
            raw2 = resp2.choices[0].message.content or ""
            context_for_action = parse_phase2_response(raw2)
            should_inject = context_for_action is not None
        except Exception as exc:
            logger.error("PMA Phase 2 error: %s", exc, exc_info=True)

        return MemoryAgentResult(
            operations=operations,
            should_inject=should_inject,
            context_for_action=context_for_action,
            raw_response_phase1=raw1 if isinstance(raw1, str) else None,
            raw_response_phase2=raw2,
        )

    def _execute_tool_calls(self, message: Any) -> list[MemoryOperation]:
        operations: list[MemoryOperation] = []
        tool_calls = list(getattr(message, "tool_calls", None) or [])
        if not tool_calls:
            raw = getattr(message, "content", None) or ""
            for name, args in parse_tool_calls_from_text(raw):
                tool_calls.append(_FakeToolCall(name, args))

        for tool_call in tool_calls:
            name, args = extract_tool_call(tool_call)
            if not name:
                continue
            try:
                if name == "memory_save_knowledge":
                    content = str(args.get("content") or "").strip()
                    if not content:
                        continue
                    mem_id = self.memory.save_knowledge(content)
                    operations.append(
                        MemoryOperation(
                            action="save_knowledge", memory_id=mem_id, content=content
                        )
                    )
                elif name == "memory_save_procedural":
                    content = str(args.get("content") or "").strip()
                    if not content:
                        continue
                    mem_id = self.memory.save_procedural(content)
                    operations.append(
                        MemoryOperation(
                            action="save_procedural", memory_id=mem_id, content=content
                        )
                    )
                elif name == "memory_update_status":
                    content = str(args.get("content") or "").strip()
                    self.memory.update_status(content)
                    operations.append(
                        MemoryOperation(action="update_status", content=content)
                    )
                elif name == "memory_delete":
                    mem_id = str(args.get("memory_id") or "")
                    ok = self.memory.delete(mem_id)
                    operations.append(
                        MemoryOperation(
                            action="delete",
                            memory_id=mem_id,
                            success=ok,
                            error=None if ok else "ID not found",
                        )
                    )
            except Exception as exc:
                operations.append(
                    MemoryOperation(action=name, success=False, error=str(exc)[:200])
                )
        return operations


class _FakeToolCall:
    def __init__(self, name: str, args: dict[str, Any]):
        self.function = type("F", (), {"name": name, "arguments": args})()


def extract_tool_call(tool_call: Any) -> tuple[str | None, dict[str, Any]]:
    fn = getattr(tool_call, "function", None)
    if fn is None:
        return None, {}
    name = getattr(fn, "name", None)
    args = getattr(fn, "arguments", {}) or {}
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            args = {"content": args}
    if not isinstance(args, dict):
        args = {}
    return name, args


def parse_tool_calls_from_text(text: str) -> list[tuple[str, dict[str, Any]]]:
    parsed: list[tuple[str, dict[str, Any]]] = []
    if not text:
        return parsed
    for block in re.finditer(r"<tool_call>(.*?)</tool_call>", text, re.DOTALL):
        block_text = block.group(1)
        func_match = re.search(r"function[=:](\w+)", block_text)
        if not func_match:
            continue
        name = func_match.group(1)
        args: dict[str, Any] = {}
        for param in re.finditer(
            r"<parameter=(\w+)>(.*?)(?:</parameter>|$)", block_text, re.DOTALL
        ):
            args[param.group(1)] = param.group(2).strip()
        if not args.get("content") and name != "memory_delete":
            remaining = re.sub(r"<[^>]+>", " ", block_text).strip()
            if remaining:
                args["content"] = remaining
        parsed.append((name, args))
    return parsed


def parse_phase2_response(raw: str) -> str | None:
    text = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL).strip()
    match = re.search(
        r"<context_for_action>(.*?)</context_for_action>", text, re.DOTALL
    )
    if match:
        context = match.group(1).strip()
        return context or None
    if "<no_intervention" in text:
        return None
    return None


def _window_from_context(context: dict[str, Any] | None, query: str, max_chars: int = 3500) -> str:
    if not context:
        return query
    chunks: list[str] = []
    day = context.get("day") or ""
    step = context.get("step") or ""
    time_str = context.get("time") or ""
    head = f"[{day} {step} {time_str}]".replace("  ", " ").strip()
    if head.strip("[] "):
        chunks.append(head)
    messages = context.get("messages") or []
    recent: list[str] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        if content.startswith("===") or "[Relevant_memories]" in content:
            continue
        role = msg.get("role") or "user"
        body = strip_abc_options(strip_action_menu(content))
        if not body:
            continue
        recent.append(f"{role}: {body}")
    if recent:
        chunks.append("\n---\n".join(recent[-8:]))
    elif context.get("observation"):
        chunks.append(strip_abc_options(str(context["observation"])))
    elif query:
        chunks.append(query)
    text = "\n\n".join(chunks).strip()
    return text[:max_chars]


class PmaBackend:
    """MemoryBackend: two-phase PMA before choose; encode appends trajectory notes."""

    name = "pma"
    uses_step_context = True

    def __init__(
        self,
        agent: PmaMemoryAgent,
        *,
        interval: int = 1,
        max_inject_chars: int = 8000,
    ):
        self.agent = agent
        self.interval = max(1, int(interval))
        self.max_inject_chars = max_inject_chars
        self._step_count = 0
        self._notes: list[str] = []
        self.last_recall_info: dict[str, Any] = {}
        self.last_encode_info: dict[str, Any] = {}

    def recall(self, query: str, *, top_k: int | None = None, context: dict | None = None) -> str:
        del top_k
        self._step_count += 1
        if self.interval > 1 and self._step_count != 1:
            if (self._step_count - 1) % self.interval != 0:
                self.last_recall_info = {
                    "triggered": False,
                    "step_count": self._step_count,
                    "injected": False,
                }
                return ""
        observation = _window_from_context(context, query)
        if self._notes:
            observation = (
                observation
                + "\n\n## Recent encoded turns\n"
                + "\n".join(self._notes[-6:])
            )
        result = self.agent.process(observation, step_count=self._step_count)
        ops = [
            {
                "action": op.action,
                "id": op.memory_id,
                "ok": op.success,
            }
            for op in result.operations
        ]
        self.last_recall_info = {
            "triggered": True,
            "step_count": self._step_count,
            "injected": bool(result.should_inject),
            "ops": ops,
            "knowledge": len(self.agent.memory.knowledge),
            "procedural": len(self.agent.memory.procedural),
        }
        if not result.should_inject or not result.context_for_action:
            return ""
        text = scrub_task_handles(result.context_for_action).strip()
        return truncate(text, self.max_inject_chars)

    def encode(self, turn: dict[str, Any]) -> None:
        note = format_turn_note(turn)
        if note.strip():
            self._notes.append(note)
            if len(self._notes) > 40:
                self._notes = self._notes[-40:]
        self.last_encode_info = {"notes": len(self._notes)}


def build_pma_backend(
    *,
    model: str,
    api_key: str,
    base_url: str | None,
    max_inject_chars: int = 8000,
    interval: int = 1,
    llm_timeout: float = 120.0,
) -> PmaBackend:
    from openai import OpenAI

    client = OpenAI(base_url=base_url, api_key=api_key, timeout=llm_timeout)
    agent = PmaMemoryAgent(client, model)
    return PmaBackend(
        agent, interval=interval, max_inject_chars=max_inject_chars
    )
