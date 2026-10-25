"""Opt-in layout-unit compiler: visited units, exact source, guarded updates.

Each public-layout unit is classified separately. Code copies exact source spans
instead of asking the model to reproduce whitespace. A separate identity check
guards only modifications/cancellations; new additions do not need old targets.
Visiting every unit is NOT a guarantee of semantic intention coverage. Compound
paragraphs without explicit layout can remain unresolved rather than being split
into guessed obligations. Originals and chronological revisions stay authoritative.
"""

import copy
from collections import deque
from dataclasses import asdict, replace
import re

from ..core import Change
from ..llm import SHORT_TEXT, _object, _rows
from ..baselines.pis import DAYS, PISEngine
from ..baselines.pis_registration import (
    COMPILE, IDENTIFIER, _clock_values, _specification_schema, _supported_days,
    _validated_rows,
)


CLASSIFY = """Identify future obligations in ONLY the focus_unit_id.
Every other source unit receives its own call. Read the WHOLE focus unit with
the full current_message and headings as context. Code copies its exact source
text; do not rewrite it. Layout boundaries do not decide semantic meaning.
This is REGISTRATION, not trigger-readiness assessment. A valid conditional
request must be registered even while its trigger is false or unknown.

An imperative IS an explicit request, even without 'please', 'remind me', or
'I request'. A conditional future action IS an obligation: waiting for a trigger
does not make the action merely a fact or contextual information. The condition
can come before or after the action, and can contain timing or several required
prerequisites. A future-plan item is a request even when not executable yet.
For example, 'Unlock the cabinet when authorization arrives' and 'If authorized,
unlock the cabinet' request an action; 'Authorization may arrive later' predicts
an event without requesting an action; 'The cabinet is unlocked' reports a fact.
First explain briefly whether the FULL unit directs an action or only reports
information, then choose the classification. Do not classify only its cue clause.

Classifications:
- new_request: a new requested future action, reminder, commitment or plan item.
  Unrelated existing records do not block additions. No old target is required.
- modify_request: explicitly changes an existing obligation's trigger, timing,
  action details, recipient, etc. Corrected instructions replacing an earlier cue
  are modifications, not additions. An unclear target remains an update.
- cancel_request: explicitly withdraws an existing obligation. Negative conditions
  within a requested action do not cancel the action.
- restatement: reaffirms an unchanged pending obligation; give its existing
  related_intention_id. Being told a task is still pending does not remove its
  original trigger or create a second untimed obligation.
- context: a heading or supporting clause containing NO requested action of its
  own. A complete action-plus-condition request must not be labelled context.
- fact: a report of state or occurrence, NOT a directive to perform an action.
- speculation: a possibility/prediction without a requested action or commitment.
- uncertain: the meaning cannot safely be established.
- compound: genuinely multiple independently requested actions in ONE layout unit
  without separate source spans. Do not silently keep just the last one.

Independent means separate obligations, not actions without trigger conditions.
ONE action at several occasions is not compound; retain it with its full schedule.
Several prerequisites of ONE action are not multiple actions. Background facts
beside ONE real update do not hide the update. Use pending_intentions to identify
restatements; source_bound_specification identifies the actual stored obligation.
Original plans may mention other tasks that are NOT the selected stored record.

Return exactly one unit_classifications row: a short reason first, then this
focus unit's exact unit_id and classification. For restatement, provide the known
related_intention_id. For modify_request/cancel_request, it may name a known
pending target as a HINT, or be '' if unresolved; later resolution and identity
review are still required. For new_request and all other classifications use ''.
Return compact JSON and stop. Nothing executes or becomes completed here.
"""

IDENTITY = """Review the identity of ONE explicit revision or cancellation.
This is NOT an ADD review: no new-registration operation is supplied here.
Does update_quote explicitly change/cancel the SAME concrete obligation represented
by target.source_bound_specification? Return same_obligation and explicit_update.
Reject mere shared topics, institutions, recipients, or generic verbs. Returning
an item and sending a message about that item are different obligations. A missing
target must not be replaced by the most similar surviving memory record.

The target's full original messages may mention many independent requests. Those
other requests are NOT the target. Use the selected source_bound_specification
to identify the concrete target; original messages supply retained context only.
Read prior accepted updates chronologically. Genuine action-detail changes can
refer back to the same obligation; an unrelated additional request cannot.
An observation, future prediction, reminder that a task is pending, or appearance
of a trigger is not an explicit modification/cancellation. When identity or the
update is ambiguous, return false rather than guessing. No rewritten summary,
target substitution, completion inference or new task is allowed. Return exactly
one identity_reviews row, compact JSON, and stop.
"""

COMPILE_V3 = COMPILE + """
Source routing: if 'events' is advertised, it denotes the public observation
stream, including visible scene changes. A physical object, location or topic
mentioned in a request does not create a tool/source identifier. Match the kind
of evidence needed, not merely words shared with a channel name. A schedule can
be specified by the user without requiring a calendar response; a visible event
can arrive through events. Use a named source only when that provider could
actually carry evidence for this condition. Source names are observation
capabilities, not a promise they can all be queried; the host separately controls
which sources permit active queries. Never infer trigger satisfaction here.
An operation's target_hint, when nonempty, is only the earlier classifier's
suggestion. Independently resolve the concrete obligation from the source and
pending records; do not treat the hint as authority. A later identity review
must still support every modification/cancellation. Unknown or ambiguous targets
remain unresolved rather than attaching to the nearest related topic.

Compile ONLY supplied operations: exactly one row per operation_id, then stop.
Unchanged pending records are reference material, not additional work. Never emit
another target row for the same operation. Explicitly requested repeated execution
requires recurring=true. A single clock/event cue is not recurrence; an event's
future timing alone does not require clock. Alternatives between visible cues
alone need no clock source unless wall-clock information is explicitly required.
"""

CLASSIFICATION_SCHEMA = _object({"unit_classifications": {"type": "array", "items": _object({
    "reason": SHORT_TEXT,
    "unit_id": IDENTIFIER,
    "classification": {"type": "string", "enum": [
        "new_request", "modify_request", "cancel_request", "restatement", "context",
        "fact", "speculation", "uncertain", "compound",
    ]},
    "related_intention_id": IDENTIFIER,
})}})
IDENTITY_SCHEMA = _object({"identity_reviews": {"type": "array", "items": _object({
    "same_obligation": {"type": "boolean"},
    "explicit_update": {"type": "boolean"},
    "reason": SHORT_TEXT,
})}})

_BULLET = re.compile(r"^(?P<indent>[ \t]*)(?:[-*+]|(?:\d+|[A-Za-z])[.)])\s+\S")
_HEADING = re.compile(r"^\s*(?:#{1,6}\s+\S|={2,}.*={2,}\s*$)")


def layout_units(text):
    """Exact public spans: headers, bullet entries, and ordinary paragraphs.

    Indented lines/sub-bullets continue their containing bullet. Arbitrary
    sentence punctuation is never segmented. Non-indented text after a bullet
    becomes a paragraph; its semantic relation remains model/context work.
    """
    units, active, offset = [], None, 0

    def flush():
        nonlocal active
        if active is None:
            return
        start, end, layout, _ = active
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            units.append({"id": f"u{len(units) + 1}", "start": start, "end": end,
                          "text": text[start:end], "layout": layout})
        active = None

    for line in text.splitlines(keepends=True):
        end = offset + len(line)
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" \t"))
        bullet = _BULLET.match(line)
        if not stripped:
            if active is not None and active[2] == "bullet":
                active[1] = end
            else:
                flush()
        elif active is not None and active[2] == "bullet" and indent > active[3]:
            active[1] = end
        elif bullet:
            flush()
            active = [offset, end, "bullet", indent]
        elif _HEADING.match(line) or stripped.endswith(":"):
            flush()
            active = [offset, end, "heading", indent]
            flush()
        elif active is not None and active[2] == "paragraph":
            active[1] = end
        else:
            flush()
            active = [offset, end, "paragraph", indent]
        offset = end
    flush()
    return units


def _today_in_scope(instruction):
    # Only the public host scope can ground today's weekday. Do not consult
    # wall-clock dates, simulator state, or guess tomorrow/relative offsets.
    if instruction.scope not in DAYS:
        return instruction
    return replace(instruction, text=re.sub(r"\btoday(?:['’]s)?\b", instruction.scope,
                                            instruction.text, flags=re.IGNORECASE))


def _spans(row, quote, error_callback):
    """Prefer the marked action/condition spans; fall back to the whole unit.

    Both spans must appear verbatim inside the request quote, so the model can
    only select text, never invent it. Anything unusable keeps the previous
    behaviour rather than dropping the intention.
    """
    action, condition = row.get("requested_action"), row.get("trigger_condition")
    if action is None and condition is None:
        return quote, quote
    for name, span in (("requested_action", action), ("trigger_condition", condition)):
        if not isinstance(span, str) or not span.strip() or span not in quote:
            error_callback("v3_span_guard",
                           ValueError(f"{name} is not a verbatim span of the request; unit retained"))
            return quote, quote
    return action, condition


def _grounded_days(instruction, quote, old, instructions):
    current = _today_in_scope(instruction)
    if current is not instruction:
        quote = re.sub(r"\btoday(?:['’]s)?\b", instruction.scope, quote, flags=re.IGNORECASE)
    histories = {key: _today_in_scope(value) for key, value in instructions.items()}
    return _supported_days(current, quote, old, histories)


def _same_target(request, operation, instruction, old, instructions):
    value = request(IDENTITY, {
        "operation": operation["operation"], "current_message": asdict(instruction),
        "update_quote": operation["complete_request_quote"],
        "target": {"id": old.id, "source_bound_specification": old.action,
                   "condition": old.condition},
        "target_original_instructions": [asdict(instructions[key]) for key in old.instruction_ids],
    }, IDENTITY_SCHEMA)
    rows = _rows(value, "identity_reviews", IDENTITY_SCHEMA)
    if len(rows) != 1:
        raise ValueError("Exactly one update identity review required")
    row = rows[0]
    if not row["same_obligation"] or not row["explicit_update"]:
        raise ValueError("Update identity not supported: " + row["reason"])


def compile_changes(request, instruction, intentions, sources, triggers,
                    instructions, error_callback, *, expand_unit=None):
    """Return Change/trigger pairs; preserve all inputs and classify every unit.

    Request failures/uncertain units are visible and local, not atomic rejection
    of an unrelated complete plan. Transport logs record every unit disposition.
    The integrating engine retains the full original input even if no change is
    accepted. Semantic extraction, grouping and identity review remain fallible.
    """
    units = layout_units(instruction.text)
    if len(units) > 64:
        raise ValueError("Layout compiler supports at most 64 public units per message")
    pending = {i.id: i for i in intentions if i.status in {"pending", "attempted"}}
    references = [{"id": old.id, "source_bound_specification": old.action,
                   "condition": old.condition} for old in pending.values()]
    operations = []
    queue = deque(units)
    visited = 0
    while queue:
        unit = queue.popleft()
        visited += 1
        try:
            value = request(CLASSIFY, {
                "focus_unit": unit, "current_message": asdict(instruction), "source_units": units,
                "focus_unit_id": unit["id"], "pending_intentions": references,
                "available_sources": list(sources),
            }, CLASSIFICATION_SCHEMA)
            rows = _rows(value, "unit_classifications", CLASSIFICATION_SCHEMA)
            if len(rows) != 1 or rows[0]["unit_id"] != unit["id"]:
                raise ValueError("Exactly one classification of the focus unit is required")
            row = rows[0]
            kind, related = row["classification"], row["related_intention_id"]
            if kind == "restatement":
                if related not in pending:
                    raise ValueError("Restatement needs a known pending intention reference")
                continue
            if kind in {"modify_request", "cancel_request"}:
                if related and related not in pending:
                    raise ValueError("Update target hint must reference a known pending intention")
            elif related:
                raise ValueError("Only restatement or an update can supply a related intention ID")
            if kind in {"uncertain", "compound"}:
                if expand_unit is not None and "parent_unit_id" not in unit:
                    children = expand_unit(unit, asdict(instruction))
                    if children:
                        if visited + len(queue) + len(children) > 64:
                            raise ValueError("Expanded compiler supports at most 64 units")
                        cursor = unit["start"]
                        for child in children:
                            start, end = child["start"], child["end"]
                            if (child.get("parent_unit_id") != unit["id"]
                                    or not cursor <= start < end <= unit["end"]
                                    or instruction.text[cursor:start].strip()
                                    or instruction.text[start:end] != child["text"]):
                                raise ValueError("Expanded unit is not an ordered exact source span")
                            cursor = end
                        if instruction.text[cursor:unit["end"]].strip():
                            raise ValueError("Expanded units omit source text")
                        queue.extendleft(reversed(children))
                        continue
                error_callback("v3_unit_unresolved", ValueError(unit["id"] + ": " + row["reason"]))
                continue
            if kind not in {"new_request", "modify_request", "cancel_request"}:
                continue
            operations.append({"operation_id": f"request_{len(operations) + 1}",
                               "source_unit_id": unit["id"], "operation": kind,
                               "target_hint": related,
                               "complete_request_quote": unit["text"]})
        except Exception as exc:
            error_callback("v3_unit_classification", exc)
    if not operations:
        return []
    if len(operations) > 32:
        raise ValueError("At most 32 source operations can be compiled per message")

    candidates = []
    if any(row["operation"] != "new_request" for row in operations):
        for old in pending.values():
            candidates.append({"id": old.id, "source_bound_specification": old.action,
                "condition": old.condition, "watched_sources": list(old.sources),
                "recurring": old.repeat, "scope": old.scope, **triggers[old.id],
                "original_messages": [asdict(instructions[key]) for key in old.instruction_ids]})
    schema = _specification_schema()
    # IDENTIFIER is shared by several schema fields. Replace this item object
    # rather than mutating it (even deepcopy preserves within-schema aliases).
    watched_schema = schema["properties"]["specifications"]["items"]["properties"]["watched_sources"]
    watched_schema["items"] = {**watched_schema["items"], "enum": list(sources)}
    value = request(COMPILE_V3, {"current_message": asdict(instruction), "operations": operations,
                             "pending_update_targets": candidates, "available_sources": list(sources)}, schema)
    rows = _validated_rows(value, "specifications", schema,
                           lambda phase, exc: error_callback(phase.replace("v2_", "v3_", 1), exc))
    by_id = {row["operation_id"]: row for row in operations}
    handled, result = set(), []
    for row in rows:
        try:
            operation_id = row["operation_id"]
            if operation_id not in by_id or operation_id in handled:
                raise ValueError("Specification needs one unique known operation ID")
            handled.add(operation_id)
            operation = by_id[operation_id]
            quote, kind = operation["complete_request_quote"], operation["operation"]
            target_id = row["target_id"]
            old = pending.get(target_id)
            if kind == "new_request":
                if target_id:
                    raise ValueError("New request cannot replace an existing intention")
            elif old is None:
                raise ValueError("Unresolved update requires a known pending target")
            if old is not None:
                try:
                    _same_target(request, operation, instruction, old, instructions)
                except Exception as exc:
                    error_callback("v3_identity_review", exc)
                    continue
            if kind == "cancel_request":
                result.append((Change("cancel", target_id=target_id, evidence_quote=quote),
                               copy.deepcopy(triggers[target_id])))
                continue

            trigger = {"days": list(dict.fromkeys(row["permitted_days"])),
                       "clock_op": row["clock_relation"], "clock_time": row["required_clock_time"]}
            PISEngine._validate_trigger(trigger)
            if set(row["watched_sources"]) - set(sources):
                raise ValueError("Unknown observation source")
            clock_support = instruction.text
            if old is not None and not _clock_values(instruction.text):
                clock_support += "\n" + "\n".join(instructions[key].text for key in old.instruction_ids)
            if trigger["clock_op"] != "none" and trigger["clock_time"] not in _clock_values(clock_support):
                trigger.update(clock_op="none", clock_time="")
                error_callback("v3_clock_guard", ValueError("Unsupported hard clock removed; source retained"))
            if trigger["days"] and set(trigger["days"]) != _grounded_days(instruction, quote, old, instructions):
                trigger["days"] = []
                error_callback("v3_day_guard", ValueError("Unsupported or ambiguous hard weekday gate removed; source retained"))
            watched = tuple(dict.fromkeys(row["watched_sources"] +
                (["clock"] if trigger["clock_op"] != "none" and "clock" in sources else [])))
            if old is None:
                specification, condition = _spans(row, quote, error_callback)
                scope = "*" if instruction.scope in (*DAYS, "*") else instruction.scope
            else:
                suffix = "\nAccepted update (overrides only changed terms):\n" + quote
                specification = old.action + suffix
                condition = old.condition.removesuffix(PISEngine._slot_suffix(triggers[old.id])) + suffix
                scope = old.scope
            condition += PISEngine._slot_suffix(trigger)
            result.append((Change("register" if old is None else "revise", specification,
                                  condition, watched, scope, row["recurring"], target_id, quote), trigger))
        except (ValueError, TypeError, KeyError) as exc:
            error_callback("v3_typed_change", exc)
    for operation_id in by_id.keys() - handled:
        error_callback("v3_typed_change", ValueError(f"Missing specification for {operation_id}"))
    return result
