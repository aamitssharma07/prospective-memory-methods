"""Regression contracts for registration recovery; no model or API calls."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import jsonschema

from run import ROOT
from registration_guard import RegistrationGuard, needs_review, partition_units, update_cue
from improved_engine import ImprovedTriggerEngine, verbatim_spans
from test_improved_engine import Provider
from prospective_memory.core import Change, Instruction
from prospective_memory.method.registration import CLASSIFICATION_SCHEMA, compile_changes, layout_units
from tests.test_pis_v3_registration import Provider as CompilerProvider, slots
import registration_replay


def payload(text="Send the file after approval."):
    unit = layout_units(text)[0]
    return {"focus_unit": unit, "focus_unit_id": unit["id"],
            "current_message": {"id": "message", "text": text},
            "pending_intentions": [{"id": "pm_000001", "source_bound_specification": "Collect a pass"}],
            "instruction_origin": {"source": "events"}}


def row(kind="new_request", target=""):
    return {"unit_classifications": [{"unit_id": "u1", "classification": kind,
            "related_intention_id": target, "reason": "Scripted classification"}]}


class GuardTests(unittest.TestCase):
    def guard(self, responses):
        calls, records, errors = [], [], []

        def request(system, data, schema):
            calls.append((system, copy.deepcopy(data), copy.deepcopy(schema)))
            result = responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        guard = RegistrationGuard(request, lambda event, **kw: records.append({"event": event, **kw}),
                                  lambda phase, exc: errors.append((phase, str(exc))))
        return guard, calls, records, errors

    def test_review_uses_focused_unit_not_other_bullets(self):
        p = payload()
        p["current_message"]["text"] += "\n- Change the calendar reminder instead."
        self.assertFalse(update_cue(p))
        self.assertFalse(needs_review(p, row("fact")["unit_classifications"][0]))
        p["focus_unit"]["text"] = "Send it to Lee instead of Morgan."
        self.assertTrue(needs_review(p, row()["unit_classifications"][0]))

    def test_invalid_link_is_retried_not_silently_cleared(self):
        guard, calls, records, errors = self.guard([row(target="pm_000001"), row("fact")])
        result = guard.classify("classify", payload(), CLASSIFICATION_SCHEMA, "review")
        self.assertEqual(result, row("fact"))
        self.assertTrue(calls[1][1]["classification_repair"])
        self.assertEqual(records[0]["response"], row(target="pm_000001"))
        self.assertEqual(len(errors), 1)

    def test_decoding_schema_enforces_classification_target_combinations(self):
        original = copy.deepcopy(CLASSIFICATION_SCHEMA)
        guard, calls, _, _ = self.guard([row("compound")])
        guard.classify("classify", payload(), CLASSIFICATION_SCHEMA, "review")
        model_schema = calls[0][2]
        for valid in (row("compound"), row(), row("modify_request"),
                      row("restatement", "pm_000001")):
            jsonschema.validate(valid, model_schema)
        for invalid in (row("compound", "pm_000001"), row(target="pm_000001"),
                        row("restatement"), row("modify_request", "invented")):
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(invalid, model_schema)
        self.assertEqual(CLASSIFICATION_SCHEMA, original)

    def test_invalid_review_cannot_drop_valid_new_without_bounded_repair(self):
        p = payload("Send the change notice when approved.")
        guard, calls, records, _ = self.guard([row(), row(target="pm_000001"), row("fact")])
        self.assertEqual(guard.classify("classify", p, CLASSIFICATION_SCHEMA, "review"), row("fact"))
        self.assertEqual(len(calls), 3)
        self.assertIn("classification_repaired", [r["event"] for r in records])

    def test_still_invalid_response_is_rejected_without_ground_truth_or_loop(self):
        guard, calls, _, _ = self.guard([row(target="pm_000001"), row(target="pm_000001")])
        with self.assertRaises(ValueError):
            guard.classify("classify", payload(), CLASSIFICATION_SCHEMA, "review")
        self.assertEqual(len(calls), 2)

    def test_resolution_does_not_see_suggested_target_and_can_abstain(self):
        guard, calls, records, _ = self.guard([row("modify_request", "pm_000001"),
            {"target_resolutions": [{"reason": "Different obligation", "target_id": ""}]}])
        with self.assertRaisesRegex(ValueError, "no unique"):
            guard.classify("classify", payload(), CLASSIFICATION_SCHEMA, "review")
        self.assertNotIn("previous_classification", calls[-1][1])
        self.assertNotIn("target_hint", calls[-1][1])
        self.assertEqual(set(calls[-1][1]["pending_intentions"][0]),
                         {"id", "source_bound_specification"})
        self.assertEqual(records[-1]["resolution"]["target_resolutions"][0]["target_id"], "")

    def test_narrative_withdrawal_is_reviewed_without_forcing_a_cancellation(self):
        p = payload("Collecting the pass no longer needs to happen.")
        guard, calls, _, _ = self.guard([row("context"), row("cancel_request", "pm_000001"),
            {"target_resolutions": [{"target_id": "pm_000001", "reason": "Same collection"}]},
            {"target_matches": [{"update_action_quote": "Collecting the pass",
                "pending_action_quote": "Collect a pass", "same_obligation": True, "reason": "Same action"}]}])
        result = guard.classify("classify", p, CLASSIFICATION_SCHEMA, "review")
        self.assertEqual(result["unit_classifications"][0]["classification"], "cancel_request")
        self.assertTrue(calls[1][1]["classification_review"])

    def test_false_target_action_match_rejects_closest_task(self):
        p = payload("The manager call moves to 16:00.")
        guard, calls, records, _ = self.guard([row("modify_request", "pm_000001"),
            {"target_resolutions": [{"target_id": "pm_000001", "reason": "Closest task"}]},
            {"target_matches": [{"update_action_quote": "manager call",
                "pending_action_quote": "Collect a pass", "same_obligation": False,
                "reason": "Unrelated actions"}]}])
        with self.assertRaisesRegex(ValueError, "no unique supported"):
            guard.classify("classify", p, CLASSIFICATION_SCHEMA, "review")
        self.assertNotIn("target_id", calls[-1][1])
        self.assertEqual(records[-1]["event"], "target_action_match")

    def test_target_match_grammar_only_permits_verbatim_source_spans(self):
        p = payload("Collect a pass at 16:00 instead.")
        guard, calls, _, _ = self.guard([row("modify_request", "pm_000001"),
            {"target_resolutions": [{"target_id": "pm_000001", "reason": "Same pass"}]},
            {"target_matches": [{"update_action_quote": "Collect a pass",
                "pending_action_quote": "Collect a pass", "same_obligation": True,
                "reason": "Only the time changes"}]}])
        guard.quote_spans = verbatim_spans
        guard.classify("classify", p, CLASSIFICATION_SCHEMA, "review")
        fields = calls[-1][2]["properties"]["target_matches"]["items"]["properties"]
        for field, source in (("update_action_quote", p["focus_unit"]["text"]),
                              ("pending_action_quote", "Collect a pass")):
            self.assertTrue(fields[field]["enum"])
            self.assertTrue(all(span in source for span in fields[field]["enum"]))
            self.assertNotIn("collect a pass", fields[field]["enum"])

    def test_provider_review_is_independent_and_can_restate_pending_action(self):
        p = payload("The pass is ready. Please collect it now.")
        p["instruction_origin"]["source"] = "email"
        comparison = {"provider_comparisons": [{"reply_action_quote": "Please collect it now.",
            "resolved_reply_action": "Collect a pass", "resolved_pending_action": "Collect a pass",
            "pending_action_quote": "Collect a pass", "pending_id": "pm_000001",
            "relationship": "existing_request", "reason": "Same pending action and occasion"}]}
        guard, calls, _, _ = self.guard([row(), comparison])
        result = guard.classify("classify", p, CLASSIFICATION_SCHEMA, "generic review")
        self.assertEqual(result["unit_classifications"][0]["classification"], "restatement")
        self.assertEqual(result["unit_classifications"][0]["related_intention_id"], "pm_000001")
        self.assertNotIn("previous_classification", calls[-1][1])
        self.assertIn("occasion", calls[-1][0])

    def test_provider_comparison_rejects_invented_action_quote(self):
        p = payload("The pass is ready. Please collect it now.")
        p["instruction_origin"]["source"] = "email"
        comparison = {"provider_comparisons": [{"reply_action_quote": "Send the form",
            "resolved_reply_action": "Send the form", "resolved_pending_action": "",
            "pending_action_quote": "", "pending_id": "", "relationship": "distinct_request",
            "reason": "Invented request"}]}
        guard, _, records, _ = self.guard([row(), comparison])
        with self.assertRaisesRegex(ValueError, "not verbatim"):
            guard.classify("classify", p, CLASSIFICATION_SCHEMA, "review")
        self.assertEqual(records[-1]["response"], comparison)

    def test_distinct_provider_comparison_can_name_a_contrasting_candidate(self):
        p = payload("Send the form after approval.")
        p["instruction_origin"]["source"] = "email"
        comparison = {"provider_comparisons": [{"reply_action_quote": "Send the form",
            "resolved_reply_action": "Send the form", "resolved_pending_action": "Collect a pass",
            "pending_action_quote": "Collect a pass", "pending_id": "pm_000001",
            "relationship": "distinct_request", "reason": "These are different actions"}]}
        guard, _, records, _ = self.guard([row(), comparison])
        result = guard.classify("classify", p, CLASSIFICATION_SCHEMA, "review")
        self.assertEqual(result["unit_classifications"][0]["classification"], "new_request")
        self.assertEqual(result["unit_classifications"][0]["related_intention_id"], "")
        self.assertEqual(records[-2]["response"], comparison)

    def test_public_event_new_request_also_receives_duplicate_review(self):
        p = payload("Please collect the pass when ready.")
        comparison = {"provider_comparisons": [{"reply_action_quote": "collect the pass",
            "resolved_reply_action": "Collect a pass", "resolved_pending_action": "Collect a pass",
            "pending_action_quote": "Collect a pass", "pending_id": "pm_000001",
            "relationship": "existing_request", "reason": "Already pending"}]}
        guard, calls, _, _ = self.guard([row(), comparison])
        result = guard.classify("classify", p, CLASSIFICATION_SCHEMA, "review")
        self.assertEqual(result["unit_classifications"][0]["classification"], "restatement")
        self.assertEqual(len(calls), 2)

    def test_comparison_requires_resolved_action_before_accepting_new_request(self):
        p = payload("Please do it now.")
        p["instruction_origin"]["source"] = "email"
        comparison = {"provider_comparisons": [{"reply_action_quote": "Please do it now.",
            "resolved_reply_action": "", "pending_action_quote": "", "resolved_pending_action": "",
            "pending_id": "", "relationship": "distinct_request", "reason": "Unresolved reference"}]}
        guard, _, _, _ = self.guard([row(), comparison])
        with self.assertRaisesRegex(ValueError, "resolved concrete action"):
            guard.classify("classify", p, CLASSIFICATION_SCHEMA, "review")

    def test_replay_seeds_public_memory_without_importing_old_runtime_or_mutating_source(self):
        original = ImprovedTriggerEngine(Provider(), sources=("events", "email"), projector_id="old")
        original.ingest(Instruction("old_request", "Send the report when approved."))
        state = original.snapshot()
        untouched = copy.deepcopy(state)
        candidate = ImprovedTriggerEngine(Provider(), sources=("events", "email"),
                                          projector_id="new", registration_grounding=True)
        registration_replay.seed_public_state(candidate, state)
        self.assertEqual(candidate.intentions, original.intentions)
        self.assertEqual(candidate.instructions, original.instructions)
        self.assertTrue(candidate.registration_grounding)
        self.assertEqual(candidate.registration_log, [])
        candidate.triggers["pm_000001"]["days"].append("Friday")
        self.assertEqual(state, untouched)

    def test_placeholder_action_gets_one_logged_repair_not_automatic_deduplication(self):
        p = payload("The pass is ready. Please do it now.")
        p["instruction_origin"]["source"] = "email"
        invalid = {"provider_comparisons": [{"reply_action_quote": "Please do it now.",
            "resolved_reply_action": "do it", "pending_action_quote": "Collect a pass",
            "resolved_pending_action": "Collect a pass", "pending_id": "pm_000001",
            "relationship": "distinct_request", "reason": "Unresolved"}]}
        valid = {"occasion_comparisons": [{"relationship": "same_occasion",
            "additional_occasion_quote": "", "reason": "Same pending occasion"}]}
        resolution = {"reference_resolutions": [{"pending_id": "pm_000001", "reason": "Same pass"}]}
        guard, calls, records, errors = self.guard([row(), invalid, resolution, valid])
        result = guard.classify("classify", p, CLASSIFICATION_SCHEMA, "review")
        self.assertEqual(result["unit_classifications"][0]["classification"], "restatement")
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[-1][1]["reference_resolution"]["id"], "pm_000001")
        self.assertNotIn("invalid_response", calls[-1][1])
        self.assertEqual(len(errors), 1)
        self.assertIn("provider_comparison_rejected", [r["event"] for r in records])
        bad_occasion = {"occasion_comparisons": [{"relationship": "additional_occasion",
            "additional_occasion_quote": "tomorrow", "reason": "Invented occasion"}]}
        guard, calls, _, _ = self.guard([row(), invalid, resolution, bad_occasion])
        with self.assertRaisesRegex(ValueError, "verbatim supporting quote"):
            guard.classify("classify", p, CLASSIFICATION_SCHEMA, "review")
        self.assertEqual(len(calls), 4)
        guard, calls, _, _ = self.guard([row(), invalid,
            {"reference_resolutions": [{"pending_id": "", "reason": "Ambiguous"}]}])
        with self.assertRaisesRegex(ValueError, "no unique supported"):
            guard.classify("classify", p, CLASSIFICATION_SCHEMA, "review")
        self.assertEqual(len(calls), 3)
        p["focus_unit"]["text"] += " Also do it again tomorrow."
        guard, _, _, _ = self.guard([row(), invalid, resolution, bad_occasion])
        result = guard.classify("classify", p, CLASSIFICATION_SCHEMA, "review")
        self.assertEqual(result["unit_classifications"][0]["classification"], "new_request")
        self.assertEqual(result["unit_classifications"][0]["related_intention_id"], "")

    def test_replay_loader_keeps_expectations_out_of_public_state(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "gpt-5-4-actor-helper-qwen3-8b-1535138"
            run.mkdir()
            state = {"instructions": [], "intentions": [], "triggers": {}, "next_id": 1,
                     "sources": ["events"], "queryable_sources": [], "errors": ["old error"],
                     "observations": ["old observations"]}
            record = {"event": "instruction_intake", "step_key": ["Monday", "s1"], "before": state,
                      "instruction": {"id": "request", "text": "Send it when ready.",
                                      "scope": "Monday", "source": "events"}}
            (run / "memory.jsonl").write_text(json.dumps(record) + "\n")
            annotations = {"request": {"name": "saved_case", "new_count": 1, "changed": {}}}
            with patch.dict(registration_replay.ANNOTATIONS, annotations, clear=True):
                cases = registration_replay.load_cases(run)
            self.assertEqual(cases[0]["text"], record["instruction"]["text"])
            self.assertEqual(cases[0]["evidence"]["memory_line"], 1)
            for key in ("errors", "observations", "new_count", "changed"):
                self.assertNotIn(key, cases[0]["initial_state"])

    def test_missing_target_probe_cannot_pass_on_transport_failure(self):
        from registration_probe import CASES, evaluate
        case = next(c for c in CASES if c["name"] == "missing_update_target")
        engine = ImprovedTriggerEngine(Provider(), sources=("events", "email"), projector_id="scripted")
        engine.errors.append({"phase": "v3_unit_classification", "error": "Connection timed out"})
        self.assertFalse(evaluate(case, {}, engine)["passed"])

    def test_partitions_preserve_offsets_duplicates_and_negation(self):
        text = "Context.\n  Send it only after approval. Send it only after approval."
        unit = {"id": "u4", "start": 21, "end": 21 + len(text), "text": text}
        parts = ["Context.", "Send it only after approval.", "Send it only after approval."]
        children = partition_units(unit, {"parts": parts})
        for child in children:
            self.assertEqual(text[child["start"]-21:child["end"]-21], child["text"])
        self.assertNotEqual(children[1]["start"], children[2]["start"])
        for bad in ([parts[1], parts[0], parts[2]], parts[:2], ["Context.", "Send it after approval."]):
            with self.assertRaises(ValueError):
                partition_units(unit, {"parts": bad})

    def test_compound_expansion_classifies_all_children_without_recursion(self):
        text = "Cancel the old delivery. Collect the pass when ready. Another ambiguous clause."
        unit = layout_units(text)[0]
        children = partition_units(unit, {"parts": ["Cancel the old delivery.",
            "Collect the pass when ready.", "Another ambiguous clause."]})
        provider = CompilerProvider({"u1": "compound", "u1.1": "fact",
            "u1.2": "new_request", "u1.3": "uncertain"}, [slots()])
        expanded, errors = [], []

        def expand(unit, message):
            expanded.append(unit)
            return children

        results = compile_changes(provider, Instruction("source", text), [], ("events",), {}, {},
                                  lambda phase, exc: errors.append((phase, str(exc))), expand_unit=expand)
        self.assertEqual(len(expanded), 1)
        self.assertEqual(results[0][0].evidence_quote, "Collect the pass when ready.")
        self.assertEqual([p[1]["focus_unit_id"] for p in provider.calls if p[0] == "unit_classifications"],
                         ["u1", "u1.1", "u1.2", "u1.3"])
        self.assertEqual(errors[0][0], "v3_unit_unresolved")

    def test_disabled_expansion_retains_original_shared_behavior(self):
        provider = CompilerProvider({"u1": "compound"}, [])
        errors = []
        result = compile_changes(provider, Instruction("source", "Do this. Do that."), [],
            ("events",), {}, {}, lambda phase, exc: errors.append(phase))
        self.assertEqual(result, [])
        self.assertEqual(errors, ["v3_unit_unresolved"])

    def test_compiler_rejects_expander_omission_even_if_callback_is_broken(self):
        provider = CompilerProvider({"u1": "compound"}, [])
        text = "Do this. Only after approval."
        child = {"id": "u1.1", "parent_unit_id": "u1", "start": 0, "end": 8, "text": "Do this."}
        errors = []
        result = compile_changes(provider, Instruction("source", text), [], ("events",), {}, {},
            lambda phase, exc: errors.append(str(exc)), expand_unit=lambda *args: [child])
        self.assertEqual(result, [])
        self.assertTrue(any("omit source" in e for e in errors))

    def test_compiler_cannot_substitute_resolved_target(self):
        class WrongTarget(Provider):
            def __call__(self, system, data, schema):
                value = super().__call__(system, data, schema)
                if "specifications" in value and self.kind == "modify_request":
                    value["specifications"][0]["target_id"] = "pm_000002"
                return value
        p = WrongTarget()
        engine = ImprovedTriggerEngine(p, sources=("events", "email"), projector_id="scripted",
                                       registration_grounding=True)
        engine.ingest(Instruction("first", "Send the report after approval."))
        engine.ingest(Instruction("second", "Collect the pass when ready."))
        before = dict(engine.intentions)
        p.kind, p.target = "modify_request", "pm_000001"
        engine.ingest(Instruction("update", "Send the report to Lee instead."))
        self.assertEqual(before, engine.intentions)
        self.assertTrue(engine.errors)

    def test_one_failed_specification_does_not_erase_other_units(self):
        class BrokenProvider(Provider):
            def __call__(self, system, data, schema):
                if "specifications" in schema["properties"] and data["operations"][0]["operation_id"] == "request_1":
                    raise ValueError("bad compiler response")
                return super().__call__(system, data, schema)
        engine = ImprovedTriggerEngine(BrokenProvider(), sources=("events", "email"),
                                       projector_id="scripted", registration_grounding=True)
        changed = engine.ingest(Instruction("plan", "- Send the file after approval.\n- Collect the pass when ready."))
        self.assertEqual(len(changed), 1)
        self.assertIn("Collect the pass", engine.intentions[changed[0]].action)
        self.assertTrue(any(r["event"] == "specification_rejected" for r in engine.registration_log))
        restored = engine.fresh()
        restored.restore(engine.snapshot())
        self.assertEqual(restored.registration_log, engine.registration_log)

    def test_same_message_duplicate_cancellations_are_idempotent_and_logged(self):
        engine = ImprovedTriggerEngine(Provider(), sources=("events", "email"),
                                       projector_id="scripted", registration_grounding=True)
        engine.ingest(Instruction("old", "Collect the pass when ready."))
        quote = "Cancel collection. Collection is canceled."
        first = Change("cancel", target_id="pm_000001", evidence_quote="Cancel collection.")
        second = Change("cancel", target_id="pm_000001", evidence_quote="Collection is canceled.")
        with patch("prospective_memory.method.registration.compile_changes", return_value=[
                (first, engine.triggers["pm_000001"]), (second, engine.triggers["pm_000001"]) ]):
            engine.ingest(Instruction("update", quote))
        self.assertEqual(engine.intentions["pm_000001"].status, "cancelled")
        self.assertEqual(engine.intentions["pm_000001"].revision, 2)
        self.assertFalse(engine.errors)
        self.assertEqual(engine.registration_log[-1]["event"], "duplicate_cancellation_coalesced")


if __name__ == "__main__":
    unittest.main()
