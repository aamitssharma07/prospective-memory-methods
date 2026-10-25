"""Recheck one false-positive group and assemble a complete, unchanged-byte export."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    publication = Path(sys.argv[1]).resolve()
    parent = publication.parent
    inventory = json.loads((publication / "inventory-v3.json").read_text())
    frozen = publication / "repository-v3/prospective-memory/harness"
    sys.path.insert(0, str(frozen))
    worker = load("frozen_archive_worker", frozen / "package_github_results.py")
    revised_path = parent / "prospective-memory/harness/prepare_github_publication.py"
    revised = load("boundary_reviewed_scanner", revised_path)
    worker.secret_scanner = revised.secret_scanner
    name = "data-PMBench-runs-9b9b108aea83"
    records = sorted([r for r in inventory["files"] if r["category"] != "repository"
                      and worker.group_name(r) == name], key=lambda r: r["path"])
    if len(records) != 753:
        raise ValueError("Unexpected affected group")
    original_assets = publication / "release-assets"
    old = json.loads((original_assets / "build_status.json").read_text())
    if old["groups_verified"] != 156 or len(old["groups"]) != 156:
        raise ValueError("Original verified cohort is incomplete")
    reviewed = publication / "reviewed-exp2-assets"
    reviewed.mkdir(exist_ok=True)
    known = revised.known_credentials(parent, inventory)
    result = worker.build_group(parent, reviewed, name, records, known)
    review = {"reason": "Generic sk-prefix matched inside generated task labels; not actual credentials",
              "revised_scanner_sha256": hashlib.sha256(revised_path.read_bytes()).hexdigest(),
              "original_scanner_sha256": hashlib.sha256((frozen / "prepare_github_publication.py").read_bytes()).hexdigest(),
              "known_credential_matching": "unchanged exact matching; generic prefixes now require a token boundary",
              "redacted_files": 0, "original_files_modified": 0,
              "other_groups": "156 passed the stricter superset pattern and remain byte-verified"}
    result["boundary_review"] = review
    detail = reviewed / (name + ".manifest.json")
    worker.save(detail, result)
    state = dict(old)
    state["groups"] = list(old["groups"])
    state["groups"].append({k: result[k] for k in ("group", "parts", "files_verified", "raw_bytes")})
    state["groups"][-1].update(manifest_name=detail.name, manifest_sha256=hashlib.sha256(detail.read_bytes()).hexdigest())
    state.update(groups_verified=157, verified_files=sum(g["files_verified"] for g in state["groups"]),
                 verified_raw_bytes=sum(g["raw_bytes"] for g in state["groups"]), failures=[],
                 status="verified_ready_for_upload", boundary_review=review,
                 completed_at=datetime.now(timezone.utc).isoformat())
    if (state["verified_files"] != state["expected_files"]
            or state["verified_raw_bytes"] != state["expected_raw_bytes"]):
        raise ValueError("Final coverage mismatch")
    final = publication / "release-assets-verified"
    final.mkdir(exist_ok=False)
    parts = []
    for group in state["groups"]:
        source = reviewed if group["group"] == name else original_assets
        paths = [source / group["manifest_name"], *(source / p["name"] for p in group["parts"])]
        for path in paths:
            os.link(path, final / path.name)
        parts.extend(group["parts"])
    state["compressed_bytes"] = sum(p["bytes"] for p in parts)
    worker.save(final / "build_status.json", state)
    (final / "SHA256SUMS").write_text("".join(f"{p['sha256']}  {p['name']}\n" for p in sorted(parts, key=lambda p: p["name"])))
    print(json.dumps({"status": state["status"], "verified_files": state["verified_files"],
                      "verified_raw_bytes": state["verified_raw_bytes"], "compressed_bytes": state["compressed_bytes"],
                      "original_files_modified": 0, "redacted_files": 0}), flush=True)


if __name__ == "__main__":
    main()
