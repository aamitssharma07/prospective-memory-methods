"""Source-bound registration for the opt-in PIS v2 candidate.

The stored ``action`` is deliberately a complete quoted obligation, not a
purportedly clean action summary. Extraction and typed compilation are separate
batch calls; new registrations never need an existing target or a reviewer.
Revisions append exact update text instead of rewriting away prerequisites.
Neither call has benchmark labels or execution-success authority.
"""

from dataclasses import asdict
import re

from ..method.calendar_guard import has_calendar_removal_clause
from ..core import Change
from ..llm import _object, _rows
from ..baselines.pis import DAYS, PISEngine


EXTRACT = """Find explicitly requested future obligations in the current message.
Return one operations row for EVERY independent request, including requests
wrapped in 'remind me to ...'. Use complete_request_quote to copy the COMPLETE
request verbatim: concrete task, object, recipient, trigger, prerequisites,
exceptions and recurrence. Never reduce a request to a verb such as 'send' or
'remind'. Include all relevant sentences when a condition continues later.
Do not generate a summary or infer missing text. The full source is also kept.

Choose the operation from the CURRENT message, without needing an existing bank:
- new_request: an additional future obligation. A new request does NOT need an
  existing target. Unrelated additions are independent even when other tasks exist.
- modify_request: explicitly changes an already requested action or its timing,
  conditions, recipient, recurrence, etc. 'Move the meeting reminder to noon'
  modifies an old obligation; it does not create a second reminder. An unresolved
  pronoun or unavailable old target is still a modification, never a new request.
- cancel_request: explicitly withdraws an existing request. A negative condition
  inside a request is NOT cancellation of the requested action.

Ordinary scene observations, status reports, future announcements, possibilities,
action menus and requests addressed to somebody else are NOT obligations for this
agent. A cue appearing is not a new request. For such messages return operations=[].
Separate independent obligations even if on one line. Include shared restrictions
in the quote when possible; full current_message always remains authoritative.
Return compact JSON only, then stop.
"""

COMPILE = """Compile typed metadata for the supplied source-bound operations.
Return exactly one specifications row per operation_id; do not drop operations.
The complete_request_quote and original current_message are authoritative. Do
NOT rewrite the requested action or generate a replacement condition summary.

NEW_REQUEST: target_id MUST be ''. No existing target or old history is needed.
MODIFY_REQUEST or CANCEL_REQUEST: choose one pending target_id for the SAME
obligation. Compare full previous specifications and original messages; topic
similarity alone does not establish identity. If no unique target is supported,
use target_id=''. Never silently convert a modification into a new registration.
For modifications compile the resulting metadata, retaining all constraints and
sources not changed. Cancellation uses the old target but empty metadata.

watched_sources contains available sources that can provide evidence of the
TRIGGER, not tools used to execute the action. For example a timed outgoing
message watches clock, not incoming mail unless incoming mail is a prerequisite.
Use events for visible scene cues, named channels for hidden facts, clock for
required time evidence. Include multiple sources when multiple prerequisites
need them; source availability is not proof of a trigger. Never invent a source.
Elapsed durations are not automatically wall-clock requirements: a timer, status
reply or visible event can report elapsed time directly. Watch the actual evidence
provider; add clock only when wall-clock information is needed to establish the
condition. Do not request the current clock merely because a duration is mentioned.

requested_action and trigger_condition (when present in the schema) are two
spans COPIED VERBATIM from complete_request_quote: the action to perform, and
the condition that must hold first. Copy exact substrings, never paraphrase or
reorder. Exclude surrounding narration, scene description and the wrapper
phrase that introduces the reminder. From "You jot down a quick reminder: On
Wednesday, Carry the prescription receipt when you notice the lab drop box",
requested_action is "Carry the prescription receipt" and trigger_condition is
"you notice the lab drop box". A span that is not an exact substring of the
quote is rejected and the whole unit is stored instead.

permitted_days contains allowed weekdays, [] if unrestricted or uncertain. A host
weekday scope restricts a daily plan unless the text explicitly specifies a
different day; '*' permits every day. recurring is true ONLY for explicit
recurrence (including a daily-plan heading), not because a source can be checked
repeatedly. Metadata must reflect the whole current message, not just a shortened
quote. For a modification, preserve old recurrence/days unless explicitly changed.
Never assume Monday-Friday, business hours or any other unstated calendar. A
relative delay alone does not restrict weekdays. Daily/every day is not weekdays.
When a weekday restriction cannot be grounded confidently, use [] and leave the
complete schedule in source text for semantic assessment rather than inventing
a restrictive calendar gate.

clock_relation is at, not_before, or none. required_clock_time is 24-hour HH:MM,
or '' for none. Only use a hard gate for ONE unambiguous required clock constraint.
Do not invent clock times for meals/events or infer them from usual routines.
Multiple independent times/occasions, alternatives, relative delays and uncertain
times cannot be expressed with one hard gate: use none and preserve them in the
source text for semantic assessment. Existing slots are metadata, not proof a
task is due now. No record is completed here. Return compact JSON only.
"""

QUOTE = {"type": "string", "maxLength": 4096}
IDENTIFIER = {"type": "string", "maxLength": 160}
OPERATIONS_SCHEMA = _object({"operations": {"type": "array", "items": _object({
    "operation": {"type": "string", "enum": ["new_request", "modify_request", "cancel_request"]},
    "complete_request_quote": QUOTE,
})}})


# A request delivered as prose carries narration around it ("You jot down a
# quick reminder: ..."). Storing the whole unit as both action and condition
# leaves a record the assessor cannot match and the host cannot resolve to an
# action. When enabled, the model marks the two spans inside the unit instead;
# both are checked as substrings of the quote, so nothing can be invented.
EXTRACT_SPANS = False


def set_extract_spans(enabled):
    """Host switch: extract action/condition spans from the request quote."""
    global EXTRACT_SPANS
    if type(enabled) is not bool:
        raise ValueError("extract spans must be boolean")
    EXTRACT_SPANS = enabled


def _specification_schema():
    # Membership checks are runtime checks, not changing grammar enums. All
    # requests share the same schema, even across different host source sets.
    fields = {
        "operation_id": IDENTIFIER,
        "target_id": IDENTIFIER,
        "watched_sources": {"type": "array", "items": IDENTIFIER},
        "permitted_days": {"type": "array", "items": {"type": "string", "enum": list(DAYS)}},
        "recurring": {"type": "boolean"},
        "clock_relation": {"type": "string", "enum": ["none", "at", "not_before"]},
        "required_clock_time": {"type": "string", "maxLength": 5},
    }
    if EXTRACT_SPANS:
        fields["requested_action"] = {"type": "string", "maxLength": 320}
        fields["trigger_condition"] = {"type": "string", "maxLength": 320}
    return _object({"specifications": {"type": "array", "items": _object(fields)}})


def _clock_values(text):
    return {f"{int(h):02d}:{m}" for h, m in
            re.findall(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", text)}


_DAY_NAMES = r"(?:" + "|".join(DAYS) + r")s?"
_CALENDAR_WORDS = re.compile(
    r"\b(?:" + _DAY_NAMES + r"|weekdays?|weekends?|daily|days?|weeks?|"
    r"today|tomorrow|yesterday)\b", re.IGNORECASE)


def _day_support(text):
    """Return (mentions_calendar, supported_days_or_None), conservatively.

    This is a provenance guard, not a calendar parser or semantic verifier.
    Restrictive gates with negated, relative or range-like wording fall back to
    the full source rather than guessing an effective schedule. Literal weekday
    mentions can still be about something other than this obligation; correct
    source grouping remains the compiler's responsibility.
    """
    if not _CALENDAR_WORDS.search(text):
        return False, None
    ambiguous = (
        r"\b(?:not|never|except|unless|excluding|without|tomorrow|yesterday|today)\b"
        r"|\b(?:instead\s+of|rather\s+than|no\s+longer|don['’]t)\b"
        r"|\b(?:before|after|until|through|between|from)\s+(?:the\s+)?" + _DAY_NAMES + r"\b"
        r"|\b" + _DAY_NAMES + r"\s*(?:[-–—]|to\b|through\b|until\b)"
        r"|\b(?:next|previous|following|same|another|any)\s+(?:day|week)\b"
        r"|\b(?:\d+|one|two|three|four|five|six|seven|several)\s+(?:days?|weeks?)\b"
    )
    if (re.search(ambiguous, text, re.IGNORECASE)
            or has_calendar_removal_clause(text, _CALENDAR_WORDS)):
        return True, None
    named = {day for day in DAYS if re.search(r"\b" + day + r"s?\b", text, re.IGNORECASE)}
    if re.search(r"\bweekdays?\b", text, re.IGNORECASE):
        named.update(DAYS[:5])
    if re.search(r"\bweekends?\b", text, re.IGNORECASE):
        named.update(DAYS[5:])
    if re.search(r"\b(?:daily|every\s+day|each\s+day|all\s+days)\b", text, re.IGNORECASE):
        named.update(DAYS)
    return True, named or None


# When an instruction names no day at all, the announcement day is a guess, not
# a stated constraint. Turning it into a hard gate makes a purely event-based
# intention ("when the lab drop box is unlocked") unable to fire on any later
# day, which is exactly what a cross-day intention must do. IMPLICIT_DAY_GATE
# keeps the historical behaviour; set it False to gate only on explicit days.
IMPLICIT_DAY_GATE = True


def set_implicit_day_gate(enabled):
    """Host switch: gate undated intentions to their announcement day or not."""
    global IMPLICIT_DAY_GATE
    if type(enabled) is not bool:
        raise ValueError("implicit day gate must be boolean")
    IMPLICIT_DAY_GATE = enabled


def _supported_days(instruction, quote, old, instructions):
    # Prefer the exact selected obligation to unrelated dates elsewhere in a
    # multi-request message. Full source supplies shared introductory schedules
    # when the selected quote itself has no calendar information.
    mentions, supported = _day_support(quote)
    if not mentions:
        mentions, supported = _day_support(instruction.text)
    if mentions:
        return supported
    if old is not None:
        # A non-calendar update must not re-scope an old request to today's day.
        # The newest explicit calendar message takes precedence, including an
        # ambiguous restriction removal which must not revive an older gate.
        for key in reversed(old.instruction_ids):
            mentions, supported = _day_support(instructions[key].text)
            if mentions:
                return supported
        scope = instructions[old.instruction_ids[0]].scope
    else:
        scope = instruction.scope
    if not IMPLICIT_DAY_GATE:
        # No stated day: leave the gate open and let the assessor judge the
        # trigger against actual evidence.
        return None
    return {scope} if scope in DAYS else (set(DAYS) if scope == "*" else None)


def _validated_rows(value, key, schema, error_callback):
    """A bad row must not discard unrelated valid requests in the same plan."""
    if not isinstance(value, dict) or set(value) != {key}:
        raise ValueError(f"Expected object with only {key}")
    rows = value[key]
    if not isinstance(rows, list) or len(rows) > 32:
        raise ValueError(f"Expected at most 32 {key}")
    valid = []
    for raw in rows:
        try:
            valid.append(_rows({key: [raw]}, key, schema)[0])
        except (ValueError, TypeError, KeyError) as exc:
            error_callback("v2_" + key, exc)
    return valid


def compile_changes(request, instruction, intentions, sources, triggers,
                    instructions, error_callback):
    """Return ``[(Change, {days, clock_op, clock_time}), ...]`` without mutation.

    ``request(system, payload, schema)`` is the host model callback. ``triggers``
    and ``instructions`` are engine-owned ID mappings. All originals are retained
    by the integrating engine. This function mutates neither those mappings nor
    the previous intentions. It performs one call for facts, two for obligations.
    Source quotation and schema validation do not prove semantic completeness.
    """
    value = request(EXTRACT, {"current_message": asdict(instruction),
                              "available_sources": list(sources)}, OPERATIONS_SCHEMA)
    extracted = _validated_rows(value, "operations", OPERATIONS_SCHEMA, error_callback)
    operations = []
    seen_quotes = set()
    for row in extracted:
        quote = row["complete_request_quote"]
        if not quote.strip() or quote not in instruction.text:
            error_callback("v2_source_quote", ValueError("Complete request needs an exact current-message quotation"))
            continue
        if quote in seen_quotes:
            error_callback("v2_source_quote", ValueError("Duplicate source operation"))
            continue
        seen_quotes.add(quote)
        operations.append({"operation_id": f"request_{len(operations) + 1}", **row})
    if not operations:
        return []

    pending = {i.id: i for i in intentions if i.status in {"pending", "attempted"}}
    needs_targets = any(row["operation"] != "new_request" for row in operations)
    candidates = []
    if needs_targets:
        for old in pending.values():
            candidates.append({
                "id": old.id, "source_bound_specification": old.action,
                "condition": old.condition, "watched_sources": list(old.sources),
                "recurring": old.repeat, "scope": old.scope, **triggers[old.id],
                "original_messages": [asdict(instructions[key]) for key in old.instruction_ids],
            })
    schema = _specification_schema()
    value = request(COMPILE, {
        "current_message": asdict(instruction), "operations": operations,
        "pending_update_targets": candidates, "available_sources": list(sources),
    }, schema)
    rows = _validated_rows(value, "specifications", schema, error_callback)
    by_id = {row["operation_id"]: row for row in operations}
    handled, result = set(), []
    for row in rows:
        try:
            operation_id = row["operation_id"]
            if operation_id not in by_id or operation_id in handled:
                raise ValueError("Specification needs one unique known operation ID")
            handled.add(operation_id)
            operation = by_id[operation_id]
            quote = operation["complete_request_quote"]
            kind, target_id = operation["operation"], row["target_id"]
            old = pending.get(target_id)
            if kind == "new_request":
                if target_id:
                    raise ValueError("New request must not replace an existing intention")
            elif old is None:
                raise ValueError("Unresolved update: a known pending target is required")
            if kind == "cancel_request":
                result.append((Change("cancel", target_id=target_id, evidence_quote=quote),
                               {k: list(v) if isinstance(v, list) else v
                                for k, v in triggers[target_id].items()}))
                continue

            trigger = {"days": list(dict.fromkeys(row["permitted_days"])),
                       "clock_op": row["clock_relation"],
                       "clock_time": row["required_clock_time"]}
            PISEngine._validate_trigger(trigger)
            if set(row["watched_sources"]) - set(sources):
                raise ValueError("Unknown observation source")

            # Use the complete original message, not only the model's quote.
            # A shortened quote must not strip a real explicit time. Retained
            # old times can support an unchanged gate on a non-temporal revision.
            clock_support = instruction.text
            if old is not None and not _clock_values(instruction.text):
                clock_support += "\n" + "\n".join(instructions[k].text for k in old.instruction_ids)
            if trigger["clock_op"] != "none" and trigger["clock_time"] not in _clock_values(clock_support):
                trigger.update(clock_op="none", clock_time="")
                error_callback("v2_clock_guard", ValueError("Unsupported hard clock removed; original source retained"))
            if trigger["days"] and set(trigger["days"]) != _supported_days(instruction, quote, old, instructions):
                trigger["days"] = []
                error_callback("v2_day_guard", ValueError("Unsupported or ambiguous hard weekday gate removed; original source retained"))
            watched = tuple(dict.fromkeys(row["watched_sources"] +
                (["clock"] if trigger["clock_op"] != "none" and "clock" in sources else [])))

            if old is None:
                specification = quote
                scope = "*" if instruction.scope in (*DAYS, "*") else instruction.scope
                condition = quote
            else:
                # Store the update, not a model's destructive rewrite. A reader
                # must interpret the chronological specification: old terms
                # apply except where the later explicit update changes them.
                specification = old.action + "\nAccepted update (overrides only changed terms):\n" + quote
                condition = old.condition.removesuffix(PISEngine._slot_suffix(triggers[old.id]))
                condition += "\nAccepted update (overrides only changed terms):\n" + quote
                scope = old.scope
            condition += PISEngine._slot_suffix(trigger)
            change = Change("register" if old is None else "revise", specification,
                            condition, watched, scope, row["recurring"], target_id, quote)
            result.append((change, trigger))
        except (ValueError, TypeError, KeyError) as exc:
            error_callback("v2_typed_change", exc)
    for operation_id in by_id.keys() - handled:
        error_callback("v2_typed_change", ValueError(f"Missing specification for {operation_id}"))
    return result
