"""Opt-in projection-engine wiring contracts; no inference is performed."""

import copy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from prospective_memory.core import Instruction, Observation
from prospective_memory.method.source_bound import SourceBoundPISEngine
from prospective_memory.method.source_bound_v3 import REFERENCE_SCHEMA, SourceBoundV3Engine
from prospective_memory.method.trigger_engine import (
    TRIGGER_ASSESS, TRIGGER_SCHEMA, SourceBoundTriggerEngine,
)
from prospective_memory.method.projection_cache import SCHEMA as PROJECTION_SCHEMA


PROJECTOR_ID = "scripted-model:v1;temperature=0;max-tokens=4096"
REQUEST = "Send the complete report to Morgan after email approval."


class Provider:
    def __init__(self):
        self.calls = []
        self.kind, self.target = "new_request", ""
        self.watched = ["email"]
        self.same_target = True
        self.recurring = False
        self.projection_mode = "projected"
        self.ready, self.ids, self.check_source = False, [], ""
        self.assessment_overrides = {}

    def keys(self):
        return [next(iter(schema["properties"])) for _, _, schema in self.calls]

    def __call__(self, system, payload, schema):
        key = next(iter(schema["properties"]))
        self.calls.append((system, copy.deepcopy(payload), copy.deepcopy(schema)))
        if key == "unit_classifications":
            return {key: [{"reason": "Scripted classification", "unit_id": payload["focus_unit_id"],
                           "classification": self.kind, "related_intention_id": self.target}]}
        if key == "specifications":
            return {key: [{"operation_id": op["operation_id"], "target_id": self.target,
                           "watched_sources": self.watched, "permitted_days": [],
                           "recurring": self.recurring, "clock_relation": "none", "required_clock_time": ""}
                          for op in payload["operations"]]}
        if key == "identity_reviews":
            return {key: [{"same_obligation": self.same_target, "explicit_update": True,
                           "reason": "Scripted identity check"}]}
        if key == "trigger_projections":
            if self.projection_mode == "error":
                raise RuntimeError("Scripted projection provider failure")
            if self.projection_mode == "invalid":
                return {key: []}
            unsupported = self.projection_mode == "unsupported"
            return {key: [{"intention_id": b["intention"]["id"], "revision": b["intention"]["revision"],
                           "source_instruction_ids": list(b["intention"]["instruction_ids"]),
                           "status": self.projection_mode,
                           "action_to_perform_next": "" if unsupported else "Send the complete report to Morgan",
                           "readiness_question": "" if unsupported else "Has the required email approval arrived?",
                           "reason": "Scripted static projection"} for b in payload["records"]]}
        if key == "assessments":
            boolean = "trigger_ready_now" if "readiness_question" in payload else "all_conditions_met"
            return {key: [{"reason": "Scripted current-observation judgment", boolean: self.ready,
                           "evidence_ids": self.ids, "missing_observation_source": self.check_source,
                           **self.assessment_overrides}]}
        raise AssertionError("Unexpected callback phase: " + key)


class TriggerEngineTests(unittest.TestCase):
    def engine(self, *, register=True, **kwargs):
        provider = Provider()
        engine = SourceBoundTriggerEngine(provider, sources=("events", "email", "sensor", "clock"),
            queryable_sources=("email", "sensor", "clock"), projector_id=PROJECTOR_ID, **kwargs)
        if register:
            self.assertEqual(engine.ingest(Instruction("request", REQUEST)), ["pm_000001"])
        return engine, provider

    def test_required_configuration_unique_policy_and_default_no_verifier(self):
        with self.assertRaises(TypeError):
            SourceBoundTriggerEngine(Provider())
        engine, _ = self.engine()
        self.assertEqual(engine.POLICY, "sbpm_no_arbiter")
        self.assertFalse(engine.verify_actions)
        self.assertEqual(engine.projections.batch_size, 4)

    def test_projection_follows_accepted_registration_without_rewriting_sources(self):
        engine, provider = self.engine()
        self.assertEqual(provider.keys(), ["unit_classifications", "specifications", "trigger_projections"])
        intention = engine.intentions["pm_000001"]
        self.assertEqual((intention.action, intention.condition), (REQUEST, REQUEST))
        self.assertEqual(engine.instructions["request"].text, REQUEST)
        record = provider.calls[-1][1]["records"][0]
        self.assertEqual(record["original_instructions"], [{"id": "request", "text": REQUEST, "scope": ""}])
        self.assertEqual(record["intention"]["id"], intention.id)
        self.assertNotIn("observations", record)

    def test_duplicate_and_fact_messages_do_not_refresh_projection(self):
        engine, provider = self.engine()
        self.assertEqual(engine.ingest(Instruction("request", REQUEST)), [])
        self.assertEqual(engine.ingest(Instruction("same-request", REQUEST)), [])
        provider.kind = "fact"
        self.assertEqual(engine.ingest(Instruction("fact", "The office has two desks.")), [])
        self.assertEqual(provider.keys().count("trigger_projections"), 1)
        self.assertEqual(len(engine.intentions), 1)

    def test_multiple_accepted_units_use_one_projection_batch(self):
        engine, provider = self.engine(register=False)
        text = "- Send the report after approval.\n- Archive the draft after the receipt arrives."
        changed = engine.ingest(Instruction("batch", text))
        self.assertEqual(len(changed), 2)
        self.assertEqual(provider.keys().count("unit_classifications"), 2)
        self.assertEqual(provider.keys().count("trigger_projections"), 1)
        self.assertEqual(len(provider.calls[-1][1]["records"]), 2)

    def test_revision_refreshes_same_id_with_full_chronological_sources(self):
        engine, provider = self.engine()
        provider.kind, provider.target = "modify_request", "pm_000001"
        update = "Send the complete report to Lee instead; keep the email approval prerequisite."
        self.assertEqual(engine.ingest(Instruction("update", update)), [provider.target])
        intention = engine.intentions[provider.target]
        self.assertEqual(intention.revision, 2)
        self.assertIn(REQUEST, intention.action)
        self.assertIn(update, intention.action)
        self.assertEqual(provider.keys().count("trigger_projections"), 2)
        record = provider.calls[-1][1]["records"][0]
        self.assertEqual([i["text"] for i in record["original_instructions"]], [REQUEST, update])
        self.assertEqual(engine.projections.get(intention, engine.instructions).revision, 2)

    def test_rejected_revision_never_projects_a_speculative_change(self):
        engine, provider = self.engine()
        before = engine.projections.snapshot()
        provider.kind, provider.target, provider.same_target = "modify_request", "pm_000001", False
        self.assertEqual(engine.ingest(Instruction("unrelated", "Change the unrelated delivery.")), [])
        self.assertEqual(engine.projections.snapshot(), before)
        self.assertEqual(provider.keys().count("trigger_projections"), 1)

    def test_failed_projection_after_revision_cannot_reuse_old_view(self):
        engine, provider = self.engine()
        provider.kind, provider.target = "modify_request", "pm_000001"
        provider.projection_mode = "error"
        engine.ingest(Instruction("update", "Keep the report pending until Lee approves it by email."))
        intention = engine.intentions[provider.target]
        view = engine.projections.get(intention, engine.instructions)
        self.assertEqual((view.revision, view.status, view.readiness_question), (2, "error", ""))
        engine.tick([])
        self.assertNotIn("readiness_question", provider.calls[-1][1])
        self.assertEqual(provider.keys().count("trigger_projections"), 2)
        self.assertEqual(provider.keys().count("assessments"), 1)
        self.assertTrue(any(e["phase"] == "trigger_projection_request" for e in engine.errors))

    def test_cancellation_retires_projection_without_call_or_completion_guess(self):
        engine, provider = self.engine()
        provider.kind, provider.target = "cancel_request", "pm_000001"
        self.assertEqual(engine.ingest(Instruction("cancel", "Cancel the report request.")), [provider.target])
        self.assertEqual(engine.intentions[provider.target].status, "cancelled")
        self.assertEqual(engine.projections.snapshot()["entries"], [])
        self.assertEqual(provider.keys().count("trigger_projections"), 1)
        self.assertEqual(engine.tick([]), [])

    def test_host_acknowledgment_preserves_only_active_views_without_inference(self):
        for outcome in ("attempted", "completed"):
            with self.subTest(outcome=outcome):
                engine, provider = self.engine()
                count = len(provider.calls)
                engine.acknowledge("pm_000001", outcome)
                self.assertEqual(len(provider.calls), count)
                self.assertEqual(len(engine.projections.snapshot()["entries"]), int(outcome == "attempted"))
        engine, provider = self.engine()
        engine.acknowledge("pm_000001", "attempted")
        engine.acknowledge("pm_000001", "failed")
        engine.tick([])
        self.assertIn("readiness_question", provider.calls[-1][1])
        self.assertEqual(provider.keys().count("trigger_projections"), 1)

    def test_recurring_completion_retains_same_source_projection(self):
        engine, provider = self.engine(register=False)
        provider.recurring = True
        engine.ingest(Instruction("request", REQUEST))
        engine.acknowledge("pm_000001", "attempted")
        engine.acknowledge("pm_000001", "completed")
        self.assertEqual(engine.intentions["pm_000001"].status, "pending")
        self.assertIsNotNone(engine.projections.get(engine.intentions["pm_000001"], engine.instructions))
        self.assertEqual(provider.keys().count("trigger_projections"), 1)
        engine.tick([])
        self.assertIn("readiness_question", provider.calls[-1][1])

    def test_host_acknowledgment_cannot_rebind_changed_semantics(self):
        engine, provider = self.engine()
        engine.intentions["pm_000001"] = replace(engine.intentions["pm_000001"], condition="Different condition")
        count = len(provider.calls)
        engine.acknowledge("pm_000001", "attempted")
        self.assertEqual(len(provider.calls), count)
        self.assertEqual(engine.projections.snapshot()["entries"], [])
        engine.acknowledge("pm_000001", "failed")
        engine.tick([])
        self.assertNotIn("readiness_question", provider.calls[-1][1])

    def test_acknowledgment_rebound_snapshot_restores_without_regeneration(self):
        engine, provider = self.engine()
        engine.acknowledge("pm_000001", "attempted")
        state = json.loads(json.dumps(engine.snapshot()))
        restored = engine.fresh()
        count = len(provider.calls)
        restored.restore(state)
        self.assertEqual(json.loads(json.dumps(restored.snapshot())), state)
        restored.acknowledge("pm_000001", "failed")
        self.assertEqual(len(provider.calls), count)
        restored.tick([])
        self.assertIn("readiness_question", provider.calls[-1][1])
        self.assertEqual(provider.keys().count("trigger_projections"), 1)

    def test_unsupported_error_and_invalid_projection_use_one_v3_assessment(self):
        for mode in ("unsupported", "error", "invalid"):
            with self.subTest(mode=mode):
                engine, provider = self.engine(register=False)
                provider.projection_mode = mode
                engine.ingest(Instruction("request", REQUEST))
                provider.ready, provider.ids = True, ["e1"]
                decision = engine.tick([Observation("approval", "Approved.", "email")])[0]
                self.assertEqual(decision.kind, "ACT")
                self.assertNotIn("readiness_question", provider.calls[-1][1])
                fields = provider.calls[-1][2]["properties"]["assessments"]["items"]["properties"]
                self.assertIn("all_conditions_met", fields)
                self.assertEqual(provider.keys().count("assessments"), 1)
                self.assertEqual(provider.keys().count("trigger_projections"), 1)

    def test_stale_projection_falls_back_without_regenerating_on_tick(self):
        engine, provider = self.engine()
        engine.intentions["pm_000001"] = replace(engine.intentions["pm_000001"], revision=2)
        engine.tick([])
        self.assertNotIn("readiness_question", provider.calls[-1][1])
        self.assertEqual(provider.keys().count("trigger_projections"), 1)
        self.assertEqual(engine.projections.snapshot()["entries"], [])

    def test_projected_assessment_preserves_original_action_and_host_evidence_ids(self):
        engine, provider = self.engine()
        provider.ready, provider.ids = True, ["e2", "e2"]
        decision = engine.tick([Observation("scene", "Quiet."), Observation("mail-892", "Approved.", "email")])[0]
        self.assertEqual((decision.kind, decision.evidence_ids), ("ACT", ("mail-892",)))
        self.assertEqual(engine.intentions[decision.intention_id].action, REQUEST)
        self.assertEqual(engine.intentions[decision.intention_id].status, "pending")
        prompt, payload, schema = provider.calls[-1]
        self.assertIn("NEXT", prompt)
        self.assertEqual(payload["readiness_question"], "Has the required email approval arrived?")
        self.assertEqual(payload["source_bound_specification"], REQUEST)
        self.assertEqual(payload["projection_binding"]["revision"], 1)
        fields = schema["properties"]["assessments"]["items"]["properties"]
        self.assertIn("trigger_ready_now", fields)
        self.assertNotIn("all_conditions_met", fields)
        self.assertEqual(engine.errors, [])

    def test_valid_projection_is_not_evidence_and_cannot_complete_task(self):
        engine, provider = self.engine()
        provider.ready, provider.ids = True, []
        self.assertEqual(engine.tick([])[0].kind, "WAIT")
        self.assertEqual(engine.intentions["pm_000001"].status, "pending")
        self.assertTrue(engine.errors)
        self.assertEqual(provider.keys().count("assessments"), 1)

    def test_malformed_assessment_does_not_start_a_second_assessment_or_retry(self):
        engine, provider = self.engine()
        provider.assessment_overrides = {"all_conditions_met": True}
        self.assertEqual(engine.tick([])[0].kind, "WAIT")
        self.assertEqual(provider.keys().count("assessments"), 1)
        self.assertEqual(provider.keys().count("trigger_projections"), 1)

    def test_invalid_stale_foreign_and_unwatched_references_fail_closed(self):
        cases = [(["unknown"], [Observation("mail", "Approved.", "email")]),
                 (["mail"], [Observation("mail", "Approved.", "email")]),
                 (["e1"], [Observation("mail", "Approved.", "email", False)]),
                 (["e1"], [Observation("sensor", "Approved.", "sensor")]),
                 ([""], [])]
        for ids, observations in cases:
            with self.subTest(ids=ids, observations=observations):
                engine, provider = self.engine()
                provider.ready, provider.ids = True, ids
                self.assertEqual(engine.tick(observations)[0].kind, "WAIT")
                self.assertTrue(engine.errors)

    def test_true_with_missing_source_and_false_with_forged_ref_fail_closed(self):
        for ready, ids, source in ((True, ["e1"], "email"), (False, ["forged"], "email")):
            with self.subTest(ready=ready):
                engine, provider = self.engine()
                provider.ready, provider.ids, provider.check_source = ready, ids, source
                self.assertEqual(engine.tick([Observation("mail", "Approved.", "email")])[0].kind, "WAIT")
                self.assertTrue(engine.errors)

    def test_query_constraints_budget_and_observation_refs_match_v3(self):
        for source, observations in (("email", [Observation("mail", "Pending.", "email")]),
                                     ("events", []), ("sensor", []), ("imagined", [])):
            with self.subTest(source=source):
                engine, provider = self.engine()
                provider.check_source = source
                self.assertEqual(engine.tick(observations)[0].kind, "WAIT")
                self.assertTrue(engine.errors)
        engine, provider = self.engine(step_query_budget=1)
        engine.begin_step("one")
        provider.check_source = "email"
        self.assertEqual(engine.tick([])[0].kind, "CHECK")
        engine.record_query("email")
        self.assertEqual(engine.tick([])[0].kind, "WAIT")
        self.assertEqual(provider.calls[-1][1]["check_sources"], [])
        engine.begin_step("two")
        self.assertEqual(engine.tick([])[0].kind, "CHECK")

    def test_repeated_ticks_use_cached_view_and_original_event_deduplication(self):
        engine, provider = self.engine()
        provider.ready, provider.ids = True, ["e1"]
        evidence = [Observation("mail", "Approved.", "email")]
        self.assertEqual(engine.tick(evidence)[0].kind, "ACT")
        self.assertEqual(engine.tick(evidence)[0].kind, "WAIT")
        self.assertEqual(provider.keys().count("trigger_projections"), 1)
        self.assertEqual(provider.keys().count("assessments"), 2)

    def test_typed_gate_still_precedes_projection_assessment(self):
        engine, provider = self.engine()
        engine.triggers["pm_000001"] = {"days": ["Thursday"], "clock_op": "none", "clock_time": ""}
        self.assertEqual(engine.tick([], scope="Friday")[0].kind, "WAIT")
        self.assertNotIn("assessments", provider.keys())

    def test_dynamic_enums_and_callback_cannot_mutate_global_schemas(self):
        originals = copy.deepcopy((TRIGGER_SCHEMA, REFERENCE_SCHEMA, PROJECTION_SCHEMA))
        engine, provider = self.engine()
        engine.tick([])
        engine.tick([Observation("mail", "Pending.", "email")])
        self.assertEqual((TRIGGER_SCHEMA, REFERENCE_SCHEMA, PROJECTION_SCHEMA), originals)
        fields = provider.calls[-1][2]["properties"]["assessments"]["items"]["properties"]
        self.assertEqual(fields["evidence_ids"]["items"]["enum"], ["e1"])
        self.assertEqual(fields["missing_observation_source"]["enum"], [""])

    def test_fresh_and_snapshot_restore_are_callback_free_and_keep_policy(self):
        engine, provider = self.engine(projection_batch_size=2)
        provider.ready, provider.ids = True, ["e1"]
        obs = [Observation("mail", "Approved.", "email")]
        self.assertEqual(engine.tick(obs)[0].kind, "ACT")
        state = json.loads(json.dumps(engine.snapshot()))
        count = len(provider.calls)
        fresh = engine.fresh()
        self.assertEqual(fresh.intentions, {})
        self.assertEqual(fresh.projections.snapshot()["entries"], [])
        fresh.restore(state)
        self.assertEqual(len(provider.calls), count)
        self.assertEqual(json.loads(json.dumps(fresh.snapshot())), state)
        self.assertIs(fresh.compiler.__self__, fresh)
        self.assertIs(fresh.matcher.__self__, fresh)
        self.assertEqual(fresh.projections.batch_size, 2)
        self.assertEqual(fresh.tick(obs)[0].kind, "WAIT")
        self.assertIn("readiness_question", provider.calls[-1][1])

    def test_snapshot_rejects_historical_policies_in_both_directions(self):
        engine, provider = self.engine()
        for cls in (SourceBoundPISEngine, SourceBoundV3Engine):
            other = cls(provider, sources=engine.sources, queryable_sources=engine.queryable_sources)
            for destination, source in ((engine, other), (other, engine)):
                with self.subTest(destination=destination.POLICY, source=source.POLICY):
                    before = destination.snapshot()
                    with self.assertRaises(ValueError):
                        destination.restore(source.snapshot())
                    self.assertEqual(destination.snapshot(), before)

    def test_snapshot_source_revision_config_and_assessor_mismatch_are_atomic(self):
        engine, provider = self.engine()
        original = engine.snapshot()
        mutations = [lambda s: s.update(trigger_assessor_sha256="wrong"),
                     lambda s: s["trigger_projection_cache"]["projector"].update(identity="other-model"),
                     lambda s: s["trigger_projection_cache"]["entries"][0].update(binding_sha256="wrong"),
                     lambda s: s["intentions"][0].update(revision=2),
                     lambda s: s["instructions"][0].update(scope="other-scope"),
                     lambda s: s["triggers"].clear()]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                state = copy.deepcopy(original)
                mutate(state)
                with self.assertRaises(ValueError):
                    engine.restore(state)
                self.assertEqual(engine.snapshot(), original)
        self.assertEqual(provider.keys().count("trigger_projections"), 1)

    def test_snapshot_cannot_restore_into_changed_model_or_assessment_definition(self):
        engine, provider = self.engine()
        state = engine.snapshot()
        other = SourceBoundTriggerEngine(provider, projector_id="other-config")
        before = other.snapshot()
        with self.assertRaises(ValueError):
            other.restore(state)
        self.assertEqual(other.snapshot(), before)
        with patch("prospective_memory.method.trigger_engine.TRIGGER_ASSESS", TRIGGER_ASSESS + " changed"):
            changed, _ = self.engine(register=False)
            with self.assertRaises(ValueError):
                changed.restore(state)

    def test_snapshot_prunes_stale_cache_without_model_calls(self):
        engine, provider = self.engine()
        engine.intentions["pm_000001"] = replace(engine.intentions["pm_000001"], revision=2)
        count = len(provider.calls)
        self.assertEqual(engine.snapshot()["trigger_projection_cache"]["entries"], [])
        self.assertEqual(len(provider.calls), count)

    def test_snapshot_unsupported_error_and_missing_views_restore_without_retry(self):
        for mode in ("unsupported", "error", "missing"):
            with self.subTest(mode=mode):
                engine, provider = self.engine(register=False)
                provider.projection_mode = "projected" if mode == "missing" else mode
                engine.ingest(Instruction("request", REQUEST))
                if mode == "missing":
                    engine.projections.invalidate("pm_000001")
                state = json.loads(json.dumps(engine.snapshot()))
                restored = engine.fresh()
                before = len(provider.calls)
                restored.restore(state)
                self.assertEqual(json.loads(json.dumps(restored.snapshot())), state)
                self.assertEqual(len(provider.calls), before)
                restored.tick([])
                self.assertNotIn("readiness_question", provider.calls[-1][1])
                self.assertEqual(provider.keys().count("trigger_projections"), 1)

    def test_projection_for_deleted_or_closed_engine_record_cannot_restore(self):
        engine, _ = self.engine()
        original = engine.snapshot()
        for remove in (False, True):
            with self.subTest(remove=remove):
                state = copy.deepcopy(original)
                if remove:
                    state["intentions"], state["triggers"] = [], {}
                else:
                    state["intentions"][0]["status"] = "completed"
                with self.assertRaises(ValueError):
                    engine.restore(state)
                self.assertEqual(engine.snapshot(), original)


if __name__ == "__main__":
    unittest.main()
