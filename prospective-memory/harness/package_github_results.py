"""Scan, hash, compress and verify all inventoried raw results, without inference."""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import time

from prepare_github_publication import known_credentials, secret_scanner


CHUNK = 1024 * 1024
PART_BYTES = 1900 * 1024 * 1024


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def now():
    return datetime.now(timezone.utc).isoformat()


def group_name(record):
    parts = PurePosixPath(record["path"]).parts
    if len(parts) > 5 and parts[1:4] == ("experiments", "rgpm", "runs"):
        prefix = parts[:6]
    elif len(parts) > 4 and parts[1:4] == ("PMBench", "runs", "core-four"):
        prefix = parts[:5]
    else:
        prefix = parts[:4]
    key = "/".join(prefix)
    readable = re.sub(r"[^a-zA-Z0-9-]+", "-", "-".join(prefix[1:])).strip("-")[:100]
    return readable + "-" + hashlib.sha256(key.encode()).hexdigest()[:12]


def safe_path(parent, relative):
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or path.parts[0] not in {
            "prospective-memory", "prospective-memory-reaearch"}:
        raise ValueError("Unexpected archive path")
    candidate = parent / relative
    if candidate.is_symlink() or not candidate.resolve().is_relative_to((parent / path.parts[0]).resolve()):
        raise ValueError("Unsafe source path")
    return candidate


class SplitWriter:
    def __init__(self, directory, name, limit=PART_BYTES):
        self.directory, self.name, self.limit = directory, name, limit
        self.stream = None
        self.current = None
        self.parts = []
        self.total = 0

    def _open(self):
        number = len(self.parts) + 1
        self.current = self.directory / f"{self.name}.tar.zst.part-{number:04d}"
        self.stream = self.current.with_suffix(self.current.suffix + ".tmp").open("xb")
        self.digest, self.size = hashlib.sha256(), 0

    def _finish(self):
        if self.stream is None:
            return
        self.stream.flush()
        os.fsync(self.stream.fileno())
        temporary = Path(self.stream.name)
        self.stream.close()
        temporary.replace(self.current)
        self.parts.append({"name": self.current.name, "bytes": self.size, "sha256": self.digest.hexdigest()})
        self.stream = None

    def write(self, data):
        original = len(data)
        while data:
            if self.stream is None:
                self._open()
            count = min(len(data), self.limit - self.size)
            payload = data[:count]
            self.stream.write(payload)
            self.digest.update(payload)
            self.size += count
            self.total += count
            data = data[count:]
            if self.size == self.limit:
                self._finish()
        return original

    def flush(self):
        if self.stream:
            self.stream.flush()

    def close(self):
        self._finish()

    def abort(self):
        if self.stream:
            self.stream.close()
            self.stream = None


class ConcatReader:
    def __init__(self, paths):
        self.paths = iter(paths)
        self.stream = None

    def read(self, count=-1):
        if count < 0:
            raise ValueError("Unbounded reads are forbidden")
        chunks, remaining = [], count
        while remaining:
            if self.stream is None:
                try:
                    self.stream = next(self.paths).open("rb")
                except StopIteration:
                    break
            data = self.stream.read(remaining)
            if not data:
                self.stream.close()
                self.stream = None
            else:
                chunks.append(data)
                remaining -= len(data)
        return b"".join(chunks)

    def close(self):
        if self.stream:
            self.stream.close()


class ScanningReader:
    def __init__(self, stream, scanner, overlap, progress):
        self.stream, self.scanner, self.overlap, self.progress = stream, scanner, overlap, progress
        self.tail = b""
        self.digest = hashlib.sha256()
        self.count = 0

    def read(self, count):
        data = self.stream.read(count)
        combined = self.tail + data
        if self.scanner.search(combined):
            raise ValueError("Credential-like content detected in raw result; upload blocked")
        self.tail = combined[-self.overlap:]
        self.digest.update(data)
        self.count += len(data)
        self.progress(len(data))
        return data


def verify_archive(directory, parts, files):
    import zstandard
    expected = iter(files)
    count = 0
    source = ConcatReader([directory / part["name"] for part in parts])
    try:
        with zstandard.ZstdDecompressor().stream_reader(source, closefd=False) as decoded:
            with tarfile.open(fileobj=decoded, mode="r|") as archive:
                for member in archive:
                    record = next(expected, None)
                    if (record is None or not member.isfile() or member.name != record["path"]
                            or member.size != record["bytes"]):
                        raise ValueError("Archive inventory mismatch")
                    stream = archive.extractfile(member)
                    digest = hashlib.sha256()
                    while data := stream.read(CHUNK):
                        digest.update(data)
                    if digest.hexdigest() != record["sha256"]:
                        raise ValueError("Archive payload hash mismatch")
                    count += 1
            while decoded.read(CHUNK):
                pass
        if next(expected, None) is not None:
            raise ValueError("Archive omitted expected files")
    finally:
        source.close()
    return count


def build_group(parent, directory, name, records, known):
    import zstandard
    scanner_identity = {"worker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                        "known_set_sha256": hashlib.sha256(b"\0".join(sorted(known))).hexdigest()}
    final = directory / (name + ".manifest.json")
    if final.exists():
        result = json.loads(final.read_text())
        if result["status"] != "verified":
            raise ValueError("Existing group is not verified")
        if result.get("scanner_identity") != scanner_identity:
            raise ValueError("Scanner or known credentials changed; use a new output directory")
        expected = [(r["path"], r["bytes"], r["mtime_ns"]) for r in records]
        actual = [(r["path"], r["bytes"], r["mtime_ns"]) for r in result["files"]]
        if expected != actual:
            raise ValueError("Cannot reuse archive for a changed inventory")
        for record in records:
            current = safe_path(parent, record["path"]).stat()
            if current.st_size != record["bytes"] or current.st_mtime_ns != record["mtime_ns"]:
                raise ValueError("Original changed since verified archive")
        for part in result["parts"]:
            digest = hashlib.sha256()
            with (directory / part["name"]).open("rb") as stream:
                while data := stream.read(CHUNK):
                    digest.update(data)
            if digest.hexdigest() != part["sha256"]:
                raise ValueError("Existing compressed part changed")
        return result
    scanner = secret_scanner(known)
    overlap = max([1024, *(len(value) + 1 for value in known)])
    progress_path = directory / (name + ".progress.json")
    progress = {"status": "scanning_and_compressing", "group": name, "files_done": 0,
                "bytes_scanned": 0, "expected_bytes": sum(r["bytes"] for r in records), "updated_at": now()}
    last = time.monotonic()

    def update(amount):
        nonlocal last
        progress["bytes_scanned"] += amount
        if time.monotonic() - last >= 5:
            progress["updated_at"] = now()
            save(progress_path, progress)
            last = time.monotonic()

    save(progress_path, progress)
    writer = SplitWriter(directory, name)
    files = []
    try:
        with zstandard.ZstdCompressor(level=1, write_checksum=True).stream_writer(writer, closefd=False) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", bufsize=CHUNK, copybufsize=CHUNK) as archive:
                for record in records:
                    path = safe_path(parent, record["path"])
                    current = path.stat()
                    if (not stat.S_ISREG(current.st_mode) or current.st_size != record["bytes"]
                            or current.st_mtime_ns != record["mtime_ns"]):
                        raise ValueError("Result changed since inventory: " + record["path"])
                    if path.suffix.lower() in {".zip", ".gz", ".xz", ".bz2", ".zst", ".7z", ".tar"}:
                        raise ValueError("Nested archive requires separate secret review: " + record["path"])
                    member = tarfile.TarInfo(record["path"])
                    member.size, member.mtime = current.st_size, int(current.st_mtime)
                    member.mode = stat.S_IMODE(current.st_mode) & ~0o022
                    with path.open("rb") as stream:
                        reader = ScanningReader(stream, scanner, overlap, update)
                        archive.addfile(member, reader)
                    after = path.stat()
                    if (reader.count != current.st_size or after.st_mtime_ns != current.st_mtime_ns
                            or after.st_size != current.st_size):
                        raise ValueError("Result changed during read: " + record["path"])
                    files.append({**record, "sha256": reader.digest.hexdigest()})
                    progress["files_done"] += 1
        writer.close()
        progress.update(status="verifying_decompressed_payload", updated_at=now())
        save(progress_path, progress)
        verified = verify_archive(directory, writer.parts, files)
        result = {"schema_version": 1, "status": "verified", "group": name, "completed_at": now(),
                  "files_verified": verified, "raw_bytes": progress["bytes_scanned"],
                  "parts": writer.parts, "files": files, "secret_scan_passed": True,
                  "scanner_identity": scanner_identity,
                  "scanner_scope": "known local credentials plus recognizable token/private-key formats; no exhaustive detection claim"}
        save(final, result)
        progress.update(status="verified", updated_at=now())
        save(progress_path, progress)
        return result
    except BaseException as exc:
        writer.abort()
        progress.update(status="failed_upload_blocked", error_type=type(exc).__name__, message=str(exc), updated_at=now())
        save(progress_path, progress)
        raise


def build(inventory_path, directory, workers):
    directory.mkdir(parents=True, exist_ok=True)
    inventory = json.loads(inventory_path.read_text())
    if inventory["manual_review"]:
        raise ValueError("Unresolved inventory review")
    parent = inventory_path.parent.parent
    known = known_credentials(parent, inventory)
    selected = [record for record in inventory["files"] if record["category"] != "repository"]
    groups = {}
    for record in selected:
        groups.setdefault(group_name(record), []).append(record)
    for records in groups.values():
        records.sort(key=lambda r: r["path"])
    state = {"schema_version": 1, "status": "building", "started_at": now(),
             "inventory_sha256": hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
             "worker_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             "total_groups": len(groups), "groups_verified": 0,
             "expected_files": len(selected), "expected_raw_bytes": sum(r["bytes"] for r in selected),
             "verified_files": 0, "verified_raw_bytes": 0, "groups": [], "failures": []}
    save(directory / "build_status.json", state)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(build_group, parent, directory, name, records, known): name
                   for name, records in groups.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                state["groups"].append({k: result[k] for k in ("group", "parts", "files_verified", "raw_bytes")})
                state["groups"][-1].update(manifest_name=name + ".manifest.json",
                    manifest_sha256=hashlib.sha256((directory / (name + ".manifest.json")).read_bytes()).hexdigest())
                state["groups_verified"] += 1
                state["verified_files"] += result["files_verified"]
                state["verified_raw_bytes"] += result["raw_bytes"]
                print(json.dumps({"group_verified": name, "groups": state["groups_verified"],
                                  "total": len(groups), "verified_raw_bytes": state["verified_raw_bytes"]}), flush=True)
            except Exception as exc:
                state["failures"].append({"group": name, "type": type(exc).__name__, "message": str(exc)})
            state["updated_at"] = now()
            save(directory / "build_status.json", state)
    parts = [part for group in state["groups"] for part in group["parts"]]
    if len(parts) + len(groups) + 1 > 1000:
        state["failures"].append({"type": "TooManyReleaseAssets"})
    if state["verified_files"] != len(selected) or state["verified_raw_bytes"] != state["expected_raw_bytes"]:
        state["failures"].append({"type": "FinalInventoryCoverageMismatch"})
    state["status"] = "failed_upload_blocked" if state["failures"] else "verified_ready_for_upload"
    state["compressed_bytes"] = sum(part["bytes"] for part in parts)
    state["completed_at"] = now()
    save(directory / "build_status.json", state)
    if state["failures"]:
        raise ValueError("Packaging checks failed; inspect build_status.json before upload")
    sums = "".join(f"{p['sha256']}  {p['name']}\n" for p in sorted(parts, key=lambda p: p["name"]))
    (directory / "SHA256SUMS").write_text(sums)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 8:
        raise ValueError("Use 1-8 CPU workers")
    build(args.inventory.resolve(), args.output.resolve(), args.workers)


if __name__ == "__main__":
    main()
