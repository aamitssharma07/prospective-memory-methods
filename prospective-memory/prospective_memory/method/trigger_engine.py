"""Opt-in ablation: source-bound V3 plus cached trigger-only views.

Selected explicitly as sbpm_no_arbiter; other policies are unchanged.
Projections are fallible interpretations, not evidence, action replacements or
completion acknowledgments.
The caller owns transport, model/config identity and raw-response logging.
"""

import copy
from dataclasses import asdict
import hashlib
import json

from ..core import Decision
from ..llm import _rows
from ..method.source_bound_v3 import REFERENCE_ASSESS, REFERENCE_SCHEMA, SourceBoundV3Engine
from ..method.projection_cache import TriggerProjectionCache


TRIGGER_ASSESS = """Answer readiness_question for ONE requested future action.
action_to_perform_next describes what should happen NEXT if the cue is satisfied;
do not require that action to have already happened. trigger_ready_now answers
the readiness question, NOT whether the requested action was completed.
The projected fields are cached, fallible interpretations of the original request,
never observations or evidence. Original instructions remain authoritative: keep
all retained prerequisites and accepted revisions, even if the view omitted one.
Use only current observations to support readiness. Nothing executes here.

""" + REFERENCE_ASSESS.replace("all_conditions_met", "trigger_ready_now")

TRIGGER_SCHEMA = copy.deepcopy(REFERENCE_SCHEMA)
_ROW = TRIGGER_SCHEMA["properties"]["assessments"]["items"]
_ROW["properties"] = {("trigger_ready_now" if key == "all_conditions_met" else key): field
                       for key, field in _ROW["properties"].items()}
_ROW["required"] = ["trigger_ready_now" if key == "all_conditions_met" else key for key in _ROW["required"]]
del _ROW


def _fingerprint(prompt, schema):
    text = json.dumps({"prompt": prompt, "schema": schema}, sort_keys=True,
                      ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SourceBoundTriggerEngine(SourceBoundV3Engine):
    """Opt-in trigger projection experiment, not a claim of improved performance.

    Registration/revision can add one projection call per changed-record batch;
    ticks never generate or retry projections. Unsupported/error/missing/stale
    projections use the inherited V3 assessor, with one assessment per eligible
    intention as before. Existing optional ACT verification defaults to false;
    this class adds no verifier. Model/config changes require a new projector_id.
    A batch-size limit is not a token budget or a semantic-fidelity guarantee.
    """

    POLICY = "sbpm_no_arbiter"

    def __init__(self, request, sources=("events",), query_budget=1,
                 queryable_sources=(), verify_actions=False, step_query_budget=2,
                 max_assess_workers=1, skip_unevidenced=False, reuse_stable_waits=False, assess_batch_size=1, *, projector_id, projection_batch_size=4):
        self.projections = TriggerProjectionCache(request, projector_id=projector_id,
                                                  batch_size=projection_batch_size)
        self._projector_id = projector_id
        self._trigger_prompt, self._trigger_schema = TRIGGER_ASSESS, copy.deepcopy(TRIGGER_SCHEMA)
        self._trigger_fingerprint = _fingerprint(self._trigger_prompt, self._trigger_schema)
        super().__init__(request, sources, query_budget, queryable_sources,
                         verify_actions, step_query_budget, max_assess_workers, skip_unevidenced,
                         reuse_stable_waits, assess_batch_size)

    def fresh(self):
        return type(self)(self.request, self.sources, self.query_budget, self.queryable_sources,
                          self.verify_actions, self.step_query_budget, self.max_assess_workers,
                          self.skip_unevidenced, self.reuse_stable_waits, self.assess_batch_size,
                          projector_id=self._projector_id,
                          projection_batch_size=self.projections.batch_size)

    def ingest(self, instruction):
        changed = super().ingest(instruction)
        for key in changed:
            if self.intentions[key].status in {"cancelled", "completed"}:
                self.projections.invalidate(key)
        if any(self.intentions[key].status in {"pending", "attempted"} for key in changed):
            previous_errors = len(self.projections.errors)
            try:
                # After accepted changes, never a speculative compiler proposal.
                self.projections.refresh(list(self.intentions.values()), self.instructions)
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                for key in changed:
                    self.projections.invalidate(key)
                self._error("trigger_projection_refresh", exc)
            for error in self.projections.errors[previous_errors:]:
                self._error("trigger_" + error["phase"], error["error"])
        return changed

    def acknowledge(self, intention_id, outcome):
        super().acknowledge(intention_id, outcome)
        # Host-confirmed active status changes preserve static meaning, without
        # inference. Closure or any changed source/semantics still invalidates.
        self.projections.rebind_status(self.intentions[intention_id], self.instructions)

    def _decide(self, intention, current, available, queryable_sources, budget):
        try:
            view = self.projections.get(intention, self.instructions)
        except (ValueError, TypeError, AttributeError) as exc:
            self._error("trigger_projection_binding", exc)
            view = None
        if view is None or view.status != "projected":
            return super()._decide(intention, current, available, queryable_sources, budget)

        references = {f"e{index + 1}": observation for index, observation in enumerate(current)}
        schema = copy.deepcopy(self._trigger_schema)
        fields = schema["properties"]["assessments"]["items"]["properties"]
        fields["missing_observation_source"]["enum"] = ["", *available]
        fields["evidence_ids"]["items"]["enum"] = list(references) or [""]
        value = self.request(self._trigger_prompt, {
            "readiness_question": view.readiness_question,
            "action_to_perform_next": view.action_to_perform_next,
            "projection_binding": {"intention_id": view.intention_id, "revision": view.revision,
                                   "source_instruction_ids": list(view.source_instruction_ids)},
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
        if row["trigger_ready_now"]:
            if source or not any(by_id[ref].source in intention.sources for ref in row["evidence_ids"]):
                raise ValueError("Reminder needs current watched-source evidence and no missing source")
            return Decision("ACT", intention.id, row["reason"],
                            tuple(dict.fromkeys(by_id[ref].id for ref in row["evidence_ids"])))
        if source:
            if source not in available:
                raise ValueError("Assessment requested an unavailable/exhausted observation source")
            return Decision("CHECK", intention.id, row["reason"], source=source)
        return Decision("WAIT", intention.id, row["reason"])

    def snapshot(self):
        # Never serialize an old derived view against a directly changed source.
        for entry in self.projections.snapshot()["entries"]:
            key = entry["projection"]["intention_id"]
            if key not in self.intentions:
                self.projections.invalidate(key)
            else:
                self.projections.get(self.intentions[key], self.instructions)
        return {**super().snapshot(), "trigger_projection_cache": self.projections.snapshot(),
                "trigger_assessor_sha256": self._trigger_fingerprint}

    def restore(self, state):
        if (not isinstance(state, dict) or state.get("policy_variant") != self.POLICY
                or state.get("trigger_assessor_sha256") != self._trigger_fingerprint
                or "trigger_projection_cache" not in state):
            raise ValueError("Expected compatible trigger-projection policy snapshot")
        fresh = self.fresh()
        if fresh._trigger_fingerprint != self._trigger_fingerprint:
            raise ValueError("Trigger assessment definition changed; construct a new engine")
        # All mutations occur on a temporary engine until BOTH states agree.
        SourceBoundV3Engine.restore(fresh, state)
        fresh.projections.restore(state["trigger_projection_cache"])
        for entry in fresh.projections.snapshot()["entries"]:
            key = entry["projection"]["intention_id"]
            intention = fresh.intentions.get(key)
            if intention is None or fresh.projections.get(intention, fresh.instructions) is None:
                raise ValueError("Projection cache disagrees with restored intention/source state")
        self.__dict__.update(fresh.__dict__)
        self.compiler, self.matcher = self._compile, self._assess
