"""Boolean launch flags and local diagnostic transport boundaries."""

from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from run import ROOT, local_url, pm_bench
from helper_probe import probe
from query_uptake_probe import probe as uptake_probe
from registration_probe import probe as registration_probe


class LauncherTests(unittest.TestCase):
    def test_boolean_zero_and_false_do_not_enable_options(self):
        script = ROOT / "experiments/rgpm/launcher_options.sh"
        for value, expected in (("0", "0"), ("", "0"), ("false", "0"), ("no", "0"),
                                ("1", "1"), ("true", "1"), ("YES", "1")):
            result = subprocess.run(["bash", "-c", 'source "$1"; rgpm_bool "$2"', "bash", str(script), value],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), expected)
        result = subprocess.run(["bash", "-c", 'source "$1"; rgpm_bool "$2"', "bash", str(script), "maybe"],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)

    def test_helper_probe_rejects_hosted_before_client_or_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "rejected"
            args = SimpleNamespace(output=output, model="local", base_url="https://example.com/v1")
            with patch.object(pm_bench, "build_llm_client", side_effect=AssertionError("Hosted forbidden")) as build:
                with self.assertRaises(ValueError):
                    probe(args)
                build.assert_not_called()
            self.assertFalse(output.exists())

    def test_local_urls_reject_embedded_credentials_or_unsupported_scheme(self):
        for url in ("http://key@localhost/v1", "http://localhost/v1?key=value",
                    "ftp://localhost/v1", "http://remote.example/v1", "http://localhost/v1#secret"):
            with self.assertRaises(ValueError):
                local_url(url)
        self.assertEqual(local_url("http://127.0.0.1:30003/v1"), "http://127.0.0.1:30003/v1")

    def test_uptake_probe_rejects_hosted_before_reading_prompts_or_building_client(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "rejected"
            args = SimpleNamespace(output=output, model="local", base_url="https://example.com/v1")
            with patch.object(pm_bench, "build_llm_client", side_effect=AssertionError("Hosted forbidden")) as build:
                with self.assertRaises(ValueError):
                    uptake_probe(args)
                build.assert_not_called()
            self.assertFalse(output.exists())

    def test_registration_probe_rejects_hosted_before_artifacts_or_client(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "rejected"
            args = SimpleNamespace(output=output, model="local", base_url="https://example.com/v1")
            with patch.object(pm_bench, "build_llm_client", side_effect=AssertionError("Hosted forbidden")) as build:
                with self.assertRaises(ValueError):
                    registration_probe(args)
                build.assert_not_called()
            self.assertFalse(output.exists())
