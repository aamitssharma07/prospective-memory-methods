"""V3 reference grounding contracts; all model responses are scripted fixtures."""

import copy
import json
import unittest

from prospective_memory.adapters.pmbench import PMBenchAdapter
from prospective_memory.core import Instruction, Observation
from prospective_memory.method.source_bound import SCHEMA, SourceBoundPISEngine
from prospective_memory.method.source_bound_v3 import REFERENCE_ASSESS, REFERENCE_SCHEMA, SourceBoundV3Engine


def assessment(met=False, ids=(), source="", **overrides):
    return {"reason": "Scripted reference assessment", "all_conditions_met": met,
            "evidence_ids": list(ids), "missing_observation_source": source, **overrides}


class Provider:
    def __init__(self):
        self.classification = "new_request"
        self.watched = ["email"]
        self.reply = assessment(source="email")
        self.calls = []

    def __call__(self, system, payload, schema):
        key = next(iter(schema["properties"]))
        self.calls.append((system, copy.deepcopy(payload), copy.deepcopy(schema)))
        if key == "unit_classifications":
            return {key: [{"unit_id": payload["focus_unit_id"], "classification": self.classification,
                           "related_intention_id": "", "reason": "Scripted fixture"}]}
        if key == "operations":
            return {key: [{"operation": "new_request", "complete_request_quote": payload["current_message"]["text"]}]}
        if key == "specifications":
            row = {"operation_id": "request_1", "target_id": "", "watched_sources": self.watched,
                   "permitted_days": [], "recurring": False, "clock_relation": "none", "required_clock_time": ""}
            if "reason" in schema["properties"][key]["items"]["properties"]:
                row["reason"] = "Scripted metadata fixture"
            return {key: [row]}
        return {"assessments": [self.reply(payload) if callable(self.reply) else copy.deepcopy(self.reply)]}


class SourceBoundV3ReferenceTests(unittest.TestCase):
    def engine(self, engine_class=SourceBoundV3Engine, **kwargs):
        provider = Provider()
        engine = engine_class(provider, sources=("events", "email", "sensor", "clock"),
                              queryable_sources=("email", "sensor", "clock"), **kwargs)
        self.assertTrue(engine.ingest(Instruction("request", "Send the full report to Morgan after email approval.")))
        return engine, provider

    def test_maps_local_references_back_to_host_ids_without_completion(self):
        engine, provider = self.engine()
        provider.reply = assessment(True, ["e2", "e2"])
        observations = [Observation("scene-27", "The desk is quiet."),
                        Observation("mail-approval-832", "Approved.", "email")]
        decision = engine.tick(observations)[0]
        self.assertEqual((decision.kind, decision.evidence_ids), ("ACT", ("mail-approval-832",)))
        self.assertEqual(engine.intentions[decision.intention_id].status, "pending")
        system, payload, schema = provider.calls[-1]
        self.assertEqual([row["id"] for row in payload["observations"]], ["e1", "e2"])
        fields = schema["properties"]["assessments"]["items"]["properties"]
        self.assertEqual(fields["evidence_ids"]["items"]["enum"], ["e1", "e2"])
        self.assertNotIn("evidence_quotes", fields)
        self.assertNotIn("evidence_quotes", system)
        self.assertEqual(engine.errors, [])

    def test_unknown_host_id_empty_and_stale_references_fail_closed(self):
        scenarios = [([], [Observation("mail-1", "Approved.", "email")]),
                     (["bogus"], [Observation("mail-1", "Approved.", "email")]),
                     (["mail-1"], [Observation("mail-1", "Approved.", "email")]),
                     (["e2"], [Observation("mail-1", "Approved.", "email")]),
                     (["e1"], [Observation("mail-1", "Approved.", "email", False)]),
                     ([""], [])]
        for ids, observations in scenarios:
            with self.subTest(ids=ids, observations=observations):
                engine, provider = self.engine()
                provider.reply = assessment(True, ids)
                self.assertEqual(engine.tick(observations)[0].kind, "WAIT")
                self.assertTrue(engine.errors)

    def test_stale_observations_are_excluded_from_payload_and_legal_refs(self):
        engine, provider = self.engine()
        provider.reply = assessment(False)
        engine.tick([Observation("old", "Approved yesterday.", "email", False),
                     Observation("current", "The desk is quiet.", "events")])
        payload, schema = provider.calls[-1][1:]
        self.assertEqual(payload["observations"], [{"id": "e1", "text": "The desk is quiet.",
                                                    "source": "events", "current": True}])
        self.assertEqual(schema["properties"]["assessments"]["items"]["properties"]
                         ["evidence_ids"]["items"]["enum"], ["e1"])
        self.assertIn("email", payload["check_sources"])

    def test_unwatched_evidence_is_not_sufficient_for_act(self):
        engine, provider = self.engine()
        provider.reply = assessment(True, ["e1"])
        self.assertEqual(engine.tick([Observation("sensor-id", "Approved.", "sensor")])[0].kind, "WAIT")
        self.assertTrue(engine.errors)

    def test_reference_remapping_preserves_delivery_deduplication(self):
        engine, provider = self.engine()
        provider.reply = lambda payload: assessment(True, [next(row["id"] for row in payload["observations"]
                                                               if row["source"] == "email")])
        scene = Observation("scene-1", "The office is quiet.")
        mail = Observation("mail-1", "Approved.", "email")
        self.assertEqual(engine.tick([scene, mail])[0].kind, "ACT")
        # The same host event changes local reference from e2 to e1, but is not
        # a new reminder. Conversely e1 can refer to a genuinely new host event.
        self.assertEqual(engine.tick([mail, scene])[0].kind, "WAIT")
        new = engine.tick([Observation("mail-2", "Approved again.", "email")])[0]
        self.assertEqual((new.kind, new.evidence_ids), ("ACT", ("mail-2",)))
        self.assertEqual(engine.errors, [])

    def test_false_missing_source_checks_then_response_can_act(self):
        engine, provider = self.engine()
        engine.begin_step("step-1")
        decision = engine.tick([])[0]
        self.assertEqual((decision.kind, decision.source), ("CHECK", "email"))
        engine.record_query("email")
        provider.reply = assessment(True, ["e1"])
        decision = engine.tick([Observation("portal-mail-result", "Approved.", "email")])[0]
        self.assertEqual((decision.kind, decision.evidence_ids), ("ACT", ("portal-mail-result",)))
        self.assertEqual(engine.errors, [])

    def test_true_with_missing_source_and_false_with_forged_id_are_rejected(self):
        for reply in [assessment(True, ["e1"], "email"), assessment(False, ["forged"], "email")]:
            with self.subTest(reply=reply):
                engine, provider = self.engine()
                provider.reply = reply
                self.assertEqual(engine.tick([Observation("scene", "Quiet.")])[0].kind, "WAIT")
                self.assertTrue(engine.errors)

    def test_observed_unwatched_push_only_and_unavailable_sources_cannot_check(self):
        for source, observations in [("email", [Observation("mail", "No approval.", "email")]),
                                      ("sensor", []), ("events", []), ("imagined", [])]:
            with self.subTest(source=source):
                engine, provider = self.engine()
                provider.reply = assessment(source=source)
                self.assertEqual(engine.tick(observations)[0].kind, "WAIT")
                self.assertTrue(engine.errors)

    def test_zero_and_exhausted_query_budgets_exclude_source(self):
        for kwargs in ({"query_budget": 0}, {"step_query_budget": 1}):
            with self.subTest(kwargs=kwargs):
                engine, provider = self.engine(**kwargs)
                engine.begin_step("step-1")
                if "step_query_budget" in kwargs:
                    engine.record_query("email")
                self.assertEqual(engine.tick([])[0].kind, "WAIT")
                self.assertEqual(provider.calls[-1][1]["check_sources"], [])
                fields = provider.calls[-1][2]["properties"]["assessments"]["items"]["properties"]
                self.assertEqual(fields["missing_observation_source"]["enum"], [""])
                if "step_query_budget" in kwargs:
                    engine.begin_step("step-2")
                    self.assertEqual(engine.tick([])[0].kind, "CHECK")

    def test_long_evidence_text_is_unchanged_in_payload_engine_and_adapter(self):
        engine, provider = self.engine()
        provider.classification = "fact"
        provider.reply = lambda payload: assessment(True, [payload["observations"][0]["id"]])
        text = ("The editor confirms that the complete report addressed to Morgan is approved, "
                "including the appendices, the amended tables and the explanatory notes; "
                "the approval applies to the final reviewed version and is effective now.")
        self.assertGreater(len(text), 171)
        adapter = PMBenchAdapter(engine)
        messages = [{"role": "system", "content": "Available state channels: email."},
                    {"role": "user", "content": "State [email]: " + text}]
        reminder = adapter.context_for(messages)
        guidance = json.loads(reminder.splitlines()[1])
        self.assertEqual(guidance[0]["evidence"], [{"source": "email", "text": text}])
        self.assertEqual(provider.calls[-1][1]["observations"][0]["text"], text)
        self.assertEqual(engine._observations["message_1"].text, text)
        self.assertEqual(adapter.last_decisions[0].evidence_ids, ("message_1",))
        self.assertEqual(engine.errors, [])

    def test_v2_and_global_v3_schemas_are_not_mutated_by_dynamic_enums(self):
        v2_before, v3_before = copy.deepcopy(SCHEMA), copy.deepcopy(REFERENCE_SCHEMA)
        engine, provider = self.engine()
        provider.reply = assessment()
        engine.tick([])
        first_schema = copy.deepcopy(provider.calls[-1][2])
        engine.tick([Observation("original-id", "No approval.", "email")])
        engine.tick([Observation("other-id", "Quiet."), Observation("sensor-id", "Ready.", "sensor")])
        self.assertEqual(SCHEMA, v2_before)
        self.assertEqual(REFERENCE_SCHEMA, v3_before)
        self.assertIn("evidence_quotes", SCHEMA["properties"]["assessments"]["items"]["required"])
        self.assertNotIn("evidence_quotes", REFERENCE_SCHEMA["properties"]["assessments"]["items"]["required"])
        self.assertEqual(first_schema["properties"]["assessments"]["items"]["properties"]
                         ["evidence_ids"]["items"]["enum"], [""])

    def test_schema_cache_shape_is_stable_across_original_host_ids(self):
        engine, provider = self.engine()
        provider.reply = assessment()
        engine.tick([Observation("id-1", "Quiet.")])
        first = provider.calls[-1][2]
        engine.tick([Observation("completely-different-long-id", "Also quiet.")])
        self.assertEqual(provider.calls[-1][2], first)

    def test_v2_still_accepts_exact_quotes_and_v3_rejects_legacy_extra_field(self):
        v2, old_provider = self.engine(SourceBoundPISEngine)
        old_provider.reply = assessment(True, ["mail"], evidence_quotes=["Approved."])
        self.assertEqual(v2.tick([Observation("mail", "Approved.", "email")])[0].kind, "ACT")
        v3, new_provider = self.engine()
        new_provider.reply = assessment(True, ["e1"], evidence_quotes=["Approved."])
        self.assertEqual(v3.tick([Observation("mail", "Approved.", "email")])[0].kind, "WAIT")
        self.assertTrue(v3.errors)

    def test_snapshot_roundtrip_retains_host_ids_and_v3_callbacks(self):
        engine, provider = self.engine()
        provider.reply = assessment(True, ["e1"])
        obs = [Observation("host-evidence", "Approved.", "email")]
        self.assertEqual(engine.tick(obs)[0].kind, "ACT")
        state = json.loads(json.dumps(engine.snapshot()))
        restored = engine.fresh()
        before_calls = len(provider.calls)
        restored.restore(state)
        self.assertEqual(json.loads(json.dumps(restored.snapshot())), state)
        self.assertEqual(len(provider.calls), before_calls)
        self.assertIsInstance(restored, SourceBoundV3Engine)
        self.assertIs(restored.compiler.__self__, restored)
        self.assertIs(restored.matcher.__self__, restored)
        self.assertEqual(restored.tick(obs)[0].kind, "WAIT")
        self.assertEqual(restored.snapshot()["policy_variant"], "sbpm_no_projection")

    def test_v2_v3_snapshot_cross_restore_is_atomic_rejection(self):
        v3, _ = self.engine()
        v2, _ = self.engine(SourceBoundPISEngine)
        for destination, source in ((v3, v2), (v2, v3)):
            with self.subTest(destination=destination.POLICY):
                before = destination.snapshot()
                with self.assertRaises(ValueError):
                    destination.restore(source.snapshot())
                self.assertEqual(destination.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
