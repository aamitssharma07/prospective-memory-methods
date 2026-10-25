# Full Raw Results

The compact tables are in `../prospective-memory/docs/experiments/results/`. `inventory.json` lists all result generations selected for publication, including failed/intermediate/archived attempts. It is metadata, not a completed raw secret scan.

Raw archive creation and upload are pending. Once available, download the split Release assets, verify checksums and restore their original sibling-workspace paths. No run should be repeated merely because an archive has not been published yet.

## Packaging Status

CPU-only Slurm job **1553130** is preparing all 84,259 raw files. It does not
run model inference. Expected uncompressed content: 277,808,207,965 bytes.
The current small matrices already contain the completed scores for all three
experiments, including the separate original/consistency RGPM cohorts.

The planned Release tag is `research-snapshot-2026-10-25`. It is not available
until the upload and verification finish. No draft or partial archive should
be treated as the complete dataset.

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
