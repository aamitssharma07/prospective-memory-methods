"""Isolated generic removal-clause tests; active calendar guards are untouched."""

import re
import unittest

from prospective_memory.method.calendar_guard import has_calendar_removal_clause
from prospective_memory.baselines.pis_registration import _CALENDAR_WORDS, _day_support


class CalendarRemovalClauseTests(unittest.TestCase):
    def flagged(self, text):
        return has_calendar_removal_clause(text, _CALENDAR_WORDS)

    def test_shared_weekday_header_does_not_attach_to_physical_sibling_actions(self):
        for action in ("Drop the spare cable in the cabinet", "Clear the packing bench",
                       "Remove the empty crate", "Lift the storage lid", "Relax the clamp", "Place the cable"):
            with self.subTest(action=action):
                text = ("Thursday workshop plan:\n"
                        "- Record the tank reading when the blue indicator lights.\n"
                        f"- {action} when the trolley arrives.")
                self.assertFalse(self.flagged(text))

    def test_markdown_heading_numbered_lettered_and_symbol_bullets(self):
        for heading in ("# Thursday workshop plan", "### Thursday workshop plan", "Thursday workshop plan:"):
            for marker in ("-", "*", "+", "1.", "2)", "A.", "b)"):
                with self.subTest(heading=heading, marker=marker):
                    text = f"{heading}\n{marker} Drop the spare cable in the cabinet.\n{marker} Record the tank reading."
                    self.assertFalse(self.flagged(text))

    def test_calendar_in_separate_sibling_does_not_contaminate_physical_action(self):
        for text in ("- On Monday, record the reading.\n- Clear the packing bench.",
                     "- Clear the packing bench.\n- On Monday, record the reading.",
                     "- Drop the cable\n- Record the reading on Monday."):
            with self.subTest(text=text):
                self.assertFalse(self.flagged(text))

    def test_true_calendar_restriction_removal_is_ambiguous(self):
        for verb in ("Remove", "Drop", "Lift", "Relax", "Clear"):
            for calendar in ("Monday", "weekday", "weekend", "daily", "day"):
                with self.subTest(verb=verb, calendar=calendar):
                    self.assertTrue(self.flagged(f"{verb} the {calendar} restriction on this reminder."))

    def test_wrapped_removal_does_not_turn_into_positive_weekday_support(self):
        for text in ("Remove the\nMonday restriction on this reminder.",
                     "Remove the\n\nMonday restriction on this reminder.",
                     "- Remove the\n  Monday restriction on this reminder.",
                     "- Remove the\nMonday restriction on this reminder.",
                     "Remove\nthe Monday restriction.",
                     "Remove the\nMonday restriction:",
                     "Remove the restriction:\n- Monday only.",
                     "Remove the\n- Monday restriction."):
            with self.subTest(text=text):
                self.assertTrue(self.flagged(text))

    def test_nested_calendar_attachment_remains_conservative(self):
        for text in ("- Remove the restriction:\n  - Monday only.",
                     "- Clear the schedule\n  Monday constraint remains unclear.",
                     "- Drop the restriction.\n  - Monday."):
            with self.subTest(text=text):
                self.assertTrue(self.flagged(text))

    def test_shared_header_does_not_hide_actual_removal_in_one_bullet(self):
        text = ("Thursday workshop plan:\n"
                "- Record the tank reading when the blue indicator lights.\n"
                "- Remove the Monday restriction from the report reminder.")
        self.assertTrue(self.flagged(text))

    def test_same_clause_unclear_attachment_is_not_semantically_guessed(self):
        for text in ("On Thursday, remove the empty crate when the trolley arrives.",
                     "Thursday plan: drop the spare cable in the cabinet.",
                     "Remove the restriction, Monday perhaps.",
                     "Drop the cable; the Monday requirement is unclear.",
                     "Remove it.\nMonday may apply."):
            with self.subTest(text=text):
                self.assertTrue(self.flagged(text))

    def test_heading_and_plain_continuation_remain_one_unclear_clause(self):
        for text in ("Monday restriction:\nRemove it.",
                     "# Monday restriction\nRemove it.",
                     "Monday restriction:\n\nRemove the old rule.",
                     "Thursday workshop plan:\nDrop the cable when the trolley arrives."):
            with self.subTest(text=text):
                self.assertTrue(self.flagged(text))

    def test_bullet_marker_does_not_resolve_anaphoric_or_incomplete_removal(self):
        for action in ("Remove it.", "Drop that.", "Clear the restriction.",
                       "Lift the rule.", "Relax the requirement.", "Remove the",
                       "Remove.", "Remove the.", "Drop!", "Clear the?"):
            with self.subTest(action=action):
                self.assertTrue(self.flagged("Monday restriction:\n- " + action))
        self.assertTrue(self.flagged("Monday plan:\n- Drop the restriction.\n- Record the reading."))
        self.assertTrue(self.flagged("- Only Monday is allowed.\n- Drop that rule."))
        self.assertTrue(self.flagged("- Drop that rule.\n- Only Monday is allowed."))
        self.assertFalse(self.flagged("Remove it."))  # No calendar support exists to license a gate.

    def test_modified_constraint_targets_keep_cross_unit_attachment_uncertain(self):
        for action in ("Remove the old rule.", "Lift remaining restrictions.",
                       "Remove only that restriction."):
            with self.subTest(action=action):
                self.assertTrue(self.flagged("Monday restriction:\n- " + action))
                self.assertTrue(self.flagged("- Only Monday is allowed.\n- " + action))
        # The safeguard does not claim that the finite noun set proves a calendar
        # relationship; it conservatively retains ambiguity when context exists.
        self.assertTrue(self.flagged("Monday plan:\n- Clear the bench beside the posted rules."))
        self.assertFalse(self.flagged("Monday plan:\n- Clear the bench beside the posted notices."))

    def test_wrapped_physical_continuation_remains_separate_from_heading(self):
        text = "Thursday workshop plan:\n- Drop the\n  spare cable in the cabinet.\n- Record the reading."
        self.assertFalse(self.flagged(text))

    def test_nonremoval_calendar_protections_remain_the_existing_callers_job(self):
        # False here is NOT permission to retain a day; the unchanged guard still
        # rejects every existing negative, relative and range-style construction.
        for text in ("No longer restrict the reminder to Monday.", "Not on Monday", "Except Monday",
                     "Monday-Friday", "After Monday", "In two days", "Tomorrow", "On any day",
                     "Do not send it today.", "Never on Monday", "Monday through Friday"):
            with self.subTest(text=text):
                self.assertFalse(self.flagged(text))
                self.assertEqual(_day_support(text), (True, None))

    def test_case_insensitive_whole_words_and_caller_owned_calendar_vocabulary(self):
        self.assertTrue(self.flagged("REMOVE THE monday RESTRICTION"))
        self.assertFalse(self.flagged("The dropdown shows Monday."))
        self.assertFalse(self.flagged("Clear the bench."))
        self.assertFalse(self.flagged("Monday only."))
        self.assertFalse(self.flagged(""))
        self.assertTrue(has_calendar_removal_clause("Drop the term-time restriction.", re.compile("term-time")))
        self.assertFalse(has_calendar_removal_clause("Drop the Monday restriction.", re.compile("term-time")))

    def test_invalid_inputs_rejected_without_inference_or_runtime_mutation(self):
        for text, pattern in ((None, _CALENDAR_WORDS), ([], _CALENDAR_WORDS), ("Monday", "Monday")):
            with self.subTest(text=text, pattern=pattern), self.assertRaises(TypeError):
                has_calendar_removal_clause(text, pattern)


if __name__ == "__main__":
    unittest.main()
