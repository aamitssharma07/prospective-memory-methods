"""Offline harness contracts; scripted responses are not model-quality evidence."""

import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from prospective_memory.evaluate_pis_grounded import (
    AuditedRequest, DEFAULT_CASES, SmokeAbort, main, phase_name, run_case,
    summarize, validate_cases,
)


SUITE = json.loads(DEFAULT_CASES.read_text())
CASES = {row["id"]: row for row in SUITE["cases"]}


def change(text, **overrides):
    return {"op": "register", "target_id": "", "action": "Take vitamin",
            "condition": "when breakfast begins", "sources": ["events"],
            "days": [], "repeat": False, "clock_op": "none", "clock_time": "",
            "evidence_quote": text, **overrides}


def assessment(state, observation=None, missing_source=""):
    return {"assessments": [{"state": state, "reason": "Scripted contract",
                            "evidence_ids": [observation["id"]] if observation else [],
                            "evidence_quotes": [observation["text"]] if observation else [],
                            "missing_source": missing_source}]}


class Scripted:
    def __init__(self, changes, assessor, verdict="supported"):
        self.changes, self.assessor, self.verdict = changes, assessor, verdict
        self.seen, self.context = [], {}

    def __call__(self, system, payload, schema):
        self.seen.append((system, copy.deepcopy(payload), copy.deepcopy(schema)))
        phase = phase_name(schema)
        if phase == "compile":
            return {"changes": self.changes.get(payload["instruction"]["id"], [])}
        if phase == "change_review":
            return {"reviews": [{"verdict": self.verdict, "reason": "Scripted review"}]}
        return self.assessor(payload)


class GroundedEvaluationTests(unittest.TestCase):
    def test_frozen_suite_has_ten_valid_cases(self):
        validate_cases(SUITE)
        self.assertEqual(len(SUITE["cases"]), 10)

    def test_duplicate_case_and_wrong_reply_source_rejected(self):
        bad = copy.deepcopy(SUITE)
        bad["cases"].append(bad["cases"][0])
        with self.assertRaises(ValueError):
            validate_cases(bad)
        bad = copy.deepcopy(SUITE)
        case = next(c for c in bad["cases"] if c["id"] == "hidden_source_check_then_act")
        case["ticks"][0]["pull_responses"]["appointment_portal"][0]["source"] = "events"
        with self.assertRaises(ValueError):
            validate_cases(bad)

    def breakfast_provider(self, **overrides):
        case = CASES["visible_breakfast"]
        return Scripted({"meal": [change(case["instructions"][0]["text"], **overrides)]},
                        lambda p: assessment("satisfied", p["observations"][0]))

    def test_positive_act_and_no_automatic_completion(self):
        result = run_case(CASES["visible_breakfast"], self.breakfast_provider())
        self.assertTrue(result["passed"])
        self.assertEqual((result["act_tp"], result["act_fp"], result["act_fn"]), (1, 0, 0))
        self.assertEqual(result["final_state"]["intentions"][0]["status"], "pending")

    def test_labels_never_enter_callback_payloads(self):
        provider = self.breakfast_provider()
        run_case(CASES["visible_breakfast"], provider)
        allowed = {
            "compile": {"instruction", "intentions", "available_sources"},
            "change_review": {"instruction", "proposed_change", "target",
                              "target_original_instructions", "available_sources"},
            "assess": {"intention", "original_instructions", "observations",
                       "current_scope", "check_sources", "remaining_check_budget"},
        }
        self.assertEqual([phase_name(s) for _, _, s in provider.seen],
                         ["compile", "change_review", "assess"])
        for _, payload, schema in provider.seen:
            self.assertEqual(set(payload), allowed[phase_name(schema)])
            self.assertNotIn("expected_", json.dumps(payload))

    def test_missing_registration_cannot_pass_negative(self):
        provider = Scripted({}, lambda p: assessment("unknown"))
        result = run_case(CASES["future_and_negative_event"], provider)
        self.assertFalse(result["passed"])
        self.assertFalse(result["registration_coverage"]["locker"])
        self.assertFalse(result["initial_record_checks"]["passed"])
        self.assertEqual(result["act_count"], 0)
        self.assertEqual(summarize([result])["registration_coverage"], 0)

    def test_rejected_registration_cannot_pass_negative(self):
        case = CASES["future_and_negative_event"]
        provider = Scripted({"locker": [change(case["instructions"][0]["text"],
                                               action="Bring pickup code")]},
                            lambda p: assessment("unknown"), verdict="unsupported")
        result = run_case(case, provider)
        self.assertFalse(result["passed"])
        self.assertTrue(result["protection_events"])
        self.assertFalse(result["unexpected_errors"])

    def test_negative_wait_requires_actual_registration(self):
        case = CASES["future_and_negative_event"]
        provider = Scripted({"locker": [change(case["instructions"][0]["text"],
                                               action="Bring pickup code")]},
                            lambda p: assessment("not_satisfied", p["observations"][0]))
        result = run_case(case, provider)
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["final_state"]["intentions"]), 1)
        self.assertEqual(len(result["registration_events"]), 2)

    def test_malformed_assessment_cannot_pass_quiet_case(self):
        case = CASES["future_and_negative_event"]
        provider = Scripted({"locker": [change(case["instructions"][0]["text"],
                                               action="Bring pickup code")]},
                            lambda p: {"assessments": []})
        result = run_case(case, provider)
        self.assertFalse(result["passed"])
        self.assertTrue(result["ticks"][0]["exact_decisions"])
        self.assertTrue(result["unexpected_errors"])

    def test_corrective_clock_guard_is_not_a_runtime_failure(self):
        provider = self.breakfast_provider(clock_op="at", clock_time="08:00")
        result = run_case(CASES["visible_breakfast"], provider)
        self.assertTrue(result["passed"])
        self.assertEqual(result["protection_events"][0]["phase"], "clock_guard")

    def test_check_response_act_and_attempt_budget_are_recorded(self):
        case = CASES["hidden_source_check_then_act"]

        def assessor(payload):
            reply = next((o for o in payload["observations"]
                          if o["source"] == "appointment_portal"), None)
            return (assessment("satisfied", reply) if reply else
                    assessment("unknown", missing_source="appointment_portal"))

        provider = Scripted({"form": [change(case["instructions"][0]["text"],
                                             action="Submit intake form",
                                             sources=["appointment_portal"])]}, assessor)
        result = run_case(case, provider)
        self.assertTrue(result["passed"])
        self.assertEqual(result["final_state"]["step_queries"], ["appointment_portal"])
        self.assertEqual([d["kind"] for rnd in result["ticks"][0]["rounds"]
                          for d in rnd["decisions"]], ["CHECK", "ACT"])
        self.assertEqual(result["act_tp"], 1)

    def test_wrong_time_act_cannot_offset_correct_time_miss(self):
        case = copy.deepcopy(CASES["future_and_negative_event"])
        case["ticks"][1]["expected_rounds"] = [[{"origin_id": "locker", "kind": "ACT"}]]
        provider = Scripted({"locker": [change(case["instructions"][0]["text"],
                                               action="Bring pickup code")]},
                            lambda p: assessment("satisfied" if p["observations"][0]["id"] == "future_light"
                                                  else "not_satisfied", p["observations"][0]))
        result = run_case(case, provider)
        self.assertEqual((result["act_tp"], result["act_fp"], result["act_fn"]), (0, 1, 1))

    def test_infrastructure_abort_is_not_swallowed_by_engine(self):
        def request(system, payload, schema):
            raise SmokeAbort("offline")
        with self.assertRaises(SmokeAbort):
            run_case(CASES["visible_breakfast"], request)


class Response:
    status = 200

    def __init__(self, content='{"label":"ready"}'):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": self.content}}],
                           "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}).encode()


class AuditedTransportTests(unittest.TestCase):
    def test_full_request_response_usage_and_phase_logging(self):
        log = io.StringIO()
        request = AuditedRequest("http://localhost/v1", "test-model", 4096, log,
                                 input_usd_per_million=1, output_usd_per_million=2)
        with patch("prospective_memory.evaluate_pis_grounded.urlopen", return_value=Response()):
            request("system", {"instruction": "public"}, {"properties": {"reviews": {}}})
        row = json.loads(log.getvalue())
        self.assertEqual(row["phase"], "change_review")
        self.assertEqual(row["request"]["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(row["system"], "system")
        self.assertEqual(row["usage"]["total_tokens"], 15)
        self.assertIn("raw_http_response", row)
        self.assertEqual(row["estimated_token_cost_usd"], 0.00002)

    def test_decode_failure_logs_raw_content(self):
        log = io.StringIO()
        request = AuditedRequest("http://localhost/v1", "test-model", 4096, log)
        with patch("prospective_memory.evaluate_pis_grounded.urlopen", return_value=Response("bad JSON")):
            with self.assertRaises(json.JSONDecodeError):
                request("system", {}, {"properties": {"assessments": {}}})
        row = json.loads(log.getvalue())
        self.assertEqual(row["raw"], "bad JSON")
        self.assertEqual(row["error"]["type"], "JSONDecodeError")

    def test_call_budget_aborts_without_extra_network_request(self):
        log = io.StringIO()
        request = AuditedRequest("http://localhost/v1", "test-model", 4096, log, max_calls=1)
        with patch("prospective_memory.evaluate_pis_grounded.urlopen", return_value=Response()) as transport:
            request("system", {}, {"properties": {"label": {}}})
            with self.assertRaises(SmokeAbort):
                request("system", {}, {"properties": {"label": {}}})
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(json.loads(log.getvalue().splitlines()[-1])["event"], "call_budget_abort")

    def test_fresh_output_refuses_existing_directory_before_network(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("prospective_memory.evaluate_pis_grounded.urlopen") as transport:
                with self.assertRaises(FileExistsError):
                    main(["--output", temp])
                transport.assert_not_called()

    def test_transport_abort_saves_failed_status_and_source_snapshots(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "new-run"
            with patch("prospective_memory.evaluate_pis_grounded.urlopen", side_effect=URLError("offline")):
                with self.assertRaises(SmokeAbort):
                    main(["--output", str(output)])
            self.assertEqual(json.loads((output / "status.json").read_text())["status"], "failed")
            self.assertFalse((output / "metrics.json").exists())
            self.assertEqual((output / "cases.json").read_bytes(), DEFAULT_CASES.read_bytes())
            self.assertTrue((output / "source/docs/dev_protocols/PIS_GROUNDED_SMOKE_PROTOCOL.md").exists())
            row = json.loads((output / "calls.jsonl").read_text())
            self.assertEqual(row["phase"], "probe")
            self.assertEqual(row["error"]["type"], "URLError")


if __name__ == "__main__":
    unittest.main()
