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


MAX_ROWS = 32  # Enforced in _rows: xgrammar rejects a schema carrying maxItems.
TEXT = {"type": "string", "maxLength": 800}
SHORT_TEXT = {"type": "string", "maxLength": 320}
CHANGE_SCHEMA = _object({
    "op": {"type": "string", "enum": ["register", "revise", "cancel"]},
    "action": TEXT,
    "condition": TEXT,
    "sources": {"type": "array", "items": {"type": "string"}},
    "scope": {"type": "string", "maxLength": 160},
    "repeat": {"type": "boolean"},
    "target_id": {"type": "string", "maxLength": 160},
    "evidence_quote": TEXT,
})
COMPILE_SCHEMA = _object({
    "changes": {"type": "array", "items": CHANGE_SCHEMA},
})
DECISION_SCHEMA = _object({
    "kind": {"type": "string", "enum": ["ACT", "CHECK", "WAIT"]},
    "intention_id": {"type": "string", "maxLength": 160},
    "reason": SHORT_TEXT,
    "evidence_ids": {"type": "array", "items": {"type": "string"}},
    "source": {"type": "string", "maxLength": 160},
})
ASSESS_SCHEMA = _object({
    "decisions": {"type": "array", "items": DECISION_SCHEMA},
})

COMPILE_PROMPT = """You register prospective intentions for an agent working on arbitrary tasks.
The instruction field is a candidate message, not necessarily an instruction:
return an empty changes list for ordinary facts, status reports, narration,
irrelevant dialogue, or instructions addressed to somebody else. Register only a
request/commitment to perform an action when a future condition occurs. Every
such request must produce a change: returning an empty list for a genuine request
silently loses it, which is the most damaging error you can make here. Store
the action that should be performed, not the wrapper phrase "remind me". For
example, from "When the courier confirms delivery, remind me to send the buyer
the care instructions", action="send the buyer the care instructions" and
condition="the courier confirms delivery". Do not use generic actions such as
"remind", "notify me", "tell me", or "send reminder" when the instruction
contains the concrete action after that phrase. If the requested action is itself
to notify/remind another person, preserve the recipient and content.

A stated condition is not evidence that it has occurred. Preserve the FULL trigger,
including conjunctions, thresholds, timing, exceptions, prerequisites, and any
specified recurrence. Copy exclusionary and negative clauses as well: text
stating what does NOT qualify, or what to do when required information is
unknown, is part of the condition and must survive into it. Separate genuinely
distinct trigger occurrences when needed. Do not invent requests or convert observations into new intentions.

For every change quote the exact instruction text supporting it in evidence_quote.
Use the supplied scope unless the instruction explicitly specifies a different
scope; '*' means the instruction applies across scopes. Do not treat ordinary
one-off intentions as recurring. Set repeat=true only for explicit recurrence.
Every entry in sources must be copied verbatim from the available_sources list
given in this message. Never invent an identifier, however plausible it sounds:
an unlisted source is rejected and the entire intention is lost. Within that
list, include EVERY identifier that could plausibly carry evidence for the
condition, not only the single most likely one; a condition about a message from
a person belongs to a message or inbox source as well as any general event
stream. Omitting a source that later carries the evidence leaves the intention
unable to act on it. If no listed source can observe the condition, leave
sources empty. This does not authorize guessing its state.

Existing intentions have software-assigned IDs. Use these IDs only to target a
revision/cancellation; use target_id='' when registering. Do not re-register an existing
intention with the same action and condition. Intentions differing in action or
in condition are different intentions: register the new one even when unrelated
intentions are already stored. A revision must refer to the SAME requested action, preserve
unchanged conditions, and replace only what the new instruction changes. A
cancellation requires an explicit cancellation, never absence from a message or
an apparent passage of time. Never mark an action complete from these messages.
Return compact JSON matching the supplied schema, with all fields present. Keep
action and condition short but specific. For a revision or cancellation the
evidence_quote MUST be copied from the message you are reading now, never from
the earlier message that created the intention: a quote taken from the original
request is rejected and the change is lost. target_id identifies which stored
intention the current message changes. For cancellation the other unused text
fields may be empty and sources may be [].
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
Over-strictness is equally an error. An observation that plainly reports the
required fact satisfies the condition even when it uses different wording, a
different order, or names the reporter differently; do not demand that evidence
repeat the instruction's phrasing. Compare numeric thresholds by actual numeric
value, remembering that among negative numbers the value nearer zero is the
larger one.

Return CHECK when needed evidence is absent and a source in the supplied
queryable_sources list could obtain it. Querying is the right move whenever a
listed source could settle a pending condition: a condition that can only be
observed by asking will never resolve on its own. Choose an exact identifier
present in both queryable_sources and that intention's own sources. A source
outside queryable_sources is a push stream, so wait for it to deliver rather
than querying it. A CHECK is a proposal to the host, not an observation and not
evidence that a condition holds. Avoid checking a source that already has
current observations unless the new question cannot be answered from them.

Output only useful interventions. If an intention should merely wait, omit it;
omitted intentions mean WAIT. Use an explicit WAIT row only when correcting a
previously plausible ACT/CHECK would be materially useful. Send at most one row
per intention. Keep every reason to one short evidence-backed sentence. Do not
write chain-of-thought, general advice, or a list of all tasks. ACT uses
source='' and nonempty evidence_ids; CHECK names its source. Return only compact
JSON matching the supplied schema, on a single line. Do not emit blank lines,
indentation or trailing whitespace; stop immediately after the final brace.
"""


def _rows(value, name, schema):
    if not isinstance(value, dict) or set(value) != {name}:
        raise ValueError(f"Expected object with only {name}")
    rows = value[name]
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
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
                if (not isinstance(item, list) or len(item) > MAX_ROWS
                        or any(not isinstance(entry, str) or not entry or len(entry) > 160
                               for entry in item)):
                    raise ValueError(f"Invalid {key}")
    return rows


class LLMMemoryPolicy:
    """Instruction compiler and trigger assessor using a host model callback."""

    def __init__(self, request):
        self.request = request

    def compile(self, instruction, intentions, sources):
        # The stored provenance quote is engine bookkeeping. Showing it invites
        # the model to copy it into a revision or cancellation, where a quote
        # from the earlier message is rejected and the change is lost.
        existing = [{key: value for key, value in asdict(item).items()
                     if key != "evidence_quote"} for item in intentions]
        value = self.request(COMPILE_PROMPT, {
            "instruction": asdict(instruction),
            "intentions": existing,
            "available_sources": list(sources),
        }, COMPILE_SCHEMA)
        return [Change(**{**row, "sources": tuple(row["sources"])})
                for row in _rows(value, "changes", COMPILE_SCHEMA)]

    def assess(self, intentions, observations, sources, queryable_sources=()):
        if not intentions:
            return []
        value = self.request(ASSESS_PROMPT, {
            "intentions": [asdict(item) for item in intentions],
            "observations": [asdict(item) for item in observations],
            "available_sources": list(sources),
            "queryable_sources": list(queryable_sources),
        }, ASSESS_SCHEMA)
        return [Decision(**{**row, "evidence_ids": tuple(row["evidence_ids"])})
                for row in _rows(value, "decisions", ASSESS_SCHEMA)]
