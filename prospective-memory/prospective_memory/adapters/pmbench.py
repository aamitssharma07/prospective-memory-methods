"""Translate PM-Bench's public conversation into the portable memory interface.

This module imports no simulator code. Menus resolve action handles only inside
the actor; they never create intentions or serve as trigger evidence here. The
adapter recommends ordinary actor queries, whose replies return through the
same public conversation and are counted by the benchmark.
"""

from dataclasses import asdict
import copy
import json
import re
import time

from ..core import Decision, Engine, Instruction, NO_INTERVENTION_REASON, Observation


_CHANNELS = re.compile(r"Available state channels:\s*([^\n.]+)")
_DAY = re.compile(r"^===\s*(.*?)\s*===\s*$", re.MULTILINE)
_STATE = re.compile(r"^State \[([^\]]+)\]:\s*(.*)$", re.DOTALL)
_MENU = re.compile(r"^(?:Step action menu|Daily action-handle legend|Action menu \(optional\))\s*:?.*$")
_OPTION = re.compile(r"^\s*[ABC]\s*[).:]\s*")
_HANDLE = re.compile(r"^\s*-?\s*task_\d+\s*:")
_TIME = re.compile(r"^\s*Time:\s*(.+)$")


def discover_sources(messages):
    """Read tool names from the actor's advertised interface, never task data."""
    sources = ["events"]
    for message in messages:
        if message.get("role") != "system":
            continue
        for match in _CHANNELS.finditer(message.get("content", "")):
            sources.extend(channel.strip() for channel in match.group(1).split(",")
                           if channel.strip())
    return tuple(dict.fromkeys(sources))


def strip_action_choices(text):
    """Keep visible prose and separately return an explicitly displayed clock."""
    prose = []
    clocks = []
    in_menu = False
    for line in text.splitlines():
        time_match = _TIME.match(line)
        if time_match:
            clocks.append(time_match.group(1))
            continue
        if _MENU.match(line):
            in_menu = True
            continue
        if in_menu or _OPTION.match(line) or _HANDLE.match(line):
            continue
        prose.append(line)
    return "\n".join(prose).strip(), clocks


class PMBenchAdapter:
    """A ``context_for(messages)`` adapter with transient ACT/CHECK guidance."""

    def __init__(self, engine, log=None, query_handoff="legacy"):
        if not isinstance(query_handoff, str) or query_handoff not in {"legacy", "explicit"}:
            raise ValueError("query_handoff must be legacy or explicit")
        self.engine = engine
        self.log = log
        self.query_handoff = query_handoff
        self.seen = 0
        self.cycles = 0
        self.scope = ""
        self.current_observations = []
        self.last_decisions = []
        self._last_messages = []
        self._act_cache = {}

    def snapshot(self):
        """Persist the conversation cursor as well as portable memory state.

        An engine-only snapshot cannot safely resume an adapter: message indices
        are evidence identities, and a resumed adapter must retain that prefix.
        The host remains responsible for persisting and replaying its own session.
        """
        state = {
            "version": 1, "adapter": "pmbench", "engine": self.engine.snapshot(),
            "seen": self.seen, "cycles": self.cycles, "scope": self.scope,
            "messages": copy.deepcopy(self._last_messages),
            "current_observations": [asdict(item) for item in self.current_observations],
            "last_decisions": [asdict(item) for item in self.last_decisions],
            "act_cache": {key: {"decision": asdict(value["decision"]), "revision": value["revision"]}
                          for key, value in self._act_cache.items()},
        }
        # Preserve the exact old shape for default/legacy adapters.
        if self.query_handoff == "explicit":
            state["query_handoff"] = "explicit"
        return state

    def restore(self, state):
        """Validate and restore a snapshot without invoking either model callback."""
        if not isinstance(state, dict) or state.get("version") != 1 or state.get("adapter") != "pmbench":
            raise ValueError("Unsupported adapter snapshot")
        recorded_handoff = state.get("query_handoff", "legacy")
        if (not isinstance(recorded_handoff, str)
                or recorded_handoff not in {"legacy", "explicit"}
                or recorded_handoff != self.query_handoff):
            raise ValueError("Adapter query_handoff mode does not match snapshot")
        state = copy.deepcopy(state)
        seen, cycles, scope = state.get("seen"), state.get("cycles"), state.get("scope")
        messages = state.get("messages")
        if (type(seen) is not int or seen < 0 or type(cycles) is not int or cycles < 0
                or not isinstance(scope, str) or not isinstance(messages, list) or len(messages) != seen):
            raise ValueError("Invalid adapter cursor, scope, or messages")
        if any(not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant", "tool"}
               or not isinstance(message.get("content"), str) for message in messages):
            raise ValueError("Invalid conversation message")
        expected_scope = ""
        for message in messages:
            if message["role"] == "user":
                day = _DAY.search(message["content"])
                if day:
                    expected_scope = day.group(1).strip()
        if scope != expected_scope:
            raise ValueError("Scope does not match conversation prefix")
        fresh_engine = (self.engine.fresh() if hasattr(self.engine, "fresh")
                        else Engine(self.engine.compiler, self.engine.matcher, ["events"]))
        try:
            fresh_engine.restore(state["engine"])
            raw_observations = state["current_observations"]
            raw_decisions = state["last_decisions"]
            raw_cache = state["act_cache"]
            if not isinstance(raw_observations, list) or not isinstance(raw_decisions, list) or not isinstance(raw_cache, dict):
                raise ValueError("Invalid adapter evidence/decision collections")
            observations = [Observation(**item) for item in raw_observations]
            decisions = [Decision(**{**item, "evidence_ids": tuple(item["evidence_ids"])})
                         for item in raw_decisions]
            cache = {key: {"decision": Decision(**{**item["decision"],
                         "evidence_ids": tuple(item["decision"]["evidence_ids"])}), "revision": item["revision"]}
                     for key, item in raw_cache.items()}
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("Malformed adapter snapshot") from exc
        if seen and (fresh_engine.sources != discover_sources(messages)
                     or set(fresh_engine.queryable_sources) != set(fresh_engine.sources) - {"events"}):
            raise ValueError("Observation capabilities do not match public interface")
        known_observations = {item["id"]: item for item in state["engine"]["observations"]}
        current = {}
        for observation in observations:
            identity = re.fullmatch(r"message_(\d+)(?:_clock_\d+)?", observation.id)
            if (identity is None or int(identity.group(1)) >= seen
                    or messages[int(identity.group(1))]["role"] != "user"
                    or observation.id in current or not observation.current
                    or asdict(observation) != known_observations.get(observation.id)):
                raise ValueError("Current observation does not match persisted engine evidence")
            current[observation.id] = observation
        for decision in decisions + [item["decision"] for item in cache.values()]:
            if (decision.kind not in {"ACT", "CHECK", "WAIT"}
                    or decision.intention_id not in fresh_engine.intentions
                    or not isinstance(decision.reason, str) or not isinstance(decision.source, str)
                    or any(not isinstance(ref, str) for ref in decision.evidence_ids)):
                raise ValueError("Invalid persisted decision")
            if decision.kind == "ACT" and (not decision.evidence_ids or any(ref not in current for ref in decision.evidence_ids)):
                raise ValueError("Persisted ACT lacks current evidence")
            if decision.kind == "CHECK" and decision.source not in fresh_engine.queryable_sources:
                raise ValueError("Persisted CHECK targets a push-only source")
        for key, value in cache.items():
            intention = fresh_engine.intentions.get(key)
            if (intention is None or value["decision"].intention_id != key
                    or value["decision"].kind != "ACT" or type(value["revision"]) is not int
                    or value["revision"] != intention.revision or intention.status != "pending"
                    or intention.scope not in {"", "*", scope}):
                raise ValueError("Invalid persisted ACT cache")
        # Commit only after validating both layers; preserve the host's engine
        # object and model callbacks so existing references remain valid.
        self.engine.restore(state["engine"])
        self.seen, self.cycles, self.scope = seen, cycles, scope
        self._last_messages = messages
        self.current_observations, self.last_decisions = observations, decisions
        self._act_cache = cache

    def _retain_current_acts(self, decisions):
        """Keep an undelivered ACT visible through within-step actor queries."""
        current = {item.id for item in self.current_observations if item.current}
        for key, value in list(self._act_cache.items()):
            intention = self.engine.intentions.get(key)
            if (intention is None or intention.status != "pending" or intention.revision != value["revision"]
                    or intention.scope not in {"", "*", self.scope}
                    or not set(value["decision"].evidence_ids).issubset(current)):
                del self._act_cache[key]
        result = []
        for decision in decisions:
            if decision.kind == "ACT":
                self._act_cache[decision.intention_id] = {
                    "decision": decision, "revision": self.engine.intentions[decision.intention_id].revision}
            elif decision.kind == "WAIT" and decision.reason == NO_INTERVENTION_REASON:
                if decision.intention_id in self._act_cache:
                    decision = self._act_cache[decision.intention_id]["decision"]
            else:
                # A new explicit WAIT or CHECK supersedes a previous ACT. The
                # engine's default WAIT above only reports delivery deduplication.
                self._act_cache.pop(decision.intention_id, None)
            result.append(decision)
        return result

    def _ingest(self, message_id, text, scope):
        if text.strip():
            self.engine.ingest(Instruction(id=message_id, text=text, scope=scope))

    def _explicit_query_handoff(self):
        """Render optional host-routed queries; never execute or mark them done.

        CHECK decisions have already passed the engine's validation. Defensively
        verify capability/record membership before constructing concrete actions.
        An attempted source need not be valid: preserve wrong/repeated attempts
        from the host ledger rather than laundering them into fulfilled CHECKs.
        """
        actions = []
        for decision in self.last_decisions:
            if decision.kind != "CHECK":
                continue
            intention = self.engine.intentions.get(decision.intention_id)
            if (intention is None or not isinstance(decision.source, str)
                    or decision.source not in self.engine.sources
                    or decision.source not in self.engine.queryable_sources
                    or decision.source not in intention.sources):
                raise ValueError("Explicit query handoff requires a validated advertised CHECK source")
            actions.append({"action": "query_state", "choice": "NONE",
                            "task_ids": [], "channel": decision.source})
        if not actions:
            return ""
        observed_sources = list(dict.fromkeys(
            item.source for item in self.current_observations
            if item.current and item.source in self.engine.sources))
        attempts = getattr(self.engine, "step_queries", None)
        if attempts is not None:
            if not isinstance(attempts, (list, tuple)) or any(not isinstance(item, str) for item in attempts):
                raise ValueError("Invalid host step-query ledger")
            attempts = list(attempts)
        data = {"optional_query_actions": actions,
                "current_observed_sources": observed_sources,
                "actual_query_attempts_this_step": attempts}
        text = ("Optional exact-source query handoff (advisory, not executed):\n"
                + json.dumps(data, ensure_ascii=False)
                + "\nAnother clock read does not answer a request for a different source. "
                "Observed sources and attempted queries do not establish that a task is due. "
                "You may decline or choose another action; the query-budget guidance still applies.")
        if attempts is None:
            text += " A null attempt list means this engine does not expose step-query tracking, not zero attempts."
        return text

    def context_for(self, messages):
        started = time.monotonic()
        # Reusing a prefix is safe. Replacing/truncating conversation history would
        # invalidate index-based evidence IDs; require a new adapter for that case.
        if len(messages) < self.seen or messages[:self.seen] != self._last_messages:
            raise ValueError("Conversation changed; create a fresh PMBenchAdapter")
        sources = discover_sources(messages)
        self.engine.set_sources(sources, queryable_sources=[source for source in sources if source != "events"])
        self.cycles += 1
        errors_before = len(self.engine.errors)
        attempts = []
        for index, message in enumerate(messages[self.seen:], start=self.seen):
            role, text = message.get("role"), message.get("content", "")
            if not isinstance(text, str):
                continue
            message_id = f"message_{index}"
            if role == "assistant":
                try:
                    action = json.loads(text)
                    if isinstance(action, dict) and action.get("action") == "choose":
                        self._act_cache.clear()
                        attempts.append({"message_id": message_id,
                                         "task_ids": action.get("task_ids", [])})
                    elif (isinstance(action, dict) and action.get("action") in {"check_time", "query_state"}
                          and hasattr(self.engine, "record_query")):
                        self.engine.record_query("clock" if action["action"] == "check_time"
                                                 else str(action.get("channel", "")))
                except (ValueError, TypeError):
                    pass
                continue
            if role != "user":
                continue
            # Simulator acknowledgements and protocol errors carry no intention
            # or trigger evidence. They remain in the actor's original history.
            if text.startswith(("Invalid ", "Heartbeat ")):
                continue
            day = _DAY.search(text)
            if day:
                self.scope = day.group(1).strip()
                self.current_observations = []
                self._act_cache.clear()
                cleaned, _ = strip_action_choices(text)
                self._ingest(message_id, cleaned, self.scope)
                continue
            if text.startswith("Regular tasks for every day:"):
                cleaned, _ = strip_action_choices(text)
                self._ingest(message_id, cleaned, "*")
                continue
            state = _STATE.match(text)
            if state:
                source = state.group(1)
                if source not in self.engine.sources:
                    continue
                # A newer snapshot supersedes the old state from the same source.
                # A single response may itself contain a stream of delta events.
                self.current_observations = [item for item in self.current_observations
                                             if item.source != source]
                observation = Observation(id=message_id, text=state.group(2), source=source)
                self.current_observations.append(observation)
                self._ingest(message_id, state.group(2), self.scope)
                continue
            has_step_menu = any(line.startswith("Step action menu") for line in text.splitlines())
            if has_step_menu:
                self.current_observations = []
                self._act_cache.clear()
                if hasattr(self.engine, "begin_step"):
                    self.engine.begin_step(message_id)
            cleaned, clocks = strip_action_choices(text)
            if not cleaned and not clocks:
                continue
            if cleaned:
                self._ingest(message_id, cleaned, self.scope)
                self.current_observations.append(Observation(id=message_id, text=cleaned, source="events"))
            for clock_index, clock_text in enumerate(clocks):
                if "clock" in self.engine.sources:
                    self.current_observations.append(Observation(
                        id=f"{message_id}_clock_{clock_index}", text=clock_text, source="clock"))

        self.seen = len(messages)
        self._last_messages = copy.deepcopy(messages)
        self.last_decisions = self._retain_current_acts(
            self.engine.tick(self.current_observations, scope=self.scope))
        bank = self.engine.snapshot()
        intentions = {item["id"]: item for item in bank["intentions"]}
        observations = {item.id: item for item in self.current_observations}
        guidance = []
        for decision in self.last_decisions:
            intention = intentions.get(decision.intention_id)
            if intention is None:
                continue
            if decision.kind == "ACT":
                evidence = [{"source": observations[ref].source,
                             "text": observations[ref].text}
                            for ref in decision.evidence_ids if ref in observations]
                guidance.append({"decision": "ACT", "action": intention["action"],
                                 "condition": intention["condition"], "evidence": evidence,
                                 "reason": decision.reason})
            elif decision.kind == "CHECK":
                guidance.append({"decision": "CHECK", "source": decision.source,
                                 "action": intention["action"], "condition": intention["condition"],
                                 "reason": decision.reason})
        reminder = ""
        if guidance:
            reminder = ("Prospective-memory observations and proposals:\n"
                        + json.dumps(guidance, ensure_ascii=False)
                        + "\nFor CHECK, use the ordinary query_state action with the exact source as channel. "
                        "A proposed check does not establish that the task is due. "
                        "For ACT, verify the evidence and resolve the action description against the current "
                        "menu; use only the current task handle. You retain the final action choice.")
        if hasattr(self.engine, "exhausted_query_guidance"):
            budget_note = self.engine.exhausted_query_guidance()
            if budget_note:
                reminder = (reminder + "\n" + budget_note).strip()
        if self.query_handoff == "explicit":
            handoff = self._explicit_query_handoff()
            if handoff:
                reminder = (reminder + "\n" + handoff).strip()
        if self.log is not None:
            self.log.write(json.dumps({
                "cycle": self.cycles, "mode": "portable", "scope": self.scope,
                "bank": bank, "observations": [asdict(item) for item in self.current_observations],
                "decisions": [asdict(item) for item in self.last_decisions],
                "attempts": attempts, "reminder": reminder,
                "errors": self.engine.errors[errors_before:],
                "elapsed_seconds": time.monotonic() - started,
            }, ensure_ascii=False) + "\n")
            self.log.flush()
        return reminder
