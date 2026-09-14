"""Model policies for the portable memory engine, independent of model providers.

The host supplies ``request(system, payload, schema) -> dict``. It can use a local
model, a hosted model, or a deterministic fixture. Schemas are plain JSON Schema;
transport settings, output-token limits, and inference logging belong to the host.
"""

from dataclasses import asdict

from .core import Change, Decision


def _object(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


TEXT = {"type": "string", "maxLength": 1600}
CHANGE_SCHEMA = _object({
    "op": {"type": "string", "enum": ["register", "revise", "cancel"]},
    "action": TEXT,
    "condition": TEXT,
    "sources": {"type": "array", "items": {"type": "string"}, "maxItems": 16},
    "scope": {"type": "string", "maxLength": 160},
    "repeat": {"type": "boolean"},
    "target_id": {"type": "string", "maxLength": 160},
    "evidence_quote": TEXT,
})
COMPILE_SCHEMA = _object({
    "changes": {"type": "array", "items": CHANGE_SCHEMA, "maxItems": 32},
})
DECISION_SCHEMA = _object({
    "kind": {"type": "string", "enum": ["ACT", "CHECK", "WAIT"]},
    "intention_id": {"type": "string", "maxLength": 160},
    "reason": TEXT,
    "evidence_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 16},
    "source": {"type": "string", "maxLength": 160},
})
ASSESS_SCHEMA = _object({
    "decisions": {"type": "array", "items": DECISION_SCHEMA, "maxItems": 128},
})

COMPILE_PROMPT = """You register prospective intentions for an agent working on arbitrary tasks.
The instruction field is a candidate message, not necessarily an instruction:
return an empty changes list for ordinary facts, status reports, narration,
irrelevant dialogue, or instructions addressed to somebody else. Register only a
request/commitment to perform an action when a future condition occurs. A stated
condition is not evidence that it has occurred. Preserve the FULL trigger,
including conjunctions, thresholds, timing, exceptions, prerequisites, and any
specified recurrence. Separate genuinely distinct trigger occurrences when
needed. Do not invent requests or convert observations into new intentions.

For every change quote the exact instruction text supporting it in evidence_quote.
Use the supplied scope unless the instruction explicitly specifies a different
scope; '*' means the instruction applies across scopes. Do not treat ordinary
one-off intentions as recurring. Set repeat=true only for explicit recurrence.
Use only the advertised observation source identifiers, chosen by meaning.
Use events for conditions observed in incoming text when that source is available.
An unavailable source cannot be invented: leave sources empty if no offered
source can observe the condition. This does not authorize guessing its state.

Existing intentions have software-assigned IDs. Use these IDs only to target a
revision/cancellation; use target_id='' when registering. Do not duplicate an
existing intention. A revision must refer to the SAME requested action, preserve
unchanged conditions, and replace only what the new instruction changes. A
cancellation requires an explicit cancellation, never absence from a message or
an apparent passage of time. Never mark an action complete from these messages.
Return the supplied JSON schema, with all fields present. For cancellation the
target_id and evidence_quote identify the cancellation; other unused text fields
may be empty and sources may be [].
"""

ASSESS_PROMPT = """You monitor prospective intentions for an agent performing arbitrary work.
For each pending intention assess its FULL condition against the observations.
The tasks need not share a goal or follow a sequence. Return ACT only when
current observations explicitly support ALL required conditions, and cite the
observation IDs providing that evidence. Retain action constraints in the reason.
The instruction describing a condition is not evidence of its satisfaction.
Do not infer current time, hidden state, successful completion, or prerequisites
from guesses, stale observations, a remembered request, or an attempted action.
Current means recently received evidence, not necessarily a recently occurring
event: tool replies may contain buffered earlier events. Respect event timestamps
and wording; do not assert an event happened now merely because its reply arrived
now. If the required timing cannot be established, return WAIT or CHECK.
For conjunctions every part must be supported. Similar words alone are not proof
of a semantic match; negative, conditional, and future statements do not establish
that an event happened. Do not claim certainty beyond what the evidence says.

Return CHECK when needed evidence is absent and one of the offered observation
sources could obtain it. Choose only an exact offered source identifier, also
listed for that intention. A CHECK is a proposal to the host, not an observation
and not evidence that a condition holds. Avoid checking a source that already has
current observations unless the new question cannot be answered from them.
The source events is a push stream; wait for incoming events rather than querying
it. Return WAIT if the condition is false, unsupported with no suitable checking
source, or no intervention would be useful. Omitted intentions also mean WAIT.
Send brief evidence-backed decisions, not general advice or a list of all tasks.
ACT uses source='' and nonempty evidence_ids; CHECK names its source; WAIT may
have empty evidence_ids and source. Return only the supplied JSON schema.
"""


def _rows(value, name, schema):
    if not isinstance(value, dict) or set(value) != {name}:
        raise ValueError(f"Expected object with only {name}")
    rows = value[name]
    if not isinstance(rows, list) or len(rows) > schema["properties"][name]["maxItems"]:
        raise ValueError(f"Invalid {name} array")
    item_schema = schema["properties"][name]["items"]
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(item_schema["properties"]):
            raise ValueError(f"Unexpected or missing fields in {name}")
        for key, field in item_schema["properties"].items():
            item = row[key]
            if field["type"] == "string":
                if not isinstance(item, str) or len(item) > field.get("maxLength", 1600):
                    raise ValueError(f"Invalid {key}")
                if "enum" in field and item not in field["enum"]:
                    raise ValueError(f"Invalid {key}: {item}")
            elif field["type"] == "boolean":
                if not isinstance(item, bool):
                    raise ValueError(f"Invalid {key}")
            elif field["type"] == "array":
                if (not isinstance(item, list) or len(item) > field["maxItems"]
                        or any(not isinstance(entry, str) or not entry or len(entry) > 160
                               for entry in item)):
                    raise ValueError(f"Invalid {key}")
    return rows


class LLMMemoryPolicy:
    """Instruction compiler and trigger assessor using a host model callback."""

    def __init__(self, request):
        self.request = request

    def compile(self, instruction, intentions, sources):
        value = self.request(COMPILE_PROMPT, {
            "instruction": asdict(instruction),
            "intentions": [asdict(item) for item in intentions],
            "available_sources": list(sources),
        }, COMPILE_SCHEMA)
        return [Change(**{**row, "sources": tuple(row["sources"])})
                for row in _rows(value, "changes", COMPILE_SCHEMA)]

    def assess(self, intentions, observations, sources):
        if not intentions:
            return []
        value = self.request(ASSESS_PROMPT, {
            "intentions": [asdict(item) for item in intentions],
            "observations": [asdict(item) for item in observations],
            "available_sources": list(sources),
        }, ASSESS_SCHEMA)
        return [Decision(**{**row, "evidence_ids": tuple(row["evidence_ids"])})
                for row in _rows(value, "decisions", ASSESS_SCHEMA)]
