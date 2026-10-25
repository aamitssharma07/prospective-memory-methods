"""Optional source-only interpretation for new, verbatim-bound requests."""

import copy

import jsonschema

from prospective_memory.llm import _object, SHORT_TEXT


ROUTE = """Choose observation sources for ONE future request.
instruction_origin, when supplied, identifies where the quoted report was
received. A status fact reported by that channel is channel evidence, not a
visible scene merely because the report uses ordinary prose. For example, an
approval announced in a queried provider reply is observed through that provider.
Future physical prerequisites mentioned in a report can still require events.
The selected action and trigger are exact excerpts of the request. Decide where
evidence of the TRIGGER would be observed, not where the future action would be
performed. Use only available_sources. If events is available, it carries the
host's visible scene and narrative observations. A visible physical cue belongs
there even when the action involves sending email or changing a calendar.
Select the smallest set of providers needed to establish the stated trigger.
Every selected source must establish an actual trigger prerequisite. Do not
monitor whether the future action was performed or its destination/status.
Do not add events as a backup for an explicit provider: a provider's report
alone needs that provider alone, unless a separate scene prerequisite is stated.
An explicit email arrival or calendar change needs that provider. A wall-clock
time needs clock. Several prerequisites may need several sources. A day alone
is supplied by the host scope and does not require a calendar query. Meal or
arrival events are not clock readings unless an explicit time is also required.

The complete_request_quote is context for omitted qualifiers, pronouns and
exceptions. Background predictions and other obligations in that context do
not add prerequisites to the selected request. Do not rewrite its action or
trigger, decide that it is due, or invent evidence. Return status=routed only
when the sources can be identified, otherwise status=unsupported with an empty
watched_sources list. Explain briefly, return compact JSON, and stop.
"""


def routing_schema(sources):
    return _object({
        "reason": SHORT_TEXT,
        "status": {"type": "string", "enum": ["routed", "unsupported"]},
        "watched_sources": {"type": "array", "maxItems": len(sources),
                            "items": {"type": "string", "enum": list(sources)}},
    })


def route_specifications(reply, payload, request, event):
    """Keep compiler output on failed routing; never repair invalid extraction."""
    result = copy.deepcopy(reply)
    operations = {o["operation_id"]: o for o in payload["operations"]}
    sources = list(payload["available_sources"])
    if not sources:
        return result
    for row in result.get("specifications", []):
        operation = operations.get(row.get("operation_id"))
        if not operation:
            continue
        if operation["operation"] != "new_request" or row.get("target_id"):
            event("source_routing_skipped", compiler_operation_id=operation["operation_id"],
                  source_unit_id=operation["source_unit_id"], target_id=row.get("target_id"),
                  reason="revision_or_cancellation_requires_existing_identity_review")
            continue
        quote = operation["complete_request_quote"]
        action, trigger = row.get("requested_action"), row.get("trigger_condition")
        details = {"compiler_operation_id": operation["operation_id"], "source_unit_id": operation["source_unit_id"],
                   "before_sources": row.get("watched_sources")}
        if any(not isinstance(s, str) or not s.strip() or s not in quote for s in (action, trigger)):
            event("source_routing_skipped", **details, reason="unvalidated_source_spans")
            continue
        route_payload = {"requested_action": action, "trigger_condition": trigger,
                         "complete_request_quote": quote, "available_sources": sources}
        if "instruction_origin" in payload:
            route_payload["instruction_origin"] = payload["instruction_origin"]
        schema = routing_schema(sources)
        try:
            verdict = request(ROUTE, route_payload, schema)
            jsonschema.validate(verdict, schema)
            selected = list(dict.fromkeys(verdict["watched_sources"]))
            if verdict["status"] == "unsupported":
                if selected:
                    raise ValueError("Unsupported routing must not select sources")
                event("source_routing_unsupported", **details, reason=verdict["reason"])
                continue
            if not selected:
                raise ValueError("Routed request requires an observation source")
            # The typed clock gate is independently validated by the compiler.
            # A routing pass must not remove its ability to obtain clock evidence.
            if row.get("clock_relation", "none") != "none" and "clock" in sources and "clock" not in selected:
                selected.append("clock")
            row["watched_sources"] = selected
            event("source_routing_applied", **details, after_sources=selected, reason=verdict["reason"])
        except Exception as exc:
            event("source_routing_error", **details,
                  error={"type": type(exc).__name__, "message": str(exc)}, recovery="retain_compiler_sources")
    return result
