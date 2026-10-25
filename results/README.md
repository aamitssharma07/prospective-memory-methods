# Full Raw Results

The compact tables are in `../prospective-memory/docs/experiments/results/`. `inventory.json` lists all result generations selected for publication, including failed/intermediate/archived attempts. It is metadata, not a completed raw secret scan.

**[Complete raw-result Release](https://github.com/aamitssharma07/prospective-memory-methods/releases/tag/research-snapshot-2026-10-25)**:
all 317 assets are published and remote-checksum verified. Download selected
groups or the complete collection using the commands below. No inference is
needed to inspect existing results.

## Packaging Status

CPU-only jobs **1553130** and **1553131** packaged and verified all 84,259 raw
files. No model inference was run. Uncompressed content: 277,808,207,965 bytes;
compressed content: 11,251,162,816 bytes, plus small manifests and restore tools.
The current small matrices already contain the completed scores for all three
experiments, including the separate original/consistency RGPM cohorts.

The published Release tag is `research-snapshot-2026-10-25`. All 157 groups
are complete. The generic-token false-positive review is recorded below;
no scientific file contents were modified or redacted.

## Archive Format

Independent result groups use Zstandard-compressed tar streams, split into
parts of at most 1,900 MiB. A group manifest records every original path, byte
count and SHA-256 hash, plus checksums for each compressed part. Concatenate
parts in numeric order, decompress with `zstd -d`, then extract with `tar` from
the repository root. The archive paths restore both sibling workspaces.

Before extraction, verify the published `SHA256SUMS` and the complete group
manifest. All groups are required for the full original result collection;
do not download only the best-scoring runs.

The archive builder is in
[`package_github_results.py`](../prospective-memory/harness/package_github_results.py).
It fails closed on detected credential content, changes during reads, unexpected
symlinks/nested archives or payload verification failures. Its detector checks
known local credential values and recognizable token/private-key formats; this
is not a claim to detect every possible type of secret or private information.

## Download and Restore

From the repository root:

```bash
python results/restore_results.py
python -m pip install zstandard
python results/restore_results.py --group 'PMBench-runs-core-four-qwen--qwen3-8b-*'
python results/restore_results.py --all
```

The first command lists the group inventory without network downloads.
Choose either a selected group or `--all`, not both. Full restore requires
roughly 259 GiB plus the 10.5 GiB compressed cache. The tool preserves existing
matching files, verifies every restored byte hash, and stops on different
existing contents. It never calls a model or requires inference API keys.

`inventory.json` is the immutable input file inventory. Its original status
field describes the initial inventory step, not current publication status.
Use `publication_status.json` and `archive_manifest.json` for availability.
The credential-pattern boundary review is documented in
[SECRET_SCAN_REVIEW.md](SECRET_SCAN_REVIEW.md).
