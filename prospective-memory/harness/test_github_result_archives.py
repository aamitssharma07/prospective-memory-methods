"""Offline round-trip and fail-closed tests for complete result publication."""

import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from package_github_results import SplitWriter, ConcatReader, ScanningReader, build_group, group_name, safe_path, verify_archive
from prepare_github_publication import secret_scanner


class ArchiveTests(unittest.TestCase):
    def test_split_writer_exact_boundary_and_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            writer = SplitWriter(root, "test", limit=4)
            writer.write(b"abcd")
            writer.write(b"efghij")
            writer.close()
            self.assertEqual([p["bytes"] for p in writer.parts], [4, 4, 2])
            reader = ConcatReader([root / p["name"] for p in writer.parts])
            try:
                self.assertEqual(reader.read(10), b"abcdefghij")
                self.assertEqual(reader.read(1), b"")
            finally:
                reader.close()
            for part in writer.parts:
                self.assertEqual(hashlib.sha256((root / part["name"]).read_bytes()).hexdigest(), part["sha256"])

    def test_secret_cannot_cross_read_boundary_undetected(self):
        secret = b"known-" + b"private-test-value"
        reader = ScanningReader(io.BytesIO(secret), secret_scanner({secret}), 1024, lambda n: None)
        with self.assertRaisesRegex(ValueError, "Credential-like"):
            while reader.read(4):
                pass

    def test_path_traversal_and_external_symlink_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("../outside", "/etc/passwd", "other/file"):
                with self.assertRaises(ValueError):
                    safe_path(root, name)
            work = root / "prospective-memory"
            work.mkdir()
            (work / "outside").symlink_to("/etc/passwd")
            with self.assertRaises(ValueError):
                safe_path(root, "prospective-memory/outside")

    def fixture(self, parent, payload=b"{\"example\":true}\n"):
        path = parent / "prospective-memory/experiments/rgpm/runs/candidate/pair/raw.jsonl"
        path.parent.mkdir(parents=True)
        path.write_bytes(payload)
        st = path.stat()
        return path, {"path": str(path.relative_to(parent)), "bytes": st.st_size,
                      "mtime_ns": st.st_mtime_ns, "category": "raw_results_release"}

    def test_verified_round_trip_and_resumable_group(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, record = self.fixture(root, os.urandom(8192))
            assets = root / "assets"
            assets.mkdir()
            result = build_group(root, assets, "example", [record], set())
            self.assertEqual(result["status"], "verified")
            self.assertEqual(result["files_verified"], 1)
            self.assertEqual(result["files"][0]["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(verify_archive(assets, result["parts"], result["files"]), 1)
            self.assertEqual(build_group(root, assets, "example", [record], set()), result)
            with self.assertRaisesRegex(ValueError, "credentials changed"):
                build_group(root, assets, "example", [record], {b"new-known-value"})

    def test_changed_file_cannot_reuse_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, record = self.fixture(root)
            assets = root / "assets"
            assets.mkdir()
            build_group(root, assets, "example", [record], set())
            source.write_bytes(b"changed contents")
            with self.assertRaisesRegex(ValueError, "changed"):
                build_group(root, assets, "example", [record], set())

    def test_secret_found_no_verified_manifest_or_upload_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, record = self.fixture(root, b"key=" + b"sk-" + b"a" * 40)
            assets = root / "assets"
            assets.mkdir()
            with self.assertRaisesRegex(ValueError, "Credential-like"):
                build_group(root, assets, "example", [record], set())
            self.assertFalse((assets / "example.manifest.json").exists())
            self.assertEqual(json.loads((assets / "example.progress.json").read_text())["status"], "failed_upload_blocked")

    def test_group_includes_workspace_and_retains_archived_attempts(self):
        before = {"path": "prospective-memory/experiments/rgpm/runs/a/pair/file"}
        after = {"path": "prospective-memory/experiments/rgpm/runs/b/pair/file"}
        self.assertNotEqual(group_name(before), group_name(after))
        self.assertTrue(group_name({"path": "prospective-memory/experiments/rgpm/runs_archived_20261007/file"}))


if __name__ == "__main__":
    unittest.main()
