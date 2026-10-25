"""Exact paired requests and strict two-call execution for the GPT diagnostic."""

import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gpt_handoff_probe import MODEL, probe
from artifacts import rows, save
from test_runner import Response


class GPTProbeTests(unittest.TestCase):
    def fixture(self, root):
        source = root / "input"
        source.mkdir()
        for name in ("memory.jsonl", "calls.jsonl", "manifest.json"):
            save(source / name, {})
        case = {"step_key": ["Example", "moment"], "cycle": 2,
                "original_call_id": "selected", "plan": {"next_action": {"channel": "email"}},
                "request": {"model": MODEL, "temperature": 0, "max_tokens": 768,
                            "messages": [{"role": "user", "content": "Saved public handoff"}],
                            "extra_body": {"reasoning": {"exclude": True}},
                            "response_format": {"type": "json_schema", "json_schema": {"schema": {
                                "type": "object", "properties": {"action": {"type": "string"}},
                                "required": ["action"]}}}}}
        args = SimpleNamespace(input_run=source, output=root / "output", source_call_id="selected")
        return args, case

    def test_exactly_two_independent_requests_preserve_original_and_change_only_handoff(self):
        with tempfile.TemporaryDirectory() as temp:
            args, case = self.fixture(Path(temp))
            before = copy.deepcopy(case)
            calls = []
            options = []
            def create(**request):
                calls.append(request)
                return Response('{"action":"query_state","channel":"email"}')
            client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
            client.with_options = lambda **kwargs: (options.append(kwargs), client)[1]
            with patch("gpt_handoff_probe.cases_from_run", return_value=[case]), patch("gpt_handoff_probe.source_files", return_value=[]):
                result = probe(args, client)
            self.assertEqual(case, before)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0], case["request"])
            second = copy.deepcopy(calls[1])
            second["messages"] = copy.deepcopy(calls[0]["messages"])
            self.assertEqual(second, calls[0])
            self.assertEqual(len(calls[1]["messages"]), len(calls[0]["messages"]))
            self.assertTrue(calls[1]["messages"][-1]["content"].startswith(calls[0]["messages"][-1]["content"] + "\n"))
            self.assertEqual(options, [{"max_retries": 0, "timeout": 180}])
            self.assertEqual(result["status"], "complete")
            self.assertTrue(result["variants"]["query_first"]["followed"])
            self.assertEqual(len(rows(args.output / "calls.jsonl")), 2)

    def test_transport_error_preserves_attempt_and_never_retries(self):
        with tempfile.TemporaryDirectory() as temp:
            args, case = self.fixture(Path(temp))
            def create(**request):
                raise ConnectionError("scripted transport failure")
            client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
            with patch("gpt_handoff_probe.cases_from_run", return_value=[case]), patch("gpt_handoff_probe.source_files", return_value=[]):
                with self.assertRaises(ConnectionError):
                    probe(args, client)
            calls = rows(args.output / "calls.jsonl")
            self.assertEqual(len(calls), 1)
            self.assertFalse(calls[0]["valid"])
            self.assertTrue((args.output / "cost.json").is_file())

    def test_missing_call_is_rejected_before_creating_output_or_client(self):
        with tempfile.TemporaryDirectory() as temp:
            args, _ = self.fixture(Path(temp))
            with patch("gpt_handoff_probe.cases_from_run", return_value=[]), patch("gpt_handoff_probe.pm_bench.build_llm_client") as build:
                with self.assertRaises(ValueError):
                    probe(args)
                build.assert_not_called()
            self.assertFalse(args.output.exists())
