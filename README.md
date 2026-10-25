# Prospective Memory Methods

Three experiments: PMBench controls, author-release memory methods, and our RGPM method.

Start with [Team Context](prospective-memory/TEAM_CONTEXT.md) and [the result tables](prospective-memory/docs/experiments/results/RESULTS.md).

- `prospective-memory/`: main project, Experiment 1, RGPM, tests and documentation.
- `prospective-memory-reaearch/`: Experiment 2 implementation and configuration.
- `results/`: complete inventory, packaging state and raw-result access instructions.

The pre-existing top-level `PMBench/`, `pmbench_fallback_audit/`,
`prospective_memory/` and `tests/` are retained as the repository's initial
historical snapshot. Use the current code inside `prospective-memory/` and
the sibling `prospective-memory-reaearch/` for the three experiments. The
previous entry-point README is preserved in `legacy_initial_snapshot/`.

Current source was exported without `.env`, caches, model weights or old Git history. Nested source checkouts are vendored at their current working-tree contents; see `SOURCE_PROVENANCE.json` for upstream commits and file hashes.

**[Full raw results are published here](https://github.com/aamitssharma07/prospective-memory-methods/releases/tag/research-snapshot-2026-10-25).**
All 84,259 inventoried files (approximately 259 GiB), including failed and
archived attempts, are preserved in 10.5 GiB of compressed Release archives.
All 317 assets passed remote checksum verification. Every original payload was
credential-scanned, hashed and verified after decompression; no research data
was changed or redacted. See [the raw-result guide](results/README.md).

Statements inside older context files about tracked `.env` or missing
submodules refer to the original research checkout, not this clean export.
No original research Git history, private environment file or nested `.git`
directory was copied here. Existing GitHub history is preserved without force pushes.

## Read and Analyze

The [comparison table](prospective-memory/docs/experiments/results/RESULTS.md)
and its CSV/JSON exports require no model server or API key. Current code and
test commands run from the main research folder:

```bash
cd prospective-memory
python -m unittest discover -s harness -p 'test_team_context.py'
```

## Restore Raw Results

Run these commands from the Git repository root, not from a child workspace:

```bash
python results/restore_results.py
python -m pip install zstandard
python results/restore_results.py --group 'PMBench-runs-core-four-qwen--qwen3-8b-*'
```

The first command only lists groups; it does not download anything. Use
`--all` for the complete 259 GiB collection, allowing additional space for
the compressed download cache. Downloads and extracted files are verified
against SHA-256 manifests; different existing results are never overwritten.
See [the archive guide](results/README.md) before restoring the full collection.
