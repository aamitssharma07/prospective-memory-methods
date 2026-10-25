"""Offline tests for the Proactive Memory Agent backend."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from pm_memory.pma import (  # noqa: E402
    PmaBackend,
    PmaMemoryAgent,
    parse_phase2_response,
    parse_tool_calls_from_text,
)


class FakeCompletions:
    def __init__(self, queue):
        self.queue = list(queue)

    def create(self, **kwargs):
        if not self.queue:
            raise AssertionError(f"unexpected LLM call: {kwargs.keys()}")
        return self.queue.pop(0)


class FakeClient:
    def __init__(self, queue):
        self.chat = SimpleNamespace(completions=FakeCompletions(queue))


def _msg(content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class PmaParseTests(unittest.TestCase):
    def test_phase2_injects_context(self):
        raw = "<context_for_action>\nPoster tube is still pending.\n</context_for_action>"
        self.assertEqual(parse_phase2_response(raw), "Poster tube is still pending.")

    def test_phase2_silence(self):
        self.assertIsNone(parse_phase2_response("<no_intervention/>"))

    def test_phase2_default_silence(self):
        self.assertIsNone(parse_phase2_response("I think things are fine."))

    def test_xml_tool_fallback(self):
        text = (
            "<tool_call><function=memory_save_knowledge>"
            "<parameter=content>Meet Dana at 11:00</parameter>"
            "</function></tool_call>"
        )
        parsed = parse_tool_calls_from_text(text)
        self.assertEqual(parsed[0][0], "memory_save_knowledge")
        self.assertEqual(parsed[0][1]["content"], "Meet Dana at 11:00")


class PmaBackendTests(unittest.TestCase):
    def test_recall_injects_reminder(self):
        fn = SimpleNamespace(
            name="memory_save_knowledge",
            arguments='{"content": "Pick up the poster tube when the shelf cue appears"}',
        )
        phase1 = _msg(tool_calls=[SimpleNamespace(function=fn)])
        phase2 = _msg(content="<context_for_action>Shelf cue: poster tube still pending.</context_for_action>")
        agent = PmaMemoryAgent(FakeClient([phase1, phase2]), "dummy")
        backend = PmaBackend(agent)
        text = backend.recall(
            "tube on shelf",
            context={
                "day": "Saturday",
                "step": "s6",
                "observation": "A poster tube sits on the shelf.",
                "messages": [
                    {"role": "user", "content": "A poster tube sits on the shelf."}
                ],
            },
        )
        self.assertIn("poster tube", text.lower())
        self.assertTrue(backend.last_recall_info["injected"])
        self.assertEqual(len(agent.memory.knowledge), 1)

    def test_recall_can_stay_silent(self):
        phase1 = _msg(content="no tools")
        phase2 = _msg(content="<no_intervention/>")
        backend = PmaBackend(PmaMemoryAgent(FakeClient([phase1, phase2]), "dummy"))
        self.assertEqual(backend.recall("hello"), "")
        self.assertFalse(backend.last_recall_info["injected"])

    def test_interval_skips_untriggered_steps(self):
        phase1 = _msg(content="")
        phase2 = _msg(content="<no_intervention/>")
        backend = PmaBackend(
            PmaMemoryAgent(FakeClient([phase1, phase2]), "dummy"),
            interval=2,
        )
        self.assertEqual(backend.recall("first"), "")  # step 1 triggers
        self.assertEqual(backend.recall("second"), "")  # step 2 skipped, no extra LLM
        self.assertFalse(backend.last_recall_info["triggered"])

    def test_encode_keeps_notes(self):
        backend = PmaBackend(PmaMemoryAgent(FakeClient([]), "dummy"))
        backend.encode(
            {
                "day": "Monday",
                "step": "s1",
                "observation": "Morning list: buy milk later.",
                "action": {"action": "choose", "choice": "A", "task_ids": []},
            }
        )
        self.assertEqual(backend.last_encode_info["notes"], 1)


if __name__ == "__main__":
    unittest.main()
