"""Offline rubric/runner contracts; no model calls or benchmark inputs."""

import copy
from dataclasses import asdict, replace
import json
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from prospective_memory.core import Instruction, Intention
from prospective_memory.method.evaluate_registration_cases import (
    DEFAULT_CASES, main, run_case, score_stage, summarize, validate_cases,
)


def rubric(key="gold_only_key", **updates):
    return {"key": key, "origin_id": "public_request", "action_fragments": ["Pack the lens"],
            "condition_fragments": ["case opens"], "forbidden_action_fragments": [],
            "sources": ["events"], "days": [], "clock_op": "none", "clock_time": "",
            "repeat": False, **updates}


def fixture_engine(records=1):
    instruction = Instruction("public_request", "Pack the lens when the case opens.")
    items = {f"pm_{i:06d}": Intention(f"pm_{i:06d}", "Pack the lens", "case opens", ("events",),
                                    instruction_ids=(instruction.id,), evidence_quote=instruction.text)
             for i in range(1, records + 1)}
    return SimpleNamespace(intentions=items, instructions={instruction.id: instruction},
                           triggers={key: {"days": [], "clock_op": "none", "clock_time": ""} for key in items})


class PublicOnlyEngine:
    """Deterministic harness fixture, not a registration-method implementation."""
    POLICY = "fixture_no_model"

    def __init__(self, request, sources, queryable_sources):
        self.request, self.sources = request, sources
        self.instructions, self.intentions, self.triggers, self.errors = {}, {}, {}, []

    def ingest(self, instruction):
        self.request("public-only fixture", {"instruction": asdict(instruction), "sources": self.sources}, {})
        self.instructions[instruction.id] = instruction
        key = "pm_000001"
        self.intentions[key] = Intention(key, "Pack the lens", "case opens", ("events",),
                                        instruction_ids=(instruction.id,), evidence_quote=instruction.text)
        self.triggers[key] = {"days": [], "clock_op": "none", "clock_time": ""}
        return [key]

    def snapshot(self):
        return {"intentions": [asdict(i) for i in self.intentions.values()], "errors": list(self.errors)}


class BatchRegistrationTests(unittest.TestCase):
    def test_frozen_suite_validates_and_has_unit_level_coverage(self):
        dataset = json.loads(DEFAULT_CASES.read_text())
        validate_cases(dataset)
        self.assertEqual(len(dataset["cases"]), 5)
        self.assertEqual(sum(len({r["key"] for s in c["stages"] for r in s["expected_records"]})
                             for c in dataset["cases"]), 19)
        self.assertEqual(sum(len(s["expected_records"]) for c in dataset["cases"] for s in c["stages"]), 27)
        first = dataset["cases"][0]["stages"][0]
        self.assertEqual(len(first["instructions"]), 1)
        self.assertEqual(len(first["expected_records"]), 8)

    def test_one_record_cannot_cover_two_requests_with_same_origin(self):
        scored = score_stage(fixture_engine(), [rubric("one"), rubric("two")])
        self.assertEqual((scored["tp"], scored["fp"], scored["fn"]), (1, 0, 1))
        self.assertFalse(scored["passed"])

    def test_duplicates_count_as_false_positive(self):
        scored = score_stage(fixture_engine(2), [rubric()])
        self.assertEqual((scored["tp"], scored["fp"], scored["fn"]), (1, 1, 0))
        self.assertEqual(len(scored["unmatched_record_ids"]), 1)

    def test_merged_and_shortened_requests_fail(self):
        engine = fixture_engine()
        engine.intentions["pm_000001"] = replace(engine.intentions["pm_000001"], action="Pack the lens. Polish the stand.")
        result = score_stage(engine, [rubric(forbidden_action_fragments=["Polish the stand"])])
        self.assertEqual((result["tp"], result["fp"], result["fn"]), (0, 1, 1))
        self.assertFalse(result["rows"][0]["checks"]["separate_request"])
        engine.intentions["pm_000001"] = replace(engine.intentions["pm_000001"], action="Pack")
        self.assertFalse(score_stage(engine, [rubric()])["passed"])

    def test_maximum_matching_not_greedy(self):
        engine = fixture_engine(2)
        engine.intentions["pm_000001"] = replace(engine.intentions["pm_000001"], action="Pack the lens and cap")
        engine.intentions["pm_000002"] = replace(engine.intentions["pm_000002"], action="Pack the lens")
        requirements = [rubric("broad"), rubric("specific", action_fragments=["Pack the lens and cap"])]
        scored = score_stage(engine, requirements)
        self.assertTrue(scored["passed"])
        self.assertEqual(scored["bindings"], {"broad": "pm_000002", "specific": "pm_000001"})

    def test_sources_gates_and_provenance_all_required(self):
        for mutation, failed_check in (
            (lambda e: e.triggers["pm_000001"].update(clock_op="at", clock_time="08:00"), "clock_op"),
            (lambda e: e.triggers["pm_000001"].update(days=["Friday"]), "effective_days"),
            (lambda e: e.intentions.update(pm_000001=replace(e.intentions["pm_000001"], sources=("events", "clock"))), "exact_sources"),
            (lambda e: e.intentions.update(pm_000001=replace(e.intentions["pm_000001"], instruction_ids=("wrong_origin",))), "provenance"),
        ):
            engine = fixture_engine()
            mutation(engine)
            with self.subTest(check=failed_check):
                result = score_stage(engine, [rubric()])
                self.assertFalse(result["passed"])
                self.assertFalse(result["rows"][0]["checks"][failed_check])

    def test_all_weekdays_and_empty_gate_are_equivalent(self):
        from prospective_memory.baselines.pis import DAYS
        engine = fixture_engine()
        engine.triggers["pm_000001"]["days"] = list(DAYS)
        self.assertTrue(score_stage(engine, [rubric()])["passed"])

    def test_revision_and_cancellation_need_same_identity(self):
        engine = fixture_engine()
        first = score_stage(engine, [rubric()])
        expected = rubric(preserve_identity=True, unchanged_from_previous=True)
        self.assertTrue(score_stage(engine, [expected], first["bindings"], first["matched_states"])["passed"])
        item = engine.intentions.pop("pm_000001")
        engine.intentions["pm_000002"] = replace(item, id="pm_000002")
        engine.triggers["pm_000002"] = engine.triggers.pop("pm_000001")
        self.assertFalse(score_stage(engine, [expected], first["bindings"], first["matched_states"])["passed"])

    def test_cancellation_provenance_and_status(self):
        engine = fixture_engine()
        first = score_stage(engine, [rubric()])
        cancellation = Instruction("cancel", "Cancel packing the lens.")
        engine.instructions["cancel"] = cancellation
        engine.intentions["pm_000001"] = replace(engine.intentions["pm_000001"], status="cancelled",
                                                 instruction_ids=("public_request", "cancel"), revision=2)
        expected = rubric(status="cancelled", instruction_ids=["public_request", "cancel"], preserve_identity=True)
        self.assertTrue(score_stage(engine, [expected], first["bindings"])["passed"])

    def test_gold_never_enters_callback_and_no_tick_is_needed(self):
        calls, logs = [], []
        def request(system, payload, schema):
            calls.append({"system": system, "payload": payload, "schema": schema})
        case = {"id": "public", "sources": ["events"], "queryable_sources": [], "stages": [{
            "id": "start", "instructions": [{"id": "public_request", "text": "Pack the lens when the case opens."}],
            "expected_records": [rubric()]}]}
        result = run_case(case, request, PublicOnlyEngine, logs.append)
        self.assertTrue(result["passed"])
        serialized = json.dumps(calls)
        self.assertNotIn("gold_only_key", serialized)
        self.assertNotIn("expected_records", serialized)
        self.assertNotIn("action_fragments", serialized)
        self.assertEqual([row["event"] for row in logs], ["ingest", "stage_score"])
        self.assertEqual(summarize([result])["fully_registered_at_first_stage"], 1)

    def test_empty_bank_cannot_pass_registration(self):
        result = score_stage(fixture_engine(0), [rubric()])
        self.assertEqual((result["tp"], result["fp"], result["fn"]), (0, 0, 1))
        self.assertFalse(result["passed"])

    def test_invalid_gold_fragment_and_duplicate_keys_rejected(self):
        original = json.loads(DEFAULT_CASES.read_text())
        dataset = copy.deepcopy(original)
        dataset["cases"][0]["stages"][0]["expected_records"][0]["action_fragments"] = ["invented gold phrase"]
        with self.assertRaisesRegex(ValueError, "must occur"):
            validate_cases(dataset)
        dataset = copy.deepcopy(original)
        rows = dataset["cases"][0]["stages"][0]["expected_records"]
        rows[1]["key"] = rows[0]["key"]
        with self.assertRaisesRegex(ValueError, "Duplicate/empty rubric keys"):
            validate_cases(dataset)

    def test_existing_output_refused_before_any_request(self):
        with TemporaryDirectory() as directory:
            with patch("prospective_memory.method.evaluate_registration_cases.AuditedRequest") as request:
                with self.assertRaises(FileExistsError):
                    main(["--policy", "sbpm_minimal", "--output", directory])
                request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
