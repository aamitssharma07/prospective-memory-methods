"""Source-bound engine and evaluator contracts; all model replies are scripted."""

import copy
import json
import unittest

from prospective_memory.core import Instruction, Observation
from prospective_memory.evaluate_pis_grounded import DEFAULT_CASES, phase_name, run_case
from prospective_memory.baselines.pis import PISEngine
from prospective_memory.pis_grounded import GroundedPISEngine
from prospective_memory.method.source_bound import SCHEMA, SourceBoundPISEngine


def metadata(**overrides):
    return {"operation_id": "request_1", "target_id": "", "watched_sources": ["email"],
            "permitted_days": [], "recurring": False, "clock_relation": "none",
            "required_clock_time": "", **overrides}


def assessment(met=False, ids=(), quotes=(), source="", **overrides):
    return {"all_conditions_met": met, "evidence_ids": list(ids),
            "evidence_quotes": list(quotes), "missing_observation_source": source,
            "reason": "Scripted assessment", **overrides}


class Provider:
    def __init__(self):
        self.kind = "new_request"
        self.slots = metadata()
        self.reply = assessment(source="email")
        self.extract = True
        self.verdict = "supported"
        self.calls = []

    def __call__(self, system, payload, schema):
        key = next(iter(schema["properties"]))
        self.calls.append((key, copy.deepcopy(payload), copy.deepcopy(schema)))
        if key == "operations":
            return {key: [{"operation": self.kind,
                           "complete_request_quote": payload["current_message"]["text"]}]
                         if self.extract else []}
        if key == "specifications":
            return {key: [copy.deepcopy(self.slots)]}
        if key == "verdict":
            return {"verdict": self.verdict, "reason": "Scripted verifier"}
        value = self.reply(payload) if callable(self.reply) else copy.deepcopy(self.reply)
        return {"assessments": [value]}


class SourceBoundEngineTests(unittest.TestCase):
    def engine(self, register=True, **kwargs):
        p = Provider()
        e = SourceBoundPISEngine(p, sources=("events", "clock", "email", "sensor"),
                                queryable_sources=("clock", "email", "sensor"), **kwargs)
        if register:
            e.ingest(Instruction("request", "Send the complete report to Morgan when the editor approves it by email."))
        return e, p

    def test_complete_source_stored_and_assessment_has_original_history(self):
        e, p = self.engine()
        i = next(iter(e.intentions.values()))
        self.assertEqual(i.action, e.instructions["request"].text)
        self.assertIn("report to Morgan", i.action)
        e.tick([])
        self.assertEqual(p.calls[-1][1]["source_bound_specification"], i.action)
        self.assertEqual(p.calls[-1][1]["original_instructions"][0]["id"], "request")
        self.assertEqual([key for key, _, _ in p.calls], ["operations", "specifications", "assessments"])

    def test_current_source_grounded_true_proposes_act_without_completion(self):
        e, p = self.engine()
        p.reply = assessment(True, ["approval"], ["approved"])
        d = e.tick([Observation("approval", "The editor approved the report.", "email")])[0]
        self.assertEqual((d.kind, d.evidence_ids), ("ACT", ("approval",)))
        self.assertEqual(e.intentions[d.intention_id].status, "pending")
        self.assertEqual(e.errors, [])

    def test_false_can_wait_without_claiming_negative_evidence(self):
        e, p = self.engine()
        p.reply = assessment(False)
        self.assertEqual(e.tick([])[0].kind, "WAIT")
        self.assertEqual(e.errors, [])

    def test_false_with_grounded_negative_evidence_waits(self):
        e, p = self.engine()
        p.reply = assessment(False, ["declined"], ["not approved"])
        self.assertEqual(e.tick([Observation("declined", "The editor has not approved the report.", "email")])[0].kind,
                         "WAIT")
        self.assertEqual(e.errors, [])

    def test_missing_evidence_check_then_response_act(self):
        e, p = self.engine()
        e.begin_step("s1")
        self.assertEqual((e.tick([])[0].kind, e.tick([])[0].source), ("CHECK", "email"))
        # Only actual host attempts spend the per-step budget.
        self.assertEqual(e.step_queries, [])
        e.record_query("email")
        p.reply = assessment(True, ["approval"], ["Approved"])
        self.assertEqual(e.tick([Observation("approval", "Approved", "email")])[0].kind, "ACT")
        self.assertEqual(e.step_queries, ["email"])

    def test_act_requires_nonempty_paired_quotes(self):
        for reply in [assessment(True), assessment(True, ["o"], []),
                      assessment(True, ["o"], [""]), assessment(True, ["o"], ["Absent"]),
                      assessment(True, ["other"], ["Approved"])]:
            with self.subTest(reply=reply):
                e, p = self.engine()
                p.reply = reply
                self.assertEqual(e.tick([Observation("o", "Approved", "email")])[0].kind, "WAIT")
                self.assertTrue(e.errors)

    def test_stale_or_unwatched_evidence_cannot_support_act(self):
        for source, current in [("email", False), ("sensor", True)]:
            with self.subTest(source=source, current=current):
                e, p = self.engine()
                p.reply = assessment(True, ["o"], ["Approved"])
                self.assertEqual(e.tick([Observation("o", "Approved", source, current)])[0].kind, "WAIT")
                self.assertTrue(e.errors)

    def test_true_with_missing_source_is_not_turned_into_act_or_check(self):
        e, p = self.engine()
        p.reply = assessment(True, ["o"], ["Approved"], source="sensor")
        self.assertEqual(e.tick([Observation("o", "Approved", "email")])[0].kind, "WAIT")
        self.assertTrue(e.errors)

    def test_false_with_forged_evidence_is_rejected_even_for_check(self):
        e, p = self.engine()
        p.reply = assessment(False, ["forged"], ["Not seen"], source="email")
        self.assertEqual(e.tick([])[0].kind, "WAIT")
        self.assertTrue(e.errors)

    def test_observed_unwatched_or_unavailable_channel_cannot_be_queried(self):
        for source, observations in [("email", [Observation("o", "No updates", "email")]),
                                      ("sensor", []), ("events", []), ("imagined", [])]:
            with self.subTest(source=source):
                e, p = self.engine()
                p.reply = assessment(source=source)
                self.assertEqual(e.tick(observations)[0].kind, "WAIT")
                self.assertTrue(e.errors)

    def test_query_budget_zero_and_exhausted_step_cannot_check(self):
        e, p = self.engine(query_budget=0)
        self.assertEqual(e.tick([])[0].kind, "WAIT")
        self.assertEqual(p.calls[-1][1]["check_sources"], [])
        e, p = self.engine(step_query_budget=1)
        e.begin_step("step1")
        e.record_query("email")
        self.assertEqual(e.tick([])[0].kind, "WAIT")
        self.assertEqual(p.calls[-1][1]["remaining_check_budget"], 0)
        self.assertTrue(e.exhausted_query_guidance())
        e.begin_step("step2")
        self.assertEqual(e.tick([])[0].kind, "CHECK")

    def test_generated_schema_matches_legal_sources_and_fresh_evidence_each_step(self):
        e, p = self.engine()
        p.reply = assessment()
        base_schema = copy.deepcopy(SCHEMA)

        def enum_after(observations):
            e.tick(observations)
            key, payload, schema = p.calls[-1]
            self.assertEqual(key, "assessments")
            choices = schema["properties"][key]["items"]["properties"]["missing_observation_source"]["enum"]
            self.assertEqual(choices, ["", *payload["check_sources"]])
            return choices

        e.begin_step("first")
        self.assertEqual(enum_after([]), ["", "email"])
        self.assertEqual(enum_after([Observation("reply", "No updates", "email")]), [""])
        # A stale reply is not a current channel observation. Historical storage
        # must not permanently suppress checking on the next host decision.
        e.begin_step("second")
        self.assertEqual(enum_after([Observation("reply", "No updates", "email", False)]), ["", "email"])
        self.assertEqual(SCHEMA, base_schema)
        self.assertNotIn("enum", SCHEMA["properties"]["assessments"]["items"]
                         ["properties"]["missing_observation_source"])

    def test_generated_schema_excludes_push_only_and_host_unavailable_sources(self):
        p = Provider()
        p.slots = metadata(watched_sources=["events", "sensor", "email"])
        p.reply = assessment()
        e = SourceBoundPISEngine(p, sources=("events", "sensor", "email"),
                                queryable_sources=("email",))
        e.ingest(Instruction("request", "Send the report when the sensor confirms readiness."))

        def choices():
            e.tick([])
            return p.calls[-1][2]["properties"]["assessments"]["items"]["properties"] \
                ["missing_observation_source"]["enum"]

        self.assertEqual(choices(), ["", "email"])
        e.set_sources(e.sources, queryable_sources=())
        self.assertEqual(choices(), [""])
        e.set_sources(e.sources, queryable_sources=("sensor",))
        self.assertEqual(choices(), ["", "sensor"])

    def test_generated_schema_enforces_budget_and_does_not_mutate_previous_call(self):
        e, p = self.engine(step_query_budget=1)
        p.reply = assessment()
        e.begin_step("first")
        e.tick([])
        first_schema = copy.deepcopy(p.calls[-1][2])
        e.record_query("email")
        e.tick([])
        field = p.calls[-1][2]["properties"]["assessments"]["items"]["properties"] \
            ["missing_observation_source"]
        self.assertEqual(field["enum"], [""])
        self.assertEqual(first_schema["properties"]["assessments"]["items"]["properties"]
                         ["missing_observation_source"]["enum"], ["", "email"])
        e.begin_step("second")
        e.tick([])
        self.assertEqual(p.calls[-1][2], first_schema)

    def test_generated_schema_per_intention_removes_channel_already_allocated(self):
        e, p = self.engine()
        e.ingest(Instruction("other", "Archive the report after email confirmation."))
        p.reply = lambda payload: assessment(source="email" if payload["check_sources"] else "")
        e.tick([])
        decisions = [call for call in p.calls if call[0] == "assessments"]
        choices = [schema["properties"]["assessments"]["items"]["properties"]
                   ["missing_observation_source"]["enum"] for _, _, schema in decisions]
        self.assertEqual(choices, [["", "email"], [""]])

    def test_two_intentions_share_one_query_per_assessment(self):
        e, p = self.engine()
        e.ingest(Instruction("other", "Archive the report after the editor confirms approval by email."))
        p.reply = lambda payload: assessment(source="email" if payload["check_sources"] else "")
        ds = e.tick([])
        self.assertEqual([d.kind for d in ds], ["CHECK", "WAIT"])
        self.assertEqual(e.errors, [])

    def test_clock_gate_checks_before_assessor_then_requires_other_prerequisite(self):
        e, p = self.engine(False)
        p.slots = metadata(watched_sources=["clock", "email"], clock_relation="at", required_clock_time="09:15")
        e.ingest(Instruction("timed", "At 09:15 send the report only after email approval."))
        calls = len(p.calls)
        self.assertEqual(e.tick([])[0].source, "clock")
        self.assertEqual(len(p.calls), calls)
        self.assertEqual(e.tick([Observation("early", "Time 09:00", "clock")])[0].kind, "WAIT")
        self.assertEqual(len(p.calls), calls)
        self.assertEqual(e.tick([Observation("due", "Time 09:15", "clock")])[0].source, "email")
        self.assertEqual(len(p.calls), calls + 1)

    def test_nonboolean_truth_flag_fails_closed(self):
        e, p = self.engine()
        p.reply = assessment("true", ["o"], ["Approved"])
        self.assertEqual(e.tick([Observation("o", "Approved", "email")])[0].kind, "WAIT")
        self.assertTrue(e.errors)

    def test_revision_keeps_identity_prerequisites_and_latest_clock_then_cancel(self):
        e, p = self.engine(False)
        p.slots = metadata(watched_sources=["clock", "email"], clock_relation="not_before", required_clock_time="09:15")
        key = e.ingest(Instruction("first", "Send report no earlier than 09:15, only after email approval."))[0]
        p.kind = "modify_request"
        p.slots.update(target_id=key, required_clock_time="09:45")
        update = "Change the report's earliest sending time to 09:45 instead."
        self.assertEqual(e.ingest(Instruction("update", update)), [key])
        self.assertEqual(len(e.intentions), 1)
        self.assertEqual(e.intentions[key].instruction_ids, ("first", "update"))
        self.assertIn("only after email approval", e.intentions[key].condition)
        self.assertIn(update, e.intentions[key].condition)
        self.assertEqual(e.triggers[key]["clock_time"], "09:45")
        self.assertEqual(e.tick([Observation("early", "Time 09:15", "clock")])[0].kind, "WAIT")
        p.kind = "cancel_request"
        e.ingest(Instruction("cancel", "Cancel the report reminder."))
        self.assertEqual(e.intentions[key].status, "cancelled")
        self.assertEqual(e.tick([]), [])

    def test_reused_source_evidence_deduplicated_but_host_completion_supported(self):
        e, p = self.engine()
        p.reply = assessment(True, ["o"], ["Approved"])
        obs = [Observation("o", "Approved", "email")]
        d = e.tick(obs)[0]
        self.assertEqual(d.kind, "ACT")
        self.assertEqual(e.tick(obs)[0].kind, "WAIT")
        e.acknowledge(d.intention_id, "completed")
        self.assertEqual(e.tick(obs), [])

    def test_optional_verifier_rejects_without_execution(self):
        e, p = self.engine(verify_actions=True)
        p.verdict = "unsupported"
        p.reply = assessment(True, ["o"], ["Approved"])
        self.assertEqual(e.tick([Observation("o", "Approved", "email")])[0].kind, "WAIT")
        self.assertEqual(p.calls[-1][0], "verdict")
        self.assertEqual(next(iter(e.intentions.values())).status, "pending")

    def test_snapshot_roundtrip_keeps_policy_compiler_matcher_and_budget(self):
        e, p = self.engine()
        e.begin_step("step1")
        e.record_query("email")
        state = json.loads(json.dumps(e.snapshot()))
        restored = e.fresh()
        before_calls = len(p.calls)
        restored.restore(state)
        self.assertEqual(restored.snapshot(), e.snapshot())
        self.assertEqual(len(p.calls), before_calls)
        self.assertIs(restored.compiler.__self__, restored)
        self.assertIs(restored.matcher.__self__, restored)
        self.assertEqual(restored.step_queries, ["email"])
        restored.ingest(Instruction("second", "File the signed document after email authorization."))
        self.assertEqual(len(restored.intentions), 2)
        self.assertEqual(restored.snapshot()["policy_variant"], "sbpm_minimal")

    def test_snapshot_policy_isolation_and_atomic_rejection(self):
        e, p = self.engine()
        for wrong in [PISEngine(p).snapshot(), GroundedPISEngine(p).snapshot(),
                      {**e.snapshot(), "policy_variant": "other"}]:
            with self.subTest(wrong=wrong.get("policy_variant")):
                before = e.snapshot()
                with self.assertRaises(ValueError):
                    e.restore(wrong)
                self.assertEqual(e.snapshot(), before)
        for other in (PISEngine(p), GroundedPISEngine(p)):
            with self.assertRaises(ValueError):
                other.restore(e.snapshot())

    def test_snapshot_bad_typed_suffix_does_not_mutate_live_engine(self):
        e, _ = self.engine()
        before = e.snapshot()
        bad = copy.deepcopy(before)
        bad["triggers"]["pm_000001"].update(clock_op="at", clock_time="09:15")
        with self.assertRaises(ValueError):
            e.restore(bad)
        self.assertEqual(e.snapshot(), before)


class SourceBoundEvaluationTests(unittest.TestCase):
    def case(self, name):
        return next(row for row in json.loads(DEFAULT_CASES.read_text())["cases"] if row["id"] == name)

    def test_evaluator_selects_source_bound_and_keeps_expected_labels_private(self):
        p = Provider()
        p.slots = metadata(watched_sources=["events"])
        p.reply = lambda payload: assessment(True, [payload["observations"][0]["id"]],
                                             [payload["observations"][0]["text"]])
        result = run_case(self.case("visible_breakfast"), p, engine_class=SourceBoundPISEngine)
        self.assertTrue(result["passed"])
        self.assertEqual(result["final_state"]["policy_variant"], "sbpm_minimal")
        self.assertEqual([phase_name(schema) for _, _, schema in p.calls],
                         ["extract", "compile_typed", "assess"])
        for _, payload, _ in p.calls:
            self.assertNotIn("expected_", json.dumps(payload))
            self.assertNotIn("action_contains_any", json.dumps(payload))
        restored = SourceBoundPISEngine(p)
        restored.restore(result["final_state"])
        self.assertEqual(restored.snapshot(), result["final_state"])

    def test_evaluator_check_reply_act_counts_actual_attempt(self):
        p = Provider()
        p.slots = metadata(watched_sources=["appointment_portal"])

        def reply(payload):
            observation = next((o for o in payload["observations"] if o["source"] == "appointment_portal"), None)
            return (assessment(True, [observation["id"]], [observation["text"]]) if observation
                    else assessment(source="appointment_portal"))

        p.reply = reply
        result = run_case(self.case("hidden_source_check_then_act"), p, engine_class=SourceBoundPISEngine)
        self.assertTrue(result["passed"])
        self.assertEqual(result["final_state"]["step_queries"], ["appointment_portal"])
        self.assertEqual((result["act_tp"], result["act_fp"], result["act_fn"]), (1, 0, 0))
        self.assertEqual(result["final_state"]["intentions"][0]["status"], "pending")

    def test_missing_registration_cannot_make_negative_case_pass(self):
        p = Provider()
        p.extract = False
        result = run_case(self.case("future_and_negative_event"), p, engine_class=SourceBoundPISEngine)
        self.assertFalse(result["passed"])
        self.assertFalse(result["registration_coverage"]["locker"])
        self.assertEqual(result["act_count"], 0)


if __name__ == "__main__":
    unittest.main()
