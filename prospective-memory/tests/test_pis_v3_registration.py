"""Scripted layout/identity/source contracts, not model semantic evaluation."""

import copy
import unittest

from prospective_memory.core import Instruction, Intention
from prospective_memory.baselines.pis import DAYS, PISEngine
from prospective_memory.baselines.pis_registration import IDENTIFIER, _specification_schema
from prospective_memory.method.registration import (
    CLASSIFY, CLASSIFICATION_SCHEMA, COMPILE_V3,
    compile_changes, layout_units,
)


def slots(**updates):
    return {"operation_id": "request_1", "target_id": "", "watched_sources": ["events"],
            "permitted_days": [], "recurring": False, "clock_relation": "none",
            "required_clock_time": "", **updates}


class Provider:
    def __init__(self, classifications, specifications, *, same=True, explicit=True):
        self.classifications = classifications
        self.specifications = specifications
        self.same, self.explicit = same, explicit
        self.calls = []
        self.fail_units = set()
        self.fail_review = False

    def __call__(self, system, payload, schema):
        key = next(iter(schema["properties"]))
        self.calls.append((key, copy.deepcopy(payload), copy.deepcopy(schema)))
        if key == "unit_classifications":
            focus = payload["focus_unit_id"]
            if focus in self.fail_units:
                raise RuntimeError("Scripted unit failure")
            raw = self.classifications[focus]
            if isinstance(raw, dict):
                return {key: [copy.deepcopy(raw)]}
            kind, related = raw if isinstance(raw, tuple) else (raw, "")
            return {key: [{"unit_id": focus, "classification": kind,
                           "related_intention_id": related, "reason": "Scripted disposition"}]}
        if key == "specifications":
            return {key: copy.deepcopy(self.specifications)}
        if key == "identity_reviews":
            if self.fail_review:
                raise RuntimeError("Scripted review outage")
            return {key: [{"same_obligation": self.same, "explicit_update": self.explicit,
                           "reason": "Scripted identity verdict"}]}
        raise AssertionError(key)


class LayoutTests(unittest.TestCase):
    def test_bullet_entries_headers_and_continuations_preserve_exact_source(self):
        text = "## Morning plan\nTasks:\n- Send the report when approved.\n  Only after signature.\n  - Never attach the draft.\n- Collect the badge when ready.\n"
        units = layout_units(text)
        self.assertEqual([u["layout"] for u in units], ["heading", "heading", "bullet", "bullet"])
        self.assertEqual(units[2]["text"], "- Send the report when approved.\n  Only after signature.\n  - Never attach the draft.")
        for index, unit in enumerate(units, 1):
            self.assertEqual(unit["id"], f"u{index}")
            self.assertEqual(text[unit["start"]:unit["end"]], unit["text"])

    def test_sentences_semicolons_abbreviations_not_invented_source_units(self):
        text = "Ask Dr. Hale to approve it. Then send it; keep the notes."
        units = layout_units(text)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]["text"], text)

    def test_paragraphs_numbered_lists_crlf_and_duplicate_lines_have_distinct_spans(self):
        text = "Context paragraph.\r\nWrapped context.\r\n\r\n1. Inspect when ready.\r\n   Keep the seal.\r\n2. Inspect when ready.\r\n\r\nSeparate note."
        units = layout_units(text)
        self.assertEqual([u["layout"] for u in units], ["paragraph", "bullet", "bullet", "paragraph"])
        for unit in units:
            self.assertEqual(text[unit["start"]:unit["end"]], unit["text"])
        self.assertIn("\r\n", units[1]["text"])
        repeated = layout_units("- Do the task.\n- Do the task.")
        self.assertEqual(repeated[0]["text"], repeated[1]["text"])
        self.assertNotEqual(repeated[0]["start"], repeated[1]["start"])

    def test_blank_line_indented_continuation_stays_in_bullet(self):
        text = "- Send it when approved.\n\n  Do not include personal notes.\n- Collect the pass."
        units = layout_units(text)
        self.assertEqual(len(units), 2)
        self.assertIn("\n\n  Do not", units[0]["text"])

    def test_empty_input_has_no_units(self):
        self.assertEqual(layout_units(" \n\t"), [])


class CompilerTests(unittest.TestCase):
    def test_shared_weekday_heading_survives_unrelated_physical_removal_actions(self):
        first = "- Record the tank reading when the blue indicator lights."
        for action in ("Drop the spare cable in the cabinet", "Clear the packing bench",
                       "Remove the empty crate", "Place the spare cable in the cabinet"):
            with self.subTest(action=action):
                second = f"- {action} when the trolley arrives."
                text = "Thursday workshop plan:\n" + first + "\n" + second
                rows = [slots(permitted_days=["Thursday"]),
                        slots(operation_id="request_2", permitted_days=["Thursday"])]
                result, _, errors = self.run_compile(text,
                    {"u1": "context", "u2": "new_request", "u3": "new_request"}, rows, scope="Monday")
                self.assertEqual([trigger["days"] for _, trigger in result], [["Thursday"], ["Thursday"]])
                self.assertEqual([change.action for change, _ in result], [first, second])
                self.assertEqual(errors, [])

    def test_today_heading_with_physical_removal_uses_only_public_host_scope(self):
        text = "Today's workshop plan:\n- Remove the empty crate when the trolley arrives."
        result, _, errors = self.run_compile(text, {"u1": "context", "u2": "new_request"},
            [slots(permitted_days=["Monday"])], scope="Monday")
        self.assertEqual(result[0][1]["days"], ["Monday"])
        self.assertEqual(errors, [])

    def test_wrapped_and_referential_calendar_removal_cannot_revive_old_day(self):
        cases = [("Remove the\nMonday restriction on the report reminder.", {"u1": "modify_request"}),
                 ("Monday restriction:\n- Remove the old rule.", {"u1": "context", "u2": "modify_request"}),
                 ("Monday restriction:\n- Lift remaining restrictions.", {"u1": "context", "u2": "modify_request"}),
                 ("Monday restriction:\n- Remove only that restriction.", {"u1": "context", "u2": "modify_request"})]
        old = self.old("On Monday, send the signed report after email approval.", day="Monday")
        for text, labels in cases:
            with self.subTest(text=text):
                result, _, errors = self.run_compile(text, labels,
                    [slots(target_id="pm_000007", permitted_days=["Monday"])], scope="Thursday", old=old)
                self.assertEqual(result[0][1]["days"], [])
                self.assertEqual(result[0][0].target_id, "pm_000007")
                self.assertEqual([phase for phase, _ in errors], ["v3_day_guard"])

    def run_compile(self, text, classifications, specifications=(), *, scope="", old=None,
                    sources=("events", "clock", "email"), same=True, explicit=True, provider=None):
        p = provider or Provider(classifications, specifications, same=same, explicit=explicit)
        errors = []
        state = old or {"intentions": [], "triggers": {}, "instructions": {}}
        original = copy.deepcopy(state)
        result = compile_changes(p, Instruction("current", text, scope), state["intentions"],
                                 sources, state["triggers"], state["instructions"],
                                 lambda phase, exc: errors.append((phase, str(exc))))
        self.assertEqual(state, original)
        return result, p.calls, errors

    def old(self, action="Send the signed report to Morgan after email approval.", *, day=None):
        trigger = {"days": [day] if day else [], "clock_op": "none", "clock_time": ""}
        old = Intention("pm_000007", action, action + PISEngine._slot_suffix(trigger),
                        ("email",), scope="*" if day else "", instruction_ids=("first",))
        return {"intentions": [old], "triggers": {old.id: trigger},
                "instructions": {"first": Instruction("first", action, day or "")}}

    def test_every_layout_unit_classified_and_independent_bullets_stored_exactly(self):
        text = "Today's plan:\n- Send the signed report after approval.\n- Collect the visitor pass when reception opens."
        labels = {"u1": "context", "u2": "new_request", "u3": "new_request"}
        rows = [slots(), slots(operation_id="request_2")]
        result, calls, errors = self.run_compile(text, labels, rows, scope="Monday")
        self.assertEqual([c[1]["focus_unit_id"] for c in calls if c[0] == "unit_classifications"], ["u1", "u2", "u3"])
        self.assertEqual([c[0] for c in calls], ["unit_classifications"] * 3 + ["specifications"])
        self.assertEqual([c.action for c, _ in result], [u["text"] for u in layout_units(text)[1:]])
        self.assertEqual(errors, [])

    def test_plain_single_request_has_one_classification_and_no_add_review(self):
        text = "When the station opens, remind me to collect the visitor pass for Alex."
        result, calls, errors = self.run_compile(text, {"u1": "new_request"}, [slots()])
        self.assertEqual([c[0] for c in calls], ["unit_classifications", "specifications"])
        self.assertEqual(result[0][0].action, text)
        self.assertEqual(result[0][0].evidence_quote, text)
        self.assertEqual(errors, [])

    def test_classifier_contract_explains_conditional_imperatives_before_labels(self):
        # This checks the supplied contract, not whether an LLM obeys it.
        fields = CLASSIFICATION_SCHEMA["properties"]["unit_classifications"]["items"]["properties"]
        self.assertEqual(next(iter(fields)), "reason")
        self.assertLess(CLASSIFY.index("An imperative IS an explicit request"), CLASSIFY.index("Classifications:"))
        self.assertIn("A complete action-plus-condition request must not be labelled context", CLASSIFY)
        self.assertIn("NOT a directive to perform an action", CLASSIFY)
        self.assertIn("REGISTRATION, not trigger-readiness assessment", CLASSIFY)

    def test_generated_quote_whitespace_cannot_replace_code_owned_source(self):
        text = "- Send the report after approval.\n  Keep the attachments encrypted."
        result, calls, _ = self.run_compile(text, {"u1": "new_request"}, [slots()])
        self.assertEqual(result[0][0].action, text)
        self.assertEqual(calls[-1][1]["operations"][0]["complete_request_quote"], text)
        self.assertEqual(calls[0][1]["focus_unit"]["text"], text)
        self.assertEqual(calls[0][1]["focus_unit"]["id"], calls[0][1]["focus_unit_id"])
        fields = calls[0][2]["properties"]["unit_classifications"]["items"]["properties"]
        self.assertNotIn("complete_request_quote", fields)

    def test_same_action_multiple_occasions_remains_one_semantic_intention(self):
        text = "Perform the calibration at 10:00 and again at 18:00 every day."
        result, _, errors = self.run_compile(text, {"u1": "new_request"},
                                             [slots(watched_sources=["clock"], recurring=True)])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0].action, text)
        self.assertTrue(result[0][0].repeat)
        self.assertEqual(result[0][1]["clock_op"], "none")
        self.assertEqual(errors, [])

    def test_compound_and_uncertain_units_are_visible_not_false_coverage(self):
        for kind in ("compound", "uncertain"):
            with self.subTest(kind=kind):
                result, calls, errors = self.run_compile("Do one action and independently do another.", {"u1": kind})
                self.assertEqual(result, [])
                self.assertEqual(len(calls), 1)
                self.assertEqual(errors[0][0], "v3_unit_unresolved")

    def test_facts_speculation_context_and_restated_obligation_do_not_add(self):
        labels = {"u1": "context", "u2": "fact", "u3": "speculation",
                  "u4": ("restatement", "pm_000007")}
        text = "Notes:\n\nThe room is quiet.\n\nThe station may open later.\n\nYou still need to send the signed report."
        result, calls, errors = self.run_compile(text, labels, old=self.old())
        self.assertEqual(result, [])
        self.assertEqual(len(calls), 4)
        self.assertEqual(errors, [])
        self.assertEqual(calls[-1][1]["pending_intentions"][0]["id"], "pm_000007")

    def test_unknown_restatement_target_is_logged_not_new_registration(self):
        result, _, errors = self.run_compile("You still need to send it.",
            {"u1": ("restatement", "missing")}, old=self.old())
        self.assertEqual(result, [])
        self.assertIn("known pending", errors[0][1])

    def test_partial_unit_failure_does_not_skip_other_units_or_discard_siblings(self):
        text = "- Send the signed report after approval.\n- Collect the visitor pass when ready."
        p = Provider({"u1": "new_request", "u2": "new_request"}, [slots()])
        p.fail_units.add("u1")
        result, calls, errors = self.run_compile(text, {}, provider=p)
        self.assertEqual([c[1]["focus_unit_id"] for c in calls if c[0] == "unit_classifications"], ["u1", "u2"])
        self.assertEqual(result[0][0].action, layout_units(text)[1]["text"])
        self.assertEqual(errors[0][0], "v3_unit_classification")

    def test_wrong_focus_response_is_not_allowed_to_skip_another_unit(self):
        raw = {"unit_id": "u2", "classification": "new_request", "related_intention_id": "", "reason": "Wrong focus"}
        result, calls, errors = self.run_compile("- First request.\n- Second request.",
            {"u1": raw, "u2": "new_request"}, [slots()])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0].action, "- Second request.")
        self.assertIn("focus unit", errors[0][1])

    def test_typed_generation_sources_enum_bound_without_mutating_ids_or_globals(self):
        base_identifier = copy.deepcopy(IDENTIFIER)
        base_classifier = copy.deepcopy(CLASSIFICATION_SCHEMA)
        text = "Act when the signal arrives."
        for sources in [("events", "email"), ("sensor",)]:
            result, calls, errors = self.run_compile(text, {"u1": "new_request"},
                [slots(watched_sources=[sources[0]])], sources=sources)
            fields = calls[-1][2]["properties"]["specifications"]["items"]["properties"]
            self.assertEqual(fields["watched_sources"]["items"]["enum"], list(sources))
            self.assertNotIn("enum", fields["operation_id"])
            self.assertNotIn("enum", fields["target_id"])
            self.assertEqual(len(result), 1)
            self.assertEqual(errors, [])
        self.assertEqual(IDENTIFIER, base_identifier)
        self.assertEqual(CLASSIFICATION_SCHEMA, base_classifier)
        self.assertNotIn("enum", _specification_schema()["properties"]["specifications"]
                         ["items"]["properties"]["watched_sources"]["items"])

    def test_nonconforming_provider_cannot_register_unknown_source(self):
        result, _, errors = self.run_compile("Act when the signal arrives.", {"u1": "new_request"},
                                             [slots(watched_sources=["invented_tool"])])
        self.assertEqual(result, [])
        self.assertIn("Unknown observation source", errors[0][1])

    def test_metadata_contract_clarifies_recurrence_sources_without_new_schema(self):
        _, calls, errors = self.run_compile("Retest the lens after each recalibration.",
            {"u1": "new_request"}, [slots(recurring=True)])
        fields = calls[-1][2]["properties"]["specifications"]["items"]["properties"]
        self.assertNotIn("reason", fields)
        self.assertEqual(set(fields), set(_specification_schema()["properties"]["specifications"]["items"]["properties"]))
        self.assertIn("requires recurring=true", COMPILE_V3)
        self.assertIn("A single clock/event cue is not recurrence", COMPILE_V3)
        self.assertIn("Alternatives between visible cues\nalone need no clock source", COMPILE_V3)
        self.assertIn("Compile ONLY supplied operations: exactly one row per operation_id", COMPILE_V3)
        self.assertIn("Unchanged pending records are reference material, not additional work", COMPILE_V3)
        self.assertEqual(errors, [])

    def test_metadata_has_one_batched_worklist_without_operation_enum(self):
        text = "Instructions:\n- Retest after calibration.\n- The stage is quiet.\n- Count the lenses after inspection."
        result, calls, errors = self.run_compile(text,
            {"u1": "context", "u2": "new_request", "u3": "fact", "u4": "new_request"},
            [slots(), slots(operation_id="request_2")], old=self.old())
        metadata = [call for call in calls if call[0] == "specifications"]
        self.assertEqual(len(metadata), 1)
        _, payload, schema = metadata[0]
        fields = schema["properties"]["specifications"]["items"]["properties"]
        self.assertNotIn("enum", fields["operation_id"])
        self.assertNotIn("enum", fields["target_id"])
        self.assertEqual([op["operation_id"] for op in payload["operations"]], ["request_1", "request_2"])
        self.assertEqual(len(result), 2)
        self.assertEqual(errors, [])

    def test_unknown_operation_id_rejected_but_valid_siblings_preserved(self):
        result, _, errors = self.run_compile("- Count the lenses after inspection.\n- Retest after calibration.",
            {"u1": "new_request", "u2": "new_request"},
            [slots(operation_id="u1"), slots(operation_id="request_2")])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0].action, "- Retest after calibration.")
        self.assertTrue(any("unique known operation ID" in text for _, text in errors))
        self.assertTrue(any("Missing specification for request_1" in text for _, text in errors))

    def test_duplicate_known_operation_id_cannot_create_second_target_change(self):
        result, calls, errors = self.run_compile("Change the report recipient to Lee.", {"u1": "modify_request"},
            [slots(target_id="pm_000007"), slots(target_id="pm_000007")], old=self.old())
        self.assertEqual(len(result), 1)
        self.assertEqual(sum(key == "identity_reviews" for key, _, _ in calls), 1)
        self.assertTrue(any("unique known operation ID" in message for _, message in errors))

    def test_missing_metadata_is_visible_and_does_not_invent_coverage(self):
        result, _, errors = self.run_compile("- Count the lenses after inspection.\n- Retest after calibration.",
            {"u1": "new_request", "u2": "new_request"}, [slots()])
        self.assertEqual(len(result), 1)
        self.assertEqual(errors, [("v3_typed_change", "Missing specification for request_2")])

    def test_metadata_schema_calls_do_not_mutate_v2_or_shared_schema_dictionaries(self):
        original = copy.deepcopy(_specification_schema())
        for source in ("events", "clock"):
            _, calls, errors = self.run_compile("Retest after calibration.",
                {"u1": "new_request"}, [slots(watched_sources=[source])], sources=(source,))
            fields = calls[-1][2]["properties"]["specifications"]["items"]["properties"]
            self.assertEqual(fields["watched_sources"]["items"]["enum"], [source])
            self.assertNotIn("enum", fields["operation_id"])
            self.assertNotIn("reason", fields)
            self.assertEqual(errors, [])
        self.assertEqual(_specification_schema(), original)
        self.assertNotIn("enum", IDENTIFIER)

    def test_supported_revision_preserves_id_prerequisites_and_chronological_source(self):
        text = "Send that signed report to Lee instead of Morgan."
        old = self.old()
        result, calls, errors = self.run_compile(text, {"u1": "modify_request"},
            [slots(target_id="pm_000007", watched_sources=["email"])], old=old)
        change, _ = result[0]
        self.assertEqual((change.op, change.target_id), ("revise", "pm_000007"))
        self.assertIn(old["intentions"][0].action, change.action)
        self.assertIn(text, change.action)
        self.assertIn("after email approval", change.condition)
        self.assertEqual(change.evidence_quote, text)
        self.assertEqual(calls[-1][0], "identity_reviews")
        self.assertEqual(calls[-1][1]["target"]["source_bound_specification"], old["intentions"][0].action)
        self.assertEqual(errors, [])

    def test_known_revision_hint_reaches_metadata_and_still_requires_identity_review(self):
        text = "Change the report recipient to Lee instead."
        result, calls, errors = self.run_compile(text,
            {"u1": ("modify_request", "pm_000007")}, [slots(target_id="pm_000007")], old=self.old())
        self.assertEqual(result[0][0].target_id, "pm_000007")
        metadata_call = next(c for c in calls if c[0] == "specifications")
        self.assertEqual(metadata_call[1]["operations"][0]["target_hint"], "pm_000007")
        self.assertEqual([c[0] for c in calls], ["unit_classifications", "specifications", "identity_reviews"])
        self.assertEqual(errors, [])

    def test_known_cancellation_hint_is_accepted_only_after_identity_review(self):
        text = "Cancel sending the signed report."
        for supported in (True, False):
            with self.subTest(supported=supported):
                result, calls, errors = self.run_compile(text,
                    {"u1": ("cancel_request", "pm_000007")}, [slots(target_id="pm_000007")],
                    old=self.old(), same=supported)
                self.assertEqual(calls[-1][0], "identity_reviews")
                self.assertEqual(bool(result), supported)
                self.assertEqual(bool(errors), not supported)
                if result:
                    self.assertEqual(result[0][0].op, "cancel")

    def test_known_hint_alone_cannot_resolve_or_mutate_an_update(self):
        result, calls, errors = self.run_compile("Change that report's recipient.",
            {"u1": ("modify_request", "pm_000007")}, [slots(target_id="")], old=self.old())
        self.assertEqual(result, [])
        self.assertNotIn("identity_reviews", [c[0] for c in calls])
        self.assertIn("Unresolved update", errors[0][1])

    def test_unknown_update_hint_rejected_without_creating_or_mutating_record(self):
        result, calls, errors = self.run_compile("Change that report's recipient.",
            {"u1": ("modify_request", "unknown")}, [slots(target_id="pm_000007")], old=self.old())
        self.assertEqual(result, [])
        self.assertEqual(len(calls), 1)
        self.assertIn("target hint must reference a known", errors[0][1])

    def test_new_addition_and_facts_still_cannot_supply_existing_target_hint(self):
        for kind in ("new_request", "fact"):
            with self.subTest(kind=kind):
                result, calls, errors = self.run_compile("A separate source unit.",
                    {"u1": (kind, "pm_000007")}, [slots()], old=self.old())
                self.assertEqual(result, [])
                self.assertEqual(len(calls), 1)
                self.assertIn("Only restatement or an update", errors[0][1])

    def test_known_hint_does_not_bypass_rejection_of_wrong_concrete_target(self):
        result, calls, errors = self.run_compile("Change the trigger for returning the signed document.",
            {"u1": ("modify_request", "pm_000007")}, [slots(target_id="pm_000007")],
            old=self.old(), same=False)
        self.assertEqual(result, [])
        self.assertEqual(calls[-1][0], "identity_reviews")
        self.assertEqual(errors[0][0], "v3_identity_review")

    def test_identity_review_blocks_topically_similar_wrong_target(self):
        text = "Change the trigger for returning the signed document to the receipt arriving."
        result, calls, errors = self.run_compile(text, {"u1": "modify_request"},
            [slots(target_id="pm_000007")], old=self.old(), same=False)
        self.assertEqual(result, [])
        self.assertEqual(calls[-1][0], "identity_reviews")
        self.assertEqual(errors[0][0], "v3_identity_review")

    def test_identity_without_explicit_update_also_rejected(self):
        result, _, errors = self.run_compile("The signed report has already been mentioned.",
            {"u1": "modify_request"}, [slots(target_id="pm_000007")], old=self.old(), explicit=False)
        self.assertEqual(result, [])
        self.assertEqual(errors[0][0], "v3_identity_review")

    def test_missing_update_target_never_falls_back_to_new_or_nearest_record(self):
        result, calls, errors = self.run_compile("Change the other reminder to the new trigger.",
            {"u1": "modify_request"}, [slots()], old=self.old())
        self.assertEqual(result, [])
        self.assertNotIn("identity_reviews", [key for key, _, _ in calls])
        self.assertIn("Unresolved update", errors[0][1])

    def test_add_does_not_need_target_identity_review_with_unrelated_old_bank(self):
        result, calls, errors = self.run_compile("Collect the badge when reception opens.",
            {"u1": "new_request"}, [slots()], old=self.old(), same=False, explicit=False)
        self.assertEqual(result[0][0].op, "register")
        self.assertNotIn("identity_reviews", [key for key, _, _ in calls])
        self.assertEqual(errors, [])

    def test_cancellation_only_after_supported_same_target_review(self):
        result, _, errors = self.run_compile("Cancel sending the signed report.",
            {"u1": "cancel_request"}, [slots(target_id="pm_000007")], old=self.old())
        self.assertEqual((result[0][0].op, result[0][0].target_id), ("cancel", "pm_000007"))
        self.assertEqual(errors, [])

    def test_identity_review_failure_does_not_discard_independent_new_request(self):
        text = "- Change the report recipient.\n- Collect the badge when ready."
        p = Provider({"u1": "modify_request", "u2": "new_request"},
                     [slots(target_id="pm_000007"), slots(operation_id="request_2")])
        p.fail_review = True
        result, _, errors = self.run_compile(text, {}, old=self.old(), provider=p)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0].action, "- Collect the badge when ready.")
        self.assertEqual(errors[0][0], "v3_identity_review")

    def test_today_is_grounded_only_from_explicit_public_host_weekday(self):
        text = "Today's loose plan:\n- Send the report at 09:15."
        labels = {"u1": "context", "u2": "new_request"}
        rows = [slots(watched_sources=["clock"], permitted_days=["Monday"],
                      clock_relation="at", required_clock_time="09:15")]
        result, calls, errors = self.run_compile(text, labels, rows, scope="Monday")
        self.assertEqual(result[0][1]["days"], ["Monday"])
        self.assertEqual(errors, [])
        self.assertEqual(calls[-1][1]["current_message"]["text"], text)
        for scope in ("", "*", "unrelated-project"):
            with self.subTest(scope=scope):
                result, _, errors = self.run_compile(text, labels, rows, scope=scope)
                self.assertEqual(result[0][1]["days"], [])
                self.assertEqual(errors[0][0], "v3_day_guard")

    def test_today_does_not_authorize_guessing_tomorrow_or_negative_schedules(self):
        for text in ("Send the report tomorrow.", "Do not send the report today."):
            with self.subTest(text=text):
                result, _, errors = self.run_compile(text, {"u1": "new_request"},
                    [slots(permitted_days=["Monday"])], scope="Monday")
                self.assertEqual(result[0][1]["days"], [])
                self.assertEqual(errors[0][0], "v3_day_guard")

    def test_today_in_original_history_does_not_rebase_on_update_host_day(self):
        old = self.old("Today, send the report after approval.", day="Monday")
        result, _, errors = self.run_compile("Send it to Lee instead.", {"u1": "modify_request"},
            [slots(target_id="pm_000007", permitted_days=["Monday"])], scope="Thursday", old=old)
        self.assertEqual(result[0][1]["days"], ["Monday"])
        self.assertEqual(errors, [])

    def test_unsupported_calendar_and_clock_still_removed_preserving_full_source(self):
        text = "Inspect the sample once the timer reports enough time has elapsed."
        result, _, errors = self.run_compile(text, {"u1": "new_request"},
            [slots(permitted_days=list(DAYS[:5]), clock_relation="at", required_clock_time="00:00")])
        self.assertEqual(result[0][1], {"days": [], "clock_op": "none", "clock_time": ""})
        self.assertEqual(result[0][0].condition, text)
        self.assertEqual({phase for phase, _ in errors}, {"v3_clock_guard", "v3_day_guard"})

    def test_compiler_has_no_gold_or_simulator_data_in_inputs(self):
        _, calls, _ = self.run_compile("Act when the visible signal appears.",
                                       {"u1": "new_request"}, [slots()])
        allowed = {"unit_classifications": {"focus_unit", "current_message", "source_units", "focus_unit_id",
                                            "pending_intentions", "available_sources"},
                   "specifications": {"current_message", "operations", "pending_update_targets", "available_sources"}}
        for phase, payload, _ in calls:
            self.assertEqual(set(payload), allowed[phase])


if __name__ == "__main__":
    unittest.main()
