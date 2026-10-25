"""Offline fixtures test report integrity, never model performance."""

from collections import Counter
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from prospective_memory.evaluate_pis_grounded import run_case, summarize, phase_name, projection_definition
from prospective_memory.pis_grounded import GroundedPISEngine
from prospective_memory.method.source_bound import SourceBoundPISEngine
from prospective_memory.method.source_bound_v3 import SourceBoundV3Engine
from prospective_memory.method.trigger_engine import SourceBoundTriggerEngine
from prospective_memory.method.fair_trigger import SourceBoundFairTriggerEngine
from prospective_memory.adapters.pmbench import PMBenchAdapter
from prospective_memory.report_helper_runs import audit_run, main, write_report
from prospective_memory.report_helper_runs import recorded_projection_definition, restore_trigger_snapshot
from prospective_memory.report_helper_runs import recorded_projection_engine_class


def save(path, value):
    path.write_text(json.dumps(value))


def fixture(directory, engine_class=GroundedPISEngine, engine_options=None):
    directory.mkdir()
    options = dict(engine_options or {})
    projection_policy = issubclass(engine_class, SourceBoundTriggerEngine)
    if projection_policy and not options:
        options = {"projector_id": "fixture-model:v1;temperature=0;max-tokens=4096",
                   "projection_batch_size": 2}
    text = "Collect your badge when the reception sign lights up."
    case = {"id": "badge", "sources": ["events"], "queryable_sources": [],
            "instructions": [{"id": "request", "text": text}],
            "expected_initial_records": [{"origin_id": "request", "action_contains_any": ["badge"]}],
            "ticks": [{"id": "sign_on", "observations": [{"id": "seen", "text": "The reception sign lights up.", "source": "events"}],
                       "expected_records": [{"origin_id": "request", "action_contains_any": ["badge"]}],
                       "expected_rounds": [[{"origin_id": "request", "kind": "ACT", "source": ""}]]}]}
    calls, trace = [], []

    def request(system, payload, schema):
        properties = schema["properties"]
        if "changes" in properties:
            answer = {"changes": [{"op": "register", "target_id": "", "action": "Collect your badge",
                                   "condition": "The reception sign lights up.", "evidence_quote": text,
                                   "sources": ["events"], "days": [], "repeat": False,
                                   "clock_op": "none", "clock_time": ""}]}
        elif "reviews" in properties:
            answer = {"reviews": [{"verdict": "supported", "reason": "fixture"}]}
        elif "operations" in properties:
            answer = {"operations": [{"operation": "new_request", "complete_request_quote": text}]}
        elif "unit_classifications" in properties:
            answer = {"unit_classifications": [{"unit_id": payload["focus_unit_id"],
                "classification": "new_request", "related_intention_id": "", "reason": "fixture"}]}
        elif "specifications" in properties:
            answer = {"specifications": [{"operation_id": "request_1", "target_id": "",
                                          "watched_sources": ["events"], "permitted_days": [],
                                          "recurring": False, "clock_relation": "none", "required_clock_time": ""}]}
        elif "trigger_projections" in properties:
            answer = {"trigger_projections": [{"intention_id": row["intention"]["id"],
                "revision": row["intention"]["revision"],
                "source_instruction_ids": row["intention"]["instruction_ids"], "status": "projected",
                "action_to_perform_next": "Collect your badge", "readiness_question": "Is the reception sign lit?",
                "reason": "fixture"} for row in payload["records"]]}
        else:
            assessment = {"reason": "fixture", "evidence_ids": ["seen"],
                          "evidence_quotes": ["The reception sign lights up."]}
            if engine_class is SourceBoundV3Engine or projection_policy:
                assessment = {"reason": "fixture", "evidence_ids": ["e1"], "missing_observation_source": "",
                              "trigger_ready_now" if projection_policy else "all_conditions_met": True}
            elif engine_class is SourceBoundPISEngine:
                assessment.update(all_conditions_met=True, missing_observation_source="")
            else:
                assessment.update(state="satisfied", missing_source="")
            answer = {"assessments": [assessment]}
        usage = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
        response = {"usage": usage, "choices": [{"message": {"content": json.dumps(answer)}}]}
        calls.append({"call_id": len(calls) + 1, "phase": phase_name(schema), "usage": usage,
                      "system": system, "schema": copy.deepcopy(schema),
                      "response": response, "raw_http_response": json.dumps(response), "error": None})
        return answer

    result = run_case(case, request, trace.append, engine_class=engine_class, engine_options=options)
    assert result["passed"]
    save(directory / "cases.json", {"version": 1, "cases": [case]})
    save(directory / "case_results.json", [result])
    save(directory / "badge.json", result)
    (directory / "trace.jsonl").write_text("".join(json.dumps(row) + "\n" for row in trace))
    (directory / "calls.jsonl").write_text("".join(json.dumps(row) + "\n" for row in calls))
    source = directory / "source/prospective_memory/fixture.py"
    source.parent.mkdir(parents=True)
    source.write_text("# Frozen nonexecuted fixture source\n")
    manifest = {"policy": engine_class.POLICY, "args": {"model": "fixture", **options},
         "cases_sha256": hashlib.sha256((directory / "cases.json").read_bytes()).hexdigest(),
         "source_hashes": {"prospective_memory/fixture.py": hashlib.sha256(source.read_bytes()).hexdigest()}}
    if projection_policy:
        manifest["projection_definition"] = projection_definition()
    save(directory / "manifest.json", manifest)
    metrics = summarize([result])
    metrics.update(status="completed", model_calls_including_preflight=len(calls),
                   calls_by_phase=dict(Counter(row["phase"] for row in calls)),
                   usage={key: sum(row["usage"][key] for row in calls) for key in calls[0]["usage"]},
                   transport_or_decode_errors=0)
    save(directory / "metrics.json", metrics)
    save(directory / "status.json", {"status": "completed"})
    return directory


class HelperReportTests(unittest.TestCase):
    def test_v5_selector_audits_fair_state_with_recorded_projection_definition(self):
        for prompt in (None, "Earlier static projection definition."):
            with self.subTest(prompt=prompt), tempfile.TemporaryDirectory() as temporary:
                context = patch("prospective_memory.method.projection_cache.PROJECT", prompt) if prompt else contextlib.nullcontext()
                with context:
                    path = fixture(Path(temporary) / "v5", SourceBoundFairTriggerEngine)
                audit = audit_run(path)
                self.assertTrue(audit["audit_passed"], audit["mismatches"])
                self.assertTrue(audit["cases"][0]["snapshot_restored"])
                self.assertEqual(audit["summary"]["act_tp"], 1)
                self.assertEqual(audit["summary"]["calls_by_phase"]["trigger_projection"], 1)
                results = json.loads((path / "case_results.json").read_text())
                self.assertTrue(results[0]["final_state"]["arbitration_log"])
                del results[0]["final_state"]["fair_check_state"]
                save(path / "case_results.json", results)
                save(path / "badge.json", results[0])
                invalid = audit_run(path)
                self.assertFalse(invalid["audit_passed"])
                self.assertFalse(invalid["cases"][0]["snapshot_restored"])

    def test_recorded_definition_survives_adapter_fresh_and_strict_restore(self):
        with patch("prospective_memory.method.projection_cache.PROJECT", "Earlier static projection definition."):
            original = SourceBoundTriggerEngine(None, projector_id="fixture")
            definition = projection_definition()
            state = PMBenchAdapter(original, query_handoff="explicit").snapshot()
        definition = recorded_projection_definition({"projection_definition": definition}, [], [state])
        cls = recorded_projection_engine_class(SourceBoundTriggerEngine, definition)
        engine = cls(None, projector_id="fixture")
        self.assertEqual(engine.fresh().projections.snapshot()["projector"]["prompt_schema_sha256"], definition["sha256"])
        adapter = PMBenchAdapter(engine, query_handoff="explicit")
        adapter.restore(state)
        self.assertEqual(adapter.snapshot(), state)
        self.assertIsNone(adapter.engine.request)
        self.assertIsNone(adapter.engine.projections.request)
        with self.assertRaisesRegex(ValueError, "forbid inference"):
            cls(lambda *args: None, projector_id="fixture")
        with self.assertRaises(ValueError):
            recorded_projection_engine_class(SourceBoundV3Engine, definition)

    def test_recorded_class_delegates_fair_extra_state_to_actual_policy_restore(self):
        from prospective_memory.method.fair_trigger import SourceBoundFairTriggerEngine
        with patch("prospective_memory.method.projection_cache.PROJECT", "Earlier static projection definition."):
            original = SourceBoundFairTriggerEngine(None, sources=("events", "email"),
                queryable_sources=("email",), projector_id="fixture")
            original.record_query("email")
            state, definition = original.snapshot(), projection_definition()
        definition = recorded_projection_definition({"projection_definition": definition}, [], [state])
        cls = recorded_projection_engine_class(SourceBoundFairTriggerEngine, definition)
        restored = cls(None, projector_id="fixture")
        restored.restore(state)
        self.assertEqual(restored.snapshot(), state)
        self.assertEqual(restored.fair_checks.snapshot(), original.fair_checks.snapshot())
        bad = copy.deepcopy(state)
        del bad["fair_check_state"]
        with self.assertRaises(ValueError):
            restored.restore(bad)
        self.assertEqual(restored.snapshot(), state)

    def test_old_projection_prompt_audits_from_calls_while_runtime_restore_stays_strict(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch("prospective_memory.method.projection_cache.PROJECT", "Earlier static projection definition."):
                path = fixture(Path(temporary) / "old-v4", SourceBoundTriggerEngine)
            manifest = json.loads((path / "manifest.json").read_text())
            del manifest["projection_definition"]  # Legacy runs recorded exact call system/schema only.
            save(path / "manifest.json", manifest)
            state = json.loads((path / "case_results.json").read_text())[0]["final_state"]
            runtime = SourceBoundTriggerEngine(None, projector_id=manifest["args"]["projector_id"])
            with self.assertRaises(ValueError):
                runtime.restore(state)
            audit = audit_run(path)
            self.assertTrue(audit["audit_passed"], audit["mismatches"])
            self.assertTrue(audit["cases"][0]["snapshot_restored"])

    def test_new_and_old_manifest_definitions_restore_without_callbacks(self):
        for prompt in (None, "Earlier static projection definition."):
            with self.subTest(prompt=prompt), tempfile.TemporaryDirectory() as temporary:
                context = patch("prospective_memory.method.projection_cache.PROJECT", prompt) if prompt else contextlib.nullcontext()
                with context:
                    path = fixture(Path(temporary) / "v4", SourceBoundTriggerEngine)
                audit = audit_run(path)
                self.assertTrue(audit["audit_passed"], audit["mismatches"])

    def test_tampered_projection_definition_or_cache_fingerprint_fails_audit(self):
        for tamper in ("prompt", "sha256", "schema", "call", "initial_cache", "entry_cache"):
            with self.subTest(tamper=tamper), tempfile.TemporaryDirectory() as temporary:
                path = fixture(Path(temporary) / "v4", SourceBoundTriggerEngine)
                if tamper in {"prompt", "sha256", "schema"}:
                    manifest = json.loads((path / "manifest.json").read_text())
                    if tamper == "schema":
                        manifest["projection_definition"]["schema"]["description"] = "Changed contract"
                    else:
                        manifest["projection_definition"][tamper] += " changed"
                    save(path / "manifest.json", manifest)
                elif tamper == "call":
                    calls = [json.loads(line) for line in (path / "calls.jsonl").read_text().splitlines()]
                    next(row for row in calls if row["phase"] == "trigger_projection")["system"] += " changed"
                    (path / "calls.jsonl").write_text("".join(json.dumps(row) + "\n" for row in calls))
                else:
                    results = json.loads((path / "case_results.json").read_text())
                    cache = results[0]["initial_state"]["trigger_projection_cache"]
                    profile = cache["projector"] if tamper == "initial_cache" else cache["entries"][0]["binding"]["projector"]
                    profile["prompt_schema_sha256"] = "wrong"
                    save(path / "case_results.json", results)
                    save(path / "badge.json", results[0])
                audit = audit_run(path)
                self.assertFalse(audit["audit_passed"])
                self.assertIn("projection_definition", [row["field"] for row in audit["mismatches"]])

    def test_no_call_manifest_definition_is_required_and_must_match_empty_cache(self):
        definition = projection_definition()
        engine = SourceBoundTriggerEngine(None, projector_id="fixture", projection_batch_size=4)
        state = engine.snapshot()
        self.assertEqual(state["trigger_projection_cache"]["entries"], [])
        resolved = recorded_projection_definition({"projection_definition": definition}, [], [state])
        restored = restore_trigger_snapshot(state, projector_id="fixture", projection_batch_size=4, definition=resolved)
        self.assertEqual(restored.snapshot(), state)
        self.assertIsNone(restored.request)
        self.assertIsNone(restored.projections.request)
        with self.assertRaises(ValueError):
            recorded_projection_definition({}, [], [state])
        bad = copy.deepcopy(state)
        bad["trigger_projection_cache"]["projector"]["prompt_schema_sha256"] = "wrong"
        with self.assertRaises(ValueError):
            recorded_projection_definition({"projection_definition": definition}, [], [bad])
        bad = copy.deepcopy(state)
        bad["policy_variant"] = "sbpm"
        bad["fair_arbiter"] = {"future_state": "must not silently disappear"}
        with self.assertRaisesRegex(ValueError, "V4 snapshots only"):
            restore_trigger_snapshot(bad, projector_id="fixture", projection_batch_size=4, definition=definition)

    def test_v4_explicit_configuration_restores_and_projection_phase_is_audited(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = fixture(Path(temporary) / "v4", SourceBoundTriggerEngine)
            audit = audit_run(path)
            self.assertTrue(audit["audit_passed"], audit["mismatches"])
            self.assertTrue(audit["cases"][0]["snapshot_restored"])
            self.assertEqual(audit["summary"]["act_tp"], 1)
            self.assertEqual(audit["summary"]["model_calls_including_preflight"], 4)
            self.assertEqual(audit["summary"]["calls_by_phase"]["trigger_projection"], 1)

    def test_v4_missing_or_wrong_projector_identity_fails_snapshot_audit(self):
        for identity in (None, "", "different-model-config"):
            with self.subTest(identity=identity), tempfile.TemporaryDirectory() as temporary:
                path = fixture(Path(temporary) / "v4", SourceBoundTriggerEngine)
                manifest = json.loads((path / "manifest.json").read_text())
                if identity is None:
                    del manifest["args"]["projector_id"]
                else:
                    manifest["args"]["projector_id"] = identity
                save(path / "manifest.json", manifest)
                audit = audit_run(path)
                self.assertFalse(audit["audit_passed"])
                self.assertFalse(audit["cases"][0]["snapshot_restored"])
                self.assertIn("badge: snapshot restore", [m["field"] for m in audit["mismatches"]])

    def test_v4_saved_batch_must_match_manifest_even_if_restore_accepts_size(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = fixture(Path(temporary) / "v4", SourceBoundTriggerEngine)
            manifest = json.loads((path / "manifest.json").read_text())
            manifest["args"]["projection_batch_size"] = 8
            save(path / "manifest.json", manifest)
            audit = audit_run(path)
            self.assertFalse(audit["audit_passed"])
            self.assertIn("badge: projection batch configuration", [m["field"] for m in audit["mismatches"]])

    def test_v3_report_behavior_remains_compatible(self):
        with tempfile.TemporaryDirectory() as temporary:
            audit = audit_run(fixture(Path(temporary) / "v3", SourceBoundV3Engine))
            self.assertTrue(audit["audit_passed"], audit["mismatches"])
            self.assertEqual(audit["summary"]["model_calls_including_preflight"], 3)

    def test_both_variants_restore_and_counts_are_independent(self):
        with tempfile.TemporaryDirectory() as temporary:
            for engine_class in (GroundedPISEngine, SourceBoundPISEngine):
                path = fixture(Path(temporary) / engine_class.POLICY, engine_class)
                audit = audit_run(path)
                self.assertTrue(audit["audit_passed"], audit["mismatches"])
                self.assertTrue(audit["cases"][0]["snapshot_restored"])
                self.assertEqual(audit["summary"]["act_tp"], 1)
                self.assertEqual(audit["summary"]["registered_requirement_count"], 1)
                self.assertEqual(audit["summary"]["model_calls_including_preflight"], 3)
                self.assertEqual(audit["summary"]["usage"]["total_tokens"], 36)

    def test_tampered_summary_is_reported_not_trusted(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = fixture(Path(temporary) / "run")
            metrics = json.loads((path / "metrics.json").read_text())
            metrics["act_tp"] = 99
            save(path / "metrics.json", metrics)
            audit = audit_run(path)
            self.assertFalse(audit["audit_passed"])
            self.assertEqual(audit["summary"]["act_tp"], 1)
            self.assertIn("metrics: act_tp", [row["field"] for row in audit["mismatches"]])

    def test_frozen_hash_and_raw_usage_tampering_are_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = fixture(Path(temporary) / "run")
            (path / "source/prospective_memory/fixture.py").write_text("changed")
            calls = [json.loads(row) for row in (path / "calls.jsonl").read_text().splitlines()]
            calls[0]["usage"]["total_tokens"] = 999
            (path / "calls.jsonl").write_text("".join(json.dumps(row) + "\n" for row in calls))
            audit = audit_run(path)
            self.assertFalse(audit["audit_passed"])
            self.assertEqual(audit["summary"]["usage"]["total_tokens"], 36)
            fields = [row["field"] for row in audit["mismatches"]]
            self.assertIn("source hash: prospective_memory/fixture.py", fields)
            self.assertIn("call 1: usage", fields)

    def test_fresh_report_preserves_attempts_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = fixture(Path(temporary) / "run")
            before = {str(file.relative_to(path)): file.read_bytes() for file in path.rglob("*") if file.is_file()}
            output = Path(temporary) / "report"
            audits = write_report([path], output)
            self.assertTrue(audits[0]["audit_passed"])
            self.assertIn("NOT PM-Bench", (output / "README.md").read_text())
            self.assertIn("not semantic proof", (output / "README.md").read_text())
            self.assertEqual({file.name for file in output.iterdir()},
                             {"README.md", "AUDIT.json", "PROVENANCE.json", "CASE_RESULTS.csv", "COMPARISON.csv"})
            with self.assertRaises(FileExistsError):
                write_report([path], output)
            self.assertEqual(before, {str(file.relative_to(path)): file.read_bytes() for file in path.rglob("*") if file.is_file()})

    def test_incomplete_run_and_unknown_variant_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = fixture(Path(temporary) / "run")
            output = Path(temporary) / "report"
            save(path / "status.json", {"status": "running"})
            with self.assertRaisesRegex(ValueError, "incomplete"):
                write_report([path], output)
            self.assertFalse(output.exists())
            save(path / "status.json", {"status": "completed"})
            manifest = json.loads((path / "manifest.json").read_text())
            manifest["policy"] = "unknown"
            save(path / "manifest.json", manifest)
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                audit_run(path)

    def test_mismatch_cli_exit_is_nonzero(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = fixture(Path(temporary) / "run")
            (path / "source/prospective_memory/fixture.py").write_text("tampered")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(path), "--output", str(Path(temporary) / "report")]), 1)


if __name__ == "__main__":
    unittest.main()
