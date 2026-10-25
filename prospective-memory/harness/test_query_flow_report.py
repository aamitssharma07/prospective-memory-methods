"""Query-flow fixtures contain no inference, scorer calls or experimental scores."""

import copy
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from harness.report_query_flow import (
    FAIR_SOURCE, GUIDANCE, HANDOFF, ROOT, audit_run, digest, main, write_report,
)
from prospective_memory.core import Decision
from prospective_memory.method.fair_checks import FairCheckArbiter


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def save_lines(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def load(path):
    return json.loads(path.read_text())


def load_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def make_run(path, *, fair=False, explicit=False):
    """Two completed steps: wrong clock, repeated clock, choose; calendar, choose.

    Four CHECKs: two substituted queries, one exact query and a final skipped
    email CHECK. V5 adds full candidates including shared/deferred intentions.
    """
    path.mkdir()
    sources = ["calendar", "clock", "email"]
    variant = "sbpm" if fair else "sbpm_no_projection"
    messages = [{"role": "system", "content": "Available state channels: calendar, clock, email."},
                {"role": "user", "content": "=== Monday ==="}]
    intentions = [{"id": identity, "action": "Action " + identity, "condition": "Condition " + identity,
                   "sources": [source]} for identity, source in
                  (("calendar_1", "calendar"), ("calendar_2", "calendar"), ("email_1", "email"))]
    by_id = {item["id"]: item for item in intentions}
    check = lambda identity, source: Decision("CHECK", identity, "Current information missing", source=source)
    candidates = [check("calendar_1", "calendar"), check("calendar_2", "calendar"), check("email_1", "email")]
    arbiter, arbitration_log, memory = FairCheckArbiter(sources), [], []
    if fair:
        arbitration_log.append({"event": "capability_reset", "step_id": "", "queryable_sources": sources,
                                "previous_history": FairCheckArbiter([]).snapshot()})
    observed, queries, menu_index = [], [], 0
    sequence = [("query_state", "clock", None), ("check_time", "clock", None), ("choose", "", "A"),
                ("query_state", "calendar", None), ("choose", "", "B")]
    for cycle, (kind, source, choice) in enumerate(sequence, 1):
        if cycle in {1, 4}:
            menu_index = len(messages)
            messages.append({"role": "user", "content": f"Scene {cycle}.\nStep action menu:\n- task_1: act"})
            observed = [{"id": f"message_{menu_index}", "source": "events", "text": f"Scene {cycle}.", "current": True}]
            queries = []
        eligible = [] if cycle == 3 else [candidates[-1]] if cycle == 5 else candidates
        if fair:
            selected = arbiter.arbitrate(eligible, budget=min(1, max(0, 2 - len(queries))))
            delivered = [group.decisions[0] for group in selected.selected]
            arbitration_log.append({"event": "selection", "scope": "Monday", "step_id": f"message_{menu_index}",
                                    "queryable_sources": sources, "budget": min(1, max(0, 2 - len(queries))),
                                    "candidates": [{**asdict(d), "evidence_ids": []} for d in eligible],
                                    "priority_sources": [], "selected_sources": list(selected.selected_sources),
                                    "deferred_sources": list(selected.deferred_sources),
                                    "representatives": {g.source: g.decisions[0].intention_id for g in selected.selected}})
        else:
            delivered = [] if cycle == 3 else [candidates[0] if cycle in {1, 4} else candidates[-1]]
        bank = {"policy_variant": variant, "intentions": intentions, "sources": ["events", *sources],
                "queryable_sources": sources, "step_id": f"message_{menu_index}", "step_queries": queries,
                "query_budget": 1, "step_query_budget": 2}
        if fair:
            bank.update(arbitration_log=copy.deepcopy(arbitration_log), fair_check_state=arbiter.snapshot())
        guidance = [{"decision": "CHECK", "source": d.source, "action": by_id[d.intention_id]["action"],
                     "condition": by_id[d.intention_id]["condition"], "reason": d.reason} for d in delivered]
        reminder = GUIDANCE + json.dumps(guidance) + "\nAdvisory only." if guidance else ""
        if explicit and delivered:
            reminder += "\n" + HANDOFF + json.dumps({
                "optional_query_actions": [{"action": "query_state", "choice": "NONE", "task_ids": [], "channel": d.source} for d in delivered],
                "current_observed_sources": [o["source"] for o in observed],
                "actual_query_attempts_this_step": queries})
        memory.append(copy.deepcopy({"cycle": cycle, "mode": "portable", "scope": "Monday", "bank": bank,
                                     "observations": observed, "decisions": [{**asdict(d), "evidence_ids": []} for d in delivered],
                                     "reminder": reminder, "attempts": [], "errors": []}))
        if cycle == len(sequence):
            break  # The real adapter snapshot is before this final choice.
        messages.append({"role": "assistant", "content": json.dumps({"action": kind, "choice": choice or "NONE",
                                                                      "task_ids": ["task_1"] if choice else [],
                                                                      "channel": source or "NONE"})})
        if source:
            reply_index = len(messages)
            text = "Time 09:00" if source == "clock" else "A public calendar update."
            messages.append({"role": "user", "content": f"State [{source}]: {text}"})
            queries.append(source)
            arbiter.record_query(source)
            observed = [o for o in observed if o["source"] != source]
            observed.append({"id": f"message_{reply_index}", "source": source, "text": text, "current": True})
    snapshot = {"version": 1, "adapter": "pmbench", "seen": len(messages), "cycles": len(memory),
                "scope": "Monday", "messages": messages, "engine": memory[-1]["bank"],
                "current_observations": memory[-1]["observations"], "last_decisions": memory[-1]["decisions"], "act_cache": {}}
    if explicit:
        snapshot["query_handoff"] = "explicit"
    save(path / "memory_snapshot.json", snapshot)
    save_lines(path / "memory.jsonl", memory)
    save_lines(path / "memory_calls.jsonl", [])
    scenario = {"days": [{"name": "Monday", "steps": [{"id": "s1"}, {"id": "s2"}]}]}
    save(path / "scenario.json", scenario)
    entries = [{"day": "Monday", "step_id": "s1", "choice": "A", "task_ids": ["canonical_not_actor_handle"],
                "state_queries": {"clock": 2}, "check_time": 2},
               {"day": "Monday", "step_id": "s2", "choice": "B", "task_ids": [],
                "state_queries": {"calendar": 1}, "check_time": 0}]
    metadata = {"record_type": "run_metadata", "finished_at_utc": "2026-01-01T00:00:00Z", "entry_count": 2}
    save_lines(path / "trajectory.jsonl", [metadata, *entries])
    save(path / "metrics.json", {"steps": 2, "metrics": {"state_query_calls": 3, "check_time_calls": 2},
                                 "summary": {"state_query_calls": 3, "check_time_calls": 2}})
    frozen = path / "source" / FAIR_SOURCE
    frozen.parent.mkdir(parents=True)
    frozen.write_bytes((ROOT / FAIR_SOURCE).read_bytes())
    manifest = {"memory_version": "portable", "policy_variant": variant, "memory_check_budget": 1,
                "pis_step_query_budget": 2, "source_sha256": {FAIR_SOURCE: digest(frozen)},
                "scenario_sha256": digest(path / "scenario.json")}
    if explicit:
        manifest["memory_query_handoff"] = "explicit"
    save(path / "manifest.json", manifest)
    return path


class QueryFlowReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = make_run(self.root / "run")

    def test_final_missing_action_and_exact_wrong_skipped_queries(self):
        result = audit_run(self.run)
        s = result["summary"]
        self.assertEqual((s["delivered_checks"], s["exact_source"], s["different_source"], s["choose_without_query"]), (4, 1, 2, 1))
        self.assertEqual(s["actual_queries_by_source"], {"calendar": 1, "clock": 2})
        self.assertEqual(s["actual_queries_including_clock"], 3)
        self.assertEqual(s["repeated_queries_same_step"], 1)
        self.assertEqual(s["identical_repeat_replies"], 1)
        self.assertEqual(s["step_query_count_histogram"], {1: 1, 2: 1})
        self.assertEqual(result["checks"][-1]["action_origin"], "final_executed_trajectory_choice")
        self.assertEqual(result["checks"][-1]["check_source"], "email")
        self.assertIsNone(result["fair_arbitration"])

    def test_actual_query_without_preceding_check_is_not_invented_uptake(self):
        rows = load_lines(self.run / "memory.jsonl")
        rows[0]["decisions"], rows[0]["reminder"] = [], ""
        save_lines(self.run / "memory.jsonl", rows)
        result = audit_run(self.run)
        self.assertEqual(result["summary"]["actual_queries_without_check"], 1)
        self.assertEqual(result["summary"]["actual_queries_including_clock"], 3)
        self.assertEqual(result["summary"]["delivered_checks"], 3)

    def test_multiple_checks_share_one_actual_query_denominator(self):
        rows = load_lines(self.run / "memory.jsonl")
        other = copy.deepcopy(rows[0]["decisions"][0])
        other["intention_id"] = "calendar_2"
        rows[0]["decisions"].append(other)
        original = json.JSONDecoder().raw_decode(rows[0]["reminder"][len(GUIDANCE):])[0]
        original.append({**original[0], "action": "Action calendar_2", "condition": "Condition calendar_2"})
        rows[0]["reminder"] = GUIDANCE + json.dumps(original)
        save_lines(self.run / "memory.jsonl", rows)
        result = audit_run(self.run)
        self.assertEqual(result["summary"]["delivered_checks"], 5)
        self.assertEqual(result["summary"]["actual_queries_including_clock"], 3)

    def test_v5_replay_tracks_all_candidates_sharing_and_actual_substitutions(self):
        run = make_run(self.root / "fair", fair=True, explicit=True)
        result = audit_run(run)
        fair = result["fair_arbitration"]
        self.assertEqual(fair["selection_events"], 5)
        self.assertEqual(fair["candidate_intentions"], 10)
        self.assertEqual(fair["candidate_source_groups"], 7)
        self.assertEqual((fair["selected_source"], fair["shared_source"], fair["shared_intentions"]), (4, 2, 2))
        self.assertEqual((fair["deferred_source"], fair["deferred_intentions"]), (3, 4))
        self.assertEqual(fair["actual_queried_by_source"], {"calendar": 1, "clock": 2})
        actual_history = [h["source"] for h in result["fair_history"] if h["event"] == "queried"]
        self.assertEqual(actual_history, ["clock", "clock", "calendar"])
        self.assertEqual([h["source"] for h in result["fair_history"] if h["event"] == "offered"], ["calendar", "email", "calendar", "email"])
        self.assertEqual(result["cycles"][2]["queries_before"], ["clock", "clock"])

    def test_cycle_or_snapshot_cursor_mismatch_fails(self):
        state = load(self.run / "memory_snapshot.json")
        state["cycles"] += 1
        save(self.run / "memory_snapshot.json", state)
        with self.assertRaisesRegex(ValueError, "cycle/cursor"):
            audit_run(self.run)

    def test_same_count_but_wrong_observation_prefix_fails(self):
        rows = load_lines(self.run / "memory.jsonl")
        rows[0]["observations"][0]["id"] = "message_4"
        save_lines(self.run / "memory.jsonl", rows)
        with self.assertRaisesRegex(ValueError, "observation"):
            audit_run(self.run)

    def test_same_count_but_wrong_step_ledger_fails(self):
        rows = load_lines(self.run / "memory.jsonl")
        rows[1]["bank"]["step_queries"] = ["calendar"]
        save_lines(self.run / "memory.jsonl", rows)
        with self.assertRaisesRegex(ValueError, "step-query ledger"):
            audit_run(self.run)

    def test_query_proposal_cannot_override_rejected_actor_action(self):
        snapshot = load(self.run / "memory_snapshot.json")
        snapshot["messages"][4]["content"] = "Invalid channel. Respond again."
        save(self.run / "memory_snapshot.json", snapshot)
        with self.assertRaisesRegex(ValueError, "Query reply"):
            audit_run(self.run)

    def test_unknown_actor_action_is_not_silently_skipped(self):
        snapshot = load(self.run / "memory_snapshot.json")
        snapshot["messages"][3]["content"] = json.dumps({"action": "set_heartbeat"})
        save(self.run / "memory_snapshot.json", snapshot)
        with self.assertRaisesRegex(ValueError, "Unsupported actor action"):
            audit_run(self.run)

    def test_wrong_step_query_counts_and_choice_fail(self):
        original = load_lines(self.run / "trajectory.jsonl")
        for field, value, error in (("state_queries", {"clock": 1}, "trajectory queries"), ("choice", "C", "choice mismatch")):
            with self.subTest(field=field):
                rows = copy.deepcopy(original)
                rows[1][field] = value
                save_lines(self.run / "trajectory.jsonl", rows)
                with self.assertRaisesRegex(ValueError, error):
                    audit_run(self.run)

    def test_partial_or_live_run_is_rejected(self):
        rows = load_lines(self.run / "trajectory.jsonl")
        rows[0].pop("finished_at_utc")
        save_lines(self.run / "trajectory.jsonl", rows)
        with self.assertRaisesRegex(ValueError, "completion metadata"):
            audit_run(self.run)

    def test_missing_delivered_reminder_fails_instead_of_counting_proposal(self):
        rows = load_lines(self.run / "memory.jsonl")
        rows[0]["reminder"] = "No CHECK delivered."
        save_lines(self.run / "memory.jsonl", rows)
        with self.assertRaisesRegex(ValueError, "delivered reminder"):
            audit_run(self.run)

    def test_explicit_appendix_records_actual_wrong_queries_and_is_checked(self):
        run = make_run(self.root / "explicit", explicit=True)
        self.assertEqual(audit_run(run)["summary"]["different_source"], 2)
        rows = load_lines(run / "memory.jsonl")
        rows[1]["reminder"] = rows[1]["reminder"].replace('"actual_query_attempts_this_step": ["clock"]',
                                                         '"actual_query_attempts_this_step": ["email"]')
        save_lines(run / "memory.jsonl", rows)
        with self.assertRaisesRegex(ValueError, "handoff differs"):
            audit_run(run)

    def test_fair_history_cannot_replace_actual_query_with_offer(self):
        run = make_run(self.root / "fair", fair=True)
        rows = load_lines(run / "memory.jsonl")
        rows[1]["bank"]["fair_check_state"]["queried"][0]["source"] = "calendar"
        save_lines(run / "memory.jsonl", rows)
        with self.assertRaisesRegex(ValueError, "fair offer/query history"):
            audit_run(run)

    def test_arbitration_log_rewrite_or_selected_source_mismatch_fails(self):
        run = make_run(self.root / "fair", fair=True)
        rows = load_lines(run / "memory.jsonl")
        rows[1]["bank"]["arbitration_log"][1]["selected_sources"] = ["clock"]
        save_lines(run / "memory.jsonl", rows)
        with self.assertRaisesRegex(ValueError, "append-only"):
            audit_run(run)

    def test_source_and_expected_raw_hashes_verified(self):
        expected = {"memory.jsonl": digest(self.run / "memory.jsonl")}
        self.assertEqual(audit_run(self.run, expected_hashes=expected)["expected_raw_hashes_verified"], expected)
        with self.assertRaisesRegex(ValueError, "Expected raw hash mismatch"):
            audit_run(self.run, expected_hashes={"memory.jsonl": "0" * 64})
        (self.run / "source" / FAIR_SOURCE).write_text("changed frozen source")
        with self.assertRaisesRegex(ValueError, "Source snapshot hash mismatch"):
            audit_run(self.run)

    def test_saved_metrics_query_total_mismatch_fails(self):
        metrics = load(self.run / "metrics.json")
        metrics["metrics"]["state_query_calls"] += 1
        save(self.run / "metrics.json", metrics)
        with self.assertRaisesRegex(ValueError, "metric query totals"):
            audit_run(self.run)

    def test_reports_only_to_fresh_external_directory_and_preserves_inputs(self):
        before = {p.relative_to(self.run): digest(p) for p in self.run.rglob("*") if p.is_file()}
        result = audit_run(self.run)
        output = self.root / "report"
        write_report(result, output)
        self.assertTrue((output / "cycles.csv").is_file())
        self.assertIn("not a performance", (output / "README.md").read_text())
        self.assertEqual(load(output / "ANALYSIS.json")["summary"]["actual_queries_including_clock"], 3)
        with self.assertRaises(FileExistsError):
            write_report(result, output)
        with self.assertRaisesRegex(ValueError, "outside"):
            write_report(result, self.run / "report")
        self.assertEqual(before, {p.relative_to(self.run): digest(p) for p in self.run.rglob("*") if p.is_file()})

    def test_cli_failure_creates_no_success_report(self):
        (self.run / "metrics.json").unlink()
        with patch("sys.stderr"), self.assertRaises(SystemExit) as caught:
            main([str(self.run), str(self.root / "report")])
        self.assertEqual(caught.exception.code, 1)
        self.assertFalse((self.root / "report").exists())

    def test_completed_v3_reproduces_independent_raw_audit_when_available(self):
        run = ROOT / "harness/memory_results/qwen3-8b-pis-source-bound-pair-20260922-01/candidate-v3-01"
        if not (run / "metrics.json").is_file():
            self.skipTest("Historical completed V3 raw artifacts are not distributed")
        expected = {"memory_snapshot.json": "7c45c40cbc72e0eb8a1aa88643792938e9c529cbe2863384f9695f6bff288f57",
                    "memory.jsonl": "41a403435f1b94851088b03c25925fe38d53855ddb57eee26f7e73982f2406b9",
                    "trajectory.jsonl": "f321a661756db260d969c30fa25fb97a5b385575a799fe2739988f269bf55325"}
        result = audit_run(run, expected_hashes=expected)
        s = result["summary"]
        self.assertEqual((s["memory_cycles"], s["completed_steps"]), (196, 80))
        self.assertEqual((s["delivered_checks"], s["exact_source"], s["different_source"], s["choose_without_query"]), (147, 86, 30, 31))
        self.assertEqual(s["actual_queries_by_source"], {"appointment_portal": 6, "calendar": 16, "clock": 92, "course_portal": 2})
        self.assertEqual((s["actual_queries_including_clock"], s["repeated_queries_same_step"], s["identical_repeat_replies"]), (116, 25, 25))
        self.assertEqual(s["step_query_count_histogram"], {0: 13, 1: 18, 2: 49})


if __name__ == "__main__":
    unittest.main()
