"""Local safety and byte-for-byte round-trip tests, without network calls."""

from pathlib import Path
import sys
import tempfile
import unittest

import restore_results as restore

HARNESS = Path(__file__).resolve().parents[1] / "prospective-memory/harness"
sys.path.insert(0, str(HARNESS))
from package_github_results import build_group


class RestoreTests(unittest.TestCase):
    def test_traversal_and_symlinks_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in ("../escape", "/absolute", "another/path"):
                with self.assertRaises(ValueError):
                    restore.target_path(root, path)
            (root / "prospective-memory").symlink_to("/etc", target_is_directory=True)
            with self.assertRaises(ValueError):
                restore.target_path(root, "prospective-memory/passwd")

    def test_round_trip_preserves_bytes_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            path = parent / "prospective-memory/results/example.jsonl"
            path.parent.mkdir(parents=True)
            payload = b'{"example":true}\r\n'
            path.write_bytes(payload)
            st = path.stat()
            records = [{"path": str(path.relative_to(parent)), "bytes": st.st_size,
                        "mtime_ns": st.st_mtime_ns, "category": "raw_results_release"}]
            assets = parent / "assets"
            assets.mkdir()
            group = build_group(parent, assets, "test", records, set())
            root = parent / "restored"
            root.mkdir()
            parts = [assets / p["name"] for p in group["parts"]]
            self.assertEqual(restore.extract(root, group, parts), 1)
            restored = root / records[0]["path"]
            self.assertEqual(restored.read_bytes(), payload)
            self.assertEqual(restore.extract(root, group, parts), 1)
            restored.write_bytes(b"different result")
            with self.assertRaisesRegex(ValueError, "refusing overwrite"):
                restore.extract(root, group, parts)
            self.assertEqual(restored.read_bytes(), b"different result")


if __name__ == "__main__":
    unittest.main()
