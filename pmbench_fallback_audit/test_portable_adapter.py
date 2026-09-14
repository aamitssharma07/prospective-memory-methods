"""Contract tests for public-message isolation and provider-independent policies."""

import copy
import io
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prospective_memory import Engine, Change, Decision, Instruction
from prospective_memory.adapters.pmbench import PMBenchAdapter, discover_sources, strip_action_choices
from prospective_memory.llm import LLMMemoryPolicy


SYSTEM = {"role": "system", "content": "Available state channels: clock, inbox, build_status."}
HEADER = {"role": "user", "content": "=== Monday ===\nWhen the build completes, send the report."}
STEP = {"role": "user", "content": (
    "You walk into the office.\nA) Read.\nB) Sit.\nC) Wait.\n"
    "Step action menu:\n- task_2: Send the report\n- task_9: Water the plants\n")}


class PortableAdapterTests(unittest.TestCase):
    def make_engine(self):
        self.compiled = []
        self.observed = []
        def compile_message(instruction, intentions, sources):
            self.compiled.append(instruction)
            if "When the build completes" in instruction.text:
                return [Change("register", "Send the report", "build completes", ("build_status",),
                               scope=instruction.scope,
                               evidence_quote="When the build completes, send the report.")]
            return []
        def assess(intentions, observations, sources):
            self.observed.append(copy.deepcopy(observations))
            for intention in intentions:
                evidence = [item.id for item in observations
                            if item.source == "build_status" and item.text == "Build complete."]
                if evidence:
                    yield Decision("ACT", intention.id, evidence_ids=tuple(evidence))
                else:
                    yield Decision("CHECK", intention.id, source="build_status")
        return Engine(compile_message, assess, ["events"], query_budget=1)

    def test_public_channel_discovery_and_menu_isolation(self):
        engine = self.make_engine()
        adapter = PMBenchAdapter(engine)
        messages = [SYSTEM, HEADER, STEP]
        before = copy.deepcopy(messages)
        reminder = adapter.context_for(messages)
        self.assertEqual(messages, before)
        self.assertEqual(discover_sources(messages), ("events", "clock", "inbox", "build_status"))
        self.assertIn('"decision": "CHECK"', reminder)
        self.assertIn('"source": "build_status"', reminder)
        inputs = " ".join(item.text for item in self.compiled)
        evidence = " ".join(item.text for item in self.observed[-1])
        for forbidden in ("task_2", "Water the plants", "A) Read"):
            self.assertNotIn(forbidden, inputs + evidence)
        self.assertEqual(len(engine.intentions), 1)

    def test_observed_query_triggers_act_then_next_step_drops_evidence(self):
        engine = self.make_engine()
        log = io.StringIO()
        adapter = PMBenchAdapter(engine, log)
        messages = [SYSTEM, HEADER, STEP]
        adapter.context_for(messages)
        messages.extend([
            {"role": "assistant", "content": '{"action":"query_state","channel":"build_status"}'},
            {"role": "user", "content": "State [build_status]: Build complete."},
        ])
        reminder = adapter.context_for(messages)
        self.assertIn('"decision": "ACT"', reminder)
        self.assertIn("Build complete.", reminder)
        self.assertEqual(len(self.observed[-1]), 2)
        messages.extend([
            {"role": "assistant", "content": '{"action":"choose","task_ids":["task_2"]}'},
            {"role": "user", "content": STEP["content"].replace("office", "hall")},
        ])
        reminder = adapter.context_for(messages)
        self.assertNotIn('"decision": "ACT"', reminder)
        self.assertTrue(all(item.source != "build_status" for item in self.observed[-1]))
        self.assertEqual(next(iter(engine.intentions.values())).status, "pending")
        self.assertEqual(json.loads(log.getvalue().splitlines()[-1])["attempts"][0]["task_ids"], ["task_2"])

    def test_later_day_scope_deactivates_previous_day_intention(self):
        engine = self.make_engine()
        adapter = PMBenchAdapter(engine)
        messages = [SYSTEM, HEADER, STEP]
        adapter.context_for(messages)
        messages.extend([{"role": "user", "content": "=== Tuesday ===\nA new day begins."}, STEP])
        self.assertEqual(adapter.context_for(messages), "")
        self.assertEqual(adapter.scope, "Tuesday")

    def test_current_clock_survives_menu_stripping(self):
        prose, clocks = strip_action_choices(STEP["content"] + "\nTime: 11:00 | Stopwatch: 240 min")
        self.assertEqual(prose, "You walk into the office.")
        self.assertEqual(clocks, ["11:00 | Stopwatch: 240 min"])

    def test_history_replacement_requires_new_adapter(self):
        adapter = PMBenchAdapter(self.make_engine())
        adapter.context_for([SYSTEM, HEADER, STEP])
        with self.assertRaisesRegex(ValueError, "Conversation changed"):
            adapter.context_for([SYSTEM, STEP])

    def test_policy_callback_receives_separated_fields_and_strict_schema(self):
        calls = []
        def request(system, payload, schema):
            calls.append((system, payload, schema))
            return {"changes": []}
        policy = LLMMemoryPolicy(request)
        instruction = Instruction("note", "When the build completes, send the report.")
        self.assertEqual(policy.compile(instruction, [], ("events", "build_status")), [])
        self.assertEqual(set(calls[0][1]), {"instruction", "intentions", "available_sources"})
        self.assertFalse(calls[0][2]["additionalProperties"])
        self.assertFalse(calls[0][2]["properties"]["changes"]["items"]["additionalProperties"])

    def test_policy_rejects_malformed_model_output(self):
        instruction = Instruction("note", "Do this later.")
        for response in ('{"changes":[]}', {"changes": {}}, {"changes": [{"op": "register"}]}):
            policy = LLMMemoryPolicy(lambda *args: response)
            with self.assertRaises(ValueError):
                policy.compile(instruction, [], ("events",))

    def test_push_only_events_cannot_be_queried_even_if_matcher_requests_it(self):
        def compile_message(instruction, intentions, sources):
            if "When the build completes" in instruction.text:
                return [Change("register", "Send report", "build completes", ("events",),
                               evidence_quote="When the build completes, send the report.")]
            return []
        def assess(intentions, observations, sources):
            return [Decision("CHECK", item.id, source="events") for item in intentions]
        engine = Engine(compile_message, assess, ["events"])
        adapter = PMBenchAdapter(engine)
        self.assertEqual(adapter.context_for([SYSTEM, HEADER, STEP]), "")
        self.assertNotIn("events", engine.queryable_sources)
        self.assertTrue(any(error["phase"] == "decision" for error in engine.errors))

    def test_act_survives_an_unrelated_query_and_adapter_snapshot_roundtrip(self):
        adapter = PMBenchAdapter(self.make_engine())
        messages = [SYSTEM, HEADER, STEP,
                    {"role": "user", "content": "State [build_status]: Build complete."}]
        self.assertIn('"decision": "ACT"', adapter.context_for(messages))
        state = json.loads(json.dumps(adapter.snapshot()))
        restored = PMBenchAdapter(self.make_engine())
        restored.restore(state)
        self.assertEqual(restored.snapshot(), adapter.snapshot())
        messages.extend([
            {"role": "assistant", "content": '{"action":"query_state","channel":"inbox"}'},
            {"role": "user", "content": "State [inbox]: No new messages."},
        ])
        original_context = adapter.context_for(messages)
        restored_context = restored.context_for(messages)
        self.assertIn('"decision": "ACT"', original_context)
        self.assertEqual(restored_context, original_context)
        # A new contradictory reading replaces the cited source evidence and
        # invalidates the retained ACT even though its old ID remains archived.
        messages.append({"role": "user", "content": "State [build_status]: Build incomplete."})
        self.assertNotIn('"decision": "ACT"', restored.context_for(messages))

    def test_explicit_wait_withdraws_cached_act(self):
        adapter = PMBenchAdapter(self.make_engine())
        messages = [SYSTEM, HEADER, STEP,
                    {"role": "user", "content": "State [build_status]: Build complete."}]
        self.assertIn('"decision": "ACT"', adapter.context_for(messages))
        adapter.engine.matcher = lambda intentions, *args: [
            Decision("WAIT", item.id, "New evidence does not support acting") for item in intentions]
        self.assertEqual(adapter.context_for(messages), "")
        self.assertFalse(adapter._act_cache)

    def test_invalid_adapter_snapshot_is_atomic(self):
        adapter = PMBenchAdapter(self.make_engine())
        adapter.context_for([SYSTEM, HEADER, STEP])
        original = adapter.snapshot()
        variants = []
        wrong_cursor = copy.deepcopy(original)
        wrong_cursor["seen"] += 1
        variants.append(wrong_cursor)
        wrong_evidence = copy.deepcopy(original)
        wrong_evidence["current_observations"][0]["text"] = "Fabricated observation"
        variants.append(wrong_evidence)
        wrong_scope = copy.deepcopy(original)
        wrong_scope["scope"] = "Tuesday"
        variants.append(wrong_scope)
        for invalid in variants:
            with self.assertRaises(ValueError):
                adapter.restore(invalid)
            self.assertEqual(adapter.snapshot(), original)


if __name__ == "__main__":
    unittest.main()
