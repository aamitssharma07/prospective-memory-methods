"""Bounded, source-grounded recovery for Experiment 3 registration."""

import copy
import re

from prospective_memory.llm import SHORT_TEXT, _object, _rows


LINK_RULES = """
related_intention_id MUST be empty for new_request, context, fact, speculation,
uncertain and compound. Only restatement, modify_request and cancel_request may
name an existing record. A shared topic never makes a new request an update.
Classify only focus_unit; update words in other units do not revise this unit.
Read every clause before choosing one classification. A cancellation AND an
independent new request in one paragraph is compound; do not keep only one.
"""

RESOLVE = """Resolve the identity of an explicit update, before compiling it.
Identify the concrete ACTION being updated, not the verb describing the update.
'Reschedule mailing a letter' refers to mailing a letter, not another scheduling
task. Compare its object/recipient against ALL pending_intentions. These contain
only stored actions so trigger wording cannot be mistaken for task identity.
Select the unique SAME obligation, or target_id='' if absent
or ambiguous. Distinguish doing an action from observing its cue: a pickup
message can trigger a return action without referring to a pickup obligation.
Shared verbs like 'move', shared places or topics are insufficient. Do not pick
the closest surviving record when the requested obligation is absent.
Read prior accepted revisions, but unrelated tasks in original messages do not
belong to that record. No replacement task, guessed link or completion inference.
Return one target_resolutions row with a brief reason and target_id.
"""

PARTITION = """Partition one unresolved public paragraph into exact source spans.
Return 2 to 8 contiguous excerpts in original order, covering ALL non-whitespace
text exactly once. Copy every character within each excerpt, including punctuation.
Each excerpt must contain a complete independent request/update/cancellation or
background statement. Keep prerequisites, negation, exceptions and recurrence
with the action they constrain; do not separate a pronoun from its necessary
context. ONE action with multiple conditions/occasions stays together. Do not
infer new tasks. If no safe split exists, return an empty parts array. These are
only candidate units: each will be classified and validated separately.
"""

PROVIDER_REVIEW = """Check whether a newly requested action duplicates pending work.
Extract reply_action_quote verbatim from focus_unit, including the object being
acted on. Then identify whether ANY pending record requests that same concrete
action. Resolve 'it', 'that' and 'do so' using the public message and pending
requests BEFORE comparing. In resolved_reply_action name the concrete verb and
object, without scheduling words; a bare 'do it now' is not a resolved action.
In resolved_pending_action name the candidate's concrete verb and object.
An existing condition becoming true changes readiness, not obligation identity.
Immediate and conditional wording can therefore request the SAME action on the
SAME occasion. A trigger announcement does not itself add another occasion.
If the reference cannot be resolved safely, choose uncertain.
Do not match by imperative wording, a shared source, or merely having
one pending record. Starting a backup and reading a status page are different
actions. The new reply is authoritative for what action it requests.
If comparing with a pending record, copy pending_action_quote verbatim from its
source_bound_specification and supply its ID. These fields identify a comparison
candidate, NOT a match; leave both empty when there is no useful candidate.
Compare the occasion as well: the same action at an explicitly additional
occasion is distinct_request. Keeping the original request AND adding another
occasion does not replace or revise the original obligation.
relationship must be one of:
- distinct_request: an independently requested action or additional occasion.
- existing_request: the SAME action on the SAME occasion, including a trigger
  announcement followed by 'do it now'; a pronoun can refer to the pending action.
- uncertain: cannot establish the action or relationship safely.
This check only detects duplication. Explicit changes/cancellations belong to
the separate classification and update-resolution stages. Do not infer completion.
Return one provider_comparisons row, with the two
action quotes and resolved actions first, then pending_id, relationship, and a
short comparison reason. Resolved actions are interpretations, not new requests.
"""


def classification_row(value, schema, payload):
    rows = _rows(value, "unit_classifications", schema)
    if len(rows) != 1 or rows[0]["unit_id"] != payload["focus_unit_id"]:
        raise ValueError("Exactly one classification of the focus unit is required")
    row = rows[0]
    kind, related = row["classification"], row["related_intention_id"]
    pending = {item["id"] for item in payload["pending_intentions"]}
    if kind == "restatement" and related not in pending:
        raise ValueError("Restatement needs a known pending intention")
    if related and (kind not in {"restatement", "modify_request", "cancel_request"}
                    or related not in pending):
        raise ValueError("Only an update or restatement may link to a known pending intention")
    return row


def needs_review(payload, row):
    return bool(payload["pending_intentions"] and (
        (row["classification"] == "new_request" and (
            payload["instruction_origin"]["source"] != "events" or
            payload["focus_unit"].get("layout") != "bullet" or update_cue(payload))) or
        (row["classification"] in {"context", "fact", "restatement"} and update_cue(payload))))


def update_cue(payload):
    return re.search(r"\b(?:instead|rather than|change|replace|correction|updated?|cancel|"
                     r"no longer|does not need|doesn't need|not required|called off)\b",
                     payload["focus_unit"]["text"], re.IGNORECASE)


def partition_units(unit, value):
    """Accept only a lossless, ordered partition; never infer omitted text."""
    if not isinstance(value, dict) or set(value) != {"parts"}:
        raise ValueError("Expected parts only")
    parts = value["parts"]
    if parts == []:
        return []
    if not isinstance(parts, list) or not 2 <= len(parts) <= 8:
        raise ValueError("Partition requires two to eight parts")
    text, cursor, result = unit["text"], 0, []
    for index, part in enumerate(parts, 1):
        if not isinstance(part, str) or not part.strip() or part != part.strip():
            raise ValueError("Partition parts must be nonempty trimmed excerpts")
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if not text.startswith(part, cursor):
            raise ValueError("Partition changed, omitted, reordered or duplicated source text")
        start = unit["start"] + cursor
        result.append({"id": f"{unit['id']}.{index}", "start": start,
                       "end": start + len(part), "text": part, "layout": "semantic_span",
                       "parent_unit_id": unit["id"]})
        cursor += len(part)
    if text[cursor:].strip():
        raise ValueError("Partition omitted trailing source text")
    return result


class RegistrationGuard:
    def __init__(self, request, record, error, *, quote_spans=None):
        self.request, self.record, self.error = request, record, error
        self.quote_spans = quote_spans

    def provider_comparison(self, payload):
        kinds = {"distinct_request": "new_request", "existing_request": "restatement", "uncertain": "uncertain"}
        pending = {item["id"]: item for item in payload["pending_intentions"]}
        schema = _object({"provider_comparisons": {"type": "array", "minItems": 1, "maxItems": 1,
            "items": _object({"reply_action_quote": SHORT_TEXT, "resolved_reply_action": SHORT_TEXT,
                "pending_action_quote": {"type": "string", "enum": ["", *dict.fromkeys(
                    item["source_bound_specification"] for item in pending.values())]},
                "resolved_pending_action": SHORT_TEXT,
                "pending_id": {"type": "string", "enum": ["", *pending]},
                "relationship": {"type": "string", "enum": list(kinds)}, "reason": SHORT_TEXT})}})
        data = {**payload, "classification_review": True}
        value = self.request(PROVIDER_REVIEW, data, schema)
        self.record("provider_comparison", unit=payload["focus_unit"], response=value)
        rows = _rows(value, "provider_comparisons", schema)
        if len(rows) != 1:
            raise ValueError("Exactly one provider comparison required")
        row = rows[0]
        action, quote, key = row["reply_action_quote"], row["pending_action_quote"], row["pending_id"]
        kind = kinds[row["relationship"]]
        if action and action not in payload["focus_unit"]["text"]:
            raise ValueError("Provider action quote is not verbatim")
        if kind in {"new_request", "restatement"} and not action.strip():
            raise ValueError("Provider request needs a source action quote")
        if kind in {"new_request", "restatement"} and not row["resolved_reply_action"].strip():
            raise ValueError("Provider request needs a resolved concrete action")
        if key or quote or kind == "restatement":
            if key not in pending or not quote.strip() or quote not in pending[key]["source_bound_specification"]:
                raise ValueError("Provider comparison needs a grounded pending action")
            if not row["resolved_pending_action"].strip():
                raise ValueError("Provider comparison needs a resolved pending action")
        for field in ("resolved_reply_action", "resolved_pending_action"):
            # Reject placeholder predicates, not task identities or legitimate
            # pronouns attached to a concrete action such as "send it to Lee".
            if kind != "uncertain" and re.fullmatch(
                    r"(?:please\s+)?(?:do\s+(?:it|that|this|so|the same)|go ahead|proceed)"
                    r"(?:\s+(?:now|with (?:it|that|this)))?[.!]?",
                    row[field].strip(), re.IGNORECASE):
                error = ValueError(f"{field} is an unresolved placeholder, not a concrete action. "
                                   "Resolve its verb and object from the public message and pending "
                                   "requests, then compare the same occasion; otherwise choose uncertain.")
                self.record("provider_comparison_rejected", unit=payload["focus_unit"],
                            response=value, error=str(error))
                self.error("registration_classification_invalid", error)
                reference_schema = _object({"reference_resolutions": {"type": "array",
                    "minItems": 1, "maxItems": 1, "items": _object({
                        "pending_id": {"type": "string", "enum": ["", *pending]},
                        "reason": SHORT_TEXT})}})
                resolution = self.request(
                    "Resolve the omitted action in a public request such as 'do it'. "
                    "Which pending request supplies the concrete action referred to by "
                    "the pronoun? Compare the public cue and object with all pending "
                    "requests. Choose its pending_id only if uniquely supported, else ''. "
                    "Do not invent a new verb such as process, or decide new versus old "
                    "occasion. Return one reference_resolutions row.",
                    {"focus_unit": payload["focus_unit"],
                     "current_message": payload["current_message"],
                     "pending_intentions": payload["pending_intentions"]}, reference_schema)
                self.record("provider_reference_resolution", unit=payload["focus_unit"],
                            response=resolution)
                references = _rows(resolution, "reference_resolutions", reference_schema)
                if len(references) != 1 or references[0]["pending_id"] not in pending:
                    raise ValueError("Provider action reference has no unique supported pending target")
                reference = pending[references[0]["pending_id"]]
                occasion_schema = _object({"occasion_comparisons": {"type": "array",
                    "minItems": 1, "maxItems": 1, "items": _object({
                        "relationship": {"type": "string", "enum": [
                            "same_occasion", "additional_occasion", "uncertain"]},
                        "additional_occasion_quote": SHORT_TEXT, "reason": SHORT_TEXT})}})
                occasion = self.request(
                    "The omitted action has been resolved to reference_resolution. "
                    "Compare ONLY its occasion with the public request. Does the request "
                    "activate/restate the pending occasion, or explicitly add a separate "
                    "occasion while keeping the original? An existing trigger becoming "
                    "true followed by 'do it now' is the same occasion. For an additional "
                    "occasion copy the supporting public excerpt verbatim; otherwise "
                    "additional_occasion_quote must be empty. Unclear means uncertain. "
                    "Return one occasion_comparisons row.",
                    {"focus_unit": payload["focus_unit"],
                     "current_message": payload["current_message"],
                     "reference_resolution": reference}, occasion_schema)
                self.record("provider_occasion_comparison", unit=payload["focus_unit"],
                            response=occasion)
                occasions = _rows(occasion, "occasion_comparisons", occasion_schema)
                if len(occasions) != 1:
                    raise ValueError("Exactly one occasion comparison required")
                occasion = occasions[0]
                extra = occasion["additional_occasion_quote"]
                if occasion["relationship"] == "additional_occasion":
                    if not extra.strip() or extra not in payload["focus_unit"]["text"]:
                        raise ValueError("Additional occasion needs a verbatim supporting quote")
                elif extra:
                    raise ValueError("Only an additional occasion may have an additional quote")
                kind = {"same_occasion": "restatement", "additional_occasion": "new_request",
                        "uncertain": "uncertain"}[occasion["relationship"]]
                return {"unit_classifications": [{"reason": occasion["reason"],
                    "unit_id": payload["focus_unit_id"], "classification": kind,
                    "related_intention_id": reference["id"] if kind == "restatement" else ""}]}
        return {"unit_classifications": [{"reason": row["reason"], "unit_id": payload["focus_unit_id"],
                 "classification": kind, "related_intention_id": key if kind == "restatement" else ""}]}

    def classify(self, system, payload, schema, review_prompt):
        model_schema = copy.deepcopy(schema)
        properties = model_schema["properties"]["unit_classifications"]["items"]["properties"]
        pending_ids = [item["id"] for item in payload["pending_intentions"]]
        linked = {"modify_request", "cancel_request", "restatement"}
        groups = [([kind for kind in properties["classification"]["enum"] if kind not in linked], [""]),
                  (["modify_request", "cancel_request"], ["", *pending_ids])]
        if pending_ids:
            groups.append((["restatement"], pending_ids))
        branches = []
        for kinds, targets in groups:
            fields = copy.deepcopy(properties)
            fields["classification"] = {**fields["classification"], "enum": kinds}
            fields["related_intention_id"] = {**fields["related_intention_id"], "enum": targets}
            branches.append(_object(fields))
        model_schema["properties"]["unit_classifications"]["items"] = {"anyOf": branches}
        # One semantic repair across the initial classification and optional review.
        repaired = False

        def checked(prompt, data):
            nonlocal repaired
            value = self.request(prompt + LINK_RULES, data, model_schema)
            try:
                row = classification_row(value, schema, payload)
            except (ValueError, TypeError, KeyError) as exc:
                self.record("classification_rejected", unit=payload["focus_unit"],
                            response=copy.deepcopy(value), error=str(exc))
                self.error("registration_classification_invalid", exc)
                if repaired:
                    raise
                repaired = True
                value = self.request(prompt + LINK_RULES, {
                    **data, "classification_repair": True, "invalid_response": value,
                    "validation_error": str(exc)}, model_schema)
                row = classification_row(value, schema, payload)
                self.record("classification_repaired", unit=payload["focus_unit"], response=value)
            return value, row

        value, row = checked(system, payload)
        if needs_review(payload, row):
            if update_cue(payload):
                withdrawal = re.search(r"\b(?:no longer|does not need|doesn't need|not required|called off)\b",
                                       payload["focus_unit"]["text"], re.IGNORECASE)
                prompt = review_prompt
                if withdrawal:
                    prompt += ("\nAn explicit withdrawal such as 'no longer needs to happen' "
                               "cancels the matching obligation, including in a narrative report. "
                               "A negative prerequisite of a live action does not cancel it.")
                value, row = checked(prompt, {**payload, "classification_review": True,
                                                    "previous_classification": row})
            if row["classification"] == "new_request" and (
                    payload["instruction_origin"]["source"] != "events" or
                    payload["focus_unit"].get("layout") != "bullet"):
                # Independently compare the reply with pending work, without anchoring
                # the reviewer to the first model's NEW label or justification.
                value = self.provider_comparison(payload)
                row = classification_row(value, schema, payload)
        if row["classification"] in {"modify_request", "cancel_request"}:
            schema_resolve = _object({"target_resolutions": {"type": "array", "minItems": 1,
                "maxItems": 1, "items": _object({"reason": SHORT_TEXT,
                    "target_id": {"type": "string", "enum": ["", *(
                        item["id"] for item in payload["pending_intentions"])]}})}})
            resolved = self.request(RESOLVE, {
                "update_quote": payload["focus_unit"]["text"],
                "current_message": payload["current_message"],
                "pending_intentions": [{"id": item["id"],
                    "source_bound_specification": item["source_bound_specification"]}
                    for item in payload["pending_intentions"]]}, schema_resolve)
            self.record("target_resolution", unit=payload["focus_unit"],
                        classification=row, resolution=resolved)
            rows = _rows(resolved, "target_resolutions", schema_resolve)
            if len(rows) != 1 or not rows[0]["target_id"]:
                raise ValueError("Update has no unique supported pending target")
            selected = next(item for item in payload["pending_intentions"]
                            if item["id"] == rows[0]["target_id"])
            match_schema = _object({"target_matches": {"type": "array", "minItems": 1,
                "maxItems": 1, "items": _object({"update_action_quote": SHORT_TEXT,
                    "pending_action_quote": SHORT_TEXT, "reason": SHORT_TEXT,
                    "same_obligation": {"type": "boolean"}})}})
            if self.quote_spans is not None:
                fields = match_schema["properties"]["target_matches"]["items"]["properties"]
                for field, source in (("update_action_quote", payload["focus_unit"]["text"]),
                                      ("pending_action_quote", selected["source_bound_specification"])):
                    spans = self.quote_spans(source)
                    if spans:
                        fields[field] = {**fields[field], "enum": spans}
            matched = self.request(
                "Independently check the concrete action referred to by an update. "
                "Copy short verbatim ACTION phrases (verb and object/recipient only) "
                "from update_quote and pending_action. Omit trigger and scheduling "
                "clauses from these quotes. Do they identify the task being updated? "
                "A revision changes its conditions: DIFFERENT triggers, times or "
                "explicitly changed recipients are EXPECTED and do not make the action "
                "identity false. Sending a draft after a new cue is still sending that "
                "draft. 'Send the draft to A instead of B' revises the existing task "
                "to send that draft to B: same_obligation=true. Canceling an action "
                "also refers to that action. Compare the "
                "underlying requested action, not performing an update versus doing it. "
                "Shared rescheduling words, triggers or objects alone are insufficient. "
                "If a different task is being updated or its identity is unclear, "
                "same_obligation=false. No closest-match substitution. Return one target_matches row.",
                {"update_quote": payload["focus_unit"]["text"],
                 "pending_action": selected["source_bound_specification"]}, match_schema)
            self.record("target_action_match", unit=payload["focus_unit"],
                        target_id=selected["id"], response=matched)
            matches = _rows(matched, "target_matches", match_schema)
            if len(matches) != 1:
                raise ValueError("Exactly one target action match required")
            match = matches[0]
            for field, source in (("update_action_quote", payload["focus_unit"]["text"]),
                                  ("pending_action_quote", selected["source_bound_specification"])):
                if not match[field].strip() or match[field] not in source:
                    raise ValueError("Target action comparison needs verbatim action quotes")
            if not match["same_obligation"]:
                raise ValueError("Update has no unique supported pending target")
            value = copy.deepcopy(value)
            value["unit_classifications"][0]["related_intention_id"] = rows[0]["target_id"]
        self.record("classification_accepted", unit=payload["focus_unit"], response=value)
        return value

    def expand(self, unit, payload):
        schema = _object({"parts": {"type": "array", "maxItems": 8,
                                    "items": {"type": "string"}}})
        value = self.request(PARTITION, {"focus_unit": unit, "current_message": payload}, schema)
        try:
            units = partition_units(unit, value)
        except (ValueError, TypeError) as exc:
            self.record("partition_rejected", unit=unit, response=value, error=str(exc))
            raise
        self.record("partition", unit=unit, response=value, children=units)
        return units
