"""Opt-in layout-unit registration with the validated source-bound assessor.

Visiting every source unit makes omission visible; it is not a guarantee that
the model classifies every obligation correctly or that units are semantic atoms.
"""

import copy
from dataclasses import asdict

from ..core import Decision
from ..llm import _rows
from ..method.source_bound import ASSESS, SCHEMA, SourceBoundPISEngine


REFERENCE_ASSESS = ASSESS.replace(
    "cite exact short quotes from current observations\nin parallel evidence_ids/evidence_quotes arrays",
    "cite the exact IDs of the current observations that support the trigger\nin evidence_ids (code retains their original text; do not rewrite quotations)",
).replace("Evidence arrays may be empty", "The evidence_ids array may be empty").replace(
    "Clear paraphrases count.",
    "Clear paraphrases and ordinary semantic entailment count. Do not confuse "
    "different wording with missing evidence or invent extra proof requirements. "
    "For example, a courier handing over the parcel supports a delivery trigger "
    "even without the word 'delivered'; a courier planning to hand it over does not. "
    "Evaluate the stated facts and their meaning, not exact-word overlap.",
)


REFERENCE_SCHEMA = copy.deepcopy(SCHEMA)
del REFERENCE_SCHEMA["properties"]["assessments"]["items"]["properties"]["evidence_quotes"]
REFERENCE_SCHEMA["properties"]["assessments"]["items"]["required"].remove("evidence_quotes")


BATCH_ASSESS = REFERENCE_ASSESS + """

You are judging SEVERAL pending intentions against the SAME observations.
Return one assessment per listed intention, in the same order, with exactly as
many rows as there are intentions. Judge each intention only against its own
typed trigger and its own watched sources; never let one intention's evidence
satisfy another. None of these intentions has a source it may request, so
missing_observation_source must be the empty string for every row.
"""


class SourceBoundV3Engine(SourceBoundPISEngine):
    POLICY = "sbpm_no_projection"

    def _compile(self, instruction, intentions, sources):
        from ..method.registration import compile_changes
        self._compiled = compile_changes(self.request, instruction, intentions, sources,
                                         self.triggers, self.instructions, self._error)
        return [change for change, _ in self._compiled]

    def _decide(self, intention, current, available, queryable_sources, budget):
        # Identity references avoid lossy reproduction of source text under
        # generation-length constraints. Valid IDs prove provenance, NOT that
        # the cited evidence entails every trigger; that remains a model judgment.
        references = {f"e{index + 1}": observation for index, observation in enumerate(current)}
        schema = copy.deepcopy(REFERENCE_SCHEMA)
        fields = schema["properties"]["assessments"]["items"]["properties"]
        fields["missing_observation_source"]["enum"] = ["", *available]
        # Local e1/e2/... handles keep grammar cache keys stable across original
        # host observation IDs. They are mapped back before engine validation.
        fields["evidence_ids"]["items"]["enum"] = list(references) or [""]
        value = self.request(REFERENCE_ASSESS, {
            "source_bound_specification": intention.action,
            "typed_trigger": self.triggers[intention.id],
            "watched_sources": list(intention.sources),
            "original_instructions": [asdict(self.instructions[i]) for i in intention.instruction_ids],
            "observations": [{**asdict(o), "id": ref} for ref, o in references.items()],
            "current_scope": self._scope, "check_sources": available,
            "remaining_check_budget": budget,
        }, schema)
        rows = _rows(value, "assessments", schema)
        if len(rows) != 1:
            raise ValueError("Exactly one trigger assessment required")
        row = rows[0]
        by_id = {ref: o for ref, o in references.items() if o.current}
        if any(ref not in by_id for ref in row["evidence_ids"]):
            raise ValueError("Evidence IDs must refer to current observations")
        source = row["missing_observation_source"]
        if row["all_conditions_met"]:
            if source or not any(by_id[ref].source in intention.sources for ref in row["evidence_ids"]):
                raise ValueError("Reminder needs current watched-source evidence and no missing source")
            return Decision("ACT", intention.id, row["reason"],
                            tuple(dict.fromkeys(by_id[ref].id for ref in row["evidence_ids"])))
        if source:
            if source not in available:
                raise ValueError("Assessment requested an unavailable/exhausted observation source")
            return Decision("CHECK", intention.id, row["reason"], source=source)
        return Decision("WAIT", intention.id, row["reason"])

    def _decide_batch(self, items, current, queryable_sources):
        """One prompt for several intentions that share the same observations."""
        references = {f"e{index + 1}": observation for index, observation in enumerate(current)}
        schema = copy.deepcopy(REFERENCE_SCHEMA)
        fields = schema["properties"]["assessments"]["items"]["properties"]
        # Deferred intentions have no queryable source, so no row may request one.
        fields["missing_observation_source"]["enum"] = [""]
        fields["evidence_ids"]["items"]["enum"] = list(references) or [""]
        payload = {
            "observations": [{**asdict(o), "id": ref} for ref, o in references.items()],
            "current_scope": self._scope,
            "intentions": [{
                "position": position + 1,
                "source_bound_specification": intention.action,
                "typed_trigger": self.triggers[intention.id],
                "watched_sources": list(intention.sources),
                "original_instructions": [asdict(self.instructions[i])
                                          for i in intention.instruction_ids],
            } for position, (intention, _) in enumerate(items)],
        }
        rows = _rows(self.request(BATCH_ASSESS, payload, schema), "assessments", schema)
        if len(rows) != len(items):
            raise ValueError("Batched assessment returned the wrong number of rows")
        by_id = {ref: o for ref, o in references.items() if o.current}
        decisions = []
        for (intention, _), row in zip(items, rows):
            if any(ref not in by_id for ref in row["evidence_ids"]):
                raise ValueError("Evidence IDs must refer to current observations")
            if row["missing_observation_source"]:
                raise ValueError("Batched rows cannot request a source")
            if row["all_conditions_met"]:
                if not any(by_id[ref].source in intention.sources for ref in row["evidence_ids"]):
                    raise ValueError("Reminder needs current watched-source evidence")
                decisions.append(Decision("ACT", intention.id, row["reason"],
                                          tuple(dict.fromkeys(by_id[ref].id
                                                              for ref in row["evidence_ids"]))))
            else:
                decisions.append(Decision("WAIT", intention.id, row["reason"]))
        return decisions
