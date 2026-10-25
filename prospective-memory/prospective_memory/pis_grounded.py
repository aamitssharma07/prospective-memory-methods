"""Opt-in evidence-first PIS pilot; no benchmark rules or automatic execution.

The model assesses evidence, code maps that assessment to a proposal. A second
semantic call reviews each proposed memory mutation before it is applied. These
are safeguards, not a proof of language understanding or benchmark improvement.
"""

import copy
from dataclasses import asdict
import re

from .core import Decision
from .llm import SHORT_TEXT, _object, _rows
from .baselines.pis import PISEngine


REVIEW = """Review ONE proposed memory change against the current original message.
Return supported only if the message genuinely requests this addition, revision,
or cancellation, and the complete action, condition, recurrence, day and sources
are faithful. Observations, menu choices and mere mentions are not new requests.
A new unrelated request must not replace an existing obligation. For updates,
the target must be the SAME obligation and unchanged constraints must survive.
Use the target's original messages to check identity and retained prerequisites.
The supporting quote is necessary but not proof of semantic correctness.
Never invent a time for a meal/event. Independent recurring occasions are not
simultaneous prerequisites. Source names identify possible evidence providers,
not additional conditions. Do not demand calendar confirmation of a schedule
already specified by the user. When a clock slot is none, explicit time language
may remain in the full condition for semantic assessment. Reject ambiguous or
unsupported changes. Return one reviews row; unsupported changes preserve the
previous store and the original input, rather than silently overwriting it.
"""

ASSESS = """Assess whether ONE intention's complete trigger is satisfied NOW.
Read its original instructions and chronological revisions as the specification;
read current observations as evidence. Do not use a request as evidence that its
trigger occurred. If the typed summary contradicts the originals, report unknown.
The code has checked explicit day/time gates; those facts alone do not prove
other prerequisites. Check every conjunction, exclusion, entity and threshold.
Accept direct statements and clear paraphrases; do not require identical words.
Sources are possible evidence providers, NOT a checklist that must all be queried.
A user-specified schedule plus a matching current clock does not require a
calendar query unless the original instruction explicitly requires that too.

Return one assessments row:
- satisfied: all trigger conditions hold. Cite exact nonempty quotations from
  current observations: parallel evidence_ids and evidence_quotes arrays with
  one exact short quote per ID. missing_source must be ''.
- not_satisfied: current evidence establishes a required condition is false;
  cite that evidence and use missing_source=''.
- unknown: evidence is missing, ambiguous or conflicts with the original request.
  Set missing_source to an exact check_sources entry only if a query could resolve
  the missing information now; otherwise ''. Never request an observed, unavailable
  or budget-exhausted source. Push-only events require waiting, not a fake query.
Return an assessment, not WAIT/CHECK/ACT. Code maps satisfied to an ACT reminder,
unknown with an available source to CHECK, and other cases to WAIT. None executes
an action or proves execution success. Do not reinterpret unsupported CHECK as ACT.
"""


class GroundedPISEngine(PISEngine):
    POLICY = "pis_grounded_v1"

    def fresh(self):
        return type(self)(self.request, self.sources, self.query_budget,
                          self.queryable_sources, self.verify_actions, self.step_query_budget)

    def _review_change(self, row, instruction, pending):
        row = copy.deepcopy(row)
        quote = row["evidence_quote"]
        if not quote.strip() or quote not in instruction.text:
            raise ValueError("Change needs an exact current-message quotation")
        targets = {i.id: i for i in pending}
        target = targets.get(row["target_id"])
        if row["op"] != "register" and target is None:
            raise ValueError("Update needs a known pending target")
        if row["op"] == "register" and row["target_id"]:
            raise ValueError("Registration must not target an existing record")

        # A conservative literal guard: unsupported/relative time expressions
        # stay semantic; never infer a fixed breakfast/dinner hour. Use the full
        # source quote as condition so removing a bad slot does not lose its cue.
        self._validate_trigger({k: row[k] for k in ("days", "clock_op", "clock_time")})
        if row["clock_op"] != "none":
            times = {f"{int(h):02d}:{m}" for h, m in
                     re.findall(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", quote)}
            if row["clock_time"] not in times:
                row.update(clock_op="none", clock_time="", condition=quote)
                self._error("clock_guard", "Unsupported hard clock removed; original quote retained")

        history = ([asdict(self.instructions[i]) for i in target.instruction_ids]
                   if target else [])
        schema = _object({"reviews": {"type": "array", "items": _object({
            "verdict": {"type": "string", "enum": ["supported", "unsupported"]},
            "reason": SHORT_TEXT,
        })}})
        try:
            value = self.request(REVIEW, {
                "instruction": asdict(instruction), "proposed_change": row,
                "target": ({**asdict(target), **self.triggers[target.id]} if target else None),
                "target_original_instructions": history,
                "available_sources": list(self.sources),
            }, schema)
        except Exception as exc:
            # A review failure must not discard valid sibling registrations.
            raise ValueError("Memory-change review failed: " + str(exc)) from exc
        reviews = _rows(value, "reviews", schema)
        if len(reviews) != 1:
            raise ValueError("Exactly one memory-change review required")
        if reviews[0]["verdict"] != "supported":
            self._error("change_review", reviews[0]["reason"])
            return None
        return row

    def _decide(self, intention, current, available, queryable_sources, budget):
        schema = _object({"assessments": {"type": "array", "items": _object({
            "state": {"type": "string", "enum": ["satisfied", "not_satisfied", "unknown"]},
            "reason": SHORT_TEXT,
            "evidence_ids": {"type": "array", "items": {"type": "string", "maxLength": 160}},
            "evidence_quotes": {"type": "array", "items": {"type": "string", "maxLength": 160}},
            # Stable schema; available/budget/source membership checked below.
            "missing_source": {"type": "string", "maxLength": 160},
        })}})
        value = self.request(ASSESS, {
            "intention": {**asdict(intention), **self.triggers[intention.id]},
            "original_instructions": [asdict(self.instructions[i]) for i in intention.instruction_ids],
            "observations": [asdict(o) for o in current],
            "current_scope": self._scope, "check_sources": available,
            "remaining_check_budget": budget,
        }, schema)
        rows = _rows(value, "assessments", schema)
        if len(rows) != 1:
            raise ValueError("Exactly one evidence assessment required")
        row = rows[0]
        by_id = {o.id: o for o in current}
        ids = []
        if len(row["evidence_ids"]) != len(row["evidence_quotes"]):
            raise ValueError("Each evidence ID needs one quotation")
        for ref, quote in zip(row["evidence_ids"], row["evidence_quotes"]):
            observation = by_id.get(ref)
            if (observation is None or not observation.current or not quote.strip()
                    or quote not in observation.text):
                raise ValueError("Evidence needs an exact quotation from a current observation")
            ids.append(observation.id)
        source = row["missing_source"]
        if row["state"] == "satisfied":
            if source or not ids or not any(by_id[i].source in intention.sources for i in ids):
                raise ValueError("Satisfied requires source-grounded evidence and no missing source")
            return Decision("ACT", intention.id, row["reason"], tuple(dict.fromkeys(ids)))
        if row["state"] == "not_satisfied":
            if source or not ids:
                raise ValueError("Not-satisfied requires evidence and no requested source")
        elif source:
            if source not in available:
                raise ValueError("Unknown assessment requested an unavailable/exhausted source")
            return Decision("CHECK", intention.id, row["reason"], source=source)
        return Decision("WAIT", intention.id, row["reason"])

    def snapshot(self):
        return {**super().snapshot(), "policy_variant": self.POLICY}

    def restore(self, state):
        if not isinstance(state, dict) or state.get("policy_variant") != self.POLICY:
            raise ValueError("Expected grounded PIS policy snapshot")
        super().restore(state)
