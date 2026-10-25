"""Offline CHECK source arbitration; no model, benchmark, or engine execution."""

import copy
from dataclasses import replace
import itertools
import json
import unittest

from prospective_memory.core import Decision
from prospective_memory.method.fair_checks import FairCheckArbiter


SOURCES = ("sensor", "inbox", "clock")


def check(key, source, reason="Need current evidence", evidence_ids=()):
    return Decision("CHECK", key, reason, evidence_ids, source)


def candidates():
    # The stale, first-in-bank source must not consume every future offer.
    return [check("oldest", "clock"), check("next", "inbox"), check("last", "sensor")]


class FairCheckTests(unittest.TestCase):
    def test_ignored_stale_first_record_rotates_three_sources(self):
        arbiter = FairCheckArbiter(SOURCES)
        selected = [arbiter.arbitrate(candidates(), budget=1).selected_sources for _ in range(6)]
        self.assertEqual(selected, [("clock",), ("inbox",), ("sensor",)] * 2)
        self.assertEqual(arbiter.snapshot()["queried"], [])
        self.assertEqual(len(arbiter.snapshot()["offered"]), 6)

    def test_offer_and_actual_query_are_separate_including_wrong_source(self):
        arbiter = FairCheckArbiter(SOURCES)
        arbiter.arbitrate(candidates(), budget=1)  # clock offered, actor ignores it
        arbiter.record_query("sensor")           # actor queries a different source
        state = arbiter.snapshot()
        self.assertEqual(state["offered"], [{"sequence": 1, "source": "clock"}])
        self.assertEqual(state["queried"], [{"sequence": 2, "source": "sensor"}])
        self.assertEqual(arbiter.arbitrate(candidates(), budget=1).selected_sources, ("inbox",))
        self.assertEqual(arbiter.arbitrate(candidates(), budget=1).selected_sources, ("clock",))

    def test_actual_queries_without_offers_and_repeats_are_recorded(self):
        arbiter = FairCheckArbiter(SOURCES)
        arbiter.record_query("clock")
        arbiter.record_query("clock")
        self.assertEqual(len(arbiter.snapshot()["queried"]), 2)
        self.assertEqual(arbiter.snapshot()["offered"], [])
        self.assertEqual(arbiter.arbitrate(candidates(), budget=1).selected_sources, ("inbox",))

    def test_deterministic_under_candidate_and_registry_permutations(self):
        for registry in itertools.permutations(SOURCES):
            for rows in itertools.permutations(candidates()):
                arbiter = FairCheckArbiter(registry)
                self.assertEqual(arbiter.arbitrate(rows, budget=2).selected_sources, ("clock", "inbox"))
                self.assertEqual(arbiter.arbitrate(rows, budget=2).selected_sources, ("sensor", "clock"))

    def test_group_cardinality_and_task_identity_do_not_buy_priority(self):
        left, right = FairCheckArbiter(SOURCES), FairCheckArbiter(SOURCES)
        many = [check(f"aaa_{n}", "sensor") for n in range(40)]
        renamed = [check("zzz", "clock"), check("aaa", "inbox"), *many]
        for _ in range(9):
            self.assertEqual(left.arbitrate(candidates(), budget=1).selected_sources,
                             right.arbitrate(renamed, budget=1).selected_sources)
        self.assertEqual(left.snapshot(), right.snapshot())

    def test_preserves_all_proposals_reason_and_evidence_without_false_decisions(self):
        first = check("two", "inbox", "  Need Alex's message\nwithout rewriting.  ", ("obs_2", "obs_1"))
        second = check("one", "inbox", "A different intended action")
        other = check("three", "sensor")
        arbiter = FairCheckArbiter(SOURCES)
        result = arbiter.arbitrate([first, other, second], budget=1)
        self.assertEqual(result.selected_sources, ("inbox",))
        self.assertEqual(result.selected[0].decisions, (second, first))
        self.assertIs(result.selected[0].decisions[1], first)
        self.assertEqual(result.deferred[0].decisions, (other,))
        self.assertEqual(result.deferred_sources, ("sensor",))
        self.assertEqual(other.kind, "CHECK")

    def test_explicit_hard_gate_priority_overrides_recency_not_budget(self):
        arbiter = FairCheckArbiter(SOURCES)
        arbiter.record_query("sensor")
        self.assertEqual(arbiter.arbitrate(candidates(), budget=1,
                                         priority_sources={"sensor"}).selected_sources, ("sensor",))
        self.assertEqual(arbiter.arbitrate(candidates(), budget=1,
                                         priority_sources={"sensor"}).selected_sources, ("sensor",))
        # Once the host removes the priority, sources not recently offered win.
        self.assertEqual(arbiter.arbitrate(candidates(), budget=1).selected_sources, ("clock",))

    def test_priority_sources_share_same_fair_order_and_absent_priority_is_no_work(self):
        arbiter = FairCheckArbiter(SOURCES)
        priorities = ("sensor", "inbox")
        self.assertEqual(arbiter.arbitrate(candidates(), budget=1,
                                         priority_sources=priorities).selected_sources, ("inbox",))
        self.assertEqual(arbiter.arbitrate(candidates(), budget=1,
                                         priority_sources=priorities).selected_sources, ("sensor",))
        result = arbiter.arbitrate([check("x", "clock")], budget=2, priority_sources=priorities)
        self.assertEqual(result.selected_sources, ("clock",))

    def test_zero_budget_retains_deferred_checks_without_changing_history(self):
        arbiter = FairCheckArbiter(SOURCES)
        before = arbiter.snapshot()
        result = arbiter.arbitrate(candidates(), budget=0, priority_sources=("sensor",))
        self.assertEqual(result.selected, ())
        self.assertEqual(result.deferred_sources, ("sensor", "clock", "inbox"))
        self.assertEqual(arbiter.snapshot(), before)

    def test_empty_input_and_push_only_registry_are_supported(self):
        arbiter = FairCheckArbiter(())
        before = arbiter.snapshot()
        self.assertEqual(arbiter.arbitrate([], budget=9).selected, ())
        self.assertEqual(arbiter.snapshot(), before)
        with self.assertRaises(ValueError):
            arbiter.arbitrate(candidates(), budget=1)

    def test_large_budget_selects_distinct_sources_not_number_of_records(self):
        arbiter = FairCheckArbiter(SOURCES)
        rows = [*candidates(), check("extra", "clock")]
        result = arbiter.arbitrate(rows, budget=20)
        self.assertEqual(result.selected_sources, ("clock", "inbox", "sensor"))
        self.assertEqual(sum(len(group.decisions) for group in result.selected), 4)
        self.assertEqual(result.deferred, ())
        self.assertEqual(arbiter.snapshot()["sequence"], 3)

    def test_snapshot_resume_preserves_next_selection_and_detaches_data(self):
        original = FairCheckArbiter(SOURCES)
        original.arbitrate(candidates(), budget=1)
        original.record_query("sensor")
        state = json.loads(json.dumps(original.snapshot()))
        restored = FairCheckArbiter(reversed(SOURCES))
        restored.restore(state)
        state["offered"][0]["source"] = "inbox"
        self.assertEqual(original.snapshot(), restored.snapshot())
        for _ in range(8):
            self.assertEqual(original.arbitrate(candidates(), budget=2),
                             restored.arbitrate(reversed(candidates()), budget=2))
        self.assertEqual(original.snapshot(), restored.snapshot())
        detached = restored.snapshot()
        detached["queried"].clear()
        self.assertEqual(len(restored.snapshot()["queried"]), 1)

    def test_invalid_registry(self):
        for value in (None, "clock", {"clock": 1}, ["clock", "clock"], [""], [3], [False]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                FairCheckArbiter(value)

    def test_invalid_candidates_fail_atomically_even_with_zero_budget(self):
        good = check("valid", "clock")
        invalid = [None, {}, replace(good, kind="ACT"), replace(good, kind="WAIT"),
                   replace(good, intention_id=""), replace(good, intention_id=[]),
                   replace(good, source="unknown"), replace(good, source=[]),
                   replace(good, reason=None), replace(good, evidence_ids="obs"),
                   replace(good, evidence_ids=[]), replace(good, evidence_ids=("",)),
                   replace(good, evidence_ids=(False,)), replace(good, evidence_ids=("o", "o"))]
        for bad in invalid:
            for budget in (0, 1):
                with self.subTest(bad=bad, budget=budget):
                    arbiter = FairCheckArbiter(SOURCES)
                    arbiter.record_query("inbox")
                    before = arbiter.snapshot()
                    with self.assertRaises(ValueError):
                        arbiter.arbitrate([good, bad], budget=budget)
                    self.assertEqual(arbiter.snapshot(), before)

    def test_duplicates_and_invalid_collections_budget_priority_are_atomic(self):
        arbiter = FairCheckArbiter(SOURCES)
        good = check("valid", "clock")
        before = arbiter.snapshot()
        bad_calls = [([good, good], {}), ([good, replace(good, source="inbox")], {}),
                     (None, {}), ("", {}), ({"x": good}, {}),
                     ([good], {"budget": True}), ([good], {"budget": -1}),
                     ([good], {"budget": 1.0}), ([good], {"priority_sources": "clock"}),
                     ([good], {"priority_sources": ("clock", "clock")}),
                     ([good], {"priority_sources": ("unknown",)})]
        for rows, kwargs in bad_calls:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                arbiter.arbitrate(rows, **{"budget": 1, **kwargs})
            self.assertEqual(arbiter.snapshot(), before)
        for source in (None, [], "", "unknown"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                arbiter.record_query(source)
            self.assertEqual(arbiter.snapshot(), before)

    def test_malformed_restore_is_atomic(self):
        arbiter = FairCheckArbiter(SOURCES)
        arbiter.arbitrate(candidates(), budget=2)
        arbiter.record_query("sensor")
        good = arbiter.snapshot()

        def changed(key, value):
            result = copy.deepcopy(good)
            result[key] = value
            return result

        invalid = [None, [], {}, {**good, "extra": 1}, changed("version", True),
                   changed("version", 2), changed("kind", "other"), changed("sequence", True),
                   changed("sequence", -1), changed("sequence", 10000000000),
                   changed("queryable_sources", ["clock", "inbox"]),
                   changed("queryable_sources", list(reversed(good["queryable_sources"]))),
                   changed("offered", {}), changed("queried", [None]),
                   changed("queried", [{"sequence": 3, "source": []}]),
                   changed("queried", [{"sequence": 3, "source": "unknown"}]),
                   changed("queried", [{"sequence": 3, "source": "sensor", "extra": 1}]),
                   changed("queried", [{"sequence": True, "source": "sensor"}]),
                   changed("queried", [{"sequence": 2, "source": "sensor"}]),
                   changed("queried", [{"sequence": 4, "source": "sensor"}]),
                   changed("queried", []), changed("offered", list(reversed(good["offered"])))]
        for bad in invalid:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                arbiter.restore(bad)
            self.assertEqual(arbiter.snapshot(), good)
        arbiter.restore(good)
        self.assertEqual(arbiter.snapshot(), good)


if __name__ == "__main__":
    unittest.main()
