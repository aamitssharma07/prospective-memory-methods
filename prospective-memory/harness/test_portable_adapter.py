"""Contract tests for public-message isolation and provider-independent policies."""

import copy
import io
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prospective_memory import Engine, Change, Decision, Instruction, Observation
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
        def assess(intentions, observations, sources, queryable=()):
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
        def assess(intentions, observations, sources, queryable=()):
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


class ExplicitQueryHandoffTests(unittest.TestCase):
    TITLE = "Optional exact-source query handoff (advisory, not executed):\n"

    def make_engine(self, sources=("build_status",), *, tracking=False, with_act=False):
        def compile_message(instruction, intentions, available):
            if "When the build completes" not in instruction.text:
                return []
            return [Change("register", "Action for " + source, "Condition for " + source,
                           (source,), scope=instruction.scope,
                           evidence_quote="When the build completes, send the report.")
                    for source in sources + (("events",) if with_act else ())]

        def assess(intentions, observations, available, queryable=()):
            for intention in intentions:
                if intention.sources == ("events",):
                    yield Decision("ACT", intention.id, "Observed cue",
                                   evidence_ids=(next(o.id for o in observations if o.current),))
                else:
                    yield Decision("CHECK", intention.id, "Need the exact source",
                                   source=intention.sources[0])
        engine = Engine(compile_message, assess, ["events"], query_budget=10)
        if tracking:
            # Scripted host ledger with the same append/reset contract as PIS.
            # The formatter must neither call record_query nor deduplicate it.
            engine.step_queries = []
            engine.step_id = ""
            engine.record_query = engine.step_queries.append

            def begin_step(step_id):
                if step_id != engine.step_id:
                    engine.step_id = step_id
                    engine.step_queries.clear()
            engine.begin_step = begin_step
        return engine

    def data(self, reminder):
        return json.loads(reminder.split(self.TITLE, 1)[1].splitlines()[0])

    def test_legacy_default_bytes_and_old_snapshot_shape_are_unchanged(self):
        default = PMBenchAdapter(self.make_engine())
        legacy = PMBenchAdapter(self.make_engine(), query_handoff="legacy")
        expected = (
            'Prospective-memory observations and proposals:\n'
            '[{"decision": "CHECK", "source": "build_status", "action": "Action for build_status", '
            '"condition": "Condition for build_status", "reason": "Need the exact source"}]'
            '\nFor CHECK, use the ordinary query_state action with the exact source as channel. '
            'A proposed check does not establish that the task is due. '
            'For ACT, verify the evidence and resolve the action description against the current '
            'menu; use only the current task handle. You retain the final action choice.')
        self.assertEqual(default.context_for([SYSTEM, HEADER, STEP]), expected)
        self.assertEqual(legacy.context_for([SYSTEM, HEADER, STEP]), expected)
        state = default.snapshot()
        self.assertEqual(set(state), {"version", "adapter", "engine", "seen", "cycles", "scope",
                                     "messages", "current_observations", "last_decisions", "act_cache"})
        restored = PMBenchAdapter(self.make_engine())
        restored.restore(json.loads(json.dumps(state)))
        self.assertEqual(restored.snapshot(), state)

    def test_explicit_maps_every_check_to_exact_optional_json_including_clock(self):
        adapter = PMBenchAdapter(self.make_engine(("clock", "inbox", "build_status"), tracking=True),
                                 query_handoff="explicit")
        reminder = adapter.context_for([SYSTEM, HEADER, STEP])
        data = self.data(reminder)
        self.assertEqual(data["optional_query_actions"], [
            {"action": "query_state", "choice": "NONE", "task_ids": [], "channel": source}
            for source in ("clock", "inbox", "build_status")])
        self.assertEqual(data["current_observed_sources"], ["events"])
        self.assertEqual(data["actual_query_attempts_this_step"], [])
        self.assertIn("Another clock read does not answer a request for a different source.", reminder)
        self.assertIn("You may decline or choose another action", reminder)
        self.assertNotIn("task_2", reminder)

    def test_actual_injected_appendix_is_logged_and_existing_act_check_budget_prefix_retained(self):
        engines = [self.make_engine(with_act=True) for _ in range(2)]
        for engine in engines:
            engine.exhausted_query_guidance = lambda: "Original host budget note."
        log = io.StringIO()
        legacy = PMBenchAdapter(engines[0])
        explicit = PMBenchAdapter(engines[1], log, query_handoff="explicit")
        messages = [SYSTEM, HEADER, STEP]
        base = legacy.context_for(messages)
        reminder = explicit.context_for(messages)
        self.assertTrue(reminder.startswith(base + "\n" + self.TITLE))
        self.assertIn('"decision": "ACT"', base)
        self.assertIn('"decision": "CHECK"', base)
        self.assertEqual(reminder.count("Original host budget note."), 1)
        self.assertEqual(json.loads(log.getvalue())["reminder"], reminder)
        self.assertEqual(explicit.last_decisions, legacy.last_decisions)

    def test_wrong_repeated_and_unadvertised_actual_queries_are_preserved_not_satisfied(self):
        engine = self.make_engine(tracking=True)
        adapter = PMBenchAdapter(engine, query_handoff="explicit")
        messages = [SYSTEM, HEADER, STEP]
        adapter.context_for(messages)
        messages.extend([
            {"role": "assistant", "content": '{"action":"check_time"}'},
            {"role": "user", "content": "State [clock]: 11:00"},
            {"role": "assistant", "content": '{"action":"query_state","channel":"clock"}'},
            {"role": "user", "content": "State [clock]: 11:00"},
            {"role": "assistant", "content": '{"action":"query_state","channel":"unadvertised"}'},
            {"role": "user", "content": "Invalid channel."},
        ])
        reminder = adapter.context_for(messages)
        self.assertEqual(self.data(reminder)["actual_query_attempts_this_step"],
                         ["clock", "clock", "unadvertised"])
        self.assertEqual(self.data(reminder)["optional_query_actions"][0]["channel"], "build_status")
        self.assertEqual(engine.step_queries, ["clock", "clock", "unadvertised"])
        self.assertEqual(adapter.context_for(messages), reminder)
        self.assertEqual(engine.step_queries, ["clock", "clock", "unadvertised"])
        self.assertEqual(next(iter(engine.intentions.values())).status, "pending")

    def test_current_observation_sources_are_not_inferred_from_queries_or_history(self):
        engine = self.make_engine(tracking=True)
        adapter = PMBenchAdapter(engine, query_handoff="explicit")
        messages = [SYSTEM, HEADER, STEP,
                    {"role": "assistant", "content": '{"action":"query_state","channel":"inbox"}'},
                    {"role": "user", "content": "State [clock]: 11:00"},
                    {"role": "user", "content": "State [clock]: 11:01"}]
        data = self.data(adapter.context_for(messages))
        self.assertEqual(data["current_observed_sources"], ["events", "clock"])
        self.assertEqual(data["actual_query_attempts_this_step"], ["inbox"])
        adapter.current_observations.append(Observation("stale", "Old reply", "inbox", False))
        self.assertEqual(self.data(adapter._explicit_query_handoff())["current_observed_sources"],
                         ["events", "clock"])
        messages.append({"role": "user", "content": STEP["content"].replace("office", "hall")})
        fresh = self.data(adapter.context_for(messages))
        self.assertEqual(fresh["current_observed_sources"], ["events"])
        self.assertEqual(fresh["actual_query_attempts_this_step"], [])

    def test_unknown_and_push_only_sources_cannot_create_concrete_query_actions(self):
        for source in ("unadvertised", "events"):
            with self.subTest(source=source):
                engine = self.make_engine()
                engine.matcher = lambda intentions, *args: [
                    Decision("CHECK", item.id, source=source) for item in intentions]
                adapter = PMBenchAdapter(engine, query_handoff="explicit")
                self.assertEqual(adapter.context_for([SYSTEM, HEADER, STEP]), "")
                self.assertTrue(engine.errors)
        adapter = PMBenchAdapter(self.make_engine(), query_handoff="explicit")
        adapter.context_for([SYSTEM, HEADER, STEP])
        for source in ("events", "inbox", "unadvertised"):
            adapter.last_decisions = [Decision("CHECK", next(iter(adapter.engine.intentions)), source=source)]
            with self.assertRaisesRegex(ValueError, "validated advertised"):
                adapter._explicit_query_handoff()

    def test_case_sensitive_advertised_channel_is_copied_without_normalization(self):
        system = {"role": "system", "content": "Available state channels: Portal_ALPHA."}
        adapter = PMBenchAdapter(self.make_engine(("Portal_ALPHA",)), query_handoff="explicit")
        self.assertEqual(self.data(adapter.context_for([system, HEADER, STEP]))
                         ["optional_query_actions"][0]["channel"], "Portal_ALPHA")

    def test_missing_tracking_is_unknown_and_bad_tracking_is_rejected(self):
        adapter = PMBenchAdapter(self.make_engine(), query_handoff="explicit")
        text = adapter.context_for([SYSTEM, HEADER, STEP])
        self.assertIsNone(self.data(text)["actual_query_attempts_this_step"])
        self.assertIn("not zero attempts", text)
        for bad in ("clock", ["clock", None], {"clock": 2}):
            adapter.engine.step_queries = bad
            with self.assertRaisesRegex(ValueError, "ledger"):
                adapter._explicit_query_handoff()

    def test_no_execution_interception_menu_change_or_automatic_completion(self):
        engine = self.make_engine(tracking=True)
        engine.acknowledge = lambda *args: self.fail("Formatter must not acknowledge actions")
        adapter = PMBenchAdapter(engine, query_handoff="explicit")
        messages = [SYSTEM, HEADER, STEP]
        untouched = copy.deepcopy(messages)
        adapter.context_for(messages)
        self.assertEqual(messages, untouched)
        self.assertEqual(engine.step_queries, [])  # Suggestion did not execute.
        messages.append({"role": "assistant", "content": '{"action":"choose","task_ids":["task_9"]}'})
        before = copy.deepcopy(messages)
        adapter.context_for(messages)
        self.assertEqual(messages, before)  # An unrelated choice was not rewritten.
        self.assertEqual(engine.step_queries, [])
        self.assertEqual(next(iter(engine.intentions.values())).status, "pending")

    def test_no_check_adds_no_appendix_or_negative_wait_section(self):
        for kind in ("ACT", "WAIT"):
            adapters = [PMBenchAdapter(self.make_engine((), with_act=True), query_handoff=mode)
                        for mode in ("legacy", "explicit")]
            if kind == "WAIT":
                for adapter in adapters:
                    adapter.engine.matcher = lambda intentions, *args: [
                        Decision("WAIT", item.id, "No new evidence") for item in intentions]
            texts = [adapter.context_for([SYSTEM, HEADER, STEP]) for adapter in adapters]
            self.assertEqual(texts[0], texts[1])
            self.assertNotIn(self.TITLE, texts[1])
            self.assertNotIn('"decision": "WAIT"', texts[1])

    def test_explicit_snapshot_roundtrip_and_mode_mismatch_are_atomic(self):
        adapters = {mode: PMBenchAdapter(self.make_engine(), query_handoff=mode)
                    for mode in ("legacy", "explicit")}
        for adapter in adapters.values():
            adapter.context_for([SYSTEM, HEADER, STEP])
        old, explicit = [adapters[mode].snapshot() for mode in ("legacy", "explicit")]
        self.assertNotIn("query_handoff", old)
        self.assertEqual(explicit["query_handoff"], "explicit")
        restored = PMBenchAdapter(self.make_engine(), query_handoff="explicit")
        restored.restore(json.loads(json.dumps(explicit)))
        self.assertEqual(restored.snapshot(), explicit)
        for adapter, invalid in ((adapters["legacy"], explicit), (adapters["explicit"], old)):
            before = adapter.snapshot()
            with self.assertRaisesRegex(ValueError, "query_handoff"):
                adapter.restore(invalid)
            self.assertEqual(adapter.snapshot(), before)
        for mode in (None, False, [], "unknown"):
            invalid = {**explicit, "query_handoff": mode}
            before = restored.snapshot()
            with self.assertRaisesRegex(ValueError, "query_handoff"):
                restored.restore(invalid)
            self.assertEqual(restored.snapshot(), before)

    def test_invalid_constructor_modes_are_rejected(self):
        for mode in (None, False, [], "unknown"):
            with self.assertRaisesRegex(ValueError, "query_handoff"):
                PMBenchAdapter(self.make_engine(), query_handoff=mode)


if __name__ == "__main__":
    unittest.main()
