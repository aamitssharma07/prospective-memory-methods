import copy
import io
import json
import unittest
from unittest.mock import patch
import tempfile
from pathlib import Path
import sys
import contextlib
from memory_intervention import MemoryAssistant


class MemoryTests(unittest.TestCase):
    def test_helper_request_enforces_json_without_thinking(self):
        from run_memory import generate_helper
        from unittest.mock import Mock
        client = Mock()
        generate_helper(client, "Qwen/Qwen3-8B", 'Return {"edits": []}', {})
        request = client.chat.completions.create.call_args.kwargs
        self.assertFalse(request["extra_body"]["chat_template_kwargs"]["enable_thinking"])
        self.assertEqual(request["max_tokens"], 2048)
        schema = request["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema["required"], ["edits"])
        self.assertFalse(schema["additionalProperties"])

    def test_full_benchmark_loop_empty_fallback(self):
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root / "benchmark/sim"))
        import pm_bench
        class Adapter:
            def context_for(self, messages):
                return "TEST_TRANSIENT"
        def invalid(client, model, messages, *args, **kwargs):
            self.assertEqual(sum(m["content"] == "TEST_TRANSIENT" for m in messages), 1)
            raise pm_bench.InvalidModelResponseError("scripted invalid action")
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(pm_bench, "build_llm_client", return_value=None), \
             patch.object(pm_bench, "request_model_action", side_effect=invalid), \
             contextlib.redirect_stdout(io.StringIO()):
            entries = pm_bench.run_llm(
                pm_bench.load_scenario(str(root / "benchmark/data/synthetic_week_v9.json")),
                str(Path(directory) / "trajectory.jsonl"), "dummy", ".env", 5,
                "sglang", None, None, invalid_response_fallback="empty",
                memory_adapter=Adapter())
        self.assertEqual(len(entries), 80)
        self.assertTrue(all(e["fallback_triggered"] and not e["task_ids"] for e in entries))

    def test_visible_messages_and_transient_reminder(self):
        calls = []
        outputs = iter(['{"edits":[]}', '{"reminder":"Check the library channel."}',
                        '{"edits":[]}', '{"reminder":""}'])
        def generate(system, payload):
            calls.append(copy.deepcopy(payload))
            return next(outputs)
        helper = MemoryAssistant(generate)
        messages = [{"role": "user", "content": "Collect book when ready."}]
        original = copy.deepcopy(messages)
        self.assertIn("Check the library", helper.context_for(messages))
        self.assertEqual(messages, original)
        self.assertEqual(helper.context_for(messages), "")
        self.assertEqual(calls[2]["new_messages"], [])
        self.assertNotIn("due_now", json.dumps(calls))

    def test_invalid_edits_atomic_and_invalid_reminder_silent(self):
        outputs = iter(['{"edits":[{"op":"status","text":"changed"},{"op":"bad"}]}', 'invalid'])
        log = io.StringIO()
        helper = MemoryAssistant(lambda *args: next(outputs), log=log)
        self.assertEqual(helper.context_for([]), "")
        self.assertEqual(helper.bank["status"], "")
        self.assertEqual(len(json.loads(log.getvalue())["errors"]), 2)

    def test_revision_delete_and_private_status(self):
        output = '{"edits":[{"op":"status","text":"private"},{"op":"delete","section":"knowledge","id":"old"},{"op":"save","section":"knowledge","id":"new","text":"Revised intention"}]}'
        helper = MemoryAssistant(lambda *args: output, mode="full_bank")
        helper.bank["knowledge"]["old"] = "Cancelled intention"
        result = helper.context_for([])
        self.assertNotIn("private", result)
        self.assertNotIn("Cancelled", result)
        self.assertIn("Revised intention", result)


if __name__ == "__main__":
    unittest.main()
