"""Offline report tests; synthetic artifact fixtures never invoke a model."""

import copy
from collections import Counter
import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from report_source_bound_pair import (
    ROOT, SIMULATOR, audit_run, compare_runs, digest, failure_rows, main,
    micro_metrics, pm_bench, read_json, write_report,
)
from prospective_memory.adapters.pmbench import PMBenchAdapter
from prospective_memory.method.source_bound import SourceBoundPISEngine
from prospective_memory.method.source_bound_v3 import SourceBoundV3Engine
from prospective_memory.method.trigger_engine import SourceBoundTriggerEngine
from prospective_memory.method.fair_trigger import SourceBoundFairTriggerEngine
from prospective_memory.method.projection_cache import projection_definition
from score_paired import metric_payload


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def save_jsonl(path, values):
    path.write_text("".join(json.dumps(value) + "\n" for value in values))


def make_run(path, candidate=False):
    """Build a valid empty-choice scorer trace and pure snapshot for auditing.

    These are explicit synthetic fixtures, not experimental performance outputs.
    Decisions/calls have no effect on the native trace and are for counter tests.
    """
    path.mkdir()
    scenario_bytes = (ROOT / "benchmark/data/synthetic_week_v9.json").read_bytes()
    (path / "scenario.json").write_bytes(scenario_bytes)
    scenario = json.loads(scenario_bytes)
    sources = [SIMULATOR]
    if candidate:
        sources += ["prospective_memory/method/source_bound.py", "prospective_memory/baselines/pis_registration.py"]
    hashes = {}
    for source in sources:
        target = path / "source" / source
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / source).read_bytes())
        hashes[source] = digest(target)
    manifest = {"mode": "selective" if candidate else "baseline", "model": "fixture-no-model",
                "memory_version": "portable" if candidate else "v1",
                "memory_policy": "sbpm_minimal" if candidate else "legacy",
                "policy_variant": SourceBoundPISEngine.POLICY if candidate else None,
                "base_url": "http://127.0.0.1:30003/v1", "max_tokens": 768,
                "temperature": 0.0, "fallback": "empty", "source_sha256": hashes,
                "scenario_sha256": digest(path / "scenario.json")}
    save_json(path / "manifest.json", manifest)
    entries = [{"day": d["name"], "step_id": s["id"], "choice": "A", "task_ids": [],
                "fallback_triggered": False, "state_queries": {}}
               for d in scenario["days"] for s in d["steps"]]
    entries[0]["state_queries"] = {"clock": 1}
    entries[0]["check_time"] = 1  # Must not double-count this compatibility field.
    if candidate:
        entries[1]["state_queries"] = {"clock": 1, "appointment_portal": 1}
    summary, per_day, steps = pm_bench.score_log(scenario, entries)
    save_json(path / "metrics.json", {"metrics": metric_payload(summary), "summary": summary,
                                      "per_day": per_day, "steps": steps, "fallback_steps": 0})
    metadata = {"record_type": "run_metadata", "entry_count": 80, "duration_seconds": 5.0}
    save_jsonl(path / "trajectory.jsonl", [metadata, *entries])
    save_jsonl(path / "memory_calls.jsonl", [])
    save_jsonl(path / "memory.jsonl", [])
    if candidate:
        adapter = PMBenchAdapter(SourceBoundPISEngine(None))
        adapter.cycles = 80
        state = json.loads(json.dumps(adapter.snapshot()))
        save_json(path / "memory_snapshot.json", state)
        save_jsonl(path / "memory.jsonl", [
            {"cycle": i, "decisions": [], "errors": [], "reminder": "", "bank": state["engine"]}
            for i in range(1, 81)])
    return path


class SourceBoundReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.baseline = make_run(self.root / "baseline")
        self.candidate = make_run(self.root / "candidate", candidate=True)

    def test_complete_pair_rescores_and_queries_include_clock_once(self):
        result = compare_runs(self.baseline, self.candidate)
        self.assertTrue(all(result["matched_actor_fields"].values()))
        self.assertTrue(result["identical_state_aware_due_occurrences"])
        self.assertEqual(result["baseline"]["actor_query_calls_including_clock"], 1)
        self.assertEqual(result["candidate"]["actor_query_calls_including_clock"], 3)
        self.assertEqual(result["candidate"]["metrics"]["check_time_calls"], 2)
        self.assertTrue(result["candidate"]["helper"]["snapshot_restore_verified"])
        self.assertEqual(result["candidate"]["helper"]["snapshot_policy_variant"], SourceBoundPISEngine.POLICY)
        self.assertEqual(result["candidate"]["metrics"]["set_tp"], 0)
        self.assertEqual(result["candidate"]["metrics"]["set_fn"], 81)

    def test_v3_snapshot_variant_is_supported_and_requires_its_sources(self):
        path = self.candidate
        manifest = read_json(path / "manifest.json")
        manifest.update(memory_policy="sbpm_no_projection", policy_variant=SourceBoundV3Engine.POLICY)
        state = read_json(path / "memory_snapshot.json")
        state["engine"]["policy_variant"] = SourceBoundV3Engine.POLICY
        save_json(path / "memory_snapshot.json", state)
        for name in ("method/source_bound_v3.py", "method/registration.py"):
            relative = "prospective_memory/" + name
            target = path / "source" / relative
            # Synthetic source fixture: hashes are verified, not executed.
            target.write_text("# fixture source for policy isolation test\n")
            manifest["source_sha256"][relative] = digest(target)
        save_json(path / "manifest.json", manifest)
        rows = [json.loads(line) for line in (path / "memory.jsonl").read_text().splitlines()]
        for row in rows:
            row["bank"]["policy_variant"] = SourceBoundV3Engine.POLICY
        save_jsonl(path / "memory.jsonl", rows)
        result = compare_runs(self.baseline, path)
        self.assertEqual(result["candidate"]["helper"]["snapshot_policy_variant"], SourceBoundV3Engine.POLICY)
        del manifest["source_sha256"]["prospective_memory/method/registration.py"]
        save_json(path / "manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "Missing source-bound"):
            compare_runs(self.baseline, path)

    def test_report_exports_every_failure_and_refuses_overwrite(self):
        report = compare_runs(self.baseline, self.candidate)
        output = self.root / "report"
        before = digest(self.candidate / "metrics.json")
        write_report(report, output)
        with (output / "failures.csv").open() as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 162)
        self.assertEqual({row["kind"] for row in rows}, {"FN"})
        self.assertEqual(len(list(failure_rows(report))), len(rows))
        text = (output / "README.md").read_text()
        self.assertIn("Helper tokens only", text)
        self.assertIn("not counts of", text)
        self.assertIn("earlier observations may matter", text)
        self.assertEqual(before, digest(self.candidate / "metrics.json"))
        with self.assertRaises(FileExistsError):
            write_report(report, output)
        self.assertEqual(read_json(output / "ANALYSIS.json")["candidate"]["steps"], 80)

    def test_query_handoff_mode_is_restored_and_must_match_manifest(self):
        path = self.candidate
        manifest = read_json(path / "manifest.json")
        manifest["memory_query_handoff"] = "explicit"
        save_json(path / "manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "handoff mode disagrees"):
            compare_runs(self.baseline, path)
        state = read_json(path / "memory_snapshot.json")
        state["query_handoff"] = "explicit"
        save_json(path / "memory_snapshot.json", state)
        self.assertTrue(compare_runs(self.baseline, path)["candidate"]["helper"]["snapshot_restore_verified"])
        manifest["memory_query_handoff"] = "legacy"
        save_json(path / "manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "handoff mode disagrees"):
            compare_runs(self.baseline, path)

    def projected_run(self, engine_class=SourceBoundTriggerEngine):
        path = self.candidate
        manifest = read_json(path / "manifest.json")
        manifest.update(memory_policy=engine_class.POLICY, policy_variant=engine_class.POLICY,
                        memory_projector_id="fixture-model-config", memory_projection_batch_size=2,
                        projection_definition=projection_definition())
        adapter = PMBenchAdapter(engine_class(None, projector_id="fixture-model-config", projection_batch_size=2))
        adapter.cycles = 80
        state = json.loads(json.dumps(adapter.snapshot()))
        save_json(path / "memory_snapshot.json", state)
        save_jsonl(path / "memory.jsonl", [
            {"cycle": i, "decisions": [], "errors": [], "reminder": "", "bank": state["engine"]}
            for i in range(1, 81)])
        sources = ["method/source_bound_v3.py", "method/registration.py", "method/projection_cache.py",
                   "method/trigger_engine.py", "method/calendar_guard.py"]
        if engine_class is SourceBoundFairTriggerEngine:
            sources += ["method/fair_checks.py", "method/fair_trigger.py"]
        for name in sources:
            relative = "prospective_memory/" + name
            target = path / "source" / relative
            target.write_bytes((ROOT / relative).read_bytes())
            manifest["source_sha256"][relative] = digest(target)
        save_json(path / "manifest.json", manifest)
        return path, manifest

    def test_v4_requires_matching_projector_configuration_and_complete_sources(self):
        path, manifest = self.projected_run()
        result = compare_runs(self.baseline, path)
        self.assertEqual(result["candidate"]["helper"]["snapshot_policy_variant"], SourceBoundTriggerEngine.POLICY)
        for field, value in (("memory_projector_id", None), ("memory_projector_id", "another-config"),
                             ("memory_projection_batch_size", 4)):
            changed = {**manifest, field: value}
            save_json(path / "manifest.json", changed)
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                compare_runs(self.baseline, path)
        changed = copy.deepcopy(manifest)
        del changed["source_sha256"]["prospective_memory/method/projection_cache.py"]
        save_json(path / "manifest.json", changed)
        with self.assertRaisesRegex(ValueError, "Missing source-bound"):
            compare_runs(self.baseline, path)

    def test_recorded_projection_survives_changed_live_prompt_but_not_tampered_record(self):
        path, manifest = self.projected_run()
        with patch("prospective_memory.method.projection_cache.PROJECT", "A later runtime prompt"):
            self.assertTrue(compare_runs(self.baseline, path)["candidate"]["helper"]["snapshot_restore_verified"])
        manifest["projection_definition"]["prompt"] += " Tampered recorded prompt"
        save_json(path / "manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
            compare_runs(self.baseline, path)

    def test_v5_audit_validates_extra_fair_state_and_source_snapshot(self):
        path, manifest = self.projected_run(SourceBoundFairTriggerEngine)
        result = compare_runs(self.baseline, path)
        self.assertEqual(result["candidate"]["helper"]["snapshot_policy_variant"], SourceBoundFairTriggerEngine.POLICY)
        state = read_json(path / "memory_snapshot.json")
        del state["engine"]["fair_check_state"]
        save_json(path / "memory_snapshot.json", state)
        with self.assertRaisesRegex(ValueError, "fair-trigger"):
            compare_runs(self.baseline, path)
        del manifest["source_sha256"]["prospective_memory/method/fair_checks.py"]
        save_json(path / "manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "Missing source-bound"):
            compare_runs(self.baseline, path)

    def test_recorded_query_budgets_must_match_snapshot(self):
        path, manifest = self.projected_run(SourceBoundFairTriggerEngine)
        manifest.update(memory_check_budget=1, pis_step_query_budget=2)
        save_json(path / "manifest.json", manifest)
        self.assertTrue(compare_runs(self.baseline, path)["candidate"]["helper"]["snapshot_restore_verified"])
        for field, value in (("memory_check_budget", 2), ("pis_step_query_budget", 3),
                             ("memory_check_budget", True)):
            save_json(path / "manifest.json", {**manifest, field: value})
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "snapshot query budget"):
                compare_runs(self.baseline, path)

    def test_incomplete_duplicate_and_uninstrumented_traces_rejected(self):
        path = self.candidate / "trajectory.jsonl"
        original = [json.loads(line) for line in path.read_text().splitlines()]
        for kind in ("incomplete", "duplicate", "uninstrumented"):
            values = copy.deepcopy(original)
            if kind == "incomplete":
                values.pop()
            elif kind == "duplicate":
                values[-1] = values[-2]
            else:
                values[-1].pop("fallback_triggered")
            save_jsonl(path, values)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                audit_run(self.candidate)
        save_jsonl(path, original)

    def test_stored_native_counter_tampering_rejected(self):
        path = self.candidate / "metrics.json"
        original = read_json(path)
        for field in ("metrics", "summary"):
            value = copy.deepcopy(original)
            value[field]["set_tp"] += 1
            save_json(path, value)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "Stored native result"):
                audit_run(self.candidate)
        save_json(path, original)

    def test_source_and_scenario_hash_tampering_rejected(self):
        for relative in ("source/" + SIMULATOR, "scenario.json"):
            path = self.candidate / relative
            original = path.read_bytes()
            path.write_bytes(original + b"\n")
            with self.subTest(path=relative), self.assertRaisesRegex(ValueError, "hash mismatch"):
                audit_run(self.candidate)
            path.write_bytes(original)

    def test_other_frozen_simulator_not_scored_by_current_code(self):
        target = self.candidate / "source" / SIMULATOR
        target.write_bytes(target.read_bytes() + b"\n")
        path = self.candidate / "manifest.json"
        value = read_json(path)
        value["source_sha256"][SIMULATOR] = digest(target)
        save_json(path, value)
        with self.assertRaisesRegex(ValueError, "Current native scorer differs"):
            audit_run(self.candidate)

    def test_snapshot_variant_and_identity_mismatch_rejected(self):
        path = self.candidate / "memory_snapshot.json"
        original = read_json(path)
        value = copy.deepcopy(original)
        value["engine"]["policy_variant"] = "pis_grounded_v1"
        save_json(path, value)
        with self.assertRaisesRegex(ValueError, "Snapshot policy variant"):
            audit_run(self.candidate)
        value = copy.deepcopy(original)
        value["cycles"] = 79
        save_json(path, value)
        with self.assertRaisesRegex(ValueError, "Snapshot/cycle log count"):
            audit_run(self.candidate)

    def test_unmatched_actor_and_scenario_rejected(self):
        path = self.candidate / "manifest.json"
        original = read_json(path)
        value = copy.deepcopy(original)
        value["model"] = "other-fixture-model"
        save_json(path, value)
        with self.assertRaisesRegex(ValueError, "Unmatched fresh pair: model"):
            compare_runs(self.baseline, self.candidate)
        # A format-only JSON change preserves semantics but violates exact frozen
        # scenario matching, even after updating that run's own honest hash.
        scenario = self.candidate / "scenario.json"
        scenario.write_bytes(scenario.read_bytes() + b"\n")
        value = copy.deepcopy(original)
        value["scenario_sha256"] = digest(scenario)
        save_json(path, value)
        with self.assertRaisesRegex(ValueError, "Unmatched fresh pair: scenario_sha256"):
            compare_runs(self.baseline, self.candidate)

    def test_helper_counters_and_error_reconciliation(self):
        calls = [
            {"phase": "extract", "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}, "finish_reason": "stop"},
            {"phase": "assess", "usage": {"prompt_tokens": 9, "completion_tokens": 5, "total_tokens": 14}, "finish_reason": "length", "error": "JSON failed"},
            {"phase": "assess", "error": "transport failed"},
        ]
        save_jsonl(self.candidate / "memory_calls.jsonl", calls)
        state = read_json(self.candidate / "memory_snapshot.json")
        error = {"phase": "assess", "error": "fixture failure"}
        state["engine"]["errors"] = [error]
        save_json(self.candidate / "memory_snapshot.json", state)
        # Artificial deliveries test reporting counters, not model behavior.
        cycles = [{"cycle": i, "decisions": [], "errors": [], "reminder": "", "bank": state["engine"]}
                  for i in range(1, 81)]
        cycles[0].update(decisions=[{"kind": "ACT"}, {"kind": "CHECK"}, {"kind": "WAIT"}],
                         errors=[error], reminder="fixture guidance")
        save_jsonl(self.candidate / "memory.jsonl", cycles)
        helper = audit_run(self.candidate)["helper"]
        self.assertEqual(helper["calls"], 3)
        self.assertEqual(helper["tokens_excluding_probe"]["total_tokens"], 24)
        self.assertEqual(helper["api_or_json_errors"], 2)
        self.assertEqual(helper["calls_without_usage"], 1)
        self.assertEqual(helper["length_finishes"], 1)
        self.assertEqual(helper["adapter_decision_counts"], {"WAIT": 1, "CHECK": 1, "ACT": 1})
        self.assertEqual(helper["engine_errors_by_phase"], {"assess": 1})
        cycles[0]["errors"] = [{"phase": "assess", "error": "different failure"}]
        save_jsonl(self.candidate / "memory.jsonl", cycles)
        with self.assertRaisesRegex(ValueError, "Logged engine errors"):
            audit_run(self.candidate)

    def test_fallback_must_be_empty_and_match_native_count(self):
        path = self.candidate / "trajectory.jsonl"
        values = [json.loads(line) for line in path.read_text().splitlines()]
        values[1]["fallback_triggered"] = True
        values[1]["task_ids"] = ["invented"]
        save_jsonl(path, values)
        with self.assertRaisesRegex(ValueError, "empty-fallback step contains"):
            audit_run(self.candidate)
        values[1]["task_ids"] = []
        save_jsonl(path, values)
        with self.assertRaisesRegex(ValueError, "Actor fallback count mismatch"):
            audit_run(self.candidate)
        metrics = read_json(self.candidate / "metrics.json")
        metrics["fallback_steps"] = 1
        save_json(self.candidate / "metrics.json", metrics)
        self.assertEqual(audit_run(self.candidate)["fallback_steps"], 1)

    def test_zero_denominators_and_explicit_metrics(self):
        self.assertEqual(micro_metrics(0, 0, 0)["set_f1"], 0)
        self.assertAlmostEqual(micro_metrics(62, 146, 19)["set_f1"], 0.4290657439446367)

    def test_cli_refuses_existing_output_before_audit(self):
        output = self.root / "existing"
        output.mkdir()
        with patch("report_source_bound_pair.compare_runs") as compare:
            with self.assertRaisesRegex(ValueError, "refusing overwrite"):
                main([str(self.baseline), str(self.candidate), "--output", str(output)])
            compare.assert_not_called()


class HistoricalReferenceReportTests(unittest.TestCase):
    def test_available_frozen_prior_pis_read_only(self):
        root = ROOT / "harness/memory_results/qwen3-8b-pis-triplet-20260922-03"
        if not (root / "pis/metrics.json").exists():
            self.skipTest("Historical run artifacts are optional and are not shipped with code")
        checksums = {arm: digest(root / arm / "metrics.json") for arm in ("baseline", "pis")}
        base, old = (audit_run(root / arm) for arm in ("baseline", "pis"))
        self.assertEqual((base["metrics"]["set_tp"], base["metrics"]["set_fp"], base["metrics"]["set_fn"]), (78, 484, 3))
        self.assertEqual((old["metrics"]["set_tp"], old["metrics"]["set_fp"], old["metrics"]["set_fn"]), (62, 146, 19))
        self.assertEqual(old["helper"]["adapter_decision_counts"]["ACT"], 0)
        self.assertEqual(old["actor_query_calls_including_clock"], 157)
        self.assertTrue(old["helper"]["snapshot_restore_verified"])
        failures = list(failure_rows({"baseline": base, "candidate": old}))
        self.assertEqual(Counter((row["method"], row["kind"]) for row in failures),
                         {("baseline", "FN"): 3, ("baseline", "FP"): 484,
                          ("candidate", "FN"): 19, ("candidate", "FP"): 146})
        self.assertEqual(checksums, {arm: digest(root / arm / "metrics.json") for arm in ("baseline", "pis")})
        with self.assertRaisesRegex(ValueError, "Candidate must be the source-bound"):
            compare_runs(root / "baseline", root / "pis")


if __name__ == "__main__":
    unittest.main()
