"""Safety checks for metadata-only full-publication inventory."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from prepare_github_publication import category, exclusion, inventory, secret_scanner, check_source, stage_repository


class PublicationTests(unittest.TestCase):
    def test_credentials_and_history_excluded(self):
        for name in (".env", ".env.local", "id_rsa", "credentials", "test.pem"):
            self.assertIsNotNone(exclusion(Path(name)))
        self.assertIsNotNone(exclusion(Path(".git"), directory=True))
        self.assertIsNotNone(exclusion(Path(".venv-sglang"), directory=True))
        self.assertIsNone(exclusion(Path(".env.example")))

    def test_all_result_generations_retained(self):
        for name in ("runs", "runs_archived_20261007", "jobs", "smoke_artifacts", "legacy_outputs_archived_20261001"):
            self.assertEqual(category(Path("experiments/rgpm") / name / "raw.jsonl", 123), "raw_results_release")
        self.assertEqual(category(Path("data/PMBench/runs/trajectory.jsonl"), 123), "raw_results_release")
        self.assertEqual(category(Path("docs/experiments/results/snapshot.json"), 123), "repository")

    def test_large_file_is_release_asset_not_normal_git(self):
        self.assertEqual(category(Path("data/large.json"), 100 * 1024 * 1024), "large_asset_release")

    def test_inventory_does_not_read_file_contents_or_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "workspace"
            root.mkdir()
            (root / ".env").write_text("SECRET=do-not-publish\n")
            (root / "results.txt").write_text("test")
            (root / "external").symlink_to("/etc", target_is_directory=True)
            result = inventory([root])
            self.assertEqual([r["path"] for r in result["files"]], ["workspace/results.txt"])
            self.assertEqual(result["excluded"][0]["reason"], "environment_file")
            self.assertEqual(len(result["manual_review"]), 1)
            self.assertEqual((root / ".env").read_text(), "SECRET=do-not-publish\n")

    def test_source_scan_blocks_known_values_and_token_formats(self):
        scanner = secret_scanner({b"known" + b"-test-credential-value"})
        with self.assertRaisesRegex(ValueError, "Credential-like"):
            check_source(Path("code.py"), b"key=" + b"known" + b"-test-credential-value", scanner)
        with self.assertRaisesRegex(ValueError, "Credential-like"):
            check_source(Path("code.py"), b"key=" + b"sk-" + b"a" * 40, scanner)
        check_source(Path("code.py"), b"key = os.environ.get('OPENAI_API_KEY')", scanner)

    def test_source_zip_cannot_hide_environment_file(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "data.zip"
            with zipfile.ZipFile(archive, "w") as stream:
                stream.writestr("nested/.env", "anything")
            with self.assertRaisesRegex(ValueError, "Nested credential"):
                check_source(archive, archive.read_bytes(), secret_scanner(set()))

    def test_task_labels_are_not_generic_api_keys_but_known_keys_still_block(self):
        scanner = secret_scanner(set())
        label = b"digital_procedural_" + b"task-" + b"generated_identifier_with_underscores"
        self.assertIsNone(scanner.search(label))
        key = b"sk-" + b"a" * 40
        self.assertIsNotNone(scanner.search(b"Bearer " + key))
        self.assertIsNotNone(secret_scanner({key}).search(b"attachedprefix" + key))

    def test_clean_source_stage_keeps_raw_results_pending_and_leaves_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            roots = [parent / "prospective-memory", parent / "prospective-memory-reaearch"]
            for root in roots:
                root.mkdir()
                (root / "code.py").write_text("print('example')\n")
                (root / ".env").write_text("OPENAI_API_KEY=" + "sk-" + "a" * 40 + "\n")
                (root / ".git").mkdir()
                (root / ".git/private_history").write_text("do not export")
            raw = roots[0] / "experiments/rgpm/runs/run"
            raw.mkdir(parents=True)
            (raw / "response.jsonl").write_text("{}\n")
            output = parent / "publication"
            with patch("prepare_github_publication.source_revision", return_value={"head": "test"}):
                state = stage_repository(inventory(roots), roots, output,
                                         "https://github.com/example/research.git")
            self.assertEqual(state["source_files_scanned"], 2)
            self.assertFalse(state["raw_results_uploaded"])
            self.assertFalse(state["raw_result_payloads_scanned"])
            self.assertTrue((output / "prospective-memory/code.py").is_file())
            self.assertFalse((output / "prospective-memory/.env").exists())
            self.assertFalse((output / "prospective-memory/.git").exists())
            self.assertFalse((output / "prospective-memory/experiments/rgpm/runs").exists())
            self.assertTrue((raw / "response.jsonl").is_file())
            self.assertTrue((roots[0] / ".env").is_file())

    def test_credential_embedded_repository_url_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "credential-free"):
            stage_repository({}, [], Path("unused"), "https://secret@github.com/example/repo.git")


if __name__ == "__main__":
    unittest.main()
