"""Read-only and no-network validation for the GitHub team context export."""

from collections import Counter
import contextlib
import io
import json
from pathlib import Path
import re
import tempfile
import unittest

import export_team_context as context


class TeamContextTests(unittest.TestCase):
    def test_markdown_score_uses_integer_counts_not_rounded_percentage(self):
        text = "| Set TP | 47 |\n| Set FP | 155 |\n| Set FN | 34 |\n| Set F1 | 33.2% |\n"
        result = context.markdown_metrics(text)
        self.assertAlmostEqual(result["f1"], 94 / 283)
        with self.assertRaises(ValueError):
            context.markdown_metrics(text.replace("33.2%", "80.0%"))
        with self.assertRaises(ValueError):
            context.markdown_metrics(text + "| Set TP | 48 |\n")

    def test_partial_runs_are_not_validated_as_results(self):
        for status, steps in [("interrupted", 73), ("complete", 79), ("serving_probe_failed", 0)]:
            with self.assertRaises(ValueError):
                context.validate_complete({"status": status, "completed_steps": steps})
        self.assertEqual(context.percent({"status": "interrupted", "f1": 0.99}), "N/A")
        self.assertEqual(context.percent({"status": "complete", "f1": 0.0}), "0.00")

    def test_consistency_selection_is_not_best_f1_or_success_only(self):
        original = {"actor": "mistralai/Ministral-3-3B-Instruct-2512", "helper": context.HELPERS[0],
                    "cohort": "original_v15_32", "status": "complete", "f1": 0.9}
        corrected = {**original, "actor": original["actor"] + "-BF16", "cohort": "consistency_v15", "f1": 0.4}
        key = ("Ministral-3-3B", context.HELPERS[0])
        self.assertEqual(context.preferred_rows([original, corrected])[key], corrected)
        failed = {**corrected, "status": "serving_probe_failed", "f1": None}
        self.assertEqual(context.preferred_rows([original, failed])[key], failed)

    def test_snapshot_matrix_counts_and_all_reported_scores(self):
        path = context.ROOT / "docs/experiments/results/snapshot.json"
        snapshot = context.read(path)
        self.assertEqual(len(snapshot["experiment1"]), 44)
        self.assertEqual(len(snapshot["experiment2"]), 44)
        self.assertEqual(Counter(r["cohort"] for r in snapshot["experiment3"]),
                         Counter({"original_v15_32": 32, "consistency_v15": 11, "gpt_v15": 4}))
        for key in ("experiment1", "experiment2", "experiment3"):
            for row in snapshot[key]:
                self.assertFalse(Path(row["source"]).is_absolute())
                if row["status"] == "complete":
                    context.validate_complete(row)
                    self.assertAlmostEqual(row["f1"], context.score_metrics(row["tp"], row["fp"], row["fn"])["f1"])
                else:
                    self.assertIsNone(row["f1"])
        self.assertEqual((path.parent / "RESULTS.md").read_text(), context.render(snapshot))

    def test_context_links_resolve_without_accessing_raw_storage(self):
        paths = [context.ROOT / "TEAM_CONTEXT.md", context.ROOT / "docs/GITHUB_HANDOFF.md",
                 context.ROOT / "docs/experiments/README.md", context.ROOT / "docs/experiments/results/RESULTS.md"]
        paths += list((context.ROOT / "docs/experiments").glob("*_context.md"))
        for path in paths:
            for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", path.read_text()):
                if "://" in target or target.startswith("#"):
                    continue
                relative = target.split("#", 1)[0]
                self.assertTrue((path.parent / relative).exists(), f"Broken link in {path}: {target}")

    def test_snapshot_is_small_and_has_no_credential_like_values(self):
        directory = context.ROOT / "docs/experiments/results"
        paths = list(directory.iterdir())
        self.assertLess(sum(p.stat().st_size for p in paths), 1000000)
        for path in paths:
            self.assertIsNone(re.search(r"(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9_-]{20,})", path.read_text()))

    @unittest.skipUnless((context.ROOT / "PMBench/runs/core-four").is_dir()
                         and (context.ROOT.parent / "prospective-memory-reaearch/data/PMBench/runs").is_dir(),
                         "Original research artifacts are not mounted in this checkout")
    def test_export_existing_artifacts_without_inference(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            output = Path(directory)
            context.export(context.ROOT, context.ROOT.parent / "prospective-memory-reaearch", output, "2026-10-25")
            snapshot = context.read(output / "snapshot.json")
            self.assertEqual(len(snapshot["experiment1"]), 44)
            self.assertEqual(len(snapshot["experiment2"]), 44)
            for key in ("experiment1", "experiment2", "experiment3"):
                for row in snapshot[key]:
                    if row["status"] == "complete":
                        name = row.get("metrics_source", row["source"])
                        expected = row.get("metrics_source_sha256", row["source_sha256"] if "source_sha256" in row else None)
                        self.assertEqual(context.sha(context.ROOT / name), expected)


if __name__ == "__main__":
    unittest.main()
