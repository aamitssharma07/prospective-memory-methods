# Full Project and Results on GitHub

Requested scope, October 25, 2026: publish the project and its results, not
only the compact context tables. Keys and credentials must be excluded.
Nothing has been uploaded yet. This is the current packaging plan; it extends
the earlier [GitHub handoff](GITHUB_HANDOFF.md).

## What Will Be Included

- Current main-project code, scripts, tests, datasets, papers, design notes and context files.
- Current Experiment 1 PMBench source and the patched benchmark/reference trees.
- The sibling Experiment 2 implementation, scripts, tests and datasets.
- Small result tables, metrics and CSV/JSON summaries browsable in the repository.
- All raw result generations, including intermediate, failed and archived attempts,
  responses, prompts, memory traces, snapshots, checkpoints, logs, TOK/DUR and source snapshots.

The on-disk research content is roughly 260 GiB, excluding environments/caches.
It cannot sensibly be committed as an ordinary Git repository. GitHub blocks
individual regular-Git files over 100 MiB. Use compressed, checksummed, split
GitHub Release assets for the full raw results, with each part below 2 GiB.
This still keeps the results on GitHub, downloadable by collaborators without
repeating inference. The GitHub Release documentation permits up to 1000 assets
per release; do not assume an unlimited number of parts.

Sources: [regular Git file limits](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github),
[Release asset limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).

## Clean Publication Layout

Use a separate publication checkout without copying existing `.git` histories:

```text
publication-repository/
  README.md
  prospective-memory/             current project, with child source vendored
  prospective-memory-reaearch/    Experiment 2, spelling preserved
  results/                       manifest, checksums and Release download/restore instructions
```

Keep the two workspaces as siblings so their relative-path integration remains
understandable. Preserve upstream revisions, attribution and licenses when
vendoring. Restore Release archives into this same relative layout. A fresh
publication history avoids uploading old committed `.env` contents without
rewriting or damaging the original research repository's history.

## Exclusions and Security

Exclude `.env` and credential files, all nested `.git` directories, virtual
environments, dependency/build caches, machine-agent credentials, and downloaded
model weights. These are not the experiment's scientific outputs. Environment
examples can be included only after confirming they contain placeholders.

Ignoring `.env` is insufficient: keys could also appear in source, prompts or
logs. Before any upload, scan the actual exported code and complete raw-archive
payloads for both known credentials and recognizable secret formats. Report
only paths and finding types, never key values. Any necessary redaction must
occur in a separate export, be recorded, and leave originals untouched.
Compressed/nested archives and symlinks require explicit review too. Inventory
alone is not a secret scan or proof that an upload is safe.

## Current Preparation and Blockers

- File-size and result-location audit completed; no research artifacts deleted.
- Metadata inventory helper: `harness/prepare_github_publication.py`.
- Inventory output: sibling `../github-publication-20261025/inventory.json`.
- No Git remote is configured in the main research repository.
- GitHub CLI is installed but is not authenticated.
- Destination repository URL is still required. A private repository is recommended until raw-data review is complete.
- Full payload secret scanning, compression, checksum validation and actual upload are not yet complete.

Authenticate locally with `gh auth login`. Never paste a token into the chat.
Do not run `git add .` in the old research tree or push its existing history.

Read-only inventory, writing outside both original source trees:

```bash
python harness/prepare_github_publication.py \
  --output ../github-publication-20261025/inventory.json
python -m unittest discover -s harness -p 'test_github_publication.py'
```

The inventory includes all retained raw-result generations; it does not copy
hundreds of gigabytes, read `.env`, upload anything, or modify Git state. Its
per-file sizes and timestamps provide a starting point for validated packaging.
