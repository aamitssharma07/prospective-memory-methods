"""Opt-in source-bound PIS: complete requests plus evidence-based reminders.

Source quotations preserve requested content; they do not prove extraction is
complete or triggers are understood. The host alone executes and acknowledges.
"""

import copy
from dataclasses import asdict

from ..core import Decision
from ..llm import SHORT_TEXT, _object, _rows
from ..baselines.pis import PISEngine
from ..baselines.pis_registration import compile_changes


ASSESS = """Evaluate the trigger of ONE future obligation using current evidence.
The source_bound_specification contains the full request, not an executed action.
Separate the action-to-do from the trigger-to-observe. For 'When C, do A', assess
whether C holds NOW so that A should be performed NEXT. Do NOT require evidence
that A has already happened: its non-completion is not a missing prerequisite.
This is a readiness/reminder assessment, NOT a task-completion assessment.
Read original_instructions in chronological order: later explicit updates replace
only the changed terms. Other prerequisites remain. Do not activate an obsolete
time or action. Instructions are requirements, never evidence of occurrence.

Return exactly one assessments row. First write a short reason evaluating the
actual trigger against the observations, then give all_conditions_met. Compare
numeric values explicitly: 'below/less than' means strict <; 'above/more than'
means strict >; 'at least' means >=; 'at most' means <=. Equality does NOT satisfy
a strict inequality. Do not replace an instruction's operator with a looser one.
all_conditions_met is true ONLY when current
observations establish EVERY trigger prerequisite for this obligation now.
Respect conjunctions, negation, identity, thresholds, exceptions and future tense.
Clear paraphrases count. An announcement of a future event is not its occurrence.
Current observations may quote historical events: a newly fetched log does not
make every event in it happen again now. Respect explicit timestamps, current
scope and whether the instruction needs a fresh occurrence or a continuing state.
Do not infer an action succeeded merely because a previous response chose it.
Explicit clock/day gates have already passed, but other prerequisites still need
evidence. A scheduled time does not require calendar confirmation unless requested.
Watched sources identify possible evidence providers, not extra prerequisites.

When all_conditions_met=true, cite exact short quotes from current observations
in parallel evidence_ids/evidence_quotes arrays and set missing_observation_source=''.
When false, if a missing observation can usefully resolve the trigger NOW, set
missing_observation_source to one exact check_sources entry. A hidden condition
can require checking even when the scene is quiet. If known evidence already
rules the trigger out, wait rather than querying an unrelated source. For an
AND condition, one known-false prerequisite is enough to wait even if another is
unknown. Relative elapsed duration and wall-clock time are different quantities:
when an elapsed timer directly reports insufficient duration, a wall-clock query
cannot make that duration sufficient. Source availability alone is not a reason
to query; identify a genuinely missing fact that could change the decision now.
When no useful permitted query exists, use missing_observation_source=''. Missing
evidence is not proof of a negative state; it simply cannot justify a reminder.
Do not query sources absent from check_sources, including push-only events.
Evidence arrays may be empty when no supporting observation is available.

Example: 'Notify me when the build dashboard shows success': no dashboard reply
yet => false plus the available dashboard source. Reply 'still running' => false,
no query. Reply 'build succeeded' => true with that observation's exact quote.
Example: 'Bring the badge when the shuttle arrives': 'the shuttle arrives later'
=> false, no query if the shuttle is only observable from the scene.

This assessment causes a reminder or a request for information, never execution
or completion. Return compact JSON only and stop.
"""

SCHEMA = _object({"assessments": {"type": "array", "items": _object({
    "reason": SHORT_TEXT,
    "all_conditions_met": {"type": "boolean"},
    "evidence_ids": {"type": "array", "items": {"type": "string", "maxLength": 160}},
    "evidence_quotes": {"type": "array", "items": {"type": "string", "maxLength": 160}},
    "missing_observation_source": {"type": "string", "maxLength": 160},
})}})


class SourceBoundPISEngine(PISEngine):
    POLICY = "sbpm_minimal"

    def fresh(self):
        return type(self)(self.request, self.sources, self.query_budget,
                          self.queryable_sources, self.verify_actions, self.step_query_budget)

    def _compile(self, instruction, intentions, sources):
        self._compiled = compile_changes(self.request, instruction, intentions, sources,
                                         self.triggers, self.instructions, self._error)
        return [change for change, _ in self._compiled]

    def _decide(self, intention, current, available, queryable_sources, budget):
        # Expose only legal host capabilities in the generation contract. This
        # cannot establish semantic relevance, but prevents a missing condition
        # from being expressed as a query to a push-only or already-seen source.
        # Retain runtime checks for providers that do not enforce JSON Schema.
        schema = copy.deepcopy(SCHEMA)
        source_field = schema["properties"]["assessments"]["items"]["properties"]["missing_observation_source"]
        source_field["enum"] = ["", *available]
        value = self.request(ASSESS, {
            "source_bound_specification": intention.action,
            "typed_trigger": self.triggers[intention.id],
            "watched_sources": list(intention.sources),
            "original_instructions": [asdict(self.instructions[i]) for i in intention.instruction_ids],
            "observations": [asdict(o) for o in current],
            "current_scope": self._scope, "check_sources": available,
            "remaining_check_budget": budget,
        }, schema)
        rows = _rows(value, "assessments", schema)
        if len(rows) != 1:
            raise ValueError("Exactly one trigger assessment required")
        row = rows[0]
        by_id = {o.id: o for o in current}
        if len(row["evidence_ids"]) != len(row["evidence_quotes"]):
            raise ValueError("Each evidence ID needs one exact quotation")
        for ref, quote in zip(row["evidence_ids"], row["evidence_quotes"]):
            obs = by_id.get(ref)
            if obs is None or not obs.current or not quote.strip() or quote not in obs.text:
                raise ValueError("Evidence quotation must belong to the referenced current observation")
        source = row["missing_observation_source"]
        if row["all_conditions_met"]:
            if source or not any(by_id[ref].source in intention.sources for ref in row["evidence_ids"]):
                raise ValueError("Reminder needs current watched-source evidence and no missing source")
            return Decision("ACT", intention.id, row["reason"], tuple(dict.fromkeys(row["evidence_ids"])))
        if source:
            if source not in available:
                raise ValueError("Assessment requested an unavailable/exhausted observation source")
            return Decision("CHECK", intention.id, row["reason"], source=source)
        return Decision("WAIT", intention.id, row["reason"])

    def snapshot(self):
        return {**super().snapshot(), "policy_variant": self.POLICY}

    def restore(self, state):
        if not isinstance(state, dict) or state.get("policy_variant") != self.POLICY:
            raise ValueError("Expected source-bound PIS policy snapshot")
        super().restore(state)
