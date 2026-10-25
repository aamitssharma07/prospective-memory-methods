"""Compiler contracts using scripted replies, not tests of model competence."""

import copy
import unittest

from prospective_memory.core import Instruction, Intention
from prospective_memory.baselines.pis import DAYS, PISEngine
from prospective_memory.baselines.pis_registration import compile_changes


def operation(quote, kind="new_request"):
    return {"operation": kind, "complete_request_quote": quote}


def specification(**updates):
    return {"operation_id": "request_1", "target_id": "", "watched_sources": ["events"],
            "permitted_days": [], "recurring": False, "clock_relation": "none",
            "required_clock_time": "", **updates}


class Provider:
    def __init__(self, operations, specifications=()):
        self.operations, self.specifications = operations, specifications
        self.calls = []

    def __call__(self, system, payload, schema):
        self.calls.append((system, copy.deepcopy(payload), copy.deepcopy(schema)))
        key = next(iter(schema["properties"]))
        return {key: copy.deepcopy(self.operations if key == "operations" else self.specifications)}


class CompilerTests(unittest.TestCase):
    def test_shared_weekday_heading_survives_unrelated_physical_removal_actions(self):
        first = "- Record the tank reading when the blue indicator lights."
        for action in ("Drop the spare cable in the cabinet", "Clear the packing bench",
                       "Remove the empty crate", "Place the spare cable in the cabinet"):
            with self.subTest(action=action):
                second = f"- {action} when the trolley arrives."
                text = "Thursday workshop plan:\n" + first + "\n" + second
                rows = [specification(permitted_days=["Thursday"]),
                        specification(operation_id="request_2", permitted_days=["Thursday"])]
                result, _, errors = self.compile(text, [operation(first), operation(second)], rows, scope="Monday")
                self.assertEqual([trigger["days"] for _, trigger in result], [["Thursday"], ["Thursday"]])
                self.assertEqual([change.action for change, _ in result], [first, second])
                self.assertEqual(errors, [])

    def test_wrapped_and_referential_calendar_removal_cannot_revive_old_day(self):
        for text, quote in (("Remove the\nMonday restriction on the report reminder.",
                             "Remove the\nMonday restriction on the report reminder."),
                            ("Monday restriction:\n- Remove the old rule.", "- Remove the old rule."),
                            ("Monday restriction:\n- Lift remaining restrictions.", "- Lift remaining restrictions."),
                            ("Monday restriction:\n- Remove only that restriction.", "- Remove only that restriction.")):
            with self.subTest(text=text):
                result, _, errors = self.compile(text, [operation(quote, "modify_request")],
                    [specification(target_id="pm_000007", permitted_days=["Monday"])],
                    scope="Thursday", **self.day_old())
                self.assertEqual(result[0][1]["days"], [])
                self.assertIn(quote, result[0][0].action)
                self.assertEqual([phase for phase, _ in errors], ["v2_day_guard"])

    def compile(self, message, operations, specifications=(), *, intentions=(),
                triggers=None, instructions=None, sources=("events", "clock", "email"), scope=""):
        provider, errors = Provider(operations, specifications), []
        original_intentions, original_triggers = copy.deepcopy(intentions), copy.deepcopy(triggers)
        result = compile_changes(provider, Instruction("current", message, scope), intentions,
                                 sources, triggers or {}, instructions or {},
                                 lambda phase, exc: errors.append((phase, str(exc))))
        self.assertEqual(intentions, original_intentions)
        self.assertEqual(triggers, original_triggers)
        return result, provider.calls, errors

    def old(self, request="Send the report no earlier than 09:15, only after email approval."):
        trigger = {"days": [], "clock_op": "not_before", "clock_time": "09:15"}
        old = Intention("pm_000007", request, request + PISEngine._slot_suffix(trigger),
                        ("clock", "email"), instruction_ids=("first",))
        return {"intentions": [old], "triggers": {old.id: trigger},
                "instructions": {"first": Instruction("first", request)}}

    def test_full_source_request_stored_without_action_summary_or_reviewer(self):
        quote = "When the station opens, remind me to collect the visitor pass for Alex."
        result, calls, errors = self.compile(quote, [operation(quote)], [specification()])
        change, trigger = result[0]
        self.assertEqual((change.action, change.condition, change.evidence_quote), (quote, quote, quote))
        self.assertEqual(change.op, "register")
        self.assertEqual(trigger, {"days": [], "clock_op": "none", "clock_time": ""})
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][1]["pending_update_targets"], [])
        self.assertEqual(errors, [])

    def test_facts_take_one_call_and_do_not_become_obligations(self):
        result, calls, errors = self.compile("The station will open tomorrow.", [])
        self.assertEqual(result, [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(errors, [])

    def test_new_addition_needs_no_old_target_and_does_not_replace_old(self):
        quote = "Also bring the parcel when the loading desk opens."
        result, calls, errors = self.compile(quote, [operation(quote)], [specification()], **self.old())
        self.assertEqual(result[0][0].op, "register")
        self.assertEqual(result[0][0].target_id, "")
        self.assertNotIn("pending_update_targets", calls[0][1])
        self.assertEqual(calls[1][1]["pending_update_targets"], [])
        self.assertEqual(errors, [])

    def test_new_addition_cannot_overwrite_even_with_valid_existing_id(self):
        quote = "Bring the parcel when the loading desk opens."
        result, _, errors = self.compile(quote, [operation(quote)],
            [specification(target_id="pm_000007")], **self.old())
        self.assertEqual(result, [])
        self.assertIn("must not replace", errors[0][1])

    def test_revision_preserves_identity_and_full_previous_prerequisite(self):
        quote = "Change the report's earliest sending time to 09:45 instead."
        old = self.old()
        result, calls, errors = self.compile(quote, [operation(quote, "modify_request")],
            [specification(target_id="pm_000007", watched_sources=["clock", "email"],
                           clock_relation="not_before", required_clock_time="09:45")], **old)
        change, trigger = result[0]
        self.assertEqual((change.op, change.target_id), ("revise", "pm_000007"))
        self.assertIn("only after email approval", change.condition)
        self.assertIn(old["intentions"][0].action, change.action)
        self.assertIn(quote, change.action)
        self.assertIn(quote, change.condition)
        self.assertNotIn("[Typed gates: not_before=09:15]", change.condition)
        self.assertEqual(trigger["clock_time"], "09:45")
        self.assertEqual(calls[1][1]["pending_update_targets"][0]["original_messages"][0]["id"], "first")
        self.assertEqual(errors, [])

    def test_unresolved_update_is_not_silently_registered(self):
        quote = "Move that reminder to 09:45."
        result, _, errors = self.compile(quote, [operation(quote, "modify_request")],
                                        [specification()], **self.old())
        self.assertEqual(result, [])
        self.assertIn("Unresolved update", errors[0][1])

    def test_cancel_only_changes_explicit_known_target(self):
        quote = "Cancel the report reminder."
        result, _, errors = self.compile(quote, [operation(quote, "cancel_request")],
            [specification(target_id="pm_000007", watched_sources=[])], **self.old())
        change, trigger = result[0]
        self.assertEqual((change.op, change.target_id, change.evidence_quote),
                         ("cancel", "pm_000007", quote))
        self.assertEqual(trigger["clock_time"], "09:15")
        self.assertEqual(errors, [])

    def test_full_instruction_supports_clock_omitted_from_selected_quote(self):
        quote = "send the memo only if approved."
        result, _, errors = self.compile("At 9:15, " + quote, [operation(quote)],
            [specification(clock_relation="at", required_clock_time="09:15", watched_sources=["email"])])
        self.assertEqual(result[0][1]["clock_time"], "09:15")
        self.assertEqual(result[0][0].sources, ("email", "clock"))
        self.assertEqual(errors, [])

    def test_unsupported_invented_clock_removed_without_losing_obligation(self):
        quote = "Take the tablet at breakfast and dinner."
        result, _, errors = self.compile(quote, [operation(quote)],
            [specification(clock_relation="at", required_clock_time="08:00")])
        self.assertEqual(result[0][1]["clock_op"], "none")
        self.assertEqual(result[0][0].condition, quote)
        self.assertEqual(errors[0][0], "v2_clock_guard")

    def test_unchanged_clock_on_other_revision_supported_by_original(self):
        quote = "Send the report to Morgan instead of Lee."
        result, _, errors = self.compile(quote, [operation(quote, "modify_request")],
            [specification(target_id="pm_000007", clock_relation="not_before",
                           required_clock_time="09:15")], **self.old())
        self.assertEqual(result[0][1]["clock_time"], "09:15")
        self.assertEqual(errors, [])

    def test_old_time_cannot_ground_gate_when_update_explicitly_mentions_new_time(self):
        quote = "Move the report's earliest time to 09:45 instead."
        result, _, errors = self.compile(quote, [operation(quote, "modify_request")],
            [specification(target_id="pm_000007", clock_relation="not_before",
                           required_clock_time="09:15")], **self.old())
        self.assertEqual(result[0][1]["clock_op"], "none")
        self.assertIn(quote, result[0][0].condition)
        self.assertEqual(errors[0][0], "v2_clock_guard")

    def test_multiple_independent_occasions_preserved_in_semantic_specification(self):
        quote = "Check the gauge at 10:00 and again at 18:00 every day."
        result, _, _ = self.compile(quote, [operation(quote)],
                                    [specification(watched_sources=["clock"], recurring=True)])
        self.assertEqual(result[0][1]["clock_op"], "none")
        self.assertEqual(result[0][0].condition, quote)
        self.assertTrue(result[0][0].repeat)

    def test_bad_source_quote_does_not_discard_valid_sibling(self):
        quote = "Collect the pass when the station opens."
        result, _, errors = self.compile(quote,
            [operation("a forged quote"), operation(quote)], [specification()])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0].action, quote)
        self.assertEqual(errors[0][0], "v2_source_quote")

    def test_bad_metadata_row_does_not_discard_valid_sibling(self):
        first, second = "Take the pass when ready.", "Bring the parcel when ready."
        result, _, errors = self.compile(first + " " + second,
            [operation(first), operation(second)],
            [specification(watched_sources=["invented"]), specification(operation_id="request_2")])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0].action, second)
        self.assertIn("Unknown observation source", errors[0][1])

    def test_schema_malformed_row_does_not_discard_valid_sibling(self):
        quote = "Collect the pass when the station opens."
        result, _, errors = self.compile(quote, [{"operation": "new_request"}, operation(quote)],
                                        [specification()])
        self.assertEqual(len(result), 1)
        self.assertEqual(errors[0][0], "v2_operations")

    def test_missing_or_duplicate_specification_logged(self):
        first, second = "Collect the pass when ready.", "Bring the parcel when ready."
        result, _, errors = self.compile(first + " " + second,
            [operation(first), operation(second)], [specification(), specification()])
        self.assertEqual(len(result), 1)
        self.assertTrue(any("unique known" in err for _, err in errors))
        self.assertTrue(any("Missing specification for request_2" in err for _, err in errors))

    def test_clock_and_weekday_validation_remains_structural(self):
        quote = "Collect the pass when the station opens."
        for updates in ({"clock_relation": "at", "required_clock_time": "29:15"},
                        {"permitted_days": ["Funday"]}):
            with self.subTest(updates=updates):
                result, _, errors = self.compile(quote, [operation(quote)], [specification(**updates)])
                self.assertEqual(result, [])
                self.assertTrue(errors)

    def test_schema_does_not_change_with_sources_ids_or_message_length(self):
        first = "Collect the pass when the station opens."
        second = "Send the financial report to the reviewer after approval, unless permission is revoked."
        _, calls1, _ = self.compile(first, [operation(first)], [specification()])
        _, calls2, _ = self.compile(second, [operation(second)],
                                    [specification(watched_sources=["sensor"])], sources=("sensor",))
        self.assertEqual([call[2] for call in calls1], [call[2] for call in calls2])

    def test_host_day_scope_is_typed_and_other_scope_preserved(self):
        quote = "On Thursday, collect the pass when ready."
        result, _, _ = self.compile(quote, [operation(quote)],
            [specification(permitted_days=["Thursday"])], scope="Monday")
        self.assertEqual(result[0][0].scope, "*")
        self.assertEqual(result[0][1]["days"], ["Thursday"])
        result, _, _ = self.compile(quote, [operation(quote)], [specification()], scope="project-red")
        self.assertEqual(result[0][0].scope, "project-red")

    def day_old(self, text="On Monday, send the report after approval.", days=("Monday",)):
        trigger = {"days": list(days), "clock_op": "none", "clock_time": ""}
        old = Intention("pm_000007", text, text + PISEngine._slot_suffix(trigger),
                        ("events",), scope="*", instruction_ids=("first",))
        return {"intentions": [old], "triggers": {old.id: trigger},
                "instructions": {"first": Instruction("first", text, "Monday")}}

    def test_unsupported_weekday_gate_removed_without_changing_original(self):
        quote = "When the timer reports 15 minutes elapsed, inspect the specimen."
        result, _, errors = self.compile(quote, [operation(quote)],
                                         [specification(permitted_days=list(DAYS[:5]))])
        change, trigger = result[0]
        self.assertEqual(trigger["days"], [])
        self.assertEqual((change.action, change.condition), (quote, quote))
        self.assertEqual([phase for phase, _ in errors], ["v2_day_guard"])

    def test_day_and_clock_guards_independently_remove_unsupported_hard_gates(self):
        quote = "When the elapsed-duration display reaches its limit, record the reading."
        result, _, errors = self.compile(quote, [operation(quote)],
            [specification(permitted_days=list(DAYS[:5]), clock_relation="at", required_clock_time="00:00")])
        self.assertEqual(result[0][1], {"days": [], "clock_op": "none", "clock_time": ""})
        self.assertEqual({phase for phase, _ in errors}, {"v2_day_guard", "v2_clock_guard"})

    def test_explicit_simple_literal_weekdays_and_standard_groups_supported(self):
        schedules = [("On Monday", ["Monday"]), ("On mondays and thursdays", ["Monday", "Thursday"]),
                     ("On weekdays", list(DAYS[:5])), ("Each weekend", list(DAYS[5:])),
                     ("Every day", list(DAYS)), ("Daily", list(DAYS))]
        for phrase, days in schedules:
            with self.subTest(phrase=phrase):
                quote = phrase + ", inspect the specimen after approval."
                result, _, errors = self.compile(quote, [operation(quote)],
                                                 [specification(permitted_days=days)])
                self.assertEqual(result[0][1]["days"], days)
                self.assertEqual(errors, [])

    def test_explicit_schedule_cannot_be_narrowed_to_subset(self):
        for phrase, days in [("Daily", list(DAYS[:5])), ("On weekends", ["Saturday"]),
                             ("On Monday and Thursday", ["Monday"])]:
            with self.subTest(phrase=phrase):
                quote = phrase + ", inspect the specimen after approval."
                result, _, errors = self.compile(quote, [operation(quote)],
                                                 [specification(permitted_days=days)])
                self.assertEqual(result[0][1]["days"], [])
                self.assertEqual(errors[0][0], "v2_day_guard")

    def test_host_scope_supports_only_corresponding_day_when_no_calendar_text(self):
        quote = "Inspect the specimen after approval."
        result, _, errors = self.compile(quote, [operation(quote)],
            [specification(permitted_days=["Tuesday"])], scope="Tuesday")
        self.assertEqual(result[0][1]["days"], ["Tuesday"])
        self.assertEqual(errors, [])
        for scope in ("Monday", "*", "project-red", ""):
            with self.subTest(scope=scope):
                result, _, errors = self.compile(quote, [operation(quote)],
                    [specification(permitted_days=["Tuesday"])], scope=scope)
                self.assertEqual(result[0][1]["days"], [])
                self.assertEqual(errors[0][0], "v2_day_guard")

    def test_shared_original_schedule_supports_short_quote(self):
        quote = "Inspect the specimen after approval."
        result, _, errors = self.compile("Thursday plan:\n" + quote, [operation(quote)],
                                         [specification(permitted_days=["Thursday"])])
        self.assertEqual(result[0][1]["days"], ["Thursday"])
        self.assertEqual(errors, [])

    def test_selected_request_days_not_confused_with_other_request_days(self):
        quote = "On Tuesday, inspect the specimen after approval."
        message = "On Monday, file the report.\n" + quote
        result, _, errors = self.compile(message, [operation(quote)],
                                         [specification(permitted_days=["Tuesday"])])
        self.assertEqual(result[0][1]["days"], ["Tuesday"])
        self.assertEqual(errors, [])

    def test_ambiguous_schedules_remain_semantic_not_restrictive_host_day_gates(self):
        clauses = ["Except Monday", "Not on Monday", "After Monday", "Monday through Friday",
                   "Monday-Friday", "In two days", "Tomorrow", "On any day"]
        for clause in clauses:
            with self.subTest(clause=clause):
                quote = clause + ", inspect the specimen after approval."
                result, _, errors = self.compile(quote, [operation(quote)],
                    [specification(permitted_days=["Monday"])], scope="Monday")
                self.assertEqual(result[0][1]["days"], [])
                self.assertEqual(result[0][0].condition, quote)
                self.assertEqual(errors[0][0], "v2_day_guard")

    def test_non_calendar_update_retains_old_schedule_not_new_host_day(self):
        quote = "Send the report to Morgan instead."
        for proposed, expected in [(["Monday"], ["Monday"]), (["Thursday"], [])]:
            with self.subTest(proposed=proposed):
                result, _, errors = self.compile(quote, [operation(quote, "modify_request")],
                    [specification(target_id="pm_000007", permitted_days=proposed)],
                    scope="Thursday", **self.day_old())
                self.assertEqual(result[0][1]["days"], expected)
                self.assertEqual(bool(errors), not bool(expected))

    def test_explicit_calendar_revision_supersedes_old_day_and_scope(self):
        quote = "Move the report reminder to Thursday instead."
        for proposed, expected in [(["Thursday"], ["Thursday"]), (["Monday"], [])]:
            with self.subTest(proposed=proposed):
                result, _, _ = self.compile(quote, [operation(quote, "modify_request")],
                    [specification(target_id="pm_000007", permitted_days=proposed)],
                    scope="Monday", **self.day_old())
                self.assertEqual(result[0][1]["days"], expected)
                self.assertEqual(result[0][0].target_id, "pm_000007")

    def test_ambiguous_calendar_revision_cannot_revive_old_supported_day(self):
        quote = "Move the report reminder to any day after approval."
        result, _, errors = self.compile(quote, [operation(quote, "modify_request")],
            [specification(target_id="pm_000007", permitted_days=["Monday"])],
            scope="Monday", **self.day_old())
        self.assertEqual(result[0][1]["days"], [])
        self.assertIn(quote, result[0][0].condition)
        self.assertEqual(errors[0][0], "v2_day_guard")

    def test_explicit_calendar_restriction_removal_does_not_retain_named_old_days(self):
        for quote in ["Remove the Monday restriction from the report reminder.",
                      "No longer restrict the report reminder to Monday.",
                      "Drop the weekday restriction on this reminder."]:
            with self.subTest(quote=quote):
                result, _, errors = self.compile(quote, [operation(quote, "modify_request")],
                    [specification(target_id="pm_000007", permitted_days=["Monday"])],
                    scope="Monday", **self.day_old())
                self.assertEqual(result[0][1]["days"], [])
                self.assertEqual(errors[0][0], "v2_day_guard")

    def test_chronological_schedule_history_not_union_of_old_and_new_days(self):
        old = self.day_old()
        previous = old["intentions"][0]
        old["intentions"] = [Intention(previous.id, previous.action, previous.condition,
                                       previous.sources, previous.scope,
                                       instruction_ids=("first", "second"))]
        old["instructions"]["second"] = Instruction("second", "Use Thursday instead.", "Monday")
        old["triggers"][previous.id]["days"] = ["Thursday"]
        quote = "Send it to Morgan instead."
        for proposed, expected in [(["Thursday"], ["Thursday"]), (["Monday"], [])]:
            with self.subTest(proposed=proposed):
                result, _, _ = self.compile(quote, [operation(quote, "modify_request")],
                    [specification(target_id=previous.id, permitted_days=proposed)],
                    scope="Monday", **old)
                self.assertEqual(result[0][1]["days"], expected)


if __name__ == "__main__":
    unittest.main()
