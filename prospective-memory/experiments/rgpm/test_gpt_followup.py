"""Offline checks for the deferred, explicitly budgeted three-pair GPT task."""

from pathlib import Path
import subprocess
import unittest

from prepare_gpt_followup import ROOT, plan


class GPTFollowupTests(unittest.TestCase):
    def test_exact_missing_helpers_no_duplicate_32b(self):
        result = plan()
        self.assertEqual([j["helper"] for j in result["jobs"]],
                         ["Qwen/Qwen3-1.7B", "Qwen/Qwen3-4B", "Qwen/Qwen3-8B"])
        self.assertEqual(result["existing_result_to_reuse"]["job_id"], "1537307")
        for job in result["jobs"]:
            self.assertEqual(job["status"], "prepared_not_submitted")
            env = job["environment"]
            self.assertEqual(env["ACTOR_BACKEND"], "openai_chat")
            self.assertEqual(env["ACTOR_MODEL"], "gpt-5.4")
            self.assertEqual(env["SMOKE_ADMISSION_POLICY"], "report_only")
            self.assertEqual(env["RUN_HELPER_PROBES"], "0")
            self.assertEqual(env["MAX_ACTOR_CALLS"], "300")
            self.assertEqual(env["MAX_ACTOR_TOKENS"], "4000000")
            self.assertTrue(all(env[k] == "1" for k in (
                "SOURCE_ROUTING", "SCOPE_GROUNDING", "BOUNDED_PRIORITY", "REGISTRATION_GROUNDING")))
            self.assertFalse(any("API_KEY" in arg for arg in job["submission_argv_without_dependency"]))
        self.assertEqual(result["combined_proposed_caps"], {"actor_calls": 972, "actor_tokens": 13500000})

    def test_launcher_syntax_and_explicit_policy_options(self):
        launcher = ROOT / "experiments/rgpm/run_gpt_actor.sbatch"
        self.assertEqual(subprocess.run(["bash", "-n", str(launcher)], capture_output=True).returncode, 0)
        text = launcher.read_text()
        self.assertIn('${RUN_HELPER_PROBES:-1}', text)
        self.assertIn('${SMOKE_ADMISSION_POLICY:-strict}', text)
        self.assertIn('--admission-policy "$SMOKE_ADMISSION_POLICY"', text)
