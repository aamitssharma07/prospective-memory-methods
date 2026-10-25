# Complete Research Artifact Snapshot

This release contains the retained raw outputs for Experiments 1 and 2 and
RGPM/Experiment 3, including older, failed and intermediate attempts. It is
not limited to selected successful runs.

- 84,259 inventoried files; 277,808,207,965 uncompressed bytes.
- 157 independent result groups, compressed with Zstandard and split below
  GitHub's 2 GiB per-asset limit.
- Per-file SHA-256 manifests and compressed-part checksums are supplied.
- Payloads were scanned for known local credentials and recognizable
  token/private-key formats, and decompressed byte-for-byte hashes were verified.
- No `.env`, nested Git history, virtual environments, caches or downloaded
  model weights are included. No inference was rerun to prepare this release.

The code, current result matrices and teammate context are on the repository's
`main` branch. The release's source-code tag captures the input code snapshot;
publication/restore metadata may have subsequent updates on `main`.

Start here:
https://github.com/aamitssharma07/prospective-memory-methods/blob/main/results/README.md

Use `restore_results.py` with `archive_manifest.json` from this release, or
their copies in the repository. Default invocation lists groups without
downloading. `--all` downloads and restores the full collection; allow roughly
259 GiB of disk space plus the compressed download cache. `--group GLOB`
restores selected groups without running a model. Different existing files
are never overwritten.

Archive integrity and credential-pattern checks do not establish model-quality
superiority, statistical significance, or detection of every possible kind of
private information. Read the experiment contexts and preserve the distinctions
between original runs, consistency reruns, failed attempts and partial GPT work.
