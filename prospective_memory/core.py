"""Pure state/lifecycle and evidence boundaries; no benchmark or model imports.

Hosts supply instruction text, observations and available observation sources.
Callbacks interpret language; this module enforces identity, provenance, lifecycle,
deduplication and per-tick query budgets. Decisions are proposals, not executions.
"""

from dataclasses import asdict, dataclass, replace
import copy
from typing import Callable, Iterable


NO_INTERVENTION_REASON = "No new supported intervention"


@dataclass(frozen=True)
class Instruction:
    id: str
    text: str
    scope: str = ""


@dataclass(frozen=True)
class Observation:
    id: str
    text: str
    source: str = "events"
    current: bool = True


@dataclass(frozen=True)
class Intention:
    id: str
    action: str
    condition: str
    sources: tuple[str, ...]
    scope: str = ""
    repeat: bool = False
    status: str = "pending"
    revision: int = 1
    instruction_ids: tuple[str, ...] = ()
    evidence_quote: str = ""


@dataclass(frozen=True)
class Change:
    op: str
    action: str = ""
    condition: str = ""
    sources: tuple[str, ...] = ()
    scope: str = ""
    repeat: bool = False
    target_id: str = ""
    evidence_quote: str = ""


@dataclass(frozen=True)
class Decision:
    kind: str
    intention_id: str
    reason: str = ""
    evidence_ids: tuple[str, ...] = ()
    source: str = ""


def _text(value, name, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"Invalid {name}")
    return value


class Engine:
    def __init__(self, compiler: Callable, matcher: Callable,
                 sources: Iterable[str], query_budget: int = 1,
                 queryable_sources: Iterable[str] | None = None):
        if type(query_budget) is not int or query_budget < 0:
            raise ValueError("query_budget must be a nonnegative integer")
        self.compiler, self.matcher = compiler, matcher
        self.query_budget = query_budget
        self.intentions: dict[str, Intention] = {}
        self.instructions: dict[str, Instruction] = {}
        self.errors: list[dict] = []
        self._next_id = 1
        self._notified: set[tuple] = set()
        self._observations: dict[str, Observation] = {}
        self.set_sources(sources, queryable_sources=queryable_sources)

    def set_sources(self, sources, queryable_sources=None):
        if isinstance(sources, str):
            raise ValueError("Sources must be a collection")
        values = tuple(dict.fromkeys(_text(s, "source") for s in sources))
        if not values or any(set(i.sources) - set(values) for i in self.intentions.values()):
            raise ValueError("Available sources must include existing intention sources")
        if queryable_sources is None:
            queryable_sources = values
        if isinstance(queryable_sources, str):
            raise ValueError("Queryable sources must be a collection")
        queryable = tuple(dict.fromkeys(_text(s, "queryable source") for s in queryable_sources))
        if set(queryable) - set(values):
            raise ValueError("Queryable sources must be advertised observation sources")
        self.sources = values
        self.queryable_sources = queryable

    def _error(self, phase, exc):
        self.errors.append({"phase": phase, "error": str(exc)})

    def _spec(self, change):
        _text(change.action, "action")
        _text(change.condition, "condition")
        _text(change.scope, "scope", True)
        if type(change.repeat) is not bool:
            raise ValueError("repeat must be boolean")
        if not isinstance(change.sources, (tuple, list)):
            raise ValueError("Intention sources must be a list or tuple")
        sources = tuple(dict.fromkeys(_text(s, "source") for s in change.sources))
        if set(sources) - set(self.sources):
            raise ValueError("Unknown observation source")
        return sources

    def ingest(self, instruction: Instruction) -> list[str]:
        """Compile only an instruction-bearing host message, never an action menu."""
        _text(instruction.id, "instruction ID")
        _text(instruction.text, "instruction text")
        _text(instruction.scope, "instruction scope", True)
        if instruction.id in self.instructions:
            if instruction != self.instructions[instruction.id]:
                raise ValueError("Instruction ID reused with different content")
            return []
        try:
            changes = list(self.compiler(instruction, list(self.intentions.values()), self.sources))
            if len(changes) > 128:
                raise ValueError("Too many changes in one message")
        except Exception as exc:
            self._error("compile", exc)
            return []
        changed = []
        for change in changes:
            try:
                if not isinstance(change, Change):
                    raise ValueError("Compiler must return Change values")
                _text(change.evidence_quote, "instruction quote")
                if change.evidence_quote not in instruction.text:
                    raise ValueError("Quote absent from the source instruction")
                if change.op == "register":
                    sources = self._spec(change)
                    if change.target_id:
                        raise ValueError("Registration IDs are assigned by the runtime")
                    # Suppress exact duplicate registrations, while leaving semantic
                    # equivalence to the compiler; no task-specific canonicalization.
                    duplicate = any((i.action, i.condition, i.sources, i.scope, i.repeat) ==
                                    (change.action, change.condition, sources, change.scope, change.repeat)
                                    and i.status in {"pending", "attempted"}
                                    for i in self.intentions.values())
                    if duplicate:
                        continue
                    key = f"pm_{self._next_id:06d}"
                    self._next_id += 1
                    result = Intention(key, change.action, change.condition, sources,
                                       change.scope, change.repeat,
                                       instruction_ids=(instruction.id,), evidence_quote=change.evidence_quote)
                elif change.op in {"revise", "cancel"}:
                    old = self.intentions[change.target_id]
                    key = old.id
                    if old.status in {"completed", "cancelled"}:
                        raise ValueError("Closed intention requires a new explicit registration")
                    if instruction.id in old.instruction_ids:
                        raise ValueError("Revision requires a distinct instruction")
                    if change.op == "cancel":
                        result = replace(old, status="cancelled", revision=old.revision + 1,
                                         instruction_ids=old.instruction_ids + (instruction.id,),
                                         evidence_quote=change.evidence_quote)
                    else:
                        sources = self._spec(change)
                        result = replace(old, action=change.action, condition=change.condition,
                                         sources=sources, scope=change.scope, repeat=change.repeat,
                                         status="pending", revision=old.revision + 1,
                                         instruction_ids=old.instruction_ids + (instruction.id,),
                                         evidence_quote=change.evidence_quote)
                else:
                    raise ValueError("Unknown change operation")
                self.intentions[key] = result
                changed.append(key)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                self._error("change", exc)
        self.instructions[instruction.id] = instruction
        return changed

    def tick(self, observations: list[Observation], scope: str = "") -> list[Decision]:
        """Evaluate push events or pull results. CHECK asks the host to obtain data.

        current describes relevance to this decision, not proven occurrence time.
        Hosts must mark buffered historical evidence appropriately. Reusing the
        same evidence suppresses duplicate ACT proposals for an intention revision.
        """
        active = {key: i for key, i in self.intentions.items()
                  if i.status == "pending" and i.scope in {"", "*", scope}}
        visible = {}
        for o in observations:
            try:
                if not isinstance(o, Observation):
                    raise ValueError("Expected Observation")
                _text(o.id, "observation ID")
                _text(o.text, "observation text")
                if o.source not in self.sources or type(o.current) is not bool:
                    raise ValueError("Invalid observation source/current flag")
                previous = self._observations.get(o.id)
                if previous and (o.text, o.source) != (previous.text, previous.source):
                    raise ValueError("Observation ID reused with different content")
                self._observations[o.id] = o
                visible[o.id] = o
            except (ValueError, TypeError) as exc:
                self._error("observation", exc)
        if not active:
            return []
        try:
            proposals = list(self.matcher(list(active.values()), list(visible.values()), self.sources))
            if len(proposals) > 512:
                raise ValueError("Too many decisions")
        except Exception as exc:
            self._error("assess", exc)
            proposals = []
        decisions, handled, checked = [], set(), set()
        for d in proposals:
            try:
                if not isinstance(d, Decision) or d.kind not in {"ACT", "CHECK", "WAIT"}:
                    raise ValueError("Invalid decision")
                intention = active[d.intention_id]
                if d.intention_id in handled:
                    continue
                _text(d.reason, "decision reason", True)
                if d.kind == "ACT":
                    if isinstance(d.evidence_ids, str) or not d.evidence_ids:
                        raise ValueError("ACT requires current observation references")
                    evidence = [visible[key] for key in d.evidence_ids]
                    if not all(o.current for o in evidence):
                        raise ValueError("ACT cannot rely on stale observations")
                    if not any(o.source in intention.sources for o in evidence):
                        raise ValueError("ACT lacks evidence from an intention source")
                    # Extra context from another source must not disguise reused
                    # trigger evidence. Hosts must reuse stable IDs for the same
                    # event; this is identity deduplication, not semantic proof.
                    trigger_ids = {o.id for o in evidence if o.source in intention.sources}
                    used_ids = {key for k, r, ids in self._notified
                                if (k, r) == (intention.id, intention.revision) for key in ids}
                    if trigger_ids <= used_ids:
                        continue
                    signature = (intention.id, intention.revision, tuple(sorted(trigger_ids)))
                    self._notified.add(signature)
                elif d.kind == "CHECK":
                    if d.source not in intention.sources or d.source not in self.queryable_sources:
                        raise ValueError("CHECK requests an unrelated/non-queryable source")
                    if d.source in checked or len(checked) >= self.query_budget:
                        continue
                    checked.add(d.source)
                decisions.append(d)
                handled.add(d.intention_id)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                self._error("decision", exc)
        decisions.extend(Decision("WAIT", key, NO_INTERVENTION_REASON)
                         for key in active if key not in handled)
        return decisions

    def acknowledge(self, intention_id: str, outcome: str):
        """Only the host can report action outcomes; ACT itself is not success."""
        old = self.intentions[intention_id]
        if old.status in {"cancelled", "completed"}:
            raise ValueError("Cannot acknowledge a closed intention")
        if outcome not in {"attempted", "completed", "failed"}:
            raise ValueError("Unknown outcome")
        status = "pending" if outcome == "failed" or (outcome == "completed" and old.repeat) else outcome
        self.intentions[intention_id] = replace(old, status=status)
        if outcome == "failed":
            self._notified = {s for s in self._notified if s[0] != intention_id}

    def snapshot(self) -> dict:
        return {"version": 1, "sources": list(self.sources), "query_budget": self.query_budget,
                "queryable_sources": list(self.queryable_sources),
                "next_id": self._next_id, "intentions": [asdict(i) for i in self.intentions.values()],
                "instructions": [asdict(i) for i in self.instructions.values()],
                "observations": [asdict(o) for o in self._observations.values()],
                "notified": [[k, r, list(e)] for k, r, e in sorted(self._notified)],
                "errors": copy.deepcopy(self.errors)}

    def restore(self, state: dict):
        """Restore a snapshot without invoking either model callback."""
        if not isinstance(state, dict) or state.get("version") != 1:
            raise ValueError("Unsupported state version")
        fresh = Engine(self.compiler, self.matcher, state["sources"], state["query_budget"],
                       queryable_sources=state["queryable_sources"])
        for raw in state["instructions"]:
            i = Instruction(**raw)
            _text(i.id, "instruction ID")
            _text(i.text, "instruction text")
            _text(i.scope, "instruction scope", True)
            if i.id in fresh.instructions:
                raise ValueError("Duplicate instruction ID")
            fresh.instructions[i.id] = i
        for raw in state["intentions"]:
            raw = dict(raw)
            raw["sources"] = tuple(raw["sources"])
            raw["instruction_ids"] = tuple(raw["instruction_ids"])
            i = Intention(**raw)
            _text(i.id, "intention ID")
            fresh._spec(Change("register", i.action, i.condition, i.sources, i.scope, i.repeat))
            if i.id in fresh.intentions or i.status not in {"pending", "attempted", "completed", "cancelled"}:
                raise ValueError("Invalid restored intention")
            if type(i.revision) is not int or i.revision < 1 or not i.instruction_ids:
                raise ValueError("Invalid intention provenance")
            if any(key not in fresh.instructions for key in i.instruction_ids):
                raise ValueError("Missing instruction provenance")
            if not i.evidence_quote or i.evidence_quote not in fresh.instructions[i.instruction_ids[-1]].text:
                raise ValueError("Invalid restored quote")
            fresh.intentions[i.id] = i
        fresh._next_id = state["next_id"]
        if type(fresh._next_id) is not int or fresh._next_id < 1:
            raise ValueError("Invalid ID counter")
        if any(not key.startswith("pm_") or not key[3:].isdigit() or int(key[3:]) >= fresh._next_id
               for key in fresh.intentions):
            raise ValueError("ID counter collides with restored intentions")
        for raw in state["observations"]:
            o = Observation(**raw)
            _text(o.id, "observation ID")
            _text(o.text, "observation text")
            if o.source not in fresh.sources or o.id in fresh._observations or type(o.current) is not bool:
                raise ValueError("Invalid restored observation")
            fresh._observations[o.id] = o
        for key, revision, evidence_ids in state["notified"]:
            if (key not in fresh.intentions or type(revision) is not int
                    or not 1 <= revision <= fresh.intentions[key].revision
                    or not isinstance(evidence_ids, list) or not evidence_ids
                    or any(e not in fresh._observations for e in evidence_ids)):
                raise ValueError("Invalid restored notification")
            fresh._notified.add((key, revision, tuple(evidence_ids)))
        if not isinstance(state.get("errors", []), list):
            raise ValueError("Invalid restored error history")
        fresh.errors = copy.deepcopy(state.get("errors", []))
        self.__dict__.update(fresh.__dict__)
