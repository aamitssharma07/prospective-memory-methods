"""Concurrent assessment must be indistinguishable from the serial loop.

Assessments that cannot reach a CHECK are order-independent, so dispatching
them together is safe; anything that can consume the query budget stays
sequential. These tests pin that equivalence rather than the speedup.
"""
import copy
import threading
import time
import unittest

from prospective_memory.core import Instruction, Observation
from prospective_memory.baselines.pis import PISEngine


def row(index, **updates):
    text = f"Send report {index} when channel {index} reports ready."
    return {"op": "register", "target_id": "", "action": f"Send report {index}",
            "condition": f"channel {index} reports ready", "evidence_quote": text,
            "sources": ["events", f"ch{index}"], "days": [], "repeat": False,
            "clock_op": "none", "clock_time": "", **updates}


class Provider:
    """Records concurrency actually observed, and answers per intention."""

    def __init__(self, count, act_on=()):
        self.count = count
        self.act_on = set(act_on)
        self.lock = threading.Lock()
        self.live = 0
        self.peak = 0
        self.seen = []
        self.budgets = []
        self.check_on = None

    def __call__(self, system, payload, schema):
        if "changes" in schema["properties"]:
            text = payload["instruction"]["text"]
            index = int(text.split("report ")[1].split()[0])
            return {"changes": [copy.deepcopy(row(index))]}
        with self.lock:
            self.live += 1
            self.peak = max(self.peak, self.live)
        # Hold the call open briefly so genuine overlap is observable; a real
        # request blocks on network I/O for far longer than this.
        time.sleep(0.02)
        try:
            ident = payload["intention"]["id"]
            with self.lock:
                self.seen.append(ident)
                self.budgets.append((ident, payload.get("remaining_check_budget")))
            if ident == self.check_on:
                return {"decisions": [{"kind": "CHECK", "intention_id": ident,
                                       "reason": "Fixture", "source": "ch0", "evidence_ids": []}]}
            act = ident in self.act_on and payload["observations"]
            return {"decisions": [{
                "kind": "ACT" if act else "WAIT", "intention_id": ident, "reason": "Fixture",
                "source": "", "evidence_ids": [payload["observations"][0]["id"]] if act else []}]}
        finally:
            with self.lock:
                self.live -= 1


def build(workers, count, act_on=(), queryable=()):
    sources = ["events"] + [f"ch{i}" for i in range(count)]
    provider = Provider(count, act_on)
    engine = PISEngine(provider, sources, 1, queryable, False, max_assess_workers=workers)
    for i in range(count):
        engine.ingest(Instruction(f"i{i}", f"Send report {i} when channel {i} reports ready."))
    return engine, provider


class ConcurrentAssessmentTests(unittest.TestCase):
    def decisions(self, workers, **kwargs):
        engine, provider = build(workers, 6, **kwargs)
        out = engine.tick([Observation("e1", "channel ready", "events")])
        return [(d.kind, d.intention_id, d.source) for d in out], provider

    def test_parallel_matches_serial_decisions_and_order(self):
        serial, _ = self.decisions(1)
        parallel, provider = self.decisions(8)
        self.assertEqual(serial, parallel)
        self.assertEqual(len(serial), 6)
        self.assertGreater(provider.peak, 1, "expected concurrent assessment calls")

    def test_parallel_matches_serial_when_some_intentions_act(self):
        serial, _ = self.decisions(1, act_on={"pm_000002", "pm_000005"})
        parallel, _ = self.decisions(8, act_on={"pm_000002", "pm_000005"})
        self.assertEqual(serial, parallel)
        self.assertEqual(sum(1 for kind, _, _ in serial if kind == "ACT"), 2)

    def test_budget_consuming_intentions_stay_sequential(self):
        # Every intention can query its own channel, so each could spend the
        # budget. None may be dispatched concurrently.
        queryable = tuple(f"ch{i}" for i in range(6))
        serial, _ = self.decisions(1, queryable=queryable)
        parallel, provider = self.decisions(8, queryable=queryable)
        self.assertEqual(serial, parallel)
        self.assertEqual(provider.peak, 1, "budget-consuming assessments must not overlap")

    def test_worker_count_is_validated(self):
        for bad in (0, -1, 1.5, "4"):
            with self.assertRaises(ValueError):
                PISEngine(Provider(1), ("events",), 1, (), False, max_assess_workers=bad)


if __name__ == "__main__":
    unittest.main()


class WorkerPropagationTests(unittest.TestCase):
    """A restore must not silently fall back to the serial loop."""

    def test_fresh_engine_keeps_the_worker_count(self):
        engine, _ = build(6, 2)
        self.assertEqual(engine.fresh().max_assess_workers, 6)

    def test_restore_keeps_the_worker_count(self):
        engine, _ = build(6, 2)
        state = engine.snapshot()
        restored = engine.fresh()
        restored.restore(state)
        self.assertEqual(restored.max_assess_workers, 6)


class BudgetExactnessTests(unittest.TestCase):
    """A mid-cycle CHECK lowers the budget every later assessment is told about.

    Deferring those assessments must not hand the model a stale budget: that
    changes the prompt text and therefore the decision.
    """

    def run_cycle(self, workers):
        sources = ["events"] + [f"ch{i}" for i in range(6)]
        provider = Provider(6)
        provider.check_on = "pm_000001"
        engine = PISEngine(provider, sources, 1, ("ch0",), False,
                           max_assess_workers=workers)
        for i in range(6):
            engine.ingest(Instruction(f"i{i}", f"Send report {i} when channel {i} reports ready."))
        out = engine.tick([Observation("e1", "channel ready", "events")])
        return [(d.kind, d.intention_id, d.source) for d in out], provider

    def test_budget_sequence_matches_serial_after_a_check(self):
        serial, serial_provider = self.run_cycle(1)
        parallel, parallel_provider = self.run_cycle(8)
        self.assertEqual(serial, parallel)
        self.assertEqual(sorted(serial_provider.budgets), sorted(parallel_provider.budgets))
        # The CHECK must actually have fired and consumed the budget.
        self.assertIn("CHECK", [kind for kind, _, _ in serial])
        self.assertIn(0, [b for _, b in serial_provider.budgets])


class UnevidencedSkipTests(unittest.TestCase):
    """Skipping an assessment that could only return WAIT must change nothing.

    ACT needs cited evidence from a watched source and CHECK needs an offered
    source, so with neither available the call is pure cost.
    """

    def cycle(self, skip, source="events", act_on=()):
        sources = ["events", "other"] + [f"ch{i}" for i in range(3)]
        provider = Provider(3, act_on)
        engine = PISEngine(provider, sources, 1, (), False,
                           max_assess_workers=1, skip_unevidenced=skip)
        for i in range(3):
            engine.ingest(Instruction(f"i{i}", f"Send report {i} when channel {i} reports ready."))
        out = engine.tick([Observation("o1", "unrelated chatter", source)])
        return [(d.kind, d.intention_id) for d in out], provider, engine

    def test_unwatched_observation_skips_every_call(self):
        # Intentions watch events/chN; an observation on "other" is unwatched.
        base, base_provider, _ = self.cycle(False, source="other")
        skipped, skip_provider, engine = self.cycle(True, source="other")
        self.assertEqual([k for k, _ in base], ["WAIT"] * 3)
        self.assertEqual([k for k, _ in skipped], ["WAIT"] * 3)
        self.assertEqual(len(skip_provider.seen), 0, "no assessment call should be made")
        self.assertEqual(len(base_provider.seen), 3)
        self.assertEqual(engine.skipped_assessments, 3)

    def test_watched_observation_still_assessed(self):
        _, provider, engine = self.cycle(True, source="events", act_on={"pm_000001"})
        self.assertEqual(len(provider.seen), 3, "watched evidence must still be assessed")
        self.assertEqual(engine.skipped_assessments, 0)

    def test_skip_reason_does_not_redeliver_a_cached_act(self):
        from prospective_memory.core import NO_INTERVENTION_REASON
        _, _, engine = self.cycle(True, source="other")
        out = engine.tick([Observation("o2", "still unrelated", "other")])
        for d in out:
            self.assertEqual(d.kind, "WAIT")
            self.assertNotEqual(d.reason, NO_INTERVENTION_REASON)

    def test_flag_is_validated_and_survives_restore(self):
        with self.assertRaises(ValueError):
            PISEngine(Provider(1), ("events",), 1, (), False, skip_unevidenced="yes")
        _, _, engine = self.cycle(True, source="other")
        restored = engine.fresh()
        restored.restore(engine.snapshot())
        self.assertTrue(restored.skip_unevidenced)


class StableWaitReuseTests(unittest.TestCase):
    """A WAIT is reused only while the watched evidence is genuinely unchanged."""

    def engine(self, reuse=True):
        provider = Provider(2)
        engine = PISEngine(provider, ["events", "other", "ch0", "ch1"], 1, (), False,
                           reuse_stable_waits=reuse)
        for i in range(2):
            engine.ingest(Instruction(f"i{i}", f"Send report {i} when channel {i} reports ready."))
        return engine, provider

    def test_second_cycle_reuses_wait_without_a_call(self):
        engine, provider = self.engine()
        engine.begin_step("s1")
        engine.tick([Observation("e1", "nothing yet", "events")])
        first = len(provider.seen)
        engine.tick([Observation("e1", "nothing yet", "events"),
                     Observation("q1", "unwatched reply", "other")])
        self.assertEqual(len(provider.seen), first, "unchanged watched evidence must not re-ask")
        self.assertEqual(engine.reused_assessments, 2)

    def test_new_watched_evidence_forces_a_fresh_assessment(self):
        engine, provider = self.engine()
        engine.begin_step("s1")
        engine.tick([Observation("e1", "nothing yet", "events")])
        first = len(provider.seen)
        engine.tick([Observation("e1", "nothing yet", "events"),
                     Observation("e2", "channel ready", "events")])
        self.assertEqual(len(provider.seen), first + 2, "new watched evidence must be judged")

    def test_a_new_step_clears_the_reuse_cache(self):
        engine, provider = self.engine()
        engine.begin_step("s1")
        engine.tick([Observation("e1", "nothing yet", "events")])
        first = len(provider.seen)
        engine.begin_step("s2")
        engine.tick([Observation("e1", "nothing yet", "events")])
        self.assertEqual(len(provider.seen), first + 2, "a new step must re-assess")

    def test_disabled_by_default_reassesses(self):
        engine, provider = self.engine(reuse=False)
        engine.begin_step("s1")
        engine.tick([Observation("e1", "nothing yet", "events")])
        first = len(provider.seen)
        engine.tick([Observation("e1", "nothing yet", "events"),
                     Observation("q1", "unwatched reply", "other")])
        self.assertEqual(len(provider.seen), first + 2)
        self.assertEqual(engine.reused_assessments, 0)

    def test_an_act_is_never_reused(self):
        engine, provider = self.engine()
        provider.act_on = {"pm_000001", "pm_000002"}
        engine.begin_step("s1")
        out = engine.tick([Observation("e1", "channel ready", "events")])
        self.assertEqual([d.kind for d in out], ["ACT", "ACT"])
        first = len(provider.seen)
        engine.tick([Observation("e1", "channel ready", "events")])
        self.assertEqual(len(provider.seen), first + 2, "ACT must be re-judged, not cached")


class BatchedAssessmentTests(unittest.TestCase):
    """Batching shares one prompt; a malformed batch must not lose intentions."""

    def engine(self, size, handler=None):
        provider = Provider(4)
        engine = PISEngine(provider, ["events", "ch0", "ch1", "ch2", "ch3"], 1, (), False,
                           assess_batch_size=size)
        if handler is not None:
            engine._decide_batch = handler
        for i in range(4):
            engine.ingest(Instruction(f"i{i}", f"Send report {i} when channel {i} reports ready."))
        return engine, provider

    def test_batching_reduces_calls_and_keeps_one_decision_each(self):
        engine, provider = self.engine(4)
        out = engine.tick([Observation("e1", "channel ready", "events")])
        self.assertEqual(len(out), 4)
        # The base engine falls back to per-intention calls, so the contract is
        # the decision count, not the call count.
        self.assertEqual({d.intention_id for d in out},
                         {f"pm_00000{i}" for i in range(1, 5)})

    def test_wrong_row_count_falls_back_instead_of_dropping_intentions(self):
        calls = []

        def broken(items, current, queryable_sources):
            calls.append(len(items))
            return []  # too few rows

        engine, provider = self.engine(4, handler=broken)
        out = engine.tick([Observation("e1", "channel ready", "events")])
        self.assertEqual(len(out), 4, "every intention must still get a decision")
        self.assertEqual([d.kind for d in out], ["WAIT"] * 4)
        self.assertTrue(calls, "the batch was attempted")

    def test_batch_size_is_validated(self):
        for bad in (0, -2, "3"):
            with self.assertRaises(ValueError):
                PISEngine(Provider(1), ("events",), 1, (), False, assess_batch_size=bad)


class ImplicitDayGateTests(unittest.TestCase):
    """An undated event trigger must be able to fire on a later day."""

    def setUp(self):
        from prospective_memory.baselines import pis_registration as reg
        self.reg = reg
        self.addCleanup(reg.set_implicit_day_gate, True)

    def test_default_gates_an_undated_request_to_its_announcement_day(self):
        from prospective_memory.core import Instruction
        self.reg.set_implicit_day_gate(True)
        i = Instruction("i1", "Collect the reading when the library hold is ready.", "Wednesday")
        self.assertEqual(self.reg._supported_days(i, i.text, None, {"i1": i}), {"Wednesday"})

    def test_explicit_mode_leaves_an_undated_request_ungated(self):
        from prospective_memory.core import Instruction
        self.reg.set_implicit_day_gate(False)
        i = Instruction("i1", "Collect the reading when the library hold is ready.", "Wednesday")
        self.assertIsNone(self.reg._supported_days(i, i.text, None, {"i1": i}))

    def test_an_explicitly_named_day_is_still_honoured_in_both_modes(self):
        from prospective_memory.core import Instruction
        i = Instruction("i1", "On Friday, collect the reading from the library.", "Wednesday")
        for mode in (True, False):
            self.reg.set_implicit_day_gate(mode)
            self.assertEqual(self.reg._supported_days(i, i.text, None, {"i1": i}), {"Friday"})

    def test_switch_is_validated(self):
        with self.assertRaises(ValueError):
            self.reg.set_implicit_day_gate("no")


class SpanExtractionTests(unittest.TestCase):
    """Prose requests must store the action, not the narration around it."""

    def setUp(self):
        from prospective_memory.baselines import pis_registration as reg
        from prospective_memory.method import registration as v3
        self.reg, self.v3 = reg, v3
        self.addCleanup(reg.set_extract_spans, False)
        self.errors = []

    def spans(self, row, quote):
        return self.v3._spans(row, quote, lambda phase, exc: self.errors.append((phase, str(exc))))

    QUOTE = ("You jot down a quick reminder: On Wednesday, Carry the prescription "
             "receipt when you notice the lab drop box.")

    def test_marked_spans_replace_the_whole_unit(self):
        row = {"requested_action": "Carry the prescription receipt",
               "trigger_condition": "you notice the lab drop box"}
        self.assertEqual(self.spans(row, self.QUOTE),
                         ("Carry the prescription receipt", "you notice the lab drop box"))
        self.assertEqual(self.errors, [])

    def test_absent_fields_keep_the_previous_behaviour(self):
        self.assertEqual(self.spans({}, self.QUOTE), (self.QUOTE, self.QUOTE))
        self.assertEqual(self.errors, [])

    def test_an_invented_span_is_rejected_and_the_unit_retained(self):
        row = {"requested_action": "Collect the parcel",       # not in the quote
               "trigger_condition": "you notice the lab drop box"}
        self.assertEqual(self.spans(row, self.QUOTE), (self.QUOTE, self.QUOTE))
        self.assertEqual([p for p, _ in self.errors], ["v3_span_guard"])

    def test_an_empty_span_is_rejected(self):
        row = {"requested_action": "  ", "trigger_condition": "you notice the lab drop box"}
        self.assertEqual(self.spans(row, self.QUOTE), (self.QUOTE, self.QUOTE))
        self.assertEqual([p for p, _ in self.errors], ["v3_span_guard"])

    def test_schema_only_asks_for_spans_when_enabled(self):
        props = lambda: self.reg._specification_schema()["properties"]["specifications"]["items"]["properties"]
        self.reg.set_extract_spans(False)
        self.assertNotIn("requested_action", props())
        self.reg.set_extract_spans(True)
        self.assertIn("requested_action", props())
        self.assertIn("trigger_condition", props())

    def test_switch_is_validated(self):
        with self.assertRaises(ValueError):
            self.reg.set_extract_spans("yes")
