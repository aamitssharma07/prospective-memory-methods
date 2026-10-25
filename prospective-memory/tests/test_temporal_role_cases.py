"""Static temporal-role fixture checks only; no callbacks or inference."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import unittest

from prospective_memory.evaluate_pis_grounded import validate_cases


DIRECTORY = Path(__file__).resolve().parents[1] / "prospective_memory/examples"
FROZEN = {
    "temporal_role_cases_v1.json": "4a99ad97c33d0488db9e59238365ebe5b1955cf34024388efcf4f118f08bcbf1",
    "temporal_role_cases_v2.json": "e61d3953a810241ae9a3ea7e501fc85df8022ad93b310504b29492f53ffbae22",
}
SUITES = {name: json.loads((DIRECTORY / name).read_bytes()) for name in FROZEN}


class TemporalRoleFixtureTests(unittest.TestCase):
    def test_frozen_hashes_and_existing_schema(self):
        for name, digest in FROZEN.items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((DIRECTORY / name).read_bytes()).hexdigest(), digest)
                validate_cases(SUITES[name])

    def test_counts_unique_ids_and_positive_negative_coverage(self):
        for suite in SUITES.values():
            cases = suite["cases"]
            ticks = [tick for case in cases for tick in case["ticks"]]
            observations = [o for tick in ticks for o in tick["observations"]]
            instructions = [i for case in cases for i in case["instructions"]]
            self.assertEqual((len(cases), len(ticks), len(observations), len(instructions)), (4, 8, 12, 4))
            for rows in (cases, ticks, observations, instructions):
                self.assertEqual(len({row["id"] for row in rows}), len(rows))
            public_ids = [row["id"] for row in instructions + observations]
            self.assertEqual(len(public_ids), len(set(public_ids)))
            counts = Counter(row["kind"] for tick in ticks for rnd in tick["expected_rounds"] for row in rnd)
            self.assertEqual(counts, {"WAIT": 4, "ACT": 4})
            for case in cases:
                self.assertEqual([t["expected_rounds"][0][0]["kind"] for t in case["ticks"]], ["WAIT", "ACT"])

    def test_one_origin_unchanged_pending_records_and_no_fabricated_queries(self):
        for suite in SUITES.values():
            for case in suite["cases"]:
                self.assertEqual(len(case["instructions"]), 1)
                origin = case["instructions"][0]["id"]
                self.assertEqual([row["origin_id"] for row in case["expected_initial_records"]], [origin])
                for tick in case["ticks"]:
                    self.assertNotIn("instructions", tick)
                    self.assertNotIn("pull_responses", tick)
                    self.assertEqual(tick["expected_records"], [{"origin_id": origin,
                        "status": "pending", "unchanged_from_initial": True}])
                    self.assertEqual(len(tick["expected_rounds"]), 1)
                    self.assertEqual(len(tick["expected_rounds"][0]), 1)
                    self.assertTrue(all(o["current"] for o in tick["observations"]))
                    # Even advertised pull channels already have current data.
                    self.assertTrue(set(case["queryable_sources"]) <=
                                    {o["source"] for o in tick["observations"]})

    def test_lexical_rubrics_are_literal_original_request_fragments(self):
        for suite in SUITES.values():
            for case in suite["cases"]:
                request = case["instructions"][0]["text"].casefold()
                record = case["expected_initial_records"][0]
                self.assertEqual(record["instruction_ids"], [case["instructions"][0]["id"]])
                for field in ("action_contains_any", "condition_contains_any"):
                    self.assertTrue(record[field])
                    self.assertTrue(all(fragment.casefold() in request for fragment in record[field]))

    def test_v2_only_strengthens_first_public_evidence_and_never_changes_gold(self):
        v1, v2 = SUITES["temporal_role_cases_v1.json"], SUITES["temporal_role_cases_v2.json"]
        self.assertEqual(v1["cases"][1:], v2["cases"][1:])
        old, new = v1["cases"][0], v2["cases"][0]
        for field in ("sources", "queryable_sources", "instructions", "expected_initial_records"):
            self.assertEqual(old[field], new[field])
        for first, second in zip(old["ticks"], new["ticks"]):
            for field in ("id", "expected_records", "expected_rounds"):
                self.assertEqual(first[field], second[field])
            self.assertEqual(first["observations"][0], second["observations"][0])
            self.assertNotEqual(first["observations"][1]["text"], second["observations"][1]["text"])
        self.assertIn("not yet available", new["ticks"][0]["observations"][1]["text"])
        positive = new["ticks"][1]["observations"][1]["text"]
        self.assertIn("currently approved", positive)
        self.assertIn("issuance time is not recorded", positive)
        self.assertNotRegex(positive, r"\d\d:\d\d")

    def test_action_clock_gate_is_not_applied_to_deadline_or_order_prerequisites(self):
        suite = SUITES["temporal_role_cases_v2.json"]
        self.assertEqual([(case["expected_initial_records"][0]["clock_op"],
                           case["expected_initial_records"][0]["clock_time"]) for case in suite["cases"]],
                         [("at", "16:35"), ("none", ""), ("none", ""), ("none", "")])
        deadline = suite["cases"][1]
        self.assertIn("before 05:25", deadline["instructions"][0]["text"])
        self.assertIn("05:28", deadline["ticks"][0]["observations"][0]["text"])
        self.assertIn("05:10", deadline["ticks"][1]["observations"][0]["text"])
        self.assertIn("different pottery batch", deadline["ticks"][1]["observations"][0]["text"])
        ordered = suite["cases"][2]
        self.assertIn("a flash before closure does not qualify", ordered["instructions"][0]["text"])
        self.assertIn("No flash has occurred since closure", ordered["ticks"][0]["observations"][0]["text"])
        self.assertIn("this new flash occurs after closure", ordered["ticks"][1]["observations"][0]["text"])

    def test_evidence_channel_is_distinct_from_recipient_delivery_channel(self):
        case = SUITES["temporal_role_cases_v2.json"]["cases"][3]
        record = case["expected_initial_records"][0]
        self.assertEqual(record["required_sources"], ["hatch_sensor"])
        self.assertIn("Notify Tavi through crew_chat", case["instructions"][0]["text"])
        self.assertEqual(case["queryable_sources"], ["hatch_sensor", "crew_chat"])
        positive = {o["source"]: o["text"] for o in case["ticks"][1]["observations"]}
        self.assertIn("latched now", positive["hatch_sensor"])
        self.assertIn("No hatch-readiness notification has been sent", positive["crew_chat"])


if __name__ == "__main__":
    unittest.main()
