"""Inventory a clean two-workspace publication, including all result generations.

This command does not upload, copy raw data, source .env, or modify Git history.
Its inventory is metadata only and is NOT a completed secret scan.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from urllib.parse import urlsplit
import zipfile


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRECTORIES = {".git", ".cache", ".runtime", "__pycache__", "node_modules",
                        ".aws", ".codex", ".agents", ".pytest_cache", ".mypy_cache"}
MODEL_EXTENSIONS = {".safetensors", ".gguf", ".pt", ".pth", ".onnx"}
SECRET_PATTERN = (rb"(?<![A-Za-z0-9_])(?:sk-[A-Za-z0-9_-]{20,}|hf_[A-Za-z0-9]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|"
                  rb"github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16})|"
                  rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")


def exclusion(path, directory=False):
    name = path.name.lower()
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return "environment_file"
    if (name in {"credentials", "id_rsa", "id_ed25519", ".netrc", ".pypirc"}
            or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}):
        return "credential_file"
    if directory and (name in EXCLUDED_DIRECTORIES or name.startswith((".venv", "venv"))):
        return "git_metadata_environment_or_cache"
    if path.suffix.lower() in MODEL_EXTENSIONS:
        return "downloaded_model_weights"
    if path.suffix.lower() in {".pyc", ".pyo"}:
        return "compiled_python_cache"
    if name.endswith(".lock") and "launches" in path.parts:
        return "runtime_lock"
    return None


def category(relative, size):
    parts = relative.parts
    if len(parts) >= 3 and parts[:2] == ("experiments", "rgpm"):
        if parts[2].startswith(("runs", "jobs", "smoke_artifacts", "preflight_", "legacy_outputs")):
            return "raw_results_release"
    if any(part in {"runs", "smoke_artifacts", "run_logs", "memory_results"} for part in parts):
        return "raw_results_release"
    if len(parts) > 1 and parts[0] == "harness" and parts[1] == "results":
        return "raw_results_release"
    if size >= 100 * 1024 * 1024:
        return "large_asset_release"
    return "repository"


def inventory(workspaces):
    records, skipped, review = [], [], []
    for root in workspaces:
        for directory, directories, files in os.walk(root, followlinks=False):
            base = Path(directory)
            retained = []
            for name in sorted(directories):
                path = base / name
                reason = exclusion(path, directory=True)
                relative = str(Path(root.name) / path.relative_to(root))
                if reason:
                    skipped.append({"path": relative, "reason": reason, "directory": True})
                elif path.is_symlink():
                    review.append({"path": relative, "reason": "directory_symlink_requires_safe_resolution"})
                else:
                    retained.append(name)
            directories[:] = retained
            for name in sorted(files):
                path = base / name
                relative = path.relative_to(root)
                public_path = str(Path(root.name) / relative)
                reason = exclusion(path)
                if reason:
                    skipped.append({"path": public_path, "reason": reason, "directory": False})
                    continue
                if path.is_symlink():
                    review.append({"path": public_path, "reason": "file_symlink_requires_safe_resolution"})
                    continue
                stat = path.stat()
                if not path.is_file():
                    review.append({"path": public_path, "reason": "nonregular_file"})
                    continue
                records.append({"path": public_path, "bytes": stat.st_size,
                                "mtime_ns": stat.st_mtime_ns, "category": category(relative, stat.st_size)})
    counts, sizes = Counter(), Counter()
    for record in records:
        counts[record["category"]] += 1
        sizes[record["category"]] += record["bytes"]
    return {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "inventory_only_not_secret_scanned_not_uploaded",
            "workspaces": [p.name for p in workspaces],
            "publication_layout": "Keep both workspaces as sibling folders in a clean publication repository",
            "history_policy": "Do not copy existing .git history; tracked .env must not enter the new publication",
            "results_policy": "All retained and archived result generations included as split GitHub Release archives",
            "release_part_max_bytes": 1900 * 1024 * 1024,
            "file_counts": dict(counts), "logical_bytes": dict(sizes),
            "files": records, "excluded": skipped, "manual_review": review}


def known_credentials(parent, result):
    values = set()
    for entry in result["excluded"]:
        if entry["reason"] != "environment_file" or entry["directory"]:
            continue
        for line in (parent / entry["path"]).read_text().splitlines():
            line = line.strip().removeprefix("export ")
            name, separator, value = line.partition("=")
            if not separator or not re.search(r"KEY|TOKEN|SECRET|PASSWORD", name.upper()):
                continue
            try:
                words = shlex.split(value, comments=True)
            except ValueError:
                continue
            if len(words) == 1 and len(words[0]) >= 12 and "${" not in words[0]:
                values.add(words[0].encode())
    for name, value in os.environ.items():
        if re.search(r"KEY|TOKEN|SECRET|PASSWORD", name.upper()) and len(value) >= 12:
            values.add(value.encode())
    return values


def secret_scanner(known):
    alternatives = [SECRET_PATTERN, *(re.escape(value) for value in sorted(known))]
    return re.compile(b"(?:" + b"|".join(alternatives) + b")")


def check_source(path, data, scanner):
    if scanner.search(data):
        raise ValueError("Credential-like content detected; no upload: " + str(path))
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                if info.file_size > 100 * 1024 * 1024:
                    raise ValueError("Large nested archive needs separate review: " + str(path))
                name = Path(info.filename).name.lower()
                if exclusion(Path(name)) in {"environment_file", "credential_file"}:
                    raise ValueError("Nested credential file detected: " + str(path))
                if scanner.search(archive.read(info.filename)):
                    raise ValueError("Credential-like content inside archive: " + str(path))


def source_revision(path):
    result = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True)
    status = subprocess.run(["git", "-C", str(path), "status", "--porcelain", "--untracked-files=no"],
                            capture_output=True, text=True, check=True)
    return {"head": result.stdout.strip(), "has_local_changes": bool(status.stdout)}


def stage_repository(result, workspaces, destination, repository_url):
    url = urlsplit(repository_url)
    if (url.scheme != "https" or url.hostname != "github.com" or url.username or url.password
            or url.query or url.fragment or len(url.path.strip("/").split("/")) != 2):
        raise ValueError("Provide a credential-free HTTPS GitHub repository URL")
    if destination.exists():
        raise ValueError("Refusing to overwrite an existing publication tree")
    if any(destination.is_relative_to(root) for root in workspaces):
        raise ValueError("Publication tree must be outside the research workspaces")
    if result["manual_review"]:
        raise ValueError("Resolve manual-review entries before staging source")
    parent = workspaces[0].parent
    if any(p.parent != parent for p in workspaces):
        raise ValueError("Workspaces must be siblings to preserve the source layout")
    known = known_credentials(parent, result)
    scanner = secret_scanner(known)
    selected = [record for record in result["files"] if record["category"] == "repository"]
    destination.mkdir(parents=True)
    evidence = []
    for record in selected:
        source = parent / record["path"]
        before = source.stat()
        if before.st_size != record["bytes"] or before.st_mtime_ns != record["mtime_ns"]:
            raise ValueError("Source changed since inventory: " + record["path"])
        data = source.read_bytes()
        check_source(source, data, scanner)
        after = source.stat()
        if after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns:
            raise ValueError("Source changed during read: " + record["path"])
        target = destination / record["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(before.st_mode & 0o777 & ~0o022)
        evidence.append({"path": record["path"], "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    (destination / ".gitignore").write_text(
        ".env\n.env.*\n!.env.example\n.git/\n.venv*/\n.cache/\n.runtime/\n__pycache__/\nresults/assets/\n")
    (destination / "README.md").write_text(
        "# Prospective Memory Methods\n\n"
        "Three experiments: PMBench controls, author-release memory methods, and our RGPM method.\n\n"
        "Start with [Team Context](prospective-memory/TEAM_CONTEXT.md) and "
        "[the result tables](prospective-memory/docs/experiments/results/RESULTS.md).\n\n"
        "- `prospective-memory/`: main project, Experiment 1, RGPM, tests and documentation.\n"
        "- `prospective-memory-reaearch/`: Experiment 2 implementation and configuration.\n"
        "- `results/`: complete inventory, packaging state and raw-result access instructions.\n\n"
        "Current source was exported without `.env`, caches, model weights or old Git history. "
        "Nested source checkouts are vendored at their current working-tree contents; "
        "see `SOURCE_PROVENANCE.json` for upstream commits and file hashes.\n\n"
        "**Raw results are not yet uploaded.** Their full inventory is preserved under `results/`; "
        "split GitHub Release archives still require payload scanning, compression and upload. "
        "Do not rerun completed experiments to recover missing raw data.\n")
    releases = destination / "results"
    releases.mkdir()
    (releases / "inventory.json").write_text(json.dumps(result, indent=2) + "\n")
    state = {"status": "source_staged_raw_archives_pending", "repository_url": repository_url,
             "source_files_scanned": len(evidence), "known_credential_values_checked": len(known),
             "scanner_scope": "known local credentials and recognizable token/private-key formats; source ZIP members included",
             "raw_result_payloads_scanned": False, "raw_results_uploaded": False,
             "original_workspaces_unchanged": True}
    (releases / "publication_status.json").write_text(json.dumps(state, indent=2) + "\n")
    (releases / "README.md").write_text(
        "# Full Raw Results\n\n"
        "The compact tables are in `../prospective-memory/docs/experiments/results/`. "
        "`inventory.json` lists all result generations selected for publication, including "
        "failed/intermediate/archived attempts. It is metadata, not a completed raw secret scan.\n\n"
        "Raw archive creation and upload are pending. Once available, download the split "
        "Release assets, verify checksums and restore their original sibling-workspace paths. "
        "No run should be repeated merely because an archive has not been published yet.\n")
    provenance = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "history_exported": False,
                  "repositories": {str(p.relative_to(parent)): source_revision(p) for p in (
                      *workspaces, workspaces[0] / "PMBench", workspaces[0] / "benchmark",
                      workspaces[0] / "third_party/author_pis")}, "files": evidence}
    (destination / "SOURCE_PROVENANCE.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exp2-root", type=Path, default=ROOT.parent / "prospective-memory-reaearch")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage-repository", type=Path)
    parser.add_argument("--repository-url")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise ValueError("Refusing to overwrite a publication inventory")
    roots = [ROOT, args.exp2_root.resolve()]
    if any(output.is_relative_to(root) for root in roots):
        raise ValueError("Write the inventory outside the two source trees")
    result = inventory(roots)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    if args.stage_repository:
        if not args.repository_url:
            raise ValueError("--repository-url is required for staging")
        state = stage_repository(result, roots, args.stage_repository.resolve(), args.repository_url)
        print(json.dumps(state, indent=2))
    print(json.dumps({"status": result["status"], "output": str(output),
                      "file_counts": result["file_counts"], "logical_bytes": result["logical_bytes"],
                      "manual_review_count": len(result["manual_review"])}, indent=2))


if __name__ == "__main__":
    main()
