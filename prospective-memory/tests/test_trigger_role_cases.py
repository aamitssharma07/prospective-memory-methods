"""Frozen fixture/harness contracts only; scripted oracles are not model evidence."""

from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import unittest

from prospective_memory.evaluate_pis_grounded import run_case, validate_cases
from prospective_memory.method.source_bound_v3 import SourceBoundV3Engine


PATH = Path(__file__).resolve().parents[1] / "prospective_memory/examples/trigger_role_cases_v1.json"
FROZEN_SHA256 = "2494810e84cddae77bdcfeb919b9e0a971fdaa7ac9df7b8b322e6b97b0bcc8e5"
SUITE = json.loads(PATH.read_bytes())


class ScriptedOracle:
    """Use fixture answers offline solely to check scoring/control feasibility."""

    def __init__(self, case):
        self.expected_by_tick = {tick["id"]:
            tick["expected_rounds"][0][0]["kind"] for tick in case["ticks"]}
        self.calls = []

    def __call__(self, prompt, payload, schema):
        self.calls.append(copy.deepcopy(payload))
        key = next(iter(schema["properties"]))
        if key == "unit_classifications":
            return {key: [{"reason": "Scripted registration", "unit_id": payload["focus_unit_id"],
                           "classification": "new_request", "related_intention_id": ""}]}
        if key == "specifications":
            return {key: [{"operation_id": row["operation_id"], "target_id": "",
                "watched_sources": ["events"], "permitted_days": [],
                "recurring": "again" in row["complete_request_quote"],
                "clock_relation": "none", "required_clock_time": ""} for row in payload["operations"]]}
        if key == "assessments":
            observation = payload["observations"][0]
            # This offline oracle reads scorer context, never a live model.
            # Logging context is not part of the model request payload.
            tick = self.context["tick_id"]
            ready = self.expected_by_tick[tick] == "ACT"
            return {key: [{"reason": "Scripted fixture oracle", "all_conditions_met": ready,
                "evidence_ids": [observation["id"]] if ready else [], "missing_observation_source": ""}]}
        raise AssertionError(key)

    context = None


class TriggerRoleFixtureTests(unittest.TestCase):
    def test_frozen_hash_and_existing_schema(self):
        self.assertEqual(hashlib.sha256(PATH.read_bytes()).hexdigest(), FROZEN_SHA256)
        validate_cases(SUITE)

    def test_counts_and_globally_unique_public_ids(self):
        cases = SUITE["cases"]
        ticks = [tick for case in cases for tick in case["ticks"]]
        rounds = [row for tick in ticks for row in tick["expected_rounds"]]
        self.assertEqual((len(cases), len(ticks), len(rounds)), (8, 19, 19))
        self.assertEqual(Counter(d["kind"] for row in rounds for d in row), {"WAIT": 10, "ACT": 9})
        ids = [row["id"] for case in cases for row in case["instructions"]]
        ids += [row["id"] for tick in ticks for row in tick["observations"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 27)

    def test_one_origin_direct_evidence_positive_negative_and_no_execution(self):
        for case in SUITE["cases"]:
            with self.subTest(case=case["id"]):
                self.assertEqual(case["sources"], ["events"])
                self.assertEqual(case["queryable_sources"], [])
                self.assertEqual(len(case["instructions"]), 1)
                origin = case["instructions"][0]["id"]
                self.assertEqual([r["origin_id"] for r in case["expected_initial_records"]], [origin])
                kinds = set()
                for tick in case["ticks"]:
                    self.assertFalse(tick.get("instructions"))
                    self.assertFalse(tick.get("pull_responses"))
                    self.assertEqual(len(tick["observations"]), 1)
                    self.assertTrue(tick["observations"][0]["current"])
                    self.assertEqual(tick["expected_records"], [{"origin_id": origin,
                        "status": "pending", "unchanged_from_initial": True}])
                    self.assertEqual(len(tick["expected_rounds"]), 1)
                    self.assertEqual(len(tick["expected_rounds"][0]), 1)
                    kinds.add(tick["expected_rounds"][0][0]["kind"])
                self.assertEqual(kinds, {"ACT", "WAIT"})

    def test_initial_lexical_fragments_are_supported_by_original_public_text(self):
        for case in SUITE["cases"]:
            text = case["instructions"][0]["text"].casefold()
            record = case["expected_initial_records"][0]
            for field in ("action_contains_any", "condition_contains_any"):
                self.assertTrue(record[field])
                self.assertTrue(all(fragment.casefold() in text for fragment in record[field]))
            self.assertEqual((record["clock_op"], record["clock_time"]), ("none", ""))

    def test_two_occasions_are_distinct_cues_not_a_joint_gate(self):
        case = next(c for c in SUITE["cases"] if c["id"] == "two_requested_occasions_are_not_conjoined")
        self.assertEqual([tick["expected_rounds"][0][0]["kind"] for tick in case["ticks"]],
                         ["WAIT", "ACT", "WAIT", "ACT"])
        self.assertIn("second act has not started", case["ticks"][1]["observations"][0]["text"])
        self.assertNotEqual(case["ticks"][1]["observations"][0]["id"],
                            case["ticks"][3]["observations"][0]["id"])

    def test_existing_harness_can_score_oracle_without_completion_or_gold_payloads(self):
        for case in SUITE["cases"]:
            with self.subTest(case=case["id"]):
                oracle = ScriptedOracle(case)
                result = run_case(case, oracle, engine_class=SourceBoundV3Engine)
                self.assertTrue(result["passed"])
                self.assertEqual(result["act_fp"], 0)
                self.assertEqual(result["act_fn"], 0)
                self.assertEqual(len(result["final_state"]["intentions"]), 1)
                self.assertEqual(result["final_state"]["intentions"][0]["status"], "pending")
                self.assertTrue(all("expected_" not in json.dumps(payload) for payload in oracle.calls))


if __name__ == "__main__":
    unittest.main()
