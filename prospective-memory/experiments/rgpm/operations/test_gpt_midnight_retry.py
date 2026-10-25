"""No-network tests for the credit-gated recovery wrapper."""

import copy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error

import gpt_midnight_retry as retry


def failed_call():
    error = {"error": {"type": "insufficient_quota", "code": "credit_balance_exhausted"}}
    return {"role": "actor", "call_id": "rejected", "usage": None,
            "request": {"messages": [{"role": "user", "content": "hello"}], "max_completion_tokens": 768},
            "error": {"type": "RateLimitError", "message": "Error code: 429 - " + repr(error)}}


class RecoveryTests(unittest.TestCase):
    def test_rejection_gets_nonzero_reservation_not_fake_usage(self):
        call = failed_call()
        original = copy.deepcopy(call)
        records = retry.reconciliation([call], [])
        self.assertGreater(records[0]["reserved_tokens"], 768)
        self.assertIsNone(records[0]["observed_usage"])
        self.assertEqual(call, original)

    def test_other_unknown_usage_and_unfinished_attempts_still_block(self):
        for detail in ["connection lost", "Error code: 429 - {'error': {'type': 'rate_limit_error'}}"]:
            call = failed_call()
            call["error"]["message"] = detail
            with self.assertRaises(ValueError):
                retry.reconciliation([call], [])
        with self.assertRaises(ValueError):
            retry.reconciliation([], [{"event": "call_start", "role": "actor", "call_id": "unmatched"}])

    def test_recovery_guard_counts_reservations_and_keeps_caps(self):
        class FakeSession:
            def __init__(self, **kwargs):
                self._actor_tokens = 123
                self._actor_usage_unknown = True
                self.max_actor_tokens = kwargs["max_actor_tokens"]
                self.events = []

            def event(self, kind, **fields):
                self.events.append((kind, fields))

        reservations = retry.reconciliation([failed_call()], [])
        session = retry.recovery_session(FakeSession, reservations)(max_actor_tokens=4000000)
        self.assertEqual(session._actor_tokens, 123 + reservations[0]["reserved_tokens"])
        self.assertFalse(session._actor_usage_unknown)
        self.assertEqual(session.max_actor_tokens, 4000000)
        untouched = retry.recovery_session(FakeSession, [])(max_actor_tokens=4000000)
        self.assertTrue(untouched._actor_usage_unknown)

    def test_credit_failure_stops_before_any_servers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = root / "plan.json"
            plan.write_text(json.dumps({"not_before_utc": datetime.now(timezone.utc).isoformat(),
                                        "operational_sha256": {}, "attempts_root": "attempts", "pairs": []}))
            with patch.object(retry, "ROOT", root), patch.dict("os.environ", {"SLURM_JOB_ID": "test"}), \
                    patch.object(retry, "credit_check", return_value=False), patch.object(retry.subprocess, "Popen") as server:
                self.assertEqual(retry.execute(plan), 2)
                server.assert_not_called()
                status = json.loads((root / "attempts/test/status.json").read_text())
                self.assertFalse(status["experiments_started"])

    def test_cannot_start_before_midnight(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps({"not_before_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}))
            with self.assertRaisesRegex(ValueError, "before"):
                retry.execute(path)

    def test_credit_check_records_error_without_key_and_never_retries(self):
        key = "fake-secret-for-test"
        body = json.dumps({"error": {"code": "credit_balance_exhausted", "message": key}}).encode()
        error = urllib.error.HTTPError("https://api.openai.com", 429, "quota", {}, io.BytesIO(body))
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"OPENAI_API_KEY": key}), \
                patch.object(retry.urllib.request, "urlopen", side_effect=error) as request:
            output = Path(directory) / "credit.json"
            self.assertFalse(retry.credit_check(output))
            self.assertEqual(request.call_count, 1)
            self.assertNotIn(key, output.read_text())
            self.assertEqual(json.loads(output.read_text())["http_status"], 429)

    def test_real_frozen_resume_fingerprint_before_any_session_or_network(self):
        manifests = [
            retry.ROOT / "experiments/rgpm/runs/registration_v15_gpt_remaining_helpers/gpt-5-4-helper-qwen3-4b/sbpm/gpt-5-4-actor-helper-qwen3-4b-1553052/manifest.json",
            retry.ROOT / "experiments/rgpm/smoke_artifacts/gpt-5-4-helper-qwen3-8b/sbpm/gpt-5-4-actor-helper-qwen3-8b-1553053/manifest.json",
        ]
        for path in manifests:
            manifest = retry.verified_manifest(path)
            runner = retry.load_runner(path, manifest)
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                (output / "manifest.json").write_text(json.dumps(manifest))
                (output / "status.json").write_text('{"status":"interrupted"}')
                args = retry.phase_arguments(path, output, manifest["kind"], manifest)
                with patch.object(runner, "Session", side_effect=InterruptedError("validated_before_session")):
                    with self.assertRaisesRegex(InterruptedError, "validated_before_session"):
                        runner.run(args)
                self.assertEqual(args.max_actor_calls, manifest["max_actor_calls"])
                self.assertEqual(args.max_actor_tokens, manifest["max_actor_tokens"])

    def test_real_session_reservations_do_not_disable_next_missing_usage_stop(self):
        path = retry.ROOT / "experiments/rgpm/runs/registration_v15_gpt_remaining_helpers/gpt-5-4-helper-qwen3-4b/sbpm/gpt-5-4-actor-helper-qwen3-4b-1553052/manifest.json"
        runner = retry.load_runner(path, retry.verified_manifest(path))
        call = failed_call()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "calls.jsonl").write_text(json.dumps(call) + "\n")
            base = runner.Session
            session = retry.recovery_session(base, retry.reconciliation([call], []))(
                output, "test", max_actor_calls=300, max_actor_tokens=4000000)
            session._admit_actor(call["request"])
            session._account_actor_usage(None)
            with self.assertRaisesRegex(BaseException, "actor_usage_unknown"):
                session._admit_actor(call["request"])
            self.assertIsNone(retry.rows(output / "calls.jsonl")[0]["usage"])
            session._actor_usage_unknown = False
            session._actor_attempts = 300
            with self.assertRaisesRegex(BaseException, "actor_call_budget_exhausted"):
                session._admit_actor(call["request"])
            session._actor_attempts = 1
            session._actor_tokens = 4000000
            with self.assertRaisesRegex(BaseException, "actor_token_budget_reservation_exceeded"):
                session._admit_actor(call["request"])

    def test_schedule_pins_two_pairs_and_verifies_utc_without_submitting_real_job(self):
        target = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(microsecond=0)
        detail = "JobId=123456 JobState=PENDING EligibleTime=" + target.strftime("%Y-%m-%dT%H:%M:%S")
        responses = [SimpleNamespace(stdout="123456\n"), SimpleNamespace(stdout=detail)]
        with tempfile.TemporaryDirectory(dir=retry.ROOT / "experiments/rgpm/launches") as directory:
            plan_path = Path(directory) / "schedule.json"
            with patch.object(retry.subprocess, "run", side_effect=responses) as commands:
                retry.schedule(plan_path, target.isoformat())
            plan = json.loads(plan_path.read_text())
            self.assertEqual(plan["job_id"], "123456")
            self.assertEqual([p["helper"] for p in plan["pairs"]], ["Qwen/Qwen3-4B", "Qwen/Qwen3-8B"])
            self.assertTrue(plan["pairs"][1]["resume_smoke"])
            self.assertFalse(plan["pairs"][0]["resume_smoke"])
            self.assertEqual(plan["credit_probe_max_calls"], 1)
            self.assertEqual(commands.call_args_list[0].kwargs["env"]["TZ"], "UTC")
            self.assertIn("--begin=" + target.strftime("%Y-%m-%dT%H:%M:%S"), commands.call_args_list[0].args[0])
            with self.assertRaisesRegex(ValueError, "duplicate"):
                retry.schedule(plan_path, target.isoformat())


if __name__ == "__main__":
    unittest.main()
