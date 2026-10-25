"""Runtime contracts with scripted judgments, not evidence of model competence."""
import copy
import json
import unittest

from prospective_memory.core import Instruction, Observation
from prospective_memory.baselines.pis import PISEngine, clock_minutes


def row(**updates):
    return {"op": "register", "target_id": "", "action": "Send report", "condition": "At 17:00 if approved",
            "evidence_quote": "At 17:00 send report if approved.", "sources": ["events", "clock", "email"],
            "days": ["Friday"], "repeat": False, "clock_op": "at", "clock_time": "17:00", **updates}


class Provider:
    def __init__(self):
        self.changes = [row()]
        self.kind = "ACT"
        self.source = "email"
        self.verdict = "supported"
        self.payloads = []

    def __call__(self, system, payload, schema):
        self.payloads.append(payload)
        if "changes" in schema["properties"]:
            return {"changes": copy.deepcopy(self.changes)}
        if "verdict" in schema["properties"]:
            return {"verdict": self.verdict, "reason": "Fixture"}
        return {"decisions": [{"kind": self.kind, "intention_id": payload["intention"]["id"],
                               "reason": "Fixture", "source": self.source if self.kind == "CHECK" else "",
                               "evidence_ids": [o["id"] for o in payload["observations"]] if self.kind == "ACT" else []}]}


class PISTests(unittest.TestCase):
    def engine(self, verified=False, budget=1):
        p = Provider()
        e = PISEngine(p, ("events", "clock", "email"), budget, ("clock", "email"), verified)
        e.ingest(Instruction("i", "At 17:00 send report if approved.", "Friday"))
        return e, p

    def test_weekday_clock_filters_before_inference(self):
        e, p = self.engine()
        for scope, time in [("Thursday", "17:00"), ("Friday", "16:00"), ("Friday", "18:00")]:
            ds = e.tick([Observation(time, time, "clock")], scope)
            self.assertEqual(ds[0].kind, "WAIT")
        self.assertEqual(len(p.payloads), 1)
        self.assertEqual(e.tick([Observation("now", "17:00", "clock")], "Friday")[0].kind, "ACT")

    def test_missing_clock_is_check_not_guessed_time_from_events(self):
        e, p = self.engine()
        ds = e.tick([Observation("event", "At 17:00 send report if approved.")], "Friday")
        self.assertEqual((ds[0].kind, ds[0].source), ("CHECK", "clock"))
        self.assertEqual(len(p.payloads), 1)

    def test_zero_budget_missing_clock_waits(self):
        e, _ = self.engine(budget=0)
        self.assertEqual(e.tick([], "Friday")[0].kind, "WAIT")

    def test_clock_parser_rejects_ambiguous_or_invalid(self):
        self.assertEqual(clock_minutes("Time 17:30 | Stopwatch: 540 min"), 1050)
        self.assertIsNone(clock_minutes("25:00"))
        self.assertIsNone(clock_minutes("Old 16:30, new 17:30"))

    def test_reschedule_keeps_identity_cancellation_closes(self):
        e, p = self.engine()
        key = next(iter(e.intentions))
        p.changes = [row(op="reschedule", target_id=key, evidence_quote="Move it to 18:00.",
                         condition="At 18:00 if approved", clock_time="18:00")]
        e.ingest(Instruction("u", "Move it to 18:00.", "Friday"))
        self.assertEqual(e.intentions[key].revision, 2)
        self.assertEqual(e.triggers[key]["clock_time"], "18:00")
        p.changes = [row(op="cancel", target_id=key, evidence_quote="Cancel the report.",
                         action="", condition="", days=[], sources=[], clock_op="none", clock_time="")]
        e.ingest(Instruction("c", "Cancel the report.", "Friday"))
        self.assertEqual(e.tick([], "Friday"), [])
        restored = e.fresh()
        restored.restore(json.loads(json.dumps(e.snapshot())))
        self.assertEqual(restored.snapshot(), e.snapshot())

    def test_bad_row_does_not_drop_other_rows(self):
        p = Provider()
        p.changes = [row(clock_time="25:00"), row()]
        e = PISEngine(p, ("events", "clock", "email"))
        e.ingest(Instruction("i", "At 17:00 send report if approved.", "Friday"))
        self.assertEqual(len(e.intentions), 1)
        self.assertTrue(e.errors)

    def test_rejected_second_revision_cannot_replace_applied_clock_gate(self):
        e, p = self.engine()
        key = next(iter(e.intentions))
        quote = "Move it to 18:00, not 19:00."
        p.changes = [row(op="reschedule", target_id=key, evidence_quote=quote,
                         condition=f"At {hour}:00 if approved", clock_time=f"{hour}:00")
                     for hour in (18, 19)]
        e.ingest(Instruction("u", quote, "Friday"))
        self.assertEqual(e.intentions[key].revision, 2)
        self.assertIn("18:00", e.intentions[key].condition)
        self.assertEqual(e.triggers[key]["clock_time"], "18:00")
        restored = e.fresh()
        restored.restore(json.loads(json.dumps(e.snapshot())))
        self.assertEqual(restored.snapshot(), e.snapshot())

    def test_failed_provider_preserves_raw_input(self):
        def fail(*args):
            raise RuntimeError("provider failed")
        e = PISEngine(fail)
        i = Instruction("i", "At noon send the report.")
        e.ingest(i)
        self.assertEqual(e.instructions["i"], i)
        self.assertTrue(e.errors)

    def test_verifier_uses_original_and_can_reject(self):
        e, p = self.engine(verified=True)
        p.verdict = "unsupported"
        self.assertEqual(e.tick([Observation("t", "17:00", "clock")], "Friday")[0].kind, "WAIT")
        self.assertEqual(p.payloads[-1]["original_instructions"][0]["id"], "i")
        self.assertEqual(len(e.verification_log), 1)

    def test_without_verifier_no_source_history_sent_to_decider(self):
        e, p = self.engine()
        e.tick([Observation("t", "17:00", "clock")], "Friday")
        self.assertNotIn("original_instructions", p.payloads[-1])
        self.assertEqual(e.verification_log, [])

    def test_query_budget_and_source_dedup_before_generation(self):
        e, p = self.engine()
        p.changes = [row(action="Send second report", evidence_quote="Send second report if ready.",
                         days=[], clock_op="none", clock_time="")]
        e.ingest(Instruction("i2", "Send second report if ready."))
        p.kind = "CHECK"
        ds = e.tick([Observation("t", "17:00", "clock")], "Friday")
        self.assertEqual(sum(d.kind == "CHECK" for d in ds), 1)
        self.assertEqual(p.payloads[-1]["check_sources"], [])
        self.assertEqual(p.payloads[-1]["remaining_check_budget"], 0)

    def test_stale_clock_cannot_fire_and_already_observed_channel_not_requeried(self):
        e, p = self.engine()
        self.assertEqual(e.tick([Observation("t", "17:00", "clock", False)], "Friday")[0].kind, "CHECK")
        p.kind = "CHECK"
        ds = e.tick([Observation("new", "17:00", "clock"), Observation("mail", "Nothing", "email")], "Friday")
        self.assertEqual(ds[0].kind, "WAIT")
        self.assertEqual(p.payloads[-1]["check_sources"], [])

    def test_restore_is_atomic_and_callbacks_bound(self):
        e, p = self.engine(verified=True)
        state = json.loads(json.dumps(e.snapshot()))
        other = e.fresh()
        other.restore(state)
        self.assertEqual(json.loads(json.dumps(other.snapshot())), state)
        self.assertIs(other.matcher.__self__, other)
        bad = copy.deepcopy(state)
        bad["triggers"]["pm_000001"]["clock_time"] = "99:99"
        with self.assertRaises(ValueError):
            other.restore(bad)
        self.assertEqual(json.loads(json.dumps(other.snapshot())), state)
        bad["triggers"]["pm_000001"]["clock_time"] = "18:00"
        with self.assertRaises(ValueError):
            other.restore(bad)

    def test_host_completion_not_proposal_closes_once_and_repeat_stays_pending(self):
        e, p = self.engine()
        key = next(iter(e.intentions))
        e.tick([Observation("t", "17:00", "clock")], "Friday")
        self.assertEqual(e.intentions[key].status, "pending")
        e.acknowledge(key, "completed")
        self.assertEqual(e.intentions[key].status, "completed")

    def test_non_temporal_host_scope_not_discarded(self):
        p = Provider()
        e = PISEngine(p, ("events", "clock", "email"))
        e.ingest(Instruction("i", "At 17:00 send report if approved.", "project-a"))
        self.assertEqual(e.tick([], "project-b"), [])

    def test_not_before_allows_later_but_retains_semantic_judge(self):
        e, p = self.engine()
        e.triggers["pm_000001"]["clock_op"] = "not_before"
        p.kind = "WAIT"
        ds = e.tick([Observation("t", "18:00", "clock")], "Friday")
        self.assertEqual(ds[0].kind, "WAIT")
        self.assertEqual(len(p.payloads), 2)

    def test_different_days_or_times_are_not_duplicate_intentions(self):
        p = Provider()
        e = PISEngine(p, ("events", "clock", "email"))
        for n, (days, time) in enumerate([(["Monday"], "17:00"), (["Friday"], "17:00"),
                                          (["Friday"], "18:00")]):
            p.changes = [row(days=days, clock_time=time)]
            e.ingest(Instruction(str(n), "At 17:00 send report if approved."))
        self.assertEqual(len(e.intentions), 3)
        # A genuinely identical record still deduplicates.
        e.ingest(Instruction("duplicate", "At 17:00 send report if approved."))
        self.assertEqual(len(e.intentions), 3)

    def test_stable_schema_still_rejects_wrong_intention_and_unknown_update(self):
        e, p = self.engine()
        def wrong(system, payload, schema):
            result = p(system, payload, schema)
            if "decisions" in result:
                result["decisions"][0]["intention_id"] = "pm_999999"
            return result
        e.request = wrong
        self.assertEqual(e.tick([Observation("t", "17:00", "clock")], "Friday")[0].kind, "WAIT")
        p.changes = [row(op="cancel", target_id="pm_999999", evidence_quote="Cancel it.")]
        e.ingest(Instruction("u", "Cancel it."))
        self.assertEqual(e.intentions["pm_000001"].status, "pending")

    def test_actual_wrong_queries_exhaust_step_budget_and_reset(self):
        e, p = self.engine()
        e.begin_step("step1")
        e.record_query("wrong_channel")
        e.record_query("wrong_channel")
        self.assertEqual(e.tick([], "Friday")[0].kind, "WAIT")
        self.assertTrue(e.exhausted_query_guidance())
        state = json.loads(json.dumps(e.snapshot()))
        restored = e.fresh()
        restored.restore(state)
        self.assertEqual(restored.step_queries, ["wrong_channel", "wrong_channel"])
        restored.begin_step("step1")
        self.assertEqual(len(restored.step_queries), 2)
        restored.begin_step("step2")
        self.assertEqual(restored.tick([], "Friday")[0].kind, "CHECK")
        self.assertFalse(restored.exhausted_query_guidance())

    def test_runaway_actor_queries_abort_without_fabricating_action(self):
        e, _ = self.engine()
        e.begin_step("step1")
        for _ in range(12):
            e.record_query("email")
        with self.assertRaises(RuntimeError):
            e.record_query("email")


if __name__ == "__main__":
    unittest.main()
