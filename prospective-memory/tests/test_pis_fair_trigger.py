"""Offline contracts for the opt-in fair trigger engine. No inference calls."""

import copy
from dataclasses import replace
import json
import unittest

from prospective_memory.core import Instruction, Observation
from prospective_memory.method.fair_trigger import SourceBoundFairTriggerEngine
from prospective_memory.method.trigger_engine import SourceBoundTriggerEngine
from tests.test_pis_trigger_projection import Provider as ProjectionProvider


PROJECTOR = "scripted-fair-engine:v1;temperature=0;max-tokens=4096"
SOURCES = ("events", "alpha", "beta", "gamma", "clock")
QUERYABLE = ("alpha", "beta", "gamma", "clock")


class Provider(ProjectionProvider):
    def __init__(self):
        super().__init__()
        self.assessment_rows = {}
        self.verdict = "supported"

    def __call__(self, system, payload, schema):
        key = next(iter(schema["properties"]))
        if key in {"assessments", "verdict"}:
            self.calls.append((system, copy.deepcopy(payload), copy.deepcopy(schema)))
            if key == "verdict":
                return {"verdict": self.verdict, "reason": "Scripted source verification"}
            boolean = "trigger_ready_now" if "readiness_question" in payload else "all_conditions_met"
            row = {"reason": "Scripted current-observation judgment", boolean: False, "evidence_ids": [],
                   "missing_observation_source": next(iter(payload["check_sources"]), "")}
            row.update(self.assessment_rows.get(payload["source_bound_specification"], {}))
            return {key: [row]}
        return super().__call__(system, payload, schema)


class FairTriggerTests(unittest.TestCase):
    def engine(self, **kwargs):
        provider = Provider()
        engine = SourceBoundFairTriggerEngine(provider, sources=SOURCES, queryable_sources=QUERYABLE,
                                              projector_id=PROJECTOR, **kwargs)
        return engine, provider

    def register(self, engine, provider, source, *, ready=False):
        number = len(engine.intentions) + 1
        text = f"Move parcel {number} when {source} confirms readiness."
        provider.watched = [source]
        changed = engine.ingest(Instruction(f"request_{number}", text))
        self.assertEqual(len(changed), 1)
        key = changed[0]
        if ready:
            provider.assessment_rows[engine.intentions[key].action] = {
                "trigger_ready_now": True, "evidence_ids": ["e1"], "missing_observation_source": ""}
        return key

    def checks(self, decisions):
        return [d for d in decisions if d.kind == "CHECK"]

    def test_opt_in_policy_default_verifier_unchanged_and_all_rows_get_budget(self):
        engine, provider = self.engine()
        for source in ("alpha", "beta", "gamma"):
            self.register(engine, provider, source)
        selected = [self.checks(engine.tick([]))[0].source for _ in range(6)]
        self.assertEqual(selected, ["alpha", "beta", "gamma"] * 2)
        self.assertEqual(engine.POLICY, "sbpm")
        self.assertFalse(engine.verify_actions)
        assessments = [payload for _, payload, schema in provider.calls if "assessments" in schema["properties"]]
        self.assertEqual(len(assessments), 18)
        self.assertEqual([p["check_sources"] for p in assessments[:3]], [["alpha"], ["beta"], ["gamma"]])
        self.assertEqual({p["remaining_check_budget"] for p in assessments}, {1})
        self.assertEqual(len(engine.fair_checks.snapshot()["offered"]), 6)
        self.assertEqual(engine.fair_checks.snapshot()["queried"], [])
        self.assertFalse(engine.errors)

    def test_act_and_semantic_wait_survive_query_arbitration(self):
        engine, provider = self.engine()
        first = self.register(engine, provider, "alpha")
        actor = self.register(engine, provider, "events", ready=True)
        waiter = self.register(engine, provider, "gamma")
        provider.assessment_rows[engine.intentions[waiter].action] = {"missing_observation_source": ""}
        original = copy.deepcopy(engine.intentions)
        decisions = engine.tick([Observation("cue", "The parcel is ready.")])
        self.assertEqual([(d.intention_id, d.kind) for d in decisions],
                         [(first, "CHECK"), (actor, "ACT"), (waiter, "WAIT")])
        self.assertEqual(decisions[1].evidence_ids, ("cue",))
        self.assertEqual(decisions[2].reason, "Scripted current-observation judgment")
        self.assertEqual(engine.intentions, original)  # no auto-completion
        self.assertEqual(engine.tick([Observation("cue", "The parcel is ready.")])[1].kind, "WAIT")

    def test_shared_and_deferred_proposals_are_explicit_uncertainty(self):
        engine, provider = self.engine()
        for source in ("alpha", "alpha", "beta"):
            self.register(engine, provider, source)
        decisions = engine.tick([])
        self.assertEqual([d.kind for d in decisions], ["CHECK", "WAIT", "WAIT"])
        self.assertIn("Check shared", decisions[1].reason)
        self.assertIn("Check deferred", decisions[2].reason)
        for d in decisions[1:]:
            self.assertIn("trigger unresolved", d.reason)
            self.assertIn("Scripted current-observation judgment", d.reason)
        log = engine.arbitration_log[-1]
        self.assertEqual(len(log["candidates"]), 3)
        self.assertEqual(log["selected_sources"], ["alpha"])
        self.assertEqual(log["deferred_sources"], ["beta"])
        self.assertEqual(log["representatives"], {"alpha": "pm_000001"})

    def test_distinct_proposal_cap_respects_remaining_actual_step_budget(self):
        engine, provider = self.engine(query_budget=3, step_query_budget=2)
        for source in ("alpha", "alpha", "beta", "gamma"):
            self.register(engine, provider, source)
        engine.begin_step("s1")
        self.assertEqual([d.source for d in self.checks(engine.tick([]))], ["alpha", "beta"])
        engine.record_query("gamma")
        self.assertEqual(len(self.checks(engine.tick([]))), 1)
        engine.record_query("gamma")
        self.assertEqual(self.checks(engine.tick([])), [])
        engine.begin_step("s2")
        self.assertEqual(len(self.checks(engine.tick([]))), 2)

    def test_zero_proposal_or_step_budget_does_not_suppress_supported_act(self):
        for kwargs in ({"query_budget": 0}, {"step_query_budget": 0}):
            with self.subTest(kwargs=kwargs):
                engine, provider = self.engine(**kwargs)
                self.register(engine, provider, "alpha")
                self.register(engine, provider, "events", ready=True)
                decisions = engine.tick([Observation("cue", "Ready.")])
                self.assertEqual([d.kind for d in decisions], ["WAIT", "ACT"])
                self.assertEqual(engine.fair_checks.snapshot()["sequence"], 0)

    def hard_clock(self, engine, key, *, days=()):
        trigger = {"days": list(days), "clock_op": "at", "clock_time": "09:00"}
        engine.triggers[key] = trigger
        old = engine.intentions[key]
        engine.intentions[key] = replace(old, condition=old.condition + engine._slot_suffix(trigger))

    def test_required_clock_priority_then_ordinary_source_rotation(self):
        engine, provider = self.engine()
        self.register(engine, provider, "alpha")
        self.register(engine, provider, "beta")
        clock_key = self.register(engine, provider, "clock")
        self.hard_clock(engine, clock_key)
        engine.begin_step("s1")
        decisions = engine.tick([])
        self.assertEqual([d.source for d in self.checks(decisions)], ["clock"])
        self.assertEqual(engine.arbitration_log[-1]["priority_sources"], ["clock"])
        engine.record_query("clock")
        # Once clock evidence exists, it cannot be queried again this observation
        # cycle. A not-yet-due gate is filtered without assessing that intention.
        obs = [Observation("clock_reply", "08:00", "clock")]
        decisions = engine.tick(obs)
        self.assertEqual([d.source for d in self.checks(decisions)], ["alpha"])
        self.assertEqual(engine.arbitration_log[-1]["priority_sources"], [])
        self.assertIn("Outside explicit clock gate", decisions[2].reason)
        self.assertEqual([d.source for d in self.checks(engine.tick(obs))], ["beta"])

    def test_ordinary_clock_check_has_no_automatic_priority(self):
        engine, provider = self.engine()
        self.register(engine, provider, "clock")
        self.register(engine, provider, "alpha")
        self.assertEqual([d.source for d in self.checks(engine.tick([]))], ["alpha"])
        self.assertEqual(engine.arbitration_log[-1]["priority_sources"], [])

    def test_multislot_handoff_keeps_priority_order_and_act_wait_positions(self):
        engine, provider = self.engine(query_budget=2)
        alpha = self.register(engine, provider, "alpha")
        actor = self.register(engine, provider, "events", ready=True)
        beta = self.register(engine, provider, "beta")
        clock = self.register(engine, provider, "clock")
        self.hard_clock(engine, clock)
        decisions = engine.tick([Observation("cue", "Ready.")])
        self.assertEqual(engine.arbitration_log[-1]["selected_sources"], ["clock", "alpha"])
        self.assertEqual([d.source for d in self.checks(decisions)], ["clock", "alpha"])
        self.assertEqual([(d.intention_id, d.kind) for d in decisions],
                         [(clock, "CHECK"), (actor, "ACT"), (beta, "WAIT"), (alpha, "CHECK")])
        self.assertEqual(decisions[1].evidence_ids, ("cue",))
        self.assertIn("trigger unresolved", decisions[2].reason)

    def test_multislot_handoff_follows_fair_rank_not_bank_order(self):
        engine, provider = self.engine(query_budget=2)
        for source in ("gamma", "alpha", "beta"):
            self.register(engine, provider, source)
        expected = [["alpha", "beta"], ["gamma", "alpha"], ["beta", "gamma"]]
        for selected in expected:
            decisions = engine.tick([])
            self.assertEqual(engine.arbitration_log[-1]["selected_sources"], selected)
            self.assertEqual([d.source for d in self.checks(decisions)], selected)

    def test_weekday_gate_and_unusable_current_clock_remain_conservative(self):
        engine, provider = self.engine()
        key = self.register(engine, provider, "clock")
        self.hard_clock(engine, key, days=("Tuesday",))
        self.assertEqual(engine.tick([], scope="Wednesday")[0].kind, "WAIT")
        self.assertEqual(engine.arbitration_log[-1]["candidates"], [])
        self.assertEqual(engine.tick([Observation("bad_clock", "No time available", "clock")],
                                     scope="Tuesday")[0].reason, "Current clock unavailable")
        self.assertNotIn("assessments", provider.keys())

    def test_wrong_repeated_unknown_and_push_only_attempts_preserve_parent_accounting(self):
        engine, provider = self.engine(step_query_budget=5)
        self.register(engine, provider, "alpha")
        self.register(engine, provider, "beta")
        engine.begin_step("s1")
        self.assertEqual(self.checks(engine.tick([]))[0].source, "alpha")
        for source in ("beta", "beta", "imagined", "events"):
            engine.record_query(source)
        self.assertEqual(engine.step_queries, ["beta", "beta", "imagined", "events"])
        self.assertEqual([e["source"] for e in engine.fair_checks.snapshot()["queried"]], ["beta", "beta"])
        self.assertNotIn("imagined", engine.queryable_sources)
        self.assertEqual(self.checks(engine.tick([]))[0].source, "alpha")
        state = engine.fair_checks.snapshot()
        with self.assertRaises(ValueError):
            engine.record_query(None)
        self.assertEqual(engine.fair_checks.snapshot(), state)

    def test_parent_safety_abort_still_records_actual_thirteenth_known_query(self):
        engine, _ = self.engine()
        for _ in range(12):
            engine.record_query("alpha")
        with self.assertRaises(RuntimeError):
            engine.record_query("alpha")
        self.assertEqual(len(engine.step_queries), 13)
        self.assertEqual(len(engine.fair_checks.snapshot()["queried"]), 13)

    def test_current_source_exclusion_and_source_bound_evidence_guards_remain(self):
        for override, obs in [
            ({"missing_observation_source": "alpha"}, [Observation("seen", "Pending", "alpha")]),
            ({"missing_observation_source": "events"}, []),
            ({"missing_observation_source": "beta"}, []),
            ({"trigger_ready_now": True, "missing_observation_source": "", "evidence_ids": ["e1"]},
             [Observation("wrong", "Ready", "beta")]),
            ({"trigger_ready_now": True, "missing_observation_source": "", "evidence_ids": ["forged"]},
             [Observation("right", "Ready", "alpha")]),
        ]:
            with self.subTest(override=override):
                engine, provider = self.engine()
                key = self.register(engine, provider, "alpha")
                provider.assessment_rows[engine.intentions[key].action] = override
                self.assertEqual(engine.tick(obs)[0].kind, "WAIT")
                self.assertTrue(engine.errors)
                self.assertEqual(engine.fair_checks.snapshot()["offered"], [])

    def test_optional_verifier_contract_is_unchanged(self):
        engine, provider = self.engine(verify_actions=True)
        self.register(engine, provider, "events", ready=True)
        provider.verdict = "unsupported"
        result = engine.tick([Observation("cue", "Ready")])
        self.assertEqual(result[0].kind, "WAIT")
        self.assertEqual(result[0].reason, "Source verifier: Scripted source verification")
        self.assertEqual(provider.keys().count("verdict"), 1)
        self.assertEqual(engine.verification_log[0]["verdict"], "unsupported")

    def test_capability_change_only_resets_arbitration_and_records_reset(self):
        engine, provider = self.engine()
        self.register(engine, provider, "alpha")
        engine.begin_step("s1")
        engine.tick([])
        engine.record_query("alpha")
        bank = copy.deepcopy(engine.intentions)
        projections = engine.projections.snapshot()
        old_history = engine.fair_checks.snapshot()
        engine.set_sources(SOURCES, tuple(reversed(QUERYABLE)))
        self.assertEqual(engine.fair_checks.snapshot(), old_history)
        self.assertEqual(len(engine.arbitration_log), 1)
        engine.set_sources(SOURCES, ("alpha", "beta"))
        self.assertEqual(engine.fair_checks.snapshot()["sequence"], 0)
        self.assertEqual(engine.arbitration_log[-1]["event"], "capability_reset")
        self.assertEqual(engine.arbitration_log[-1]["previous_history"], old_history)
        self.assertEqual(engine.intentions, bank)
        self.assertEqual(engine.projections.snapshot(), projections)
        self.assertEqual(engine.step_queries, ["alpha"])
        self.assertEqual((engine.query_budget, engine.step_query_budget), (1, 2))
        self.assertFalse(engine.errors)
        before = engine.snapshot()
        with self.assertRaises(ValueError):
            engine.set_sources(("events",), ())  # would drop an intention's watched source
        self.assertEqual(engine.snapshot(), before)
        restored = engine.fresh()
        restored.restore(json.loads(json.dumps(before)))
        self.assertEqual(restored.snapshot(), engine.snapshot())

    def test_initial_empty_capabilities_are_normal_and_do_not_invoke_callback(self):
        engine = SourceBoundFairTriggerEngine(None, projector_id=PROJECTOR)
        self.assertEqual(engine.arbitration_log, [])
        self.assertEqual(engine.fair_checks.queryable_sources, ())
        engine.set_sources(SOURCES, QUERYABLE)
        self.assertEqual(len(engine.arbitration_log), 1)
        self.assertFalse(engine.errors)
        same = engine.fair_checks
        engine.set_sources(SOURCES, QUERYABLE)
        self.assertIs(engine.fair_checks, same)

    def test_fresh_and_none_callback_restore_resume_fairness_without_calls(self):
        engine, provider = self.engine(projection_batch_size=2)
        for source in ("alpha", "beta", "gamma"):
            self.register(engine, provider, source)
        engine.tick([])
        engine.record_query("gamma")
        state = json.loads(json.dumps(engine.snapshot()))
        count = len(provider.calls)
        fresh = engine.fresh()
        self.assertIsInstance(fresh, SourceBoundFairTriggerEngine)
        self.assertEqual(fresh.intentions, {})
        self.assertEqual(fresh.arbitration_log, [])
        self.assertEqual(fresh.fair_checks.snapshot()["sequence"], 0)
        restored = SourceBoundFairTriggerEngine(None, projector_id=PROJECTOR, projection_batch_size=2)
        restored.restore(state)
        self.assertIsNone(restored.request)
        self.assertEqual(json.loads(json.dumps(restored.snapshot())), state)
        self.assertEqual(len(provider.calls), count)
        self.assertIs(restored.compiler.__self__, restored)
        self.assertIs(restored.matcher.__self__, restored)
        fresh.restore(state)
        self.assertEqual([d.source for d in self.checks(fresh.tick([]))], ["beta"])

    def test_policy_caps_projector_and_fair_snapshot_mismatches_restore_atomically(self):
        engine, provider = self.engine()
        self.register(engine, provider, "alpha")
        engine.tick([])
        original = engine.snapshot()
        mutations = [
            lambda s: s.update(policy_variant="sbpm_no_arbiter"),
            lambda s: s.update(query_budget=True),
            lambda s: s.update(step_query_budget=-1),
            lambda s: s["fair_check_state"].update(queryable_sources=["alpha"]),
            lambda s: s["fair_check_state"].update(sequence=999),
            lambda s: s.update(arbitration_log=[{}]),
            lambda s: s["arbitration_log"][0].update(budget=100),
            lambda s: s["arbitration_log"][0].update(selected_sources=["alpha", "alpha"]),
            lambda s: s["arbitration_log"][0].update(representatives={"alpha": "unknown"}),
            lambda s: s["trigger_projection_cache"]["projector"].update(identity="other-model"),
            lambda s: s.update(trigger_assessor_sha256="wrong"),
        ]
        calls = len(provider.calls)
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                bad = copy.deepcopy(original)
                mutate(bad)
                with self.assertRaises(ValueError):
                    engine.restore(bad)
                self.assertEqual(engine.snapshot(), original)
        self.assertEqual(len(provider.calls), calls)
        other = SourceBoundTriggerEngine(None, projector_id=PROJECTOR)
        with self.assertRaises(ValueError):
            other.restore(original)
        with self.assertRaises(ValueError):
            engine.restore(other.snapshot())


if __name__ == "__main__":
    unittest.main()
