"""Opt-in V5: cached trigger views with source-fair CHECK proposal allocation.

No host/runner selects this policy implicitly. The inherited compiler, readiness
assessor, evidence boundaries, deduplication, lifecycle and optional ACT verifier
are unchanged. This policy removes bank-order allocation of CHECK slots: all
eligible intentions can propose a query before source-level arbitration.

An unselected or shared CHECK becomes an explicit uncertainty WAIT, never a
claim that its trigger is false. One representative per selected source is sent
to the host; the diagnostic log retains every original CHECK and its reason.
Offers do not execute queries. The host still executes, reports actual attempts,
supplies current observations, advances steps and acknowledges completed actions.

This can improve source coverage, not guarantee useful queries, faithful source
metadata, semantic accuracy, actor uptake or better benchmark scores. A genuinely
missing hard clock gate gets explicit priority; ordinary clock requests do not.
"""

import copy
from dataclasses import asdict

from ..core import Decision
from ..method.fair_checks import FairCheckArbiter
from ..llm import SHORT_TEXT, _object
from ..baselines.pis import DAYS, VERIFY, clock_minutes
from ..method.trigger_engine import SourceBoundTriggerEngine


class SourceBoundFairTriggerEngine(SourceBoundTriggerEngine):
    POLICY = "sbpm"

    def __init__(self, request, sources=("events",), query_budget=1,
                 queryable_sources=(), verify_actions=False, step_query_budget=2,
                 max_assess_workers=1, skip_unevidenced=False, reuse_stable_waits=False, assess_batch_size=1, *, projector_id, projection_batch_size=4):
        self.fair_checks = None
        self.arbitration_log = []
        super().__init__(request, sources, query_budget, queryable_sources,
                         verify_actions, step_query_budget, max_assess_workers, skip_unevidenced,
                         reuse_stable_waits, assess_batch_size, projector_id=projector_id,
                         projection_batch_size=projection_batch_size)

    def set_sources(self, sources, queryable_sources=None):
        # Parent validation is atomic; invalid capabilities cannot reset history.
        super().set_sources(sources, queryable_sources)
        registry = tuple(sorted(self.queryable_sources))
        if self.fair_checks is None:
            # Empty initial capabilities are a normal host setup, not an error.
            self.fair_checks = FairCheckArbiter(registry)
        elif self.fair_checks.queryable_sources != registry:
            previous = self.fair_checks.snapshot()
            self.fair_checks = FairCheckArbiter(registry)
            self.arbitration_log.append({
                "event": "capability_reset", "step_id": self.step_id,
                "queryable_sources": list(registry), "previous_history": previous,
            })

    def record_query(self, source):
        # Parent counts wrong, repeated and even unknown host attempts. Such an
        # attempt must not advertise a new capability to the fair scheduler.
        try:
            super().record_query(source)
        finally:
            # Parent records the 13th attempt before its safety abort. Preserve
            # that actual known-source attempt as well; malformed values are not
            # recorded by either layer.
            if isinstance(source, str) and source in self.queryable_sources:
                self.fair_checks.record_query(source)

    def _assess(self, intentions, observations, sources, queryable_sources=()):
        current = [o for o in observations if o.current]
        clock_values = {clock_minutes(o.text) for o in current if o.source == "clock"}
        clock_values.discard(None)
        now = next(iter(clock_values)) if len(clock_values) == 1 else None
        observed = {o.source for o in current}
        budget = min(self.query_budget, max(0, self.step_query_budget - len(self.step_queries)))
        decisions, candidates, board, priority = [], [], [], set()
        for intention in intentions:
            trigger = self.triggers[intention.id]
            if trigger["days"] and self._scope in DAYS and self._scope not in trigger["days"]:
                decisions.append(Decision("WAIT", intention.id, "Outside explicit weekday gate"))
                continue
            if trigger["clock_op"] != "none":
                due = clock_minutes(trigger["clock_time"])
                if now is None:
                    if ("clock" in queryable_sources and "clock" in intention.sources
                            and "clock" not in observed):
                        d = Decision("CHECK", intention.id, "Need current clock", source="clock")
                        decisions.append(d)
                        candidates.append(d)
                        priority.add("clock")
                    else:
                        decisions.append(Decision("WAIT", intention.id, "Current clock unavailable"))
                    continue
                if (trigger["clock_op"] == "at" and now != due) or (
                        trigger["clock_op"] == "not_before" and now < due):
                    decisions.append(Decision("WAIT", intention.id, "Outside explicit clock gate"))
                    continue
            board.append(intention.id)
            # Do not spend the shared proposal budget in bank order. Each row
            # sees the same remaining cap, but only its own unseen capabilities.
            available = ([s for s in queryable_sources if s in intention.sources and s not in observed]
                         if budget else [])
            try:
                d = self._decide(intention, current, available, queryable_sources, budget)
                if (not isinstance(d, Decision) or d.kind not in {"ACT", "CHECK", "WAIT"}
                        or d.intention_id != intention.id):
                    raise ValueError("Invalid decision or different intention")
                if d.kind == "CHECK":
                    if d.source not in available or not isinstance(d.reason, str) or d.evidence_ids != ():
                        raise ValueError("Invalid or exhausted check source/proposal")
                if d.kind == "ACT" and self.verify_actions:
                    # Identical opt-in verifier contract to PISEngine._assess.
                    verdict_schema = _object({"verdict": {"type": "string", "enum": ["supported", "unsupported"]},
                                              "reason": SHORT_TEXT})
                    verdict = self.request(VERIFY, {
                        "intention": asdict(intention), "proposal": asdict(d),
                        "original_instructions": [asdict(self.instructions[k]) for k in intention.instruction_ids],
                        "observations": [asdict(o) for o in current], "current_scope": self._scope,
                    }, verdict_schema)
                    if (not isinstance(verdict, dict) or set(verdict) != {"verdict", "reason"}
                            or verdict["verdict"] not in {"supported", "unsupported"}
                            or not isinstance(verdict["reason"], str)):
                        raise ValueError("Invalid verification")
                    self.verification_log.append({"intention_id": intention.id, **verdict})
                    if verdict["verdict"] != "supported":
                        d = Decision("WAIT", intention.id, "Source verifier: " + verdict["reason"])
                decisions.append(d)
                if d.kind == "CHECK":
                    candidates.append(d)
            except Exception as exc:
                self._error("pis_decide", exc)
                decisions.append(Decision("WAIT", intention.id, "Unresolved decision error"))

        selection = self.fair_checks.arbitrate(candidates, budget=budget, priority_sources=priority)
        representatives = {group.source: group.decisions[0].intention_id for group in selection.selected}
        final = []
        for d in decisions:
            if d.kind != "CHECK" or representatives.get(d.source) == d.intention_id:
                final.append(d)
            elif d.source in representatives:
                final.append(Decision("WAIT", d.intention_id,
                                      "Check shared with another intention; trigger unresolved. " + d.reason))
            else:
                final.append(Decision("WAIT", d.intention_id,
                                      "Check deferred by shared query budget; trigger unresolved. " + d.reason))
        # Preserve ACT/WAIT positions and relative order, but do not undo source
        # priority/fairness at handoff by emitting CHECKs in bank insertion order.
        ranked_checks = iter(group.decisions[0] for group in selection.selected)
        final = [next(ranked_checks) if d.kind == "CHECK" else d for d in final]
        self.arbitration_log.append({
            "event": "selection", "scope": self._scope, "step_id": self.step_id,
            "queryable_sources": sorted(queryable_sources), "budget": budget,
            "candidates": [{**asdict(d), "evidence_ids": list(d.evidence_ids)} for d in candidates],
            "priority_sources": sorted(priority),
            "selected_sources": list(selection.selected_sources),
            "deferred_sources": list(selection.deferred_sources), "representatives": representatives,
        })
        self.board_log.append({"scope": self._scope, "active": len(intentions), "eligible": board,
                               "checked_sources": sorted(selection.selected_sources)})
        return final

    def snapshot(self):
        return {**super().snapshot(), "fair_check_state": self.fair_checks.snapshot(),
                "arbitration_log": copy.deepcopy(self.arbitration_log)}

    @staticmethod
    def _validate_log(log, query_budget, step_query_budget):
        """Validate diagnostic structure, not replayed semantic judgments."""
        if not isinstance(log, list):
            raise ValueError("Invalid arbitration log")
        for entry in log:
            if not isinstance(entry, dict) or not isinstance(entry.get("step_id"), str):
                raise ValueError("Invalid arbitration event")
            checker = FairCheckArbiter(entry.get("queryable_sources"))
            if list(checker.queryable_sources) != entry["queryable_sources"]:
                raise ValueError("Noncanonical arbitration capabilities")
            if entry.get("event") == "capability_reset":
                if set(entry) != {"event", "step_id", "queryable_sources", "previous_history"}:
                    raise ValueError("Invalid arbitration reset")
                previous = entry["previous_history"]
                old = FairCheckArbiter(previous["queryable_sources"])
                old.restore(previous)
                if old.queryable_sources == checker.queryable_sources:
                    raise ValueError("Arbitration reset did not change capabilities")
                continue
            fields = {"event", "scope", "step_id", "queryable_sources", "budget", "candidates",
                      "priority_sources", "selected_sources", "deferred_sources", "representatives"}
            if (set(entry) != fields or entry["event"] != "selection"
                    or not isinstance(entry["scope"], str) or type(entry["budget"]) is not int
                    or not 0 <= entry["budget"] <= min(query_budget, step_query_budget)
                    or not isinstance(entry["candidates"], list)):
                raise ValueError("Invalid arbitration selection")
            candidates = []
            for row in entry["candidates"]:
                if not isinstance(row, dict) or not isinstance(row.get("evidence_ids"), (list, tuple)):
                    raise ValueError("Invalid logged CHECK")
                candidates.append(Decision(**{**row, "evidence_ids": tuple(row["evidence_ids"])}))
            # Validates known CHECK sources, duplicates, reasons and priorities;
            # selection order is historical diagnostic data, not recomputed from
            # empty history or asserted to establish any trigger semantics.
            checker.arbitrate(candidates, budget=0, priority_sources=entry["priority_sources"])
            selected, deferred = entry["selected_sources"], entry["deferred_sources"]
            if (not isinstance(selected, list) or not isinstance(deferred, list)
                    or any(not isinstance(s, str) for s in selected + deferred)
                    or len(set(selected + deferred)) != len(selected + deferred)
                    or set(selected + deferred) != {d.source for d in candidates}
                    or len(selected) > entry["budget"]
                    or not isinstance(entry["representatives"], dict)):
                raise ValueError("Invalid logged source partition")
            expected = {source: min(d.intention_id for d in candidates if d.source == source)
                        for source in selected}
            if entry["representatives"] != expected:
                raise ValueError("Invalid logged CHECK representatives")

    def restore(self, state):
        if (not isinstance(state, dict) or state.get("policy_variant") != self.POLICY
                or "fair_check_state" not in state or "arbitration_log" not in state):
            raise ValueError("Expected fair-trigger policy snapshot")
        fresh = self.fresh()
        try:
            # Parent restore validates source-bound bank/projections/config on a
            # temporary instance. No provider calls occur, even with request=None.
            SourceBoundTriggerEngine.restore(fresh, state)
            arbiter = FairCheckArbiter(fresh.queryable_sources)
            arbiter.restore(state["fair_check_state"])
            self._validate_log(state["arbitration_log"], fresh.query_budget, fresh.step_query_budget)
            fresh.fair_checks = arbiter
            fresh.arbitration_log = copy.deepcopy(state["arbitration_log"])
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("Malformed fair-trigger snapshot") from exc
        self.__dict__.update(fresh.__dict__)
        self.compiler, self.matcher = self._compile, self._assess
