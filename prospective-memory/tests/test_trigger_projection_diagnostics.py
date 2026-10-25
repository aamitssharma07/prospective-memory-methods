"""Offline V4 diagnostic CLI/factory contracts; transport is always scripted."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from prospective_memory.method import evaluate_registration_cases as batch
from prospective_memory import evaluate_pis_grounded as smoke
from prospective_memory.method.trigger_engine import SourceBoundTriggerEngine
from prospective_memory.method.fair_trigger import SourceBoundFairTriggerEngine


POLICY = "sbpm_no_arbiter"
FAIR_POLICY = "sbpm"
PROJECTOR_ID = "fixture:v1;temperature=0;thinking=false;max-tokens=4096"
TEXT = "File the record when the console lamp lights."


def smoke_dataset():
    requirement = {"origin_id": "request", "action_contains_any": ["File the record"]}
    return {"version": 1, "cases": [{"id": "console", "sources": ["events"], "queryable_sources": [],
        "instructions": [{"id": "request", "text": TEXT}], "expected_initial_records": [requirement],
        "ticks": [{"id": "lit", "observations": [{"id": "visible", "text": "The console lamp lights."}],
                   "expected_records": [requirement],
                   "expected_rounds": [[{"origin_id": "request", "kind": "ACT", "source": ""}]]}]}]}


def batch_dataset():
    return {"version": 1, "cases": [{"id": "console", "sources": ["events"], "queryable_sources": [],
        "stages": [{"id": "initial", "instructions": [{"id": "request", "text": TEXT}],
            "expected_records": [{"key": "scorer_only_identity", "origin_id": "request",
                "action_fragments": ["File the record"], "condition_fragments": ["console lamp lights"],
                "forbidden_action_fragments": [], "sources": ["events"], "days": [],
                "clock_op": "none", "clock_time": "", "repeat": False}]}]}]}


class Scripted:
    def __init__(self):
        self.payloads = []

    def __call__(self, system, payload, schema):
        self.payloads.append(payload)
        key = next(iter(schema["properties"]))
        if key == "label":
            return {"label": "ready"}
        if key == "unit_classifications":
            return {key: [{"reason": "fixture", "unit_id": payload["focus_unit_id"],
                           "classification": "new_request", "related_intention_id": ""}]}
        if key == "specifications":
            return {key: [{"operation_id": operation["operation_id"], "target_id": "",
                           "watched_sources": ["events"], "permitted_days": [], "recurring": False,
                           "clock_relation": "none", "required_clock_time": ""}
                          for operation in payload["operations"]]}
        if key == "trigger_projections":
            return {key: [{"intention_id": row["intention"]["id"], "revision": row["intention"]["revision"],
                           "source_instruction_ids": list(row["intention"]["instruction_ids"]),
                           "status": "projected", "action_to_perform_next": "File the record",
                           "readiness_question": "Has the console lamp lit?", "reason": "fixture"}
                          for row in payload["records"]]}
        if key == "assessments":
            return {key: [{"reason": "fixture", "trigger_ready_now": True,
                           "evidence_ids": ["e1"], "missing_observation_source": ""}]}
        raise AssertionError(key)

    def urlopen(self, request, **kwargs):
        body = json.loads(request.data)
        answer = self(body["messages"][0]["content"], json.loads(body["messages"][1]["content"]),
                      body["response_format"]["json_schema"]["schema"])
        return Response(answer)


class Response:
    status = 200

    def __init__(self, answer):
        self.answer = answer

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(self.answer)}}],
                           "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}}).encode()


class ProjectionDiagnosticTests(unittest.TestCase):
    def test_selectors_and_explicit_config_validation_leave_other_policies_unchanged(self):
        self.assertIs(smoke.ENGINES[POLICY], SourceBoundTriggerEngine)
        self.assertIs(batch.engine_class(POLICY), SourceBoundTriggerEngine)
        self.assertIs(smoke.ENGINES[FAIR_POLICY], SourceBoundFairTriggerEngine)
        self.assertIs(batch.engine_class(FAIR_POLICY), SourceBoundFairTriggerEngine)
        self.assertEqual(smoke.projection_options(FAIR_POLICY, PROJECTOR_ID),
                         {"projector_id": PROJECTOR_ID, "projection_batch_size": 4})
        self.assertEqual(smoke.projection_options("sbpm_no_projection"), {})
        self.assertEqual(smoke.projection_options(POLICY, PROJECTOR_ID),
                         {"projector_id": PROJECTOR_ID, "projection_batch_size": 4})
        for identity, size in ((None, 4), ("", 4), (" ", 4), (PROJECTOR_ID, 0),
                               (PROJECTOR_ID, 33), (PROJECTOR_ID, True)):
            with self.subTest(identity=identity, size=size), self.assertRaises(ValueError):
                smoke.projection_options(POLICY, identity, size)

    def test_missing_v4_identity_rejected_before_output_or_transport(self):
        for module, policy in ((module, policy) for module in (smoke, batch) for policy in (POLICY, FAIR_POLICY)):
            with self.subTest(module=module.__name__, policy=policy), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "run"
                with patch("prospective_memory.evaluate_pis_grounded.urlopen") as transport, \
                        contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    module.main(["--policy", policy, "--output", str(output)])
                self.assertFalse(output.exists())
                transport.assert_not_called()

    def test_smoke_programmatic_factory_passes_config_without_scoring_leakage(self):
        provider = Scripted()
        options = smoke.projection_options(POLICY, PROJECTOR_ID, 2)
        result = smoke.run_case(smoke_dataset()["cases"][0], provider,
                                engine_class=SourceBoundTriggerEngine, engine_options=options)
        self.assertTrue(result["passed"])
        self.assertEqual((result["act_tp"], result["act_fp"], result["act_fn"]), (1, 0, 0))
        cache = result["final_state"]["trigger_projection_cache"]
        self.assertEqual((cache["projector"]["identity"], cache["batch_size"]), (PROJECTOR_ID, 2))
        self.assertNotIn("expected_", json.dumps(provider.payloads))

    def test_batch_programmatic_factory_projects_without_assessing_or_leaking_rubrics(self):
        provider = Scripted()
        result = batch.run_case(batch_dataset()["cases"][0], provider, SourceBoundTriggerEngine,
                                engine_options=smoke.projection_options(POLICY, PROJECTOR_ID, 3))
        self.assertTrue(result["passed"])
        self.assertEqual(result["final_snapshot"]["trigger_projection_cache"]["batch_size"], 3)
        self.assertEqual(len(provider.payloads), 3)
        self.assertNotIn("scorer_only_identity", json.dumps(provider.payloads))
        self.assertNotIn("action_fragments", json.dumps(provider.payloads))

    def test_both_clis_record_exact_identity_batch_phase_and_source_snapshots(self):
        runs = [(module, dataset, policy) for module, dataset in ((smoke, smoke_dataset()), (batch, batch_dataset()))
                for policy in (POLICY, FAIR_POLICY)]
        for module, dataset, policy in runs:
            with self.subTest(module=module.__name__, policy=policy), tempfile.TemporaryDirectory() as temporary:
                cases, output = Path(temporary) / "cases.json", Path(temporary) / "run"
                cases.write_text(json.dumps(dataset))
                provider = Scripted()
                with patch("prospective_memory.evaluate_pis_grounded.urlopen", side_effect=provider.urlopen), \
                        contextlib.redirect_stdout(io.StringIO()):
                    module.main(["--cases", str(cases), "--policy", policy, "--output", str(output),
                                 "--model", "fixture", "--projector-id", PROJECTOR_ID,
                                 "--projection-batch-size", "2"])
                manifest = json.loads((output / "manifest.json").read_text())
                self.assertEqual(manifest["policy"], policy)
                self.assertEqual(manifest["args"]["projector_id"], PROJECTOR_ID)
                self.assertEqual(manifest["args"]["projection_batch_size"], 2)
                self.assertEqual(manifest["projection_definition"], smoke.projection_definition())
                metrics = json.loads((output / "metrics.json").read_text())
                self.assertTrue(metrics["all_cases_passed"])
                self.assertEqual(metrics["calls_by_phase"]["trigger_projection"], 1)
                for name in ("method/trigger_engine.py", "method/projection_cache.py",
                             "method/fair_trigger.py", "method/fair_checks.py"):
                    relative = "prospective_memory/" + name
                    self.assertIn(relative, manifest["source_hashes"])
                    self.assertTrue((output / "source" / relative).is_file())
                self.assertEqual((output / "cases.json").read_bytes(), cases.read_bytes())
                self.assertNotIn("expected_", json.dumps(provider.payloads))
                results = json.loads((output / "case_results.json").read_text())
                state = results[0]["final_state" if module is smoke else "final_snapshot"]
                if policy == FAIR_POLICY:
                    self.assertIn("fair_check_state", state)
                    self.assertIn("arbitration_log", state)

    def test_manifests_save_projection_definition_before_any_projector_call(self):
        for module in (smoke, batch):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "run"
                with patch("prospective_memory.evaluate_pis_grounded.urlopen", side_effect=OSError("offline")), \
                        self.assertRaises(smoke.SmokeAbort):
                    module.main(["--policy", POLICY, "--output", str(output), "--projector-id", PROJECTOR_ID])
                manifest = json.loads((output / "manifest.json").read_text())
                self.assertEqual(manifest["projection_definition"], smoke.projection_definition())
                calls = [json.loads(line) for line in (output / "calls.jsonl").read_text().splitlines()]
                self.assertNotIn("trigger_projection", [row["phase"] for row in calls])


if __name__ == "__main__":
    unittest.main()
