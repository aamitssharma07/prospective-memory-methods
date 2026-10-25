"""Download checksum-verified Release groups and restore original result paths.

Default invocation lists groups without downloading. Install `zstandard` to
extract; --all restores about 259 GiB. Existing different files are never replaced.
"""

import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import tempfile
import urllib.request


CHUNK = 1024 * 1024


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while data := stream.read(CHUNK):
            value.update(data)
    return value.hexdigest()


def download(url, destination, expected):
    if destination.name in {"", ".", ".."}:
        raise ValueError("Invalid download name")
    if destination.exists():
        if digest(destination) != expected:
            raise ValueError(f"Existing cached file has a different hash: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            value = hashlib.sha256()
            with urllib.request.urlopen(url, timeout=120) as response:
                while data := response.read(CHUNK):
                    output.write(data)
                    value.update(data)
        if value.hexdigest() != expected:
            raise ValueError("Downloaded file failed SHA-256 verification")
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class Parts:
    def __init__(self, paths):
        self.paths, self.stream = iter(paths), None

    def read(self, count):
        if count < 0:
            raise ValueError("Unbounded read")
        result = []
        while count:
            if self.stream is None:
                try:
                    self.stream = next(self.paths).open("rb")
                except StopIteration:
                    break
            data = self.stream.read(count)
            if not data:
                self.stream.close()
                self.stream = None
            else:
                count -= len(data)
                result.append(data)
        return b"".join(result)

    def close(self):
        if self.stream:
            self.stream.close()


def target_path(root, relative):
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or path.parts[0] not in {
            "prospective-memory", "prospective-memory-reaearch"}:
        raise ValueError("Unsafe archive path")
    target = root
    for part in path.parts:
        target = target / part
        if target.is_symlink():
            raise ValueError("Refusing to restore through a symlink")
    return target


def extract(root, group, paths):
    import zstandard
    expected, count = iter(group["files"]), 0
    source = Parts(paths)
    try:
        with zstandard.ZstdDecompressor().stream_reader(source, closefd=False) as decoded:
            with tarfile.open(fileobj=decoded, mode="r|") as archive:
                for member in archive:
                    record = next(expected, None)
                    if (record is None or not member.isfile() or member.name != record["path"]
                            or member.size != record["bytes"]):
                        raise ValueError("Archive does not match its file manifest")
                    target = target_path(root, member.name)
                    existing = target.exists()
                    if existing and (not target.is_file() or digest(target) != record["sha256"]):
                        raise ValueError(f"Existing result differs; refusing overwrite: {target}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary, output = None, None
                    try:
                        if not existing:
                            output = tempfile.NamedTemporaryFile(dir=target.parent, delete=False)
                            temporary = Path(output.name)
                        value = hashlib.sha256()
                        stream = archive.extractfile(member)
                        while data := stream.read(CHUNK):
                            value.update(data)
                            if output is not None:
                                output.write(data)
                        if output is not None:
                            output.close()
                        if value.hexdigest() != record["sha256"]:
                            raise ValueError("Decompressed result failed SHA-256 verification")
                        if temporary is not None:
                            temporary.chmod(member.mode & 0o777 & ~0o022)
                            os.link(temporary, target)
                    finally:
                        if output is not None:
                            output.close()
                        if temporary is not None:
                            temporary.unlink(missing_ok=True)
                    count += 1
            while decoded.read(CHUNK):
                pass
        if next(expected, None) is not None:
            raise ValueError("Archive is missing expected files")
    finally:
        source.close()
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("archive_manifest.json"))
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--cache", type=Path, default=Path(__file__).with_name(".download-cache"))
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--group", action="append", default=[], help="Archive group glob; may be repeated")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if manifest["status"] != "available":
        raise ValueError("Raw results have not been published completely")
    selected = [g for g in manifest["groups"] if args.all or any(fnmatch.fnmatch(g["group"], p) for p in args.group)]
    if not args.all and not args.group:
        for group in manifest["groups"]:
            print(f"{group['group']}  {group['raw_bytes'] / 1024**3:.3f} GiB  {group['files_verified']} files")
        print("Use --all or --group GLOB to download and extract. Full restore needs about 259 GiB.")
        return
    if not selected:
        raise ValueError("No archive groups matched")
    root = args.directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for group in selected:
        names = [group["manifest_name"], *(part["name"] for part in group["parts"])]
        if any(PurePosixPath(name).name != name or name in {".", ".."} for name in names):
            raise ValueError("Unsafe cached asset name")
        local = args.cache / group["manifest_name"]
        download(group["manifest_url"], local, group["manifest_sha256"])
        detail = json.loads(local.read_text())
        if (detail["status"] != "verified" or detail["group"] != group["group"]
                or detail["parts"] != [{k: p[k] for k in ("name", "bytes", "sha256")} for p in group["parts"]]):
            raise ValueError("Group metadata does not match the repository manifest")
        paths = []
        for part in group["parts"]:
            destination = args.cache / part["name"]
            download(part["url"], destination, part["sha256"])
            paths.append(destination)
        count = extract(root, detail, paths)
        if count != group["files_verified"]:
            raise ValueError("Restored file count differs from the published inventory")
        print(f"Verified/restored {count} files: {group['group']}")


if __name__ == "__main__":
    main()
