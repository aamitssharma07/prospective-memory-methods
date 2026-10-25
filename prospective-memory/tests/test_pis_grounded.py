"""Scripted contracts for the opt-in variant, NOT model-quality measurements."""

import copy
import json
import unittest

from prospective_memory.core import Instruction, Observation
from prospective_memory.baselines.pis import PISEngine
from prospective_memory.pis_grounded import GroundedPISEngine
from prospective_memory.adapters.pmbench import PMBenchAdapter


def change(**overrides):
    return {"op": "register", "target_id": "", "action": "Send report",
            "condition": "when the reviewer approves it", "sources": ["email"],
            "days": [], "repeat": False, "clock_op": "none", "clock_time": "",
            "evidence_quote": "Send report when the reviewer approves it.", **overrides}


class Provider:
    def __init__(self):
        self.changes = [change()]
        self.review = "supported"
        self.response = {"state": "unknown", "reason": "Missing evidence",
                         "evidence_ids": [], "evidence_quotes": [], "missing_source": "email"}
        self.calls = []
        self.fail_first_review = False

    def __call__(self, system, payload, schema):
        phase = next(iter(schema["properties"]))
        self.calls.append((phase, copy.deepcopy(payload)))
        if phase == "changes":
            return {"changes": copy.deepcopy(self.changes)}
        if phase == "reviews":
            if self.fail_first_review:
                self.fail_first_review = False
                raise RuntimeError("scripted outage")
            return {"reviews": [{"verdict": self.review, "reason": "Scripted review"}]}
        if phase == "verdict":
            return {"verdict": "supported", "reason": "Scripted verification"}
        return {"assessments": [copy.deepcopy(self.response)]}


class GroundedPISTests(unittest.TestCase):
    def engine(self, register=True):
        p = Provider()
        e = GroundedPISEngine(p, ("events", "clock", "email", "sensor"),
                              queryable_sources=("clock", "email", "sensor"))
        if register:
            e.ingest(Instruction("request", p.changes[0]["evidence_quote"]))
        return e, p

    def satisfied(self, p, ref="reply", quote="Reviewer approved the report."):
        p.response.update(state="satisfied", reason="Trigger supported",
                          evidence_ids=[ref], evidence_quotes=[quote], missing_source="")

    def test_supported_current_evidence_maps_to_act_without_execution(self):
        e, p = self.engine()
        self.satisfied(p)
        ds = e.tick([Observation("reply", "Reviewer approved the report.", "email")])
        self.assertEqual(ds[0].kind, "ACT")
        self.assertEqual(e.intentions[ds[0].intention_id].status, "pending")
        self.assertEqual(p.calls[-1][1]["original_instructions"][0]["id"], "request")

    def test_missing_evidence_maps_to_check(self):
        e, _ = self.engine()
        d = e.tick([])[0]
        self.assertEqual((d.kind, d.source), ("CHECK", "email"))

    def test_observed_channel_cannot_be_requeried(self):
        e, _ = self.engine()
        self.assertEqual(e.tick([Observation("reply", "No updates", "email")])[0].kind, "WAIT")
        self.assertIn("unavailable", e.errors[-1]["error"])

    def test_no_budget_does_not_convert_unknown_to_act(self):
        e, _ = self.engine()
        e.begin_step("s1")
        e.record_query("email")
        e.record_query("sensor")
        self.assertEqual(e.tick([])[0].kind, "WAIT")
        self.assertTrue(e.exhausted_query_guidance())

    def test_false_condition_waits(self):
        e, p = self.engine()
        p.response.update(state="not_satisfied", evidence_ids=["reply"],
                          evidence_quotes=["Rejected"], missing_source="")
        self.assertEqual(e.tick([Observation("reply", "Rejected", "email")])[0].kind, "WAIT")

    def test_unknown_push_event_waits_without_fabricated_tool(self):
        e, p = self.engine(False)
        p.changes = [change(sources=["events"])]
        e.ingest(Instruction("request", p.changes[0]["evidence_quote"]))
        p.response.update(missing_source="")
        self.assertEqual(e.tick([])[0].kind, "WAIT")

    def test_forged_missing_or_stale_evidence_cannot_act(self):
        for ref, quote, current in [("missing", "Approved", True),
                                    ("reply", "Approved", True),
                                    ("reply", "Rejected", False),
                                    ("request", "Rejected", True)]:
            with self.subTest(ref=ref, quote=quote, current=current):
                e, p = self.engine()
                self.satisfied(p, ref, quote)
                self.assertEqual(e.tick([Observation("reply", "Rejected", "email", current)])[0].kind, "WAIT")

    def test_unwatched_source_cannot_support_act(self):
        e, p = self.engine()
        self.satisfied(p)
        self.assertEqual(e.tick([Observation("reply", "Reviewer approved the report.", "sensor")])[0].kind, "WAIT")

    def test_satisfied_with_missing_source_or_unpaired_quotes_rejected(self):
        for updates in [{"missing_source": "email"}, {"evidence_quotes": []},
                        {"evidence_ids": [], "evidence_quotes": []}]:
            with self.subTest(updates=updates):
                e, p = self.engine()
                self.satisfied(p)
                p.response.update(updates)
                self.assertEqual(e.tick([Observation("reply", "Reviewer approved the report.", "email")])[0].kind, "WAIT")

    def test_invented_meal_clock_downgraded_and_quote_preserved(self):
        e, p = self.engine(False)
        quote = "Take the tablet at breakfast and dinner."
        p.changes = [change(action="Take the tablet", condition="every day", sources=["events", "clock"],
                            evidence_quote=quote, clock_op="at", clock_time="08:00")]
        key = e.ingest(Instruction("meal", quote))[0]
        self.assertEqual(e.triggers[key]["clock_op"], "none")
        self.assertEqual(e.intentions[key].condition, quote)
        self.assertEqual(p.calls[-1][1]["proposed_change"]["clock_time"], "")
        self.satisfied(p, "breakfast", "Breakfast has begun.")
        self.assertEqual(e.tick([Observation("breakfast", "Breakfast has begun.")])[0].kind, "ACT")

    def test_literal_clock_retained_and_does_not_need_calendar_confirmation(self):
        e, p = self.engine(False)
        quote = "Send the report at 9:15."
        p.changes = [change(evidence_quote=quote, condition="at 9:15", sources=["clock"],
                            clock_op="at", clock_time="09:15")]
        key = e.ingest(Instruction("timed", quote))[0]
        self.assertEqual(e.triggers[key]["clock_time"], "09:15")
        self.assertEqual(e.tick([])[0].source, "clock")
        self.satisfied(p, "clock", "Time 09:15")
        self.assertEqual(e.tick([Observation("clock", "Time 09:15", "clock")])[0].kind, "ACT")

    def test_clock_match_does_not_override_missing_other_prerequisite(self):
        e, p = self.engine(False)
        quote = "At 09:15 send report only if approved."
        p.changes = [change(evidence_quote=quote, condition="At 09:15 only if approved",
                            sources=["clock", "email"], clock_op="at", clock_time="09:15")]
        e.ingest(Instruction("timed", quote))
        self.assertEqual(e.tick([Observation("clock", "Time 09:15", "clock")])[0].kind, "CHECK")

    def test_wrong_target_update_rejected_preserving_old_and_new_input(self):
        e, p = self.engine()
        before = copy.deepcopy(e.intentions)
        quote = "Bring the parcel when the desk opens."
        p.changes = [change(op="override", target_id="pm_000001", action="Bring the parcel",
                            condition="when desk opens", evidence_quote=quote)]
        p.review = "unsupported"
        self.assertEqual(e.ingest(Instruction("new", quote)), [])
        self.assertEqual(e.intentions, before)
        self.assertEqual(e.instructions["new"].text, quote)
        self.assertEqual(p.calls[-1][1]["target_original_instructions"][0]["id"], "request")

    def test_supported_revision_preserves_identity_then_cancel_closes(self):
        e, p = self.engine()
        quote = "Send it only after the editor approves instead."
        p.changes = [change(op="override", target_id="pm_000001", evidence_quote=quote,
                            condition="when editor approves")]
        e.ingest(Instruction("update", quote))
        self.assertEqual(e.intentions["pm_000001"].revision, 2)
        self.assertEqual(e.intentions["pm_000001"].instruction_ids, ("request", "update"))
        p.changes = [change(op="cancel", target_id="pm_000001", evidence_quote="Cancel the report.")]
        e.ingest(Instruction("cancel", "Cancel the report."))
        self.assertEqual(e.intentions["pm_000001"].status, "cancelled")
        self.assertEqual(e.tick([]), [])

    def test_review_outage_does_not_drop_valid_sibling(self):
        e, p = self.engine(False)
        p.fail_first_review = True
        p.changes = [change(), change(action="Archive report")]
        self.assertEqual(len(e.ingest(Instruction("request", p.changes[0]["evidence_quote"]))), 1)
        self.assertEqual(next(iter(e.intentions.values())).action, "Archive report")
        self.assertTrue(e.errors)

    def test_duplicate_registration_still_deduplicates(self):
        e, p = self.engine()
        e.ingest(Instruction("again", p.changes[0]["evidence_quote"]))
        self.assertEqual(len(e.intentions), 1)

    def test_narration_rejected_by_review(self):
        e, p = self.engine(False)
        p.changes = [change(evidence_quote="The office is quiet.")]
        p.review = "unsupported"
        self.assertEqual(e.ingest(Instruction("scene", "The office is quiet.")), [])

    def test_act_delivery_deduplicated_and_only_host_closes(self):
        e, p = self.engine()
        self.satisfied(p)
        obs = [Observation("reply", "Reviewer approved the report.", "email")]
        self.assertEqual(e.tick(obs)[0].kind, "ACT")
        self.assertEqual(e.tick(obs)[0].kind, "WAIT")
        e.acknowledge("pm_000001", "completed")
        self.assertEqual(e.tick(obs), [])

    def test_snapshot_roundtrip_policy_isolation_and_atomic_failure(self):
        e, p = self.engine()
        state = json.loads(json.dumps(e.snapshot()))
        restored = e.fresh()
        restored.restore(state)
        self.assertEqual(restored.snapshot(), e.snapshot())
        self.assertIs(restored.matcher.__self__, restored)
        self.assertEqual(restored.tick([])[0].kind, "CHECK")
        for wrong in [PISEngine(p).snapshot(), {**state, "policy_variant": "unknown"}]:
            before = restored.snapshot()
            with self.assertRaises(ValueError):
                restored.restore(wrong)
            self.assertEqual(restored.snapshot(), before)
        with self.assertRaises(ValueError):
            PISEngine(p).restore(state)

    def test_adapter_check_reply_act_and_choice_does_not_complete(self):
        e, p = self.engine(False)
        adapter = PMBenchAdapter(e)
        messages = [
            {"role": "system", "content": "Available state channels: email."},
            {"role": "user", "content": p.changes[0]["evidence_quote"]},
        ]
        self.assertIn('"decision": "CHECK"', adapter.context_for(messages))
        p.changes = []
        self.satisfied(p, "message_3")
        messages += [
            {"role": "assistant", "content": '{"action":"query_state","channel":"email"}'},
            {"role": "user", "content": "State [email]: Reviewer approved the report."},
        ]
        self.assertIn('"decision": "ACT"', adapter.context_for(messages))
        state = json.loads(json.dumps(adapter.snapshot()))
        restored = PMBenchAdapter(e.fresh())
        restored.restore(state)
        self.assertEqual(json.loads(json.dumps(restored.snapshot())), state)
        messages.append({"role": "assistant", "content": '{"action":"choose","task_ids":["task_1"]}'})
        adapter.context_for(messages)
        self.assertEqual(e.intentions["pm_000001"].status, "pending")


if __name__ == "__main__":
    unittest.main()
