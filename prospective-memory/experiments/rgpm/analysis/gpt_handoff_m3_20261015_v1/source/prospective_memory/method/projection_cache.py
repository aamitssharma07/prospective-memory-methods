"""Opt-in experiment: cached, source-bound trigger-only derived views.

The V4 trigger-projection policy imports this utility. A projection is a fallible
interpretation of a request, NOT evidence, an ACT proposal, or completion state. Original
intentions/messages are retained byte-for-byte in cache bindings and never edited.
The caller's request callback owns inference transport and raw-response logging.
"""

import copy
from dataclasses import asdict, dataclass, fields
import hashlib
import json

from ..core import Instruction, Intention
from ..llm import SHORT_TEXT, TEXT, _object


PROJECT = """Create static trigger-only views of the supplied future intentions.
This is request interpretation, NOT readiness assessment. No current observations
are supplied. Do not claim a trigger occurred, a task is due, or an action ran.

For each record separate:
- action_to_perform_next: the COMPLETE concrete requested action, including its
  stated object, recipient and content; never just a bare verb or generic 'remind'.
  Do not invent an unstated recipient or delivery method. A channel that supplies
  prerequisite evidence is not automatically the channel for the future action.
- readiness_question: a question about the cue/prerequisites that must hold so
  that this action should be performed NEXT. Do not ask whether this same future
  action has already been completed. Another explicitly required earlier action
  can be a prerequisite; do not confuse that with completion of the future action.

Use the selected source-bound intention to identify the obligation. Full original
messages can mention unrelated tasks; they supply context, not permission to mix
obligations. Read accepted revisions in order: later explicit changes replace
only changed terms. Retain every prerequisite, exception, threshold/operator,
entity, time/scope restriction and recurrence. One action at several independent
occasions has alternative activation opportunities; do not require all those
occasions simultaneously. Genuine conjunctions still require all prerequisites.
Example: 'Record a checkpoint when the process starts AND AGAIN when it exits'
means two independent activation opportunities for the SAME action. Express the
readiness question as 'Has the process just started OR just exited?', not 'Has
the process started AND is it exiting?'. The first occurrence does not require
the second, nor vice versa. In contrast, 'Record a checkpoint when the process
starts AND authorization is present' keeps BOTH prerequisites as a conjunction.
Never invent a clock/day schedule, extra condition, source, or successful action.
Keep temporal operators attached to the clause they modify. Worked example:
Source: 'At 16:40, release the crate only if the inspector has cleared it on the
inspection board.'
action_to_perform_next: 'Release the crate.'
readiness_question: 'Is it 16:40 now AND does the inspection board confirm that
the inspector has cleared the crate?'
The inspector is not an inferred recipient, and the board is not an action
delivery route. Current clearance needs no independently recorded earlier
timestamp. Contrast: if the source explicitly requires 'clearance issued before
16:10', retain that deadline and require evidence supporting its timing.
A prerequisite must hold when acting; this alone creates no earlier deadline.
Explicit before/after deadlines and ordering constraints must still be retained.

Return one trigger_projections row per supplied intention_id and revision.
source_instruction_ids must reproduce that intention's complete chronological
instruction_ids exactly. status='projected' means only that a faithful static
view can be expressed, never that its readiness question is true. When the
meaning/target/conditions cannot be faithfully separated, status='unsupported',
both derived text fields='', and explain briefly. Also use unsupported if the
complete faithful view cannot fit the field limits; never truncate an obligation
or omit a condition to fit. Keep originals authoritative; these derived fields
must not replace them. Return compact JSON and stop.
"""

SCHEMA = _object({"trigger_projections": {"type": "array", "items": _object({
    "intention_id": {"type": "string", "maxLength": 160},
    "revision": {"type": "integer", "minimum": 1},
    "source_instruction_ids": {"type": "array", "items": {"type": "string", "maxLength": 160}},
    "status": {"type": "string", "enum": ["projected", "unsupported"]},
    "action_to_perform_next": TEXT,
    "readiness_question": TEXT,
    "reason": SHORT_TEXT,
})}})


@dataclass(frozen=True)
class TriggerProjection:
    intention_id: str
    revision: int
    source_instruction_ids: tuple[str, ...]
    status: str  # projected, unsupported, or local error; NEVER readiness truth
    action_to_perform_next: str = ""
    readiness_question: str = ""
    reason: str = ""


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _binding(intention, instructions):
    if not isinstance(intention, Intention):
        raise ValueError("Expected an Intention")
    if (not all(_nonempty(value) for value in (intention.id, intention.action, intention.condition))
            or type(intention.revision) is not int or intention.revision < 1
            or type(intention.repeat) is not bool or not isinstance(intention.scope, str)
            or not isinstance(intention.evidence_quote, str)
            or intention.status not in {"pending", "attempted", "completed", "cancelled"}):
        raise ValueError("Invalid intention binding")
    for values, allow_empty in ((intention.instruction_ids, False), (intention.sources, True)):
        if (not isinstance(values, (tuple, list)) or (not values and not allow_empty)
                or any(not _nonempty(v) for v in values) or len(set(values)) != len(values)):
            raise ValueError("Invalid intention source references")
    originals = []
    for key in intention.instruction_ids:
        message = instructions.get(key)
        if (not isinstance(message, Instruction) or message.id != key
                or not _nonempty(message.text) or not isinstance(message.scope, str)):
            raise ValueError("Missing or inconsistent original instruction")
        originals.append(asdict(message))
    return {"intention": asdict(intention), "original_instructions": originals}


def _signature(binding):
    return hashlib.sha256(json.dumps(binding, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def projection_definition():
    """Return static prompt/schema data and its cache-compatible fingerprint."""
    definition = {"prompt": PROJECT, "schema": copy.deepcopy(SCHEMA)}
    return {**definition, "sha256": _signature(definition)}


def _projection(row, binding, *, allow_error=False):
    expected = {f.name for f in fields(TriggerProjection)}
    if not isinstance(row, dict) or set(row) != expected:
        raise ValueError("Invalid projection fields")
    intention = binding["intention"]
    if (row["intention_id"] != intention["id"] or type(row["revision"]) is not int
            or row["revision"] != intention["revision"]):
        raise ValueError("Projection identity/revision mismatch")
    refs = row["source_instruction_ids"]
    if (not isinstance(refs, (tuple, list))
            or tuple(refs) != tuple(intention["instruction_ids"])):
        raise ValueError("Projection must cite complete chronological source identity")
    if row["status"] not in ({"projected", "unsupported", "error"} if allow_error else {"projected", "unsupported"}):
        raise ValueError("Invalid projection status")
    for name, limit in (("action_to_perform_next", 800), ("readiness_question", 800), ("reason", 320)):
        if not isinstance(row[name], str) or len(row[name]) > limit:
            raise ValueError("Invalid projection text")
    if row["status"] == "projected":
        if not _nonempty(row["action_to_perform_next"]) or not _nonempty(row["readiness_question"]):
            raise ValueError("A projected view requires both semantic roles")
    elif row["action_to_perform_next"] or row["readiness_question"]:
        raise ValueError("Unsupported/error views cannot expose actionable derived text")
    return TriggerProjection(**{**row, "source_instruction_ids": tuple(refs)})


class TriggerProjectionCache:
    """Opt-in static projection cache; no observations, queries, or execution.

    refresh receives the FULL current intention bank and original instruction
    mapping. New/source-changed/revised active entries are batched (default 4,
    maximum 32). This is a row limit, NOT a token budget: callers must choose a
    suitable batch size and transport budget for their original messages.
    Unchanged projected/unsupported/error entries are cached; invalidate explicitly
    to retry. get requires the caller's current source state and invalidates stale
    entries before returning anything. Bindings are cache keys, not authentication
    or proof that a model's semantic decomposition is correct. Field length and
    reference checks cannot detect semantic omissions in otherwise valid text.

    projector_id must identify the caller's model/version and decoding/config
    choices; the callback's identity cannot be inferred here. Do not change that
    callback's effective configuration in place: construct a cache with a new ID.
    Prompt/schema fingerprints are additionally bound to each entry and snapshot.
    """

    def __init__(self, request, *, projector_id, batch_size=4):
        if type(batch_size) is not int or not 1 <= batch_size <= 32:
            raise ValueError("batch_size must be between 1 and 32")
        if not _nonempty(projector_id):
            raise ValueError("projector_id must identify the model/configuration")
        self.request, self.batch_size = request, batch_size
        self._prompt, self._schema = PROJECT, copy.deepcopy(SCHEMA)
        self._projector = {"identity": projector_id,
                           "prompt_schema_sha256": _signature({"prompt": self._prompt, "schema": self._schema})}
        self._entries = {}
        self.errors = []

    def _bind(self, intention, instructions):
        return {**_binding(intention, instructions), "projector": copy.deepcopy(self._projector)}

    def invalidate(self, intention_id):
        if not _nonempty(intention_id):
            raise ValueError("Invalid intention ID")
        return self._entries.pop(intention_id, None) is not None

    def get(self, intention, instructions):
        try:
            binding = self._bind(intention, instructions)
        except (ValueError, TypeError, AttributeError):
            if isinstance(intention, Intention):
                self._entries.pop(intention.id, None)
            raise
        entry = self._entries.get(intention.id)
        if (intention.status not in {"pending", "attempted"} or entry is None
                or entry["binding_sha256"] != _signature(binding)):
            self._entries.pop(intention.id, None)
            return None
        return entry["projection"]

    def rebind_status(self, intention, instructions):
        """Preserve a static view after an authoritative active-status transition.

        Call only after host acknowledgment. Both old/new statuses must be pending
        or attempted and the complete binding must otherwise be identical. This
        neither assesses readiness nor invokes the callback. Closure or any other
        binding change invalidates; normal get remains strictly status-bound.
        """
        try:
            binding = self._bind(intention, instructions)
        except (ValueError, TypeError, AttributeError):
            if isinstance(intention, Intention):
                self._entries.pop(intention.id, None)
            raise
        entry = self._entries.get(intention.id)
        if entry is None:
            return False
        previous = entry["binding"]
        active = {"pending", "attempted"}
        if intention.status not in active or previous["intention"]["status"] not in active:
            self._entries.pop(intention.id, None)
            return False
        rebound = copy.deepcopy(previous)
        rebound["intention"]["status"] = intention.status
        if _signature(rebound) != _signature(binding):
            self._entries.pop(intention.id, None)
            return False
        self._store(binding, entry["projection"])
        return True

    def _error(self, phase, error):
        self.errors.append({"phase": phase, "error": str(error)})

    def _store(self, binding, projection):
        self._entries[binding["intention"]["id"]] = {
            "binding": copy.deepcopy(binding), "binding_sha256": _signature(binding),
            "projection": projection,
        }

    def _failed(self, binding, reason):
        i = binding["intention"]
        self._store(binding, TriggerProjection(i["id"], i["revision"],
            tuple(i["instruction_ids"]), "error", reason=str(reason)[:320]))

    def refresh(self, intentions, instructions):
        bindings = [self._bind(i, instructions) for i in intentions]
        if len({b["intention"]["id"] for b in bindings}) != len(bindings):
            raise ValueError("Duplicate intention IDs in the current bank")
        active = {b["intention"]["id"]: b for b in bindings
                  if b["intention"]["status"] in {"pending", "attempted"}}
        self._entries = {key: entry for key, entry in self._entries.items() if key in active}
        changed = [b for key, b in active.items() if key not in self._entries
                   or self._entries[key]["binding_sha256"] != _signature(b)]
        for start in range(0, len(changed), self.batch_size):
            batch = changed[start:start + self.batch_size]
            expected = {b["intention"]["id"]: b for b in batch}
            # Stale views are unavailable even if transport subsequently fails.
            for key in expected:
                self._entries.pop(key, None)
            try:
                # Configuration is a cache binding, not model-interpreted source text.
                records = [{key: value for key, value in b.items() if key != "projector"} for b in batch]
                value = self.request(self._prompt, {"records": copy.deepcopy(records)}, copy.deepcopy(self._schema))
                if (not isinstance(value, dict) or set(value) != {"trigger_projections"}
                        or not isinstance(value["trigger_projections"], list)
                        or len(value["trigger_projections"]) > 32):
                    raise ValueError("Expected at most 32 trigger projection rows")
            except Exception as exc:
                self._error("projection_request", exc)
                for binding in batch:
                    self._failed(binding, exc)
                continue
            grouped = {key: [] for key in expected}
            for row in value["trigger_projections"]:
                if (not isinstance(row, dict) or not isinstance(row.get("intention_id"), str)
                        or row["intention_id"] not in expected):
                    self._error("projection_row", "Unknown or missing intention ID")
                    continue
                grouped[row["intention_id"]].append(row)
            for key, binding in expected.items():
                try:
                    rows = grouped[key]
                    if len(rows) != 1:
                        raise ValueError("Expected exactly one row for " + key)
                    self._store(binding, _projection(rows[0], binding))
                except (ValueError, TypeError, KeyError) as exc:
                    self._error("projection_row", exc)
                    self._failed(binding, exc)
        return [b["intention"]["id"] for b in changed]

    def snapshot(self):
        return {"version": 1, "kind": "trigger_projection_cache", "batch_size": self.batch_size,
                "projector": copy.deepcopy(self._projector),
                "entries": [{"binding": copy.deepcopy(e["binding"]),
                             "binding_sha256": e["binding_sha256"],
                             "projection": asdict(e["projection"])} for e in self._entries.values()],
                "errors": copy.deepcopy(self.errors)}

    def restore(self, state):
        if (not isinstance(state, dict) or set(state) != {"version", "kind", "batch_size", "projector", "entries", "errors"}
                or type(state["version"]) is not int or state["version"] != 1
                or state["kind"] != "trigger_projection_cache"
                or not isinstance(state["entries"], list) or not isinstance(state["errors"], list)):
            raise ValueError("Invalid trigger projection cache snapshot")
        if state["projector"] != self._projector:
            raise ValueError("Projection model/configuration or prompt/schema mismatch")
        fresh = type(self)(self.request, projector_id=self._projector["identity"], batch_size=state["batch_size"])
        # A cache keeps the definition captured at its own construction.
        fresh._prompt, fresh._schema = self._prompt, copy.deepcopy(self._schema)
        fresh._projector = copy.deepcopy(self._projector)
        try:
            for entry in state["entries"]:
                if not isinstance(entry, dict) or set(entry) != {"binding", "binding_sha256", "projection"}:
                    raise ValueError("Invalid projection cache entry")
                raw = entry["binding"]
                if (not isinstance(raw, dict) or set(raw) != {"intention", "original_instructions", "projector"}
                        or raw["projector"] != self._projector):
                    raise ValueError("Invalid projection binding")
                ri = raw["intention"]
                if (not isinstance(ri, dict) or set(ri) != {f.name for f in fields(Intention)}
                        or not isinstance(raw["original_instructions"], list)):
                    raise ValueError("Invalid projection binding fields")
                intention = Intention(**{**ri, "sources": tuple(ri["sources"]),
                                         "instruction_ids": tuple(ri["instruction_ids"])})
                originals = [Instruction(**i) for i in raw["original_instructions"]]
                if [i.id for i in originals] != list(intention.instruction_ids):
                    raise ValueError("Source history order/identity mismatch")
                binding = fresh._bind(intention, {i.id: i for i in originals})
                if (intention.status not in {"pending", "attempted"}
                        or intention.id in fresh._entries
                        or entry["binding_sha256"] != _signature(binding)):
                    raise ValueError("Invalid, duplicated, or stale projection binding")
                fresh._store(binding, _projection(entry["projection"], binding, allow_error=True))
            for error in state["errors"]:
                if (not isinstance(error, dict) or set(error) != {"phase", "error"}
                        or any(not isinstance(v, str) for v in error.values())):
                    raise ValueError("Invalid projection error record")
            fresh.errors = copy.deepcopy(state["errors"])
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("Malformed trigger projection snapshot") from exc
        self._entries, self.errors, self.batch_size = fresh._entries, fresh.errors, fresh.batch_size
