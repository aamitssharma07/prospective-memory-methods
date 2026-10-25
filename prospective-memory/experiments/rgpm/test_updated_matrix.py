"""Offline checks for the finalized non-GPT, non-70B-class sweep."""

import unittest

from submit_updated_matrix import ACTORS, plan


class MatrixTests(unittest.TestCase):
    def test_four_helpers_eight_actors_and_method_flags(self):
        helpers = [f"Qwen/Qwen3-{size}B" for size in ("1.7", "4", "8", "32")]
        result = plan(helpers, "experiments/rgpm/runs/test")
        self.assertEqual(len(result["pairs"]), 32)
        self.assertEqual(len({(r["actor"], r["helper"]) for r in result["pairs"]}), 32)
        for row in result["pairs"]:
            self.assertEqual(row["gpus"], 1 if row["actor"] == row["helper"] else 2)
            for flag in ("SOURCE_ROUTING", "REGISTRATION_GROUNDING", "SCOPE_GROUNDING", "BOUNDED_PRIORITY"):
                self.assertEqual(row["environment"][flag], "1")
            self.assertEqual(row["environment"]["VERIFY_ACTIONS"], "0")
        self.assertFalse(any("70B" in a or "72B" in a or "gpt" in a.lower() for a in ACTORS))

    def test_duplicate_or_unknown_helpers_rejected(self):
        with self.assertRaises(ValueError):
            plan(["Qwen/Qwen3-8B"] * 4, "test")
        with self.assertRaises(ValueError):
            plan(["unknown"] * 4, "test")

    def test_report_only_is_explicit_and_preserves_method(self):
        helpers = [f"Qwen/Qwen3-{size}B" for size in ("1.7", "4", "8", "32")]
        strict = plan(helpers, "test")
        report = plan(helpers, "test", "report_only")
        for before, after in zip(strict["pairs"], report["pairs"]):
            original = dict(before["environment"])
            original["SMOKE_ADMISSION_POLICY"] = "report_only"
            self.assertEqual(original, after["environment"])
