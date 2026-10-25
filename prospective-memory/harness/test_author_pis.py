"""Offline tests for transport-only author reproduction and state-aware audit."""
import io
import json
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from contextlib import redirect_stdout

from run_author_pis import install_trace
from summarize_author_pis import score_with_rows, pm_bench
from tempfile import TemporaryDirectory


class AuthorReproductionTests(unittest.TestCase):
    def test_routes_only_helper_and_preserves_policy_inputs(self):
        actor, helper = object(), object()
        role = ["choose"]
        calls, log = [], io.StringIO()
        def create(resource, **kw):
            calls.append((resource, kw))
            return NS(choices=[NS(message=NS(content='{"action":"choose"}'), finish_reason="stop")],
                      usage=NS(prompt_tokens=3, completion_tokens=4, total_tokens=7))
        wrapper = install_trace(create, helper, lambda: role[0], log)
        kwargs = dict(model="Qwen/Qwen3-8B", messages=[{"role": "user", "content": "public only"}],
                      max_tokens=768, temperature=0, response_format={"type": "json_object"},
                      extra_body={"custom": 42, "chat_template_kwargs": {"other": True}})
        wrapper(actor, **kwargs)
        role[0] = "update_judge"
        wrapper(actor, **kwargs)
        self.assertIs(calls[0][0], actor)
        self.assertIs(calls[1][0], helper)
        for _, actual in calls:
            for key in ("model", "messages", "max_tokens", "temperature", "response_format"):
                self.assertEqual(actual[key], kwargs[key])
            self.assertEqual(actual["extra_body"], {"custom": 42, "chat_template_kwargs": {"other": True, "enable_thinking": False}})
        self.assertNotIn("enable_thinking", kwargs["extra_body"]["chat_template_kwargs"])
        events = [json.loads(s) for s in log.getvalue().splitlines()]
        self.assertEqual([e["role"] for e in events], ["choose", "update_judge"])
        self.assertEqual(events[0]["usage"]["total_tokens"], 7)

    def test_transport_error_is_logged_and_propagated(self):
        def fail(*args, **kwargs):
            raise ValueError("test failure")
        log = io.StringIO()
        wrapper = install_trace(fail, None, lambda: "choose", log)
        with self.assertRaisesRegex(ValueError, "test failure"):
            wrapper(None, messages=[])
        self.assertIn("test failure", json.loads(log.getvalue())["error"])

    def test_call_limit_bypasses_upstream_exception_recovery(self):
        calls = []
        def create(*args, **kwargs):
            calls.append(1)
            return NS(choices=[NS(message=NS(content="{}"), finish_reason="stop")], usage=None)
        wrapper = install_trace(create, None, lambda: "choose", io.StringIO())
        with redirect_stdout(io.StringIO()):
            for _ in range(2000):
                wrapper(None, messages=[])
        with self.assertRaisesRegex(SystemExit, "Safety abort"):
            wrapper(None, messages=[])
        self.assertEqual(len(calls), 2000)

    def test_offline_rows_reconcile_to_scorer(self):
        root = Path(__file__).resolve().parents[1]
        scenario = json.loads((root / "benchmark/data/synthetic_week_v9.json").read_text())
        entries = [{"day": d["name"], "step_id": s["id"], "choice": "A", "task_ids": []}
                   for d in scenario["days"] for s in d["steps"]]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "empty.jsonl"
            path.write_text("".join(json.dumps(e) + "\n" for e in entries))
            result = score_with_rows(scenario, path)
        expected, _, _ = pm_bench.score_log(scenario, entries)
        self.assertEqual(result["summary"], expected)
        self.assertEqual(len(result["rows"]), 80)
        self.assertEqual(sum(len(r["fn"]) for r in result["rows"]), expected["set_fn"])
        self.assertEqual(result["metrics"]["set_tp"], 0)


if __name__ == "__main__":
    unittest.main()
