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

**Raw results are not yet uploaded.** Their full inventory is preserved under `results/`; split GitHub Release archives still require payload scanning, compression and upload. Do not rerun completed experiments to recover missing raw data.

The raw-result packaging job is CPU-only and includes all 84,259 inventoried
files (approximately 259 GiB), including failed and archived attempts. Each
payload is credential-scanned, hashed, compressed and verified after
decompression before it can be published. See [raw-result status](results/README.md).

Statements inside older context files about tracked `.env` or missing
submodules refer to the original research checkout, not this clean export.
No original research Git history, private environment file or nested `.git`
directory was copied here. Existing GitHub history is preserved without force pushes.
