"""No-network checks for upload admission and remote asset integrity."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import upload_release as upload


class UploadTests(unittest.TestCase):
    def test_remote_size_and_hash_must_match(self):
        expected = {"name": "asset", "bytes": 10, "sha256": "abc"}
        remote = {"name": "asset", "size": 10, "digest": "sha256:abc"}
        self.assertTrue(upload.match_remote(remote, expected))
        with self.assertRaises(ValueError):
            upload.match_remote({**remote, "size": 11}, expected)
        with self.assertRaises(ValueError):
            upload.match_remote({**remote, "digest": "sha256:wrong"}, expected)
        self.assertFalse(upload.match_remote({**remote, "digest": None}, expected))

    def test_failed_or_partial_packaging_never_calls_github(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "build_status.json").write_text(json.dumps({"status": "building"}))
            with patch.object(upload, "gh") as gh:
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    upload.publish(root, "aamitssharma07/prospective-memory-methods", "research-snapshot-2026-10-25", "commit")
                gh.assert_not_called()

    def test_asset_listing_includes_all_paginated_pages(self):
        pages = [[{"name": "first", "id": 1}], [{"name": "second", "id": 2}]]
        with patch.object(upload, "gh", return_value=json.dumps(pages)) as gh:
            self.assertEqual(set(upload.remote_assets("example/repo", 1)), {"first", "second"})
            self.assertIn("--paginate", gh.call_args.args)

    def test_draft_upload_is_published_only_after_every_asset_digest_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets, tools = root / "assets", root / "tools"
            assets.mkdir()
            tools.mkdir()
            part_path = assets / "example.part"
            part_path.write_bytes(b"compressed fixture")
            part = {"name": part_path.name, "bytes": part_path.stat().st_size, "sha256": upload.digest(part_path)}
            detail_path = assets / "group.manifest.json"
            detail = {"status": "verified", "secret_scan_passed": True, "files_verified": 1, "parts": [part]}
            detail_path.write_text(json.dumps(detail))
            state = {"status": "verified_ready_for_upload", "failures": [], "verified_files": 1,
                     "expected_files": 1, "verified_raw_bytes": 100, "expected_raw_bytes": 100,
                     "compressed_bytes": part["bytes"], "inventory_sha256": "inventory",
                     "groups": [{"group": "group", "manifest_name": detail_path.name,
                                 "manifest_sha256": upload.digest(detail_path), "files_verified": 1,
                                 "raw_bytes": 100, "parts": [part]}]}
            (assets / "build_status.json").write_text(json.dumps(state))
            (assets / "SHA256SUMS").write_text("fixture")
            (tools / "restore_results.py").write_text("# fixture\n")
            (tools / "release_notes.md").write_text("fixture")
            remote = {"created": False, "draft": True, "id": 1, "html_url": "https://github.com/example/release", "assets": [],
                      "tag_name": "research-snapshot-2026-10-25"}

            def gh(*args, **kwargs):
                if args[:2] == ("release", "create"):
                    remote["created"] = True
                    return "created"
                if args[:2] == ("release", "upload"):
                    path = Path(args[3])
                    remote["assets"].append({"id": len(remote["assets"]) + 1, "name": path.name,
                                             "size": path.stat().st_size, "digest": "sha256:" + upload.digest(path)})
                    return "uploaded"
                if args[:2] == ("release", "edit"):
                    self.assertEqual(len(remote["assets"]), 5)
                    remote["draft"] = False
                    return "published"
                if args[0] == "api" and "/assets?" in args[1]:
                    return json.dumps([remote["assets"]])
                if args[0] == "api" and "/releases?" in args[1]:
                    return json.dumps([[remote]] if remote["created"] else [[]])
                if args[0] == "api":
                    return json.dumps(remote) if remote["created"] else None
                raise AssertionError(args)

            with patch.object(upload, "__file__", str(tools / "upload_release.py")), \
                    patch.object(upload, "gh", side_effect=gh), patch.object(upload.time, "sleep"):
                upload.publish(assets, "aamitssharma07/prospective-memory-methods", "research-snapshot-2026-10-25", "a" * 40)
            self.assertFalse(remote["draft"])
            report = json.loads((assets / "upload_status.json").read_text())
            self.assertEqual(report["status"], "published_verified")
            self.assertEqual(len(report["verified_assets"]), 5)

    def test_draft_is_found_without_a_created_git_tag(self):
        draft = {"id": 123, "draft": True, "tag_name": "snapshot"}
        with patch.object(upload, "gh", return_value=json.dumps([[draft]])):
            self.assertEqual(upload.find_release("example/repo", "snapshot"), draft)


if __name__ == "__main__":
    unittest.main()
