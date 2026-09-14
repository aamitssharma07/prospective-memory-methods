"""Offline runner wiring tests, not language-model performance measurements."""

import contextlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import run_memory


class PortableRunnerTests(unittest.TestCase):
    def test_generate_helper_preserves_explicit_portable_schema(self):
        client = Mock()
        schema = {"type": "object", "properties": {"changes": {"type": "array"}}}
        run_memory.generate_helper(client, "fixture", "compile", {}, 4096, schema=schema)
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["response_format"]["json_schema"]["schema"], schema)
        self.assertEqual(kwargs["max_tokens"], 4096)
        self.assertFalse(kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"])

    def test_portable_runner_full_80_step_public_interface(self):
        compiled, acted, helper_phases = [], [], []

        def helper(client, model, system, payload, max_tokens, schema=None):
            self.assertIsNotNone(schema)
            if "changes" in schema["properties"]:
                text = payload["instruction"]["text"]
                self.assertNotIn("Step action menu", text)
                self.assertIsNone(re.search(r"task_\d+\s*:", text))
                self.assertIsNone(re.search(r"^[ABC][).:]\s", text, re.MULTILINE))
                compiled.append(text)
                # Deliberately scripted registration: tests wiring, not semantics.
                result = {"changes": [] if len(compiled) > 1 else [{
                    "op": "register", "action": "Fixture-only action",
                    "condition": "Fixture-only condition", "sources": ["events"],
                    "scope": "*", "repeat": True, "target_id": "",
                    "evidence_quote": text[:200],
                }]}
                helper_phases.append("compile")
            else:
                observations = payload["observations"]
                result = {"decisions": [] if not observations else [{
                    "kind": "ACT", "intention_id": payload["intentions"][0]["id"],
                    "reason": "Scripted fixture", "source": "",
                    "evidence_ids": [observations[0]["id"]],
                }]}
                helper_phases.append("assess")
            self.assertNotIn("due_now", json.dumps(payload))
            return SimpleNamespace(usage=None, choices=[SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(content=json.dumps(result)))])

        def actor(client, model, messages, *args, **kwargs):
            transient = [message for message in messages
                         if message["content"].startswith("Prospective-memory observations and proposals:")]
            self.assertEqual(len(transient), 1)
            acted.append(messages[-1]["content"])
            return {"action": "choose", "choice": "A", "task_ids": [], "channel": "NONE"}

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            argv = ["run_memory.py", "--mode", "selective", "--memory-version", "portable",
                    "--model", "fixture", "--output", str(output)]
            with patch.object(sys, "argv", argv), \
                 patch.object(run_memory.pm_bench, "build_llm_client", return_value=None), \
                 patch.object(run_memory, "generate_helper", side_effect=helper), \
                 patch.object(run_memory.pm_bench, "request_model_action", side_effect=actor), \
                 contextlib.redirect_stdout(io.StringIO()):
                run_memory.main()
            self.assertEqual(len(acted), 80)
            self.assertIn("compile", helper_phases)
            self.assertEqual(helper_phases.count("assess"), 80)
            metrics = json.loads((output / "metrics.json").read_text())
            self.assertEqual(metrics["fallback_steps"], 0)
            trajectory = [json.loads(line) for line in (output / "trajectory.jsonl").read_text().splitlines()]
            self.assertEqual(sum("step_id" in entry for entry in trajectory), 80)
            self.assertEqual(len((output / "memory.jsonl").read_text().splitlines()), 80)
            self.assertIsInstance(json.loads((output / "memory_snapshot.json").read_text()), dict)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["fallback"], "empty")
            self.assertEqual(manifest["memory_version"], "portable")
            self.assertIn("prospective_memory/core.py", manifest["source_sha256"])
            self.assertEqual(len(manifest["scenario_sha256"]), 64)

    def test_unsupported_mode_fails_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "not-created"
            with patch.object(sys, "argv", ["run_memory.py", "--mode", "always",
                              "--memory-version", "portable", "--output", str(output)]), \
                 contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                run_memory.main()
            self.assertFalse(output.exists())

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sys, "argv", ["run_memory.py", "--mode", "selective",
                              "--memory-version", "portable", "--output", directory]), \
                 self.assertRaises(FileExistsError):
                run_memory.main()


if __name__ == "__main__":
    unittest.main()
