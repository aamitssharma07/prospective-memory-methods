"""Publish only fully verified archives to an explicitly selected GitHub Release."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import quote


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while data := stream.read(1024 * 1024):
            value.update(data)
    return value.hexdigest()


def gh(*args, allow_missing=False):
    env = {k: v for k, v in os.environ.items() if k != "GH_DEBUG"}
    for attempt in range(4):
        response = subprocess.run(["gh", *args], capture_output=True, text=True, env=env)
        if not response.returncode:
            return response.stdout
        if allow_missing and "404" in response.stderr:
            return None
        transient = any(text in response.stderr.lower() for text in (
            "http 429", "http 502", "http 503", "http 504", "secondary rate limit",
            "connection reset", "tls handshake timeout"))
        if transient and attempt < 3:
            time.sleep(15 * 2**attempt)
            continue
        raise RuntimeError("GitHub command failed; no credentials were logged: " + " ".join(args[:2]))


def remote_assets(repo, release_id):
    pages = json.loads(gh("api", f"repos/{repo}/releases/{release_id}/assets?per_page=100", "--paginate", "--slurp"))
    return {asset["name"]: asset for page in pages for asset in page}


def find_release(repo, tag):
    # Drafts need not have a Git tag yet; the by-tag endpoint can return 404.
    pages = json.loads(gh("api", f"repos/{repo}/releases?per_page=100", "--paginate", "--slurp"))
    matches = [release for page in pages for release in page if release["tag_name"] == tag]
    if len(matches) > 1:
        raise ValueError("Multiple matching drafts; refusing ambiguous publication")
    return matches[0] if matches else None


def match_remote(asset, expected):
    if asset["name"] != expected["name"] or asset["size"] != expected["bytes"]:
        raise ValueError("Remote Release asset name/size differs")
    remote_hash = asset.get("digest")
    if remote_hash is not None and remote_hash != "sha256:" + expected["sha256"]:
        raise ValueError("Remote Release asset digest differs")
    return remote_hash is not None


def verify_remote(repo, asset, expected):
    if match_remote(asset, expected):
        return
    # Older GitHub responses may omit digest. Hash the authenticated download
    # without printing or saving its credential or payload.
    command = ["gh", "api", "-H", "Accept: application/octet-stream",
               f"repos/{repo}/releases/assets/{asset['id']}"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env={k: v for k, v in os.environ.items() if k != "GH_DEBUG"})
    value = hashlib.sha256()
    while data := process.stdout.read(1024 * 1024):
        value.update(data)
    if process.wait() or value.hexdigest() != expected["sha256"]:
        raise ValueError("Remote Release asset download failed hash verification")


def publish(assets, repo, tag, target):
    directory = Path(__file__).resolve().parent
    state = json.loads((assets / "build_status.json").read_text())
    if (state["status"] != "verified_ready_for_upload" or state["failures"]
            or state["verified_files"] != state["expected_files"]
            or state["verified_raw_bytes"] != state["expected_raw_bytes"]):
        raise ValueError("Raw result packaging is incomplete or failed; upload blocked")
    if repo != "aamitssharma07/prospective-memory-methods" or tag != "research-snapshot-2026-10-25":
        raise ValueError("Destination differs from the approved repository/release")
    if not re.fullmatch(r"[0-9a-f]{40}", target):
        raise ValueError("Pin the source snapshot to its full commit SHA")
    root_url = f"https://github.com/{repo}/releases/download/{tag}/"
    selected, groups = [], []
    for group in sorted(state["groups"], key=lambda g: g["group"]):
        detail_path = assets / group["manifest_name"]
        if digest(detail_path) != group["manifest_sha256"]:
            raise ValueError("Group manifest changed since packaging")
        detail = json.loads(detail_path.read_text())
        if (detail["status"] != "verified" or not detail["secret_scan_passed"]
                or detail["files_verified"] != group["files_verified"] or detail["parts"] != group["parts"]):
            raise ValueError("Inconsistent archive group metadata")
        selected.append({"name": detail_path.name, "path": detail_path,
                         "bytes": detail_path.stat().st_size, "sha256": group["manifest_sha256"]})
        exported = {**group, "manifest_url": root_url + quote(group["manifest_name"]), "parts": []}
        for part in group["parts"]:
            path = assets / part["name"]
            if path.stat().st_size != part["bytes"] or digest(path) != part["sha256"]:
                raise ValueError("Compressed archive changed since verification")
            selected.append({**part, "path": path})
            exported["parts"].append({**part, "url": root_url + quote(part["name"])})
        groups.append(exported)
    manifest = {"schema_version": 1, "status": "available", "repository": repo, "tag": tag,
                "release_url": f"https://github.com/{repo}/releases/tag/{tag}",
                "source_commit": target, "raw_files": state["verified_files"],
                "raw_bytes": state["verified_raw_bytes"], "compressed_bytes": state["compressed_bytes"],
                "inventory_sha256": state["inventory_sha256"], "scanner_review": state.get("boundary_review"),
                "redacted_files": 0, "groups": groups}
    manifest_path = directory / "archive_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    for path in (assets / "SHA256SUMS", manifest_path, directory / "restore_results.py"):
        selected.append({"name": path.name, "path": path, "bytes": path.stat().st_size, "sha256": digest(path)})
    if len(selected) > 1000 or any(a["bytes"] >= 2 * 1024**3 for a in selected):
        raise ValueError("GitHub Release limits exceeded")
    release = find_release(repo, tag)
    if release is None:
        gh("release", "create", tag, "--repo", repo, "--draft", "--target", target,
           "--title", "Complete prospective-memory research results (2026-10-25)",
           "--notes-file", str(directory / "release_notes.md"))
        release = find_release(repo, tag)
    if release is None:
        raise ValueError("Created draft could not be located")
    upload_state_path = assets / "upload_status.json"
    previous = json.loads(upload_state_path.read_text()) if upload_state_path.exists() else None
    if not release["draft"] and (previous is None or previous.get("release_id") != release["id"]):
        raise ValueError("Refusing to modify an unrelated published Release")
    expected_names = {a["name"] for a in selected}
    existing = remote_assets(repo, release["id"])
    if set(existing) - expected_names:
        raise ValueError("Unexpected assets already exist; no overwrite or deletion performed")
    report = {"status": "uploading_draft", "repository": repo, "tag": tag,
              "release_id": release["id"], "total_assets": len(selected), "verified_assets": []}
    upload_state_path.write_text(json.dumps(report, indent=2) + "\n")
    last_upload = 0.0
    for index, asset in enumerate(selected, 1):
        if asset["name"] not in existing:
            if not release["draft"]:
                raise ValueError("Published Release is missing an expected asset")
            time.sleep(max(0, 1.1 - (time.monotonic() - last_upload)))
            last_upload = time.monotonic()
            gh("release", "upload", tag, str(asset["path"]), "--repo", repo)
            existing = remote_assets(repo, release["id"])
        remote = existing[asset["name"]]
        verify_remote(repo, remote, asset)
        report["verified_assets"].append({"name": asset["name"], "bytes": asset["bytes"],
                                          "sha256": asset["sha256"], "id": remote["id"]})
        upload_state_path.write_text(json.dumps(report, indent=2) + "\n")
        if index % 5 == 0 or index == len(selected):
            print(json.dumps({"assets_verified": index, "total_assets": len(selected)}), flush=True)
    if release["draft"]:
        gh("release", "edit", tag, "--repo", repo, "--draft=false")
    final = json.loads(gh("api", f"repos/{repo}/releases/{release['id']}"))
    if final["draft"] or set(remote_assets(repo, release["id"])) != expected_names:
        raise ValueError("Published Release failed final completeness verification")
    report.update(status="published_verified", release_url=final["html_url"])
    upload_state_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "release_url": final["html_url"],
                      "assets": len(selected), "raw_files": manifest["raw_files"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    publish(args.assets.resolve(), args.repository, args.tag, args.target)


if __name__ == "__main__":
    main()
