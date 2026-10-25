"""Candidate grounding, fairness and persistence contracts without inference."""

import copy
import json
import unittest

from run import ROOT
from helper_probe import CASES, fixture_engine
from improved_engine import BoundedPriorityArbiter, ImprovedTriggerEngine, compiler_slot_schema, verbatim_spans
from prospective_memory.core import Decision, Instruction, Observation
from tests.test_pis_fair_trigger import Provider as BaseProvider
from prospective_memory.baselines.pis_registration import _specification_schema


class Provider(BaseProvider):
    def __call__(self, system, payload, schema):
        if "target_matches" in schema["properties"]:
            self.calls.append((system, copy.deepcopy(payload), copy.deepcopy(schema)))
            return {"target_matches": [{"update_action_quote": payload["update_quote"],
                "pending_action_quote": payload["pending_action"],
                "same_obligation": getattr(self, "target_same_obligation", True),
                "reason": "Scripted independent action comparison"}]}
        if "provider_comparisons" in schema["properties"]:
            self.calls.append((system, copy.deepcopy(payload), copy.deepcopy(schema)))
            return {"provider_comparisons": [{"reply_action_quote": payload["focus_unit"]["text"],
                "resolved_reply_action": "Scripted requested action", "resolved_pending_action": "",
                "pending_action_quote": "", "pending_id": "", "relationship": "distinct_request",
                "reason": "Scripted independent new request"}]}
        if "target_resolutions" in schema["properties"]:
            self.calls.append((system, copy.deepcopy(payload), copy.deepcopy(schema)))
            return {"target_resolutions": [{"reason": "Scripted resolution", "target_id": self.target}]}
        return super().__call__(system, payload, schema)


class ImprovedEngineTests(unittest.TestCase):
    def test_grounding_payload_preserves_condition_and_receipt_scope(self):
        for projected in (True, False):
            provider = Provider()
            case = CASES[0]
            engine = fixture_engine(case, provider, "scripted", projected=projected)
            provider.assessment_rows[case["action"]] = {
                "trigger_ready_now" if projected else "all_conditions_met": True,
                "evidence_ids": ["e1"], "missing_observation_source": ""}
            decision = engine.tick([Observation("cue", "The service cart has reached the door.")], "Friday")[0]
            self.assertEqual(decision.kind, "ACT")
            system, payload, schema = provider.calls[-1]
            self.assertEqual(payload["selected_trigger_condition"], case["condition"])
            self.assertEqual(payload["permitted_days"], ["Friday"])
            self.assertNotIn("weekdays=", payload["selected_trigger_condition"])
            self.assertEqual(payload["observation_context"]["e1"]["receipt_scope"], "Friday")
            self.assertIn("not_inferred", payload["observation_context"]["e1"]["occurrence_time"])
            self.assertIn("need not repeat that day", system)
            self.assertNotIn("expected", json.dumps(payload))
            self.assertEqual(schema["properties"]["assessments"]["maxItems"], 1)
            self.assertEqual(schema["properties"]["assessments"]["items"]["properties"]["evidence_ids"]["maxItems"], 1)

    def test_wrong_day_and_clock_gate_prevent_assessment(self):
        for case in (CASES[1], CASES[10]):
            provider = Provider()
            engine = fixture_engine(case, provider, "scripted")
            count = len(provider.calls)
            decisions = engine.tick([Observation(str(i), text, source)
                                    for i, (source, text) in enumerate(case["observations"])],
                                   case.get("scope", "Monday"))
            self.assertEqual(decisions[0].kind, "WAIT")
            self.assertEqual(len(provider.calls), count)

    def test_invalid_evidence_does_not_create_act(self):
        for overrides in ({"evidence_ids": ["invented"]}, {"evidence_ids": []},
                          {"evidence_ids": ["e1"], "missing_observation_source": "email"}):
            provider = Provider()
            engine = fixture_engine(CASES[0], provider, "scripted")
            provider.assessment_rows[CASES[0]["action"]] = {"trigger_ready_now": True, **overrides}
            decisions = engine.tick([Observation("cue", "The cart is here.")], "Friday")
            self.assertEqual(decisions[0].kind, "WAIT")
            self.assertTrue(engine.errors)

    def test_no_watched_evidence_forces_negative_generation_contract(self):
        provider = Provider()
        case = next(c for c in CASES if c["name"] == "useful_missing_source")
        engine = fixture_engine(case, provider, "scripted")
        decision = engine.tick([Observation("scene", "The room is quiet.")], "Monday")[0]
        self.assertEqual(decision.kind, "CHECK")
        _, payload, schema = provider.calls[-1]
        self.assertEqual(payload["watched_evidence_ids"], [])
        self.assertEqual(schema["properties"]["assessments"]["items"]["properties"]["trigger_ready_now"]["enum"], [False])

    def test_unwatched_context_citation_remains_visible_and_rejects_act(self):
        provider = Provider()
        engine = fixture_engine(CASES[0], provider, "scripted")
        provider.assessment_rows[CASES[0]["action"]] = {
            "trigger_ready_now": True, "evidence_ids": ["e2"], "missing_observation_source": ""}
        decision = engine.tick([Observation("scene", "No cart is here."),
                                Observation("clock", "08:50", "clock")], "Friday")[0]
        self.assertEqual(decision.kind, "WAIT")
        schema = provider.calls[-1][2]
        evidence = schema["properties"]["assessments"]["items"]["properties"]["evidence_ids"]
        self.assertEqual(evidence["items"]["enum"], ["e1", "e2"])
        self.assertEqual(evidence["maxItems"], 2)
        self.assertIn("watched-source", engine.errors[-1]["error"])

    def test_registration_origin_and_update_guidance_preserve_identity_review(self):
        provider = Provider()
        engine = ImprovedTriggerEngine(provider, sources=("events", "email"), queryable_sources=("email",),
                                       projector_id="scripted", registration_grounding=True)
        engine.instruction_sources["mail_message"] = "email"
        engine.ingest(Instruction("mail_message", "Send the form after approval."))
        classification = next(c for c in provider.calls if "unit_classifications" in c[2]["properties"])
        self.assertEqual(classification[1]["instruction_origin"]["source"], "email")
        self.assertIn("modify_request, not new_request", classification[0])
        provider.kind, provider.target, provider.same_target = "modify_request", "pm_000001", False
        engine.ingest(Instruction("unrelated", "Change an unrelated form instead."))
        self.assertEqual(engine.intentions["pm_000001"].revision, 1)
        self.assertTrue(any("identity" in error["phase"] for error in engine.errors))

    def test_slot_schema_never_invents_time_or_collapses_multiple_occasions(self):
        for quote in ("Open the door when the courier arrives.", "Ring the bell at 10:00 and 16:00."):
            source = Instruction("request", quote, "Monday")
            schema, options = compiler_slot_schema(_specification_schema(), source,
                {"operation": "new_request", "complete_request_quote": quote}, None, {})
            fields = schema["properties"]["specifications"]["items"]["properties"]
            self.assertEqual(fields["clock_relation"]["enum"], ["none"])
            self.assertEqual(fields["required_clock_time"]["enum"], [""])
            self.assertEqual(fields["permitted_days"]["enum"], [[]])
            self.assertFalse(options["single_clock_gate_allowed"])
        quote = "On Tuesday at 09:00, ring the bell."
        schema, options = compiler_slot_schema(_specification_schema(), Instruction("request", quote, "Monday"),
            {"operation": "new_request", "complete_request_quote": quote}, None, {})
        fields = schema["properties"]["specifications"]["items"]["properties"]
        self.assertEqual(fields["permitted_days"]["enum"], [[], ["Tuesday"]])
        self.assertEqual(fields["required_clock_time"]["enum"], ["", "09:00"])
        self.assertTrue(options["single_clock_gate_allowed"])

    def test_short_extraction_grammar_cannot_copy_another_units_trigger(self):
        quote = "On Tuesday at 09:00, send the meeting reminder."
        base = _specification_schema()
        fields = base["properties"]["specifications"]["items"]["properties"]
        for key in ("requested_action", "trigger_condition"):
            fields[key] = {"type": "string", "maxLength": 320}
        schema, options = compiler_slot_schema(base, Instruction("request", quote, "Monday"),
            {"operation": "new_request", "complete_request_quote": quote}, None, {})
        fields = schema["properties"]["specifications"]["items"]["properties"]
        self.assertIn("send the meeting reminder", fields["requested_action"]["enum"])
        self.assertIn("On Tuesday at 09:00", fields["trigger_condition"]["enum"])
        self.assertNotIn("when approval arrives by email", fields["trigger_condition"]["enum"])
        self.assertTrue(all(s in quote for s in fields["trigger_condition"]["enum"]))
        self.assertTrue(options["verbatim_span_grammar"])
        self.assertIsNone(verbatim_spans("word " * 200))

    def test_reclassification_does_not_bypass_identity_review(self):
        class ReviewProvider(Provider):
            def __call__(self, system, payload, schema):
                if payload.get("classification_review"):
                    self.calls.append((system, copy.deepcopy(payload), copy.deepcopy(schema)))
                    return {"unit_classifications": [{"reason": "Explicit recipient revision",
                        "unit_id": payload["focus_unit_id"], "classification": "modify_request",
                        "related_intention_id": "pm_000001"}]}
                value = super().__call__(system, payload, schema)
                if "unit_classifications" in value:
                    value["unit_classifications"][0]["related_intention_id"] = ""
                return value
        provider = ReviewProvider()
        engine = ImprovedTriggerEngine(provider, sources=("events", "email"), queryable_sources=("email",),
                                       projector_id="scripted", registration_grounding=True)
        engine.ingest(Instruction("initial", "Send the report to Morgan after approval."))
        provider.target, provider.same_target = "pm_000001", False
        engine.ingest(Instruction("update", "Send the report to Lee instead of Morgan after approval."))
        self.assertEqual(engine.intentions["pm_000001"].revision, 1)
        self.assertTrue(any(p.get("classification_review") for _, p, _ in provider.calls))
        self.assertTrue(any("identity" in error["phase"] for error in engine.errors))

    def test_bounded_priority_covers_sources_and_survives_restore(self):
        candidates = [Decision("CHECK", source, "Missing observation", source=source)
                      for source in ("clock", "alpha", "beta", "gamma")]
        arbiter = BoundedPriorityArbiter([d.source for d in candidates])
        offered = [arbiter.arbitrate(candidates, budget=1, priority_sources=("clock",)).selected_sources[0]
                   for _ in range(8)]
        self.assertEqual(offered, ["clock", "alpha", "clock", "beta", "clock", "gamma", "clock", "alpha"])
        restored = BoundedPriorityArbiter(arbiter.queryable_sources)
        restored.restore(json.loads(json.dumps(arbiter.snapshot())))
        self.assertEqual(arbiter.arbitrate(candidates, budget=1, priority_sources=("clock",)),
                         restored.arbitrate(list(reversed(candidates)), budget=1, priority_sources=("clock",)))
        self.assertEqual(arbiter.snapshot(), restored.snapshot())

    def test_actual_queries_are_distinct_and_invalid_selection_is_atomic(self):
        arbiter = BoundedPriorityArbiter(("clock", "email"))
        candidates = [Decision("CHECK", s, "Missing observation", source=s) for s in ("clock", "email")]
        arbiter.arbitrate(candidates, budget=1, priority_sources=("clock",))
        self.assertEqual(arbiter.snapshot()["queried"], [])
        arbiter.record_query("email")
        arbiter.record_query("email")
        before = copy.deepcopy(arbiter.snapshot())
        with self.assertRaises(ValueError):
            arbiter.arbitrate(candidates, budget=1, priority_sources=("invented",))
        self.assertEqual(arbiter.snapshot(), before)
        self.assertEqual(len(before["queried"]), 2)
        self.assertEqual(arbiter.arbitrate(candidates, budget=0).selected, ())

    def test_engine_restore_preserves_policy_logs_and_query_budget(self):
        provider = Provider()
        engine = fixture_engine(CASES[-1], provider, "scripted")
        engine.tick([Observation("quiet", "The room is quiet.")], "Monday")
        engine.record_query("email")
        state = json.loads(json.dumps(engine.snapshot()))
        restored = engine.fresh()
        count = len(provider.calls)
        restored.restore(state)
        self.assertEqual(len(provider.calls), count)
        self.assertIsInstance(restored.fair_checks, BoundedPriorityArbiter)
        self.assertEqual(json.loads(json.dumps(restored.snapshot())), state)
        self.assertEqual(engine.tick([], "Monday"), restored.tick([], "Monday"))
        restored.record_query("clock")
        self.assertFalse(any(d.kind == "CHECK" for d in restored.tick([], "Monday")))
        before = restored.snapshot()
        incompatible = copy.deepcopy(state)
        incompatible["candidate_config"]["scope_grounding"] = False
        with self.assertRaises(ValueError):
            restored.restore(incompatible)
        self.assertEqual(restored.snapshot(), before)
        restored.set_sources(restored.sources, ("clock",))
        self.assertIsInstance(restored.fair_checks, BoundedPriorityArbiter)
        self.assertEqual(restored.fair_checks.queryable_sources, ("clock",))


if __name__ == "__main__":
    unittest.main()
