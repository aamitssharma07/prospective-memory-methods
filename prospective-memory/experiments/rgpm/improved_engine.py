"""Experiment 3 candidate: explicit scope grounding and bounded CHECK priority."""

import copy
from dataclasses import asdict, replace
import hashlib
import json
import re

from prospective_memory.core import Decision
from prospective_memory.llm import _rows
from prospective_memory.method.fair_checks import FairCheckArbiter
from prospective_memory.method.fair_trigger import SourceBoundFairTriggerEngine
from prospective_memory.method.source_bound_v3 import REFERENCE_ASSESS, REFERENCE_SCHEMA
from prospective_memory.method.registration import _grounded_days, _today_in_scope
from prospective_memory.baselines.pis import DAYS
from prospective_memory.baselines.pis_registration import _clock_values, _day_support
from registration_guard import RegistrationGuard


SCOPE_GROUNDING = """
Judge selected_trigger_condition for this intention, with its accepted revisions.
The host's current_scope supplies the day of the current scene. An observation
describing a present scene need not repeat that day. permitted_days lists allowed
days, including weekends when listed; it does not mean Monday through Friday.
Typed day/clock gates were checked by code before this assessment. Do not demand
another calendar or date statement merely to reconfirm those gates. Other stated
prerequisites still need evidence. Do not add prerequisites from background
speculation or unrelated obligations in the original messages.
observation_context describes receipt context, not inferred event timestamps.
A current channel reply can contain old events: obey supplied timestamps and
distinguish a fresh occurrence from a continuing state. If occurrence time is
absent, do not invent it or claim an event happened at receipt time. A prediction
or instruction is never evidence that its event occurred. All original explicit
deadlines, thresholds, conjunctions, exclusions and revisions remain binding.
Do not infer a meal, arrival, conversation or other named activity from a typical
clock time. Such a scene trigger needs an observed occurrence, even if the cached
readiness question says 'is it activity time'. Cite trigger evidence from
watched_evidence_ids; other observations provide context but cannot replace it.
"""

REGISTRATION_GROUNDING = """
requested_action and trigger_condition must be exact contiguous excerpts of the
focused operation's complete_request_quote. Other units supply context only;
never copy their action or condition into this operation. Preserve literal
wording, punctuation and conjunctions in these fields. Projection interprets
meaning later; extraction must not paraphrase the source.
Compare the entire selected request against pending records before calling it
new. Changing a recipient, object, time, prerequisite or wording 'instead of'
for the same obligation is modify_request, not new_request. Do not leave both
old and new versions active. Supply a known target hint when identifiable;
the existing compiler and identity reviewer must still accept the revision.
instruction_origin identifies the public message's observation channel.
In a channel reply, an announcement that a pending request's cue has occurred,
including 'please do it now', usually reports evidence or restates that request;
it does not by itself add another future obligation or rewrite its prerequisite.
Explicit new future requests and explicit revisions inside replies still count.
Never treat an observation or a shared topic alone as a revision.
When compiling, permitted_days comes from an explicit restriction or recurrence
in the request, not simply current_message.scope. Unrestricted requests use [].
Every-day recurrence permits all seven days. Preserve an entire multi-occasion
condition in trigger_condition; one action at several occasions must not lose
the later occasions or become gated to only the first time. Distinct explicit
times of one recurring action require clock_relation=none unless a single hard
gate truly governs all occasions. Source instructions remain authoritative.
"""

CLASSIFICATION_REVIEW = """Review a potentially mistaken NEW-request classification.
The first classification is fallible. Compare the focus unit's concrete action,
object, recipient and prerequisite with pending_intentions. An explicit change
to the SAME obligation is modify_request; an unrelated additional obligation
stays new_request. In a provider reply, a pending request's cue announcement can
be fact or restatement rather than a new obligation. Do not change a classification
merely because topics overlap. Use only known related intention IDs. Subsequent
compilation and identity review must still validate any modification/cancellation.
Return exactly one unit_classifications row for the same focus_unit_id.
"""


class BoundedPriorityArbiter(FairCheckArbiter):
    """Alternate persistent gate priority with a fair competing-source offer.

    Uses existing offer/query histories only. A prior priority offer earns a
    competing source the next slot, even when the actor ignored the offer.
    This bounds priority monopolization, not actor behavior or detection delay.
    """

    def arbitrate(self, candidates, *, budget, priority_sources=()):
        candidates, priorities = tuple(candidates), tuple(priority_sources)
        super().arbitrate(candidates, budget=0, priority_sources=priorities)
        competing = {d.source for d in candidates if isinstance(d, Decision)} - set(priorities)
        last = self._offered[-1][1] if self._offered else None
        yielded = bool(competing and last in priorities)
        effective = sorted(competing) if yielded else priorities
        selection = super().arbitrate(candidates, budget=budget, priority_sources=effective)
        self.last_selection = {
            "requested_priority": list(priorities), "effective_priority": list(effective),
            "priority_yielded": yielded,
            "selection_reason": "priority_yields_to_competing_sources" if yielded else "gate_priority_then_recency",
        }
        return selection


def verbatim_spans(quote):
    """Finite lexical spans for short requests; no semantic or label selection."""
    boundaries = sorted({0, len(quote), *(m.start() for m in re.finditer(r"\b", quote))})
    if len(quote) > 512 or len(boundaries) > 96:
        return None
    spans = {quote[start:end].strip() for i, start in enumerate(boundaries)
             for end in boundaries[i + 1:] if 0 < end - start <= 320}
    return sorted(span for span in spans if span)


def compiler_slot_schema(schema, instruction, operation, old, instructions, old_trigger=None):
    """Permit only public-provenance slots; full source remains authoritative."""
    schema = copy.deepcopy(schema)
    fields = schema["properties"]["specifications"]["items"]["properties"]
    quote = operation["complete_request_quote"]
    spans = verbatim_spans(quote)
    if spans:
        for key in ("requested_action", "trigger_condition"):
            if key in fields:
                fields[key] = {**fields[key], "enum": spans}
    if operation["operation"] != "new_request" and old is None:
        return schema, {"reason": "unknown_update_target; existing compiler resolves identity"}
    grounded = _grounded_days(instruction, quote, old, instructions)
    mentions, supported = _day_support(_today_in_scope(replace(instruction, text=quote)).text)
    if not mentions:
        supported = old_trigger.get("days", []) if old is not None and old_trigger else []
    # Shared headings remain in full source for semantic assessment. Dates from
    # unrelated units or the current scope cannot introduce a restrictive gate.
    days = [day for day in DAYS if grounded and supported and day in grounded and day in supported]
    fields["permitted_days"] = {"type": "array", "enum": [[], days] if days else [[]]}
    times = _clock_values(quote)
    if old is not None and not times:
        if old_trigger and old_trigger.get("clock_time"):
            times.add(old_trigger["clock_time"])
        else:
            times.update(_clock_values(old.condition))
    # Several alternatives cannot safely be represented as one mandatory time.
    # A missing/ambiguous slot falls back to source-based readiness, as before.
    if len(times) != 1:
        fields["clock_relation"] = {"type": "string", "enum": ["none"]}
        fields["required_clock_time"] = {"type": "string", "enum": [""]}
    else:
        fields["required_clock_time"] = {"type": "string", "enum": ["", *sorted(times)]}
    return schema, {"verbatim_span_grammar": bool(spans),
                    "permitted_day_options": [[], days] if days else [[]],
                    "explicit_clock_times": sorted(times), "single_clock_gate_allowed": len(times) == 1,
                    "note": "Conservative slots from public source; retain full conditions and original instructions."}


class ImprovedTriggerEngine(SourceBoundFairTriggerEngine):
    POLICY = "sbpm_consolidated"

    def __init__(self, *args, scope_grounding=False, bounded_priority=False, registration_grounding=False, **kwargs):
        self.scope_grounding = scope_grounding
        self.bounded_priority = bounded_priority
        self.registration_grounding = registration_grounding
        self.instruction_sources = {}
        self.monitoring_log = []
        self.readiness_log = []
        self.registration_log = []
        self._candidate_sha256 = hashlib.sha256(SCOPE_GROUNDING.encode()).hexdigest()
        super().__init__(*args, **kwargs)

    def _install_arbiter(self):
        if self.bounded_priority and not isinstance(self.fair_checks, BoundedPriorityArbiter):
            state = self.fair_checks.snapshot()
            self.fair_checks = BoundedPriorityArbiter(self.queryable_sources)
            self.fair_checks.restore(state)

    def set_sources(self, sources, queryable_sources=None):
        super().set_sources(sources, queryable_sources)
        self._install_arbiter()

    def fresh(self):
        return type(self)(self.request, self.sources, self.query_budget, self.queryable_sources,
                          self.verify_actions, self.step_query_budget, self.max_assess_workers,
                          self.skip_unevidenced, self.reuse_stable_waits, self.assess_batch_size,
                          projector_id=self._projector_id,
                          projection_batch_size=self.projections.batch_size,
                          scope_grounding=self.scope_grounding, bounded_priority=self.bounded_priority,
                          registration_grounding=self.registration_grounding)

    def _compile(self, instruction, intentions, sources):
        if not self.registration_grounding:
            return super()._compile(instruction, intentions, sources)
        from prospective_memory.method.registration import compile_changes

        def record(event, **details):
            self.registration_log.append({"event": event, "step_id": self.step_id,
                "instruction_id": instruction.id, **copy.deepcopy(details)})

        guard = RegistrationGuard(self.request, record, self._error, quote_spans=verbatim_spans)

        def request(system, payload, schema):
            if "identity_reviews" in schema["properties"]:
                # The target's source-bound action and condition retain its
                # identity; a multi-task original plan can suggest unrelated IDs.
                payload = {key: value for key, value in payload.items()
                           if key != "target_original_instructions"}
            if "specifications" in schema["properties"] and len(payload["operations"]) > 1:
                specifications = []
                for operation in payload["operations"]:
                    try:
                        reply = request(system, {**payload, "operations": [operation]}, schema)
                        specifications.extend(reply["specifications"])
                    except Exception as exc:
                        record("specification_rejected", operation=operation, error=str(exc))
                        self._error("registration_specification_invalid", exc)
                return {"specifications": specifications}
            if "specifications" in schema["properties"]:
                operation = payload["operations"][0]
                old = next((i for i in intentions if i.id == operation.get("target_hint")), None)
                schema, options = compiler_slot_schema(schema, instruction, operation, old, self.instructions,
                                                      self.triggers.get(old.id) if old else None)
                # Compilation cannot substitute a different obligation after resolution.
                fields = schema["properties"]["specifications"]["items"]["properties"]
                fields["target_id"] = {**fields["target_id"], "enum": [
                    "" if operation["operation"] == "new_request" else operation["target_hint"]]}
                payload = {**payload, "grounded_slot_options": options}
                system += "\nUse grounded_slot_options for typed metadata; uncertain slots stay empty/none."
            if {"unit_classifications", "specifications"} & set(schema["properties"]):
                payload = {**payload, "instruction_origin": {
                    "source": self.instruction_sources.get(instruction.id, "events"),
                    "public_message_id": instruction.id}}
                system = REGISTRATION_GROUNDING + "\n\n" + system
            if "unit_classifications" in schema["properties"]:
                schema = copy.deepcopy(schema)
                schema["properties"]["unit_classifications"].update(minItems=1, maxItems=1)
                fields = schema["properties"]["unit_classifications"]["items"]["properties"]
                fields["unit_id"] = {**fields["unit_id"], "enum": [payload["focus_unit_id"]]}
                fields["related_intention_id"] = {**fields["related_intention_id"], "enum": [
                    "", *(i["id"] for i in payload["pending_intentions"])]}
                return guard.classify(system, payload, schema, CLASSIFICATION_REVIEW + "\n" + REGISTRATION_GROUNDING)
            value = self.request(system, payload, schema)
            if "specifications" in schema["properties"]:
                rows = _rows(value, "specifications", schema)
                if len(rows) != 1 or rows[0]["operation_id"] != operation["operation_id"]:
                    raise ValueError("Exactly one specification of the selected operation is required")
            return value

        self._compiled = compile_changes(request, instruction, intentions, sources,
                                         self.triggers, self.instructions, self._error,
                                         expand_unit=guard.expand)
        coalesced, cancellations = [], set()
        for change, trigger in self._compiled:
            if change.op == "cancel" and change.target_id in cancellations:
                record("duplicate_cancellation_coalesced", change=asdict(change))
                continue
            if change.op == "cancel":
                cancellations.add(change.target_id)
            coalesced.append((change, trigger))
        self._compiled = coalesced
        return [change for change, _ in self._compiled]

    def _decide(self, intention, current, available, queryable_sources, budget):
        if not self.scope_grounding:
            return super()._decide(intention, current, available, queryable_sources, budget)
        try:
            view = self.projections.get(intention, self.instructions)
        except (ValueError, TypeError, AttributeError) as exc:
            self._error("trigger_projection_binding", exc)
            view = None
        projected = view is not None and view.status == "projected"
        prompt = self._trigger_prompt if projected else REFERENCE_ASSESS
        schema = copy.deepcopy(self._trigger_schema if projected else REFERENCE_SCHEMA)
        schema["properties"]["assessments"].update(minItems=1, maxItems=1)
        boolean = "trigger_ready_now" if projected else "all_conditions_met"
        refs = {f"e{index + 1}": observation for index, observation in enumerate(current)}
        fields = schema["properties"]["assessments"]["items"]["properties"]
        fields["missing_observation_source"]["enum"] = ["", *available]
        watched_refs = [ref for ref, o in refs.items() if o.current and o.source in intention.sources]
        # Keep context references available so a wrong-source citation remains
        # observable and is rejected below rather than forced to a legal ID.
        fields["evidence_ids"]["items"]["enum"] = list(refs) or [""]
        fields["evidence_ids"]["maxItems"] = len(refs)
        if not watched_refs:
            fields[boolean]["enum"] = [False]
        trigger = self.triggers[intention.id]
        payload = {
            "intention_id": intention.id, "revision": intention.revision,
            "source_bound_specification": intention.action,
            "selected_trigger_condition": intention.condition.removesuffix(self._slot_suffix(trigger)),
            "typed_trigger": trigger, "permitted_days": trigger["days"],
            "watched_sources": list(intention.sources),
            "watched_evidence_ids": watched_refs,
            "original_instructions": [asdict(self.instructions[i]) for i in intention.instruction_ids],
            "observations": [{**asdict(o), "id": ref} for ref, o in refs.items()],
            "observation_context": {ref: {
                "receipt_scope": self._scope, "receipt_step_id": self.step_id,
                "kind": "current_scene" if o.source == "events" else "channel_reply",
                "occurrence_time": "not_inferred; use only timestamps in observation text",
            } for ref, o in refs.items()},
            "current_scope": self._scope, "check_sources": available,
            "remaining_check_budget": budget,
        }
        if projected:
            payload.update(readiness_question=view.readiness_question,
                           action_to_perform_next=view.action_to_perform_next,
                           projection_binding={"intention_id": view.intention_id, "revision": view.revision,
                                               "source_instruction_ids": list(view.source_instruction_ids)})
        rows = _rows(self.request(prompt + SCOPE_GROUNDING, payload, schema), "assessments", schema)
        if len(rows) != 1:
            raise ValueError("Exactly one trigger assessment required")
        row = rows[0]
        by_id = {ref: o for ref, o in refs.items() if o.current}
        if any(ref not in by_id for ref in row["evidence_ids"]):
            raise ValueError("Evidence IDs must refer to current observations")
        source = row["missing_observation_source"]
        if row[boolean]:
            if source or not any(by_id[ref].source in intention.sources for ref in row["evidence_ids"]):
                raise ValueError("Reminder needs current watched-source evidence and no missing source")
            return Decision("ACT", intention.id, row["reason"],
                            tuple(dict.fromkeys(by_id[ref].id for ref in row["evidence_ids"])))
        if source:
            if source not in available:
                raise ValueError("Assessment requested an unavailable/exhausted observation source")
            return Decision("CHECK", intention.id, row["reason"], source=source)
        return Decision("WAIT", intention.id, row["reason"])

    def _assess(self, intentions, observations, sources, queryable_sources=()):
        before = self.fair_checks.snapshot()
        error_count = len(self.errors)
        decisions = super()._assess(intentions, observations, sources, queryable_sources)
        self.monitoring_log.append({
            "event": "selection", "step_id": self.step_id, "scope": self._scope,
            "policy": "bounded_priority" if self.bounded_priority else "legacy_priority",
            "history_before": before, "history_after": self.fair_checks.snapshot(),
            **copy.deepcopy(self.arbitration_log[-1]),
            **copy.deepcopy(getattr(self.fair_checks, "last_selection", {})),
        })
        self.readiness_log.append({
            "step_id": self.step_id, "scope": self._scope,
            "observations": [asdict(o) for o in observations],
            "decisions": [asdict(d) for d in decisions],
            "new_errors": copy.deepcopy(self.errors[error_count:]),
            "attribution": "observed_proposals; final actor behavior and task alignment require offline inspection",
        })
        return decisions

    def record_query(self, source):
        try:
            return super().record_query(source)
        finally:
            self.monitoring_log.append({"event": "actual_query_attempt", "step_id": self.step_id,
                                        "source": source, "step_queries": list(self.step_queries)})

    def snapshot(self):
        return {**super().snapshot(), "candidate_config": {
                    "scope_grounding": self.scope_grounding, "bounded_priority": self.bounded_priority,
                    "registration_grounding": self.registration_grounding,
                    "registration_policy": "focused_resolved_partition_v15",
                    "scope_prompt_sha256": self._candidate_sha256},
                "monitoring_log": copy.deepcopy(self.monitoring_log),
                "registration_log": copy.deepcopy(self.registration_log),
                "readiness_log": copy.deepcopy(self.readiness_log)}

    def restore(self, state):
        expected = {"scope_grounding": self.scope_grounding, "bounded_priority": self.bounded_priority,
                    "registration_grounding": self.registration_grounding,
                    "registration_policy": "focused_resolved_partition_v15",
                    "scope_prompt_sha256": self._candidate_sha256}
        if not isinstance(state, dict) or state.get("candidate_config") != expected:
            raise ValueError("Candidate configuration mismatch")
        for name in ("monitoring_log", "readiness_log", "registration_log"):
            if not isinstance(state.get(name), list) or any(
                    not isinstance(row, dict) or not isinstance(row.get("step_id"), str)
                    for row in state[name]):
                raise ValueError("Invalid candidate diagnostic log")
        fresh = self.fresh()
        SourceBoundFairTriggerEngine.restore(fresh, state)
        fresh._install_arbiter()
        fresh.monitoring_log = copy.deepcopy(state["monitoring_log"])
        fresh.readiness_log = copy.deepcopy(state["readiness_log"])
        fresh.registration_log = copy.deepcopy(state["registration_log"])
        self.__dict__.update(fresh.__dict__)
        self.compiler, self.matcher = self._compile, self._assess
