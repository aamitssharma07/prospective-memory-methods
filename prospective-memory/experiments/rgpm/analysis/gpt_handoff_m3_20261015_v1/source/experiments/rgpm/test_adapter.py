"""Regression coverage for unresolved readiness at the actor handoff."""

import copy
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from adapter import RGPMAdapter
from prospective_memory.adapters.pmbench import PMBenchAdapter
from prospective_memory.core import Decision, Intention, Observation
from analyze import observed_stages


class GuidanceTests(unittest.TestCase):
    def test_wait_reason_stays_out_of_actor_handoff(self):
        engine = SimpleNamespace(intentions={"pending": SimpleNamespace(
            action="Send the report", condition="approval arrives")})
        adapter = object.__new__(RGPMAdapter)
        adapter.engine = engine
        adapter.last_decisions = [Decision("WAIT", "pending", "Approval has not arrived")]
        with patch.object(PMBenchAdapter, "context_for", return_value="existing guidance"):
            context = adapter.context_for([])
        self.assertNotIn("Approval has not arrived", context)
        self.assertNotIn("Send the report", context)
        self.assertIn("existing guidance", context)
        self.assertIn("task_ids=[]", context)
        self.assertEqual(adapter.last_decisions[0].reason, "Approval has not arrived")

    def test_removed_record_is_not_rendered_as_waiting(self):
        adapter = object.__new__(RGPMAdapter)
        adapter.engine = SimpleNamespace(intentions={})
        adapter.last_decisions = [Decision("WAIT", "removed", "stale reason")]
        with patch.object(PMBenchAdapter, "context_for", return_value=""):
            self.assertNotIn("stale reason", adapter.context_for([]))

    def query_adapter(self):
        intention = Intention("remember", "Send the invoice", "when approval arrives",
                              ("email",), scope="*", revision=2)
        engine = SimpleNamespace(intentions={intention.id: intention},
                                 sources=("events", "clock", "email"), queryable_sources=("clock", "email"),
                                 step_queries=["clock"], step_query_budget=2)
        adapter = RGPMAdapter(engine, guidance="query_first", query_handoff="legacy")
        adapter.scope = "Monday"
        adapter.current_observations = [Observation("scene", "A notification arrives."),
                                        Observation("time", "09:00", "clock")]
        adapter.last_decisions = [Decision("CHECK", intention.id, "Approval needs observation", source="email")]
        return adapter

    def test_query_first_offers_exact_source_with_remaining_budget_without_execution(self):
        adapter = self.query_adapter()
        before = copy.deepcopy(adapter.engine.__dict__)
        with patch.object(PMBenchAdapter, "context_for", return_value="existing proposals"):
            context = adapter.context_for([])
        plan = adapter.last_query_plan
        self.assertEqual(plan["next_action"], {"action": "query_state", "choice": "NONE",
                                             "task_ids": [], "channel": "email"})
        self.assertEqual(plan["remaining_queries_this_step"], 1)
        self.assertEqual(plan["actual_query_attempts_this_step"], ["clock"])
        self.assertEqual(plan["revision"], 2)
        self.assertIn("Before advancing", context)
        self.assertIn("CHECK alone never authorizes task selection", context)
        self.assertEqual(adapter.engine.__dict__, before)

    def test_query_first_does_not_repeat_observed_attempted_or_exhausted_queries(self):
        for mode in ("observed", "attempted", "exhausted", "unknown_attempts"):
            adapter = self.query_adapter()
            if mode == "observed":
                adapter.current_observations.append(Observation("reply", "Pending", "email"))
            elif mode == "attempted":
                adapter.engine.step_queries = ["email"]
            elif mode == "exhausted":
                adapter.engine.step_queries = ["clock", "clock"]
            else:
                adapter.engine.step_queries = ["unknown", "clock"]
            self.assertIsNone(adapter._query_plan(), mode)

    def test_query_first_ignores_stale_observations_but_not_current_ones(self):
        adapter = self.query_adapter()
        adapter.current_observations.append(Observation("old", "No updates", "email", current=False))
        self.assertEqual(adapter._query_plan()["next_action"]["channel"], "email")

    def test_query_first_does_not_convert_wait_act_cancellation_or_wrong_scope_to_query(self):
        for mode in ("WAIT", "ACT", "cancelled", "scope"):
            adapter = self.query_adapter()
            if mode in {"WAIT", "ACT"}:
                adapter.last_decisions = [Decision(mode, "remember", "No CHECK proposal")]
            else:
                intention = adapter.engine.intentions["remember"]
                adapter.engine.intentions["remember"] = replace(intention, **(
                    {"status": "cancelled"} if mode == "cancelled" else {"scope": "Tuesday"}))
            self.assertIsNone(adapter._query_plan(), mode)

    def test_query_first_rejects_forged_capability_and_missing_ledger(self):
        adapter = self.query_adapter()
        adapter.last_decisions = [Decision("CHECK", "remember", "Forged", source="bank")]
        with self.assertRaises(ValueError):
            adapter._query_plan()
        adapter = self.query_adapter()
        adapter.engine.step_queries = None
        with self.assertRaises(ValueError):
            adapter._query_plan()

    def test_query_first_keeps_context_when_no_check_and_other_modes_unchanged(self):
        adapter = self.query_adapter()
        adapter.last_decisions = [Decision("WAIT", "remember", "Unknown")]
        with patch.object(PMBenchAdapter, "context_for", return_value="existing proposals"):
            self.assertEqual(adapter.context_for([]), "existing proposals")
            self.assertIsNone(adapter.last_query_plan)
            adapter.guidance = "none"
            self.assertEqual(adapter.context_for([]), "existing proposals")

    def test_query_uptake_diagnostic_links_each_actor_attempt_to_its_own_cycle(self):
        plan = self.query_adapter()._query_plan()
        trace = {"event": "memory_cycle", "session_id": "current", "cycle": 7,
                 "step_key": ["Monday", "scene"], "query_plan": plan,
                 "before": {"engine": {}}, "after": {"engine": {}}}
        for action, expected in (({"action": "query_state", "channel": "email"}, "followed"),
                                 ({"action": "choose", "task_ids": []}, "advanced_without_offered_check"),
                                 ({"action": "check_time", "channel": "clock"}, "different_action"),
                                 (None, "invalid_actor_response")):
            calls = [{"role": "actor", "cycle": cycle, "call_id": str(cycle),
                      "step_key": trace["step_key"],
                      "session_id": "current",
                      "phase": "actor", "parsed": action, "valid": action is not None} for cycle in (6, 7)]
            calls.append({**calls[-1], "session_id": "interrupted", "call_id": "prior_session"})
            stages = observed_stages([trace], [1], calls)
            uptake = [stage for stage in stages if stage["stage"] == "actor_check_uptake"]
            self.assertEqual(len(uptake), 1)
            self.assertEqual(uptake[0]["call_id"], "7")
            self.assertEqual(uptake[0]["uptake"], expected)
