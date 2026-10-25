"""Benchmark-independent checks; scripted providers do not test LLM ability."""

import copy
import json
import unittest

from prospective_memory import demo
from prospective_memory.core import Change, Decision, Engine, Instruction, Observation


class EventStreamTests(unittest.TestCase):
    def test_delayed_event_with_unrelated_activity(self):
        demo.delayed_event()

    def test_simultaneous_independent_intentions(self):
        demo.simultaneous_intentions()

    def test_cancellation(self):
        demo.cancelled_intention()

    def test_revision_preserves_identity_and_replaces_condition(self):
        demo.revised_intention()

    def test_never_triggered_intention_stays_quiet(self):
        demo.never_triggered()

    def test_stale_and_repeated_evidence_is_rejected(self):
        demo.stale_evidence()

    def test_invented_evidence_is_rejected(self):
        demo.invented_evidence()

    def test_push_and_pull_query_budget(self):
        demo.push_and_pull_budget()

    def test_json_snapshot_restores_lifecycle_and_deduplication(self):
        demo.persistence_restore()

    def test_recurring_intention_acknowledgement(self):
        demo.recurring_acknowledgement()


class BoundaryTests(unittest.TestCase):
    def test_new_unrelated_context_does_not_retrigger_consumed_evidence(self):
        def matcher(intentions, observations, sources, queryable=()):
            return [Decision("ACT", item.id,
                             evidence_ids=tuple(ob.id for ob in observations))
                    for item in intentions]

        engine = demo._engine({
            "start": demo._registration("Summarize experiment", "Complete",
                                        sources=("status",))
        }, matcher)
        engine.ingest(Instruction("start", "Summarize the experiment when complete."))
        trigger = Observation("complete", "Complete", source="status")
        self.assertEqual(len(demo._acts(engine.tick([trigger]))), 1)
        self.assertEqual(demo._acts(engine.tick([
            trigger, Observation("new-context", "An unrelated meeting began")
        ])), [])

    def test_fresh_trigger_with_shared_context_rearms_recurring_intention(self):
        def matcher(intentions, observations, sources, queryable=()):
            return [Decision("ACT", item.id,
                             evidence_ids=tuple(ob.id for ob in observations))
                    for item in intentions]

        engine = demo._engine({
            "start": demo._registration("Summarize experiment", "Complete",
                                        sources=("status",), repeat=True)
        }, matcher)
        intention_id = engine.ingest(Instruction(
            "start", "Summarize each experiment when complete."
        ))[0]
        context = Observation("ongoing-context", "The main agent is drafting a report")
        first_trigger = Observation("first-complete", "Complete", source="status")
        self.assertEqual(len(demo._acts(engine.tick([context, first_trigger]))), 1)
        engine.acknowledge(intention_id, outcome="completed")
        self.assertEqual(demo._acts(engine.tick([context, first_trigger])), [])
        second_trigger = Observation("second-complete", "Complete", source="status")
        self.assertEqual(len(demo._acts(engine.tick([context, second_trigger]))), 1)

    def test_subset_of_consumed_trigger_evidence_does_not_retrigger(self):
        def matcher(intentions, observations, sources, queryable=()):
            return [Decision("ACT", item.id,
                             evidence_ids=tuple(ob.id for ob in observations))
                    for item in intentions]

        engine = demo._engine({
            "start": demo._registration("Summarize experiment", "Complete",
                                        sources=("status",))
        }, matcher)
        engine.ingest(Instruction("start", "Summarize the completed experiment."))
        first = Observation("result", "Complete", source="status")
        second = Observation("confirmation", "Completion confirmed", source="status")
        self.assertEqual(len(demo._acts(engine.tick([first, second]))), 1)
        self.assertEqual(demo._acts(engine.tick([first])), [])

    def test_unobservable_intention_is_retained_but_cannot_act_or_check(self):
        def compiler(instruction, intentions, sources):
            return [Change("register", action="Notify the team", condition="Package arrives",
                           sources=(), evidence_quote=instruction.text)]

        def matcher(intentions, observations, sources, queryable=()):
            return [decision for item in intentions for decision in (
                Decision("ACT", item.id, evidence_ids=("unrelated",)),
                Decision("CHECK", item.id, source="events"),
            )]

        engine = Engine(compiler, matcher, sources=("events",))
        registered = engine.ingest(Instruction("start", "Notify the team when the package arrives."))
        self.assertEqual(len(registered), 1)
        decisions = engine.tick([Observation("unrelated", "A meeting began")])
        self.assertEqual([(item.kind, item.intention_id) for item in decisions],
                         [("WAIT", registered[0])])
        self.assertTrue(engine.errors)
        restored = Engine(compiler, matcher, sources=("events",))
        restored.restore(engine.snapshot())
        self.assertEqual(restored.intentions[registered[0]].sources, ())
        self.assertEqual(restored.intentions[registered[0]].status, "pending")

    def test_unsupported_instruction_quote_preserves_intention(self):
        def compiler(instruction, intentions, sources):
            if instruction.id == "register":
                return [Change("register", action="Send report", condition="Approved",
                               sources=("events",), evidence_quote=instruction.text)]
            return [Change("cancel", target_id=intentions[0].id,
                           evidence_quote="This quote was never provided")]

        engine = Engine(compiler, demo.literal_matcher, sources=("events",))
        registered = engine.ingest(Instruction("register", "Send the report after approval."))
        engine.ingest(Instruction("bad-cancel", "The meeting starts at noon."))
        decisions = engine.tick([Observation("approval", "Approved")])
        self.assertEqual([item.intention_id for item in decisions if item.kind == "ACT"],
                         registered)
        self.assertTrue(engine.errors)

    def test_unknown_source_cannot_register_intention(self):
        def compiler(instruction, intentions, sources):
            return [Change("register", action="Send report", condition="Approved",
                           sources=("invented-tool",), evidence_quote=instruction.text)]

        engine = Engine(compiler, demo.literal_matcher, sources=("events",))
        self.assertEqual(engine.ingest(Instruction("start", "Send the approved report.")), [])
        self.assertTrue(engine.errors)

    def test_unknown_intention_and_empty_evidence_cannot_act(self):
        def compiler(instruction, intentions, sources):
            return [Change("register", action="Send report", condition="Approved",
                           sources=("events",), evidence_quote=instruction.text)]

        def matcher(intentions, observations, sources, queryable=()):
            return [Decision("ACT", "unknown-intention", evidence_ids=("approval",)),
                    Decision("ACT", intentions[0].id, evidence_ids=())]

        engine = Engine(compiler, matcher, sources=("events",))
        engine.ingest(Instruction("start", "Send the report after approval."))
        decisions = engine.tick([Observation("approval", "Approved")])
        self.assertFalse(any(item.kind == "ACT" for item in decisions))
        self.assertTrue(engine.errors)

    def test_failed_attempt_rearms_but_completed_one_shot_does_not(self):
        engine = demo._engine({
            "start": demo._registration("Send report", "Approved")
        })
        intention_id = engine.ingest(Instruction("start", "Send the approved report."))[0]
        self.assertEqual(len(demo._acts(engine.tick([Observation("first", "Approved")]))), 1)
        engine.acknowledge(intention_id, outcome="attempted")
        engine.acknowledge(intention_id, outcome="failed")
        self.assertEqual(len(demo._acts(engine.tick([Observation("retry", "Approved")]))), 1)
        engine.acknowledge(intention_id, outcome="completed")
        self.assertEqual(demo._acts(engine.tick([Observation("later", "Approved")])), [])

    def test_scope_filters_visible_intentions(self):
        def compiler(instruction, intentions, sources):
            return [Change("register", action="Send report", condition="Approved",
                           sources=("events",), scope=instruction.scope,
                           evidence_quote=instruction.text)]

        engine = Engine(compiler, demo.literal_matcher, sources=("events",))
        engine.ingest(Instruction("start", "Send the approved report.", scope="project-a"))
        self.assertEqual(demo._acts(engine.tick(
            [Observation("unrelated-project", "Approved")], scope="project-b"
        )), [])
        self.assertEqual(len(demo._acts(engine.tick(
            [Observation("right-project", "Approved")], scope="project-a"
        ))), 1)


class RobustnessTests(unittest.TestCase):
    def test_queryable_sources_persist_and_keep_push_events_nonqueryable(self):
        plans = {
            "push": demo._registration("Acknowledge message", "Message arrived"),
            "pull": demo._registration("Summarize experiment", "Complete",
                                       sources=("status",)),
        }

        def matcher(intentions, observations, sources, queryable=()):
            return [Decision("CHECK", item.id, source=item.sources[0]) for item in intentions]

        compiler = demo.ScriptedCompiler(plans)
        original = Engine(compiler, matcher, sources=("events", "status"),
                          queryable_sources=("status",))
        push_id = original.ingest(Instruction("push", "Acknowledge the arriving message."))[0]
        pull_id = original.ingest(Instruction("pull", "Summarize the completed experiment."))[0]
        restored = Engine(compiler, matcher, sources=("events", "status"))
        restored.restore(json.loads(json.dumps(original.snapshot())))
        self.assertEqual(restored.queryable_sources, ("status",))
        self.assertEqual({item.intention_id: item.kind for item in restored.tick([])},
                         {push_id: "WAIT", pull_id: "CHECK"})

        # A host with only pushed events must not gain checking permissions on
        # restart merely because an empty list could be mistaken for a default.
        push_only = Engine(compiler, matcher, sources=("events", "status"),
                           queryable_sources=())
        push_only.ingest(Instruction("push", "Acknowledge the arriving message."))
        restored.restore(json.loads(json.dumps(push_only.snapshot())))
        self.assertEqual(restored.queryable_sources, ())
        self.assertTrue(all(item.kind == "WAIT" for item in restored.tick([])))

    def test_invalid_query_budget_is_rejected_and_zero_disables_checks(self):
        for budget in (-1, 1.5, True, "1", None):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                Engine(lambda *_: [], lambda *_: [], sources=("events",), query_budget=budget)

        def matcher(intentions, observations, sources, queryable=()):
            return [Decision("CHECK", item.id, source="status") for item in intentions]

        engine = demo._engine({
            "start": demo._registration("Summarize experiment", "Complete",
                                        sources=("status",))
        }, matcher, query_budget=0)
        engine.ingest(Instruction("start", "Summarize the completed experiment."))
        self.assertTrue(all(item.kind == "WAIT" for item in engine.tick([])))

    def test_compiler_exception_preserves_existing_bank_without_partial_update(self):
        def compiler(instruction, intentions, sources):
            yield Change("register", action=instruction.text, condition="Approved",
                         sources=("events",), evidence_quote=instruction.text)
            if instruction.id == "broken":
                raise RuntimeError("Scripted compiler failure")

        engine = Engine(compiler, demo.literal_matcher, sources=("events",))
        engine.ingest(Instruction("valid", "Send report after approval."))
        before = dict(engine.intentions)
        self.assertEqual(engine.ingest(Instruction("broken", "Archive the approved report.")), [])
        self.assertEqual(engine.intentions, before)
        self.assertEqual(engine.errors[-1]["phase"], "compile")
        self.assertEqual(len(demo._acts(engine.tick([Observation("approval", "Approved")]))), 1)

    def test_matcher_exception_returns_wait_without_partial_notification(self):
        fail = True

        def matcher(intentions, observations, sources, queryable=()):
            yield Decision("ACT", intentions[0].id, evidence_ids=("approval",))
            if fail:
                raise RuntimeError("Scripted matcher failure")

        engine = demo._engine({
            "start": demo._registration("Send report", "Approved")
        }, matcher)
        intention_id = engine.ingest(Instruction("start", "Send the approved report."))[0]
        observation = Observation("approval", "Approved")
        decisions = engine.tick([observation])
        self.assertEqual([(item.kind, item.intention_id) for item in decisions],
                         [("WAIT", intention_id)])
        self.assertEqual(engine.errors[-1]["phase"], "assess")
        fail = False
        self.assertEqual(len(demo._acts(engine.tick([observation]))), 1)

    def test_invalid_snapshot_provenance_does_not_mutate_live_state(self):
        engine = demo._engine({
            "start": demo._registration("Send report", "Approved")
        })
        engine.ingest(Instruction("start", "Send the approved report."))
        engine.tick([Observation("approval", "Approved")])
        before = engine.snapshot()
        corruptions = {
            "missing_instruction": lambda state: state.update(instructions=[]),
            "missing_instruction_field": lambda state: state.pop("instructions"),
            "missing_intention_provenance": lambda state:
                state["intentions"][0].update(instruction_ids=[]),
            "unknown_instruction_reference": lambda state:
                state["intentions"][0].update(instruction_ids=["invented"]),
            "unsupported_instruction_quote": lambda state:
                state["intentions"][0].update(evidence_quote="Not in the instruction"),
        }
        for name, corrupt in corruptions.items():
            with self.subTest(corruption=name):
                invalid = copy.deepcopy(before)
                corrupt(invalid)
                with self.assertRaises((ValueError, KeyError)):
                    engine.restore(invalid)
                self.assertEqual(engine.snapshot(), before)

    def test_instruction_id_reuse_is_idempotent_or_rejected_without_mutation(self):
        engine = demo._engine({
            "start": demo._registration("Send report", "Approved")
        })
        instruction = Instruction("start", "Send the approved report.")
        engine.ingest(instruction)
        before = engine.snapshot()
        self.assertEqual(engine.ingest(instruction), [])
        self.assertEqual(engine.snapshot(), before)
        with self.assertRaises(ValueError):
            engine.ingest(Instruction("start", "Cancel the report instead."))
        self.assertEqual(engine.snapshot(), before)

    def test_observation_id_cannot_be_rewritten_to_manufacture_trigger_evidence(self):
        engine = demo._engine({
            "start": demo._registration("Send report", "Approved")
        })
        engine.ingest(Instruction("start", "Send the approved report."))
        original = Observation("status-update", "Approval pending")
        self.assertEqual(demo._acts(engine.tick([original])), [])
        self.assertEqual(demo._acts(engine.tick([
            Observation("status-update", "Approved")
        ])), [])
        self.assertEqual(engine.errors[-1]["phase"], "observation")
        self.assertEqual(engine.snapshot()["observations"], [{
            "id": "status-update", "text": "Approval pending",
            "source": "events", "current": True,
        }])
        self.assertEqual(len(demo._acts(engine.tick([
            Observation("new-status-update", "Approved")
        ]))), 1)


if __name__ == "__main__":
    unittest.main()


class MatcherCapabilityTests(unittest.TestCase):
    """The engine rejects illegal CHECKs, so the matcher must see the same rules."""

    def test_matcher_receives_advertised_and_queryable_sources(self):
        seen = []

        def matcher(intentions, observations, sources, queryable=()):
            seen.append((tuple(sources), tuple(queryable)))
            return []

        def compiler(instruction, intentions, sources):
            return [Change("register", "Notify", "Ready", ("events", "status"),
                           evidence_quote=instruction.text)]

        engine = Engine(compiler, matcher, sources=("events", "status"),
                        queryable_sources=("status",))
        engine.ingest(Instruction("req", "Notify me when it is ready."))
        engine.tick([Observation("o1", "Nothing yet")])
        self.assertEqual(seen, [(("events", "status"), ("status",))])

    def test_push_only_engine_reports_an_empty_queryable_list(self):
        seen = []

        def matcher(intentions, observations, sources, queryable=()):
            seen.append(tuple(queryable))
            return []

        def compiler(instruction, intentions, sources):
            return [Change("register", "Notify", "Ready", ("events",),
                           evidence_quote=instruction.text)]

        engine = Engine(compiler, matcher, sources=("events",), queryable_sources=())
        engine.ingest(Instruction("req", "Notify me when it is ready."))
        engine.tick([Observation("o1", "Nothing yet")])
        self.assertEqual(seen, [()])
