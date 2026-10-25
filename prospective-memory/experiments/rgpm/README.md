# RGPM: Experiment 3

**Current handoff (2026-10-25):** read
[the RGPM context](../../docs/experiments/exp3_rgpm_context.md) and
[the current result matrices](../../docs/experiments/results/RESULTS.md).
Those pages distinguish the original 32-pair sweep, the 11 serving/checkpoint
consistency attempts and unfinished GPT combinations. They supersede stale
execution/readiness claims in the chronological documents below.

This directory is the organizational home for Experiment 3, our methodology.
The finalized full-dataset coverage requirements and deferred GPT-helper
follow-up are tracked in [TASKS.md](TASKS.md), with the exact pair/job mapping
in [launches/v15_finalized_targets.json](launches/v15_finalized_targets.json).
RGPM is the working name **Relevance-Grounded Prospective Memory**. The current
implementation lineage is called SBPM in older repository documents and evolved
from `pis_grounded` through source-bound and trigger-projection variants.

Start with [EXPERIMENT_CONTEXT.md](EXPERIMENT_CONTEXT.md). It separates our
method from the completed PMBench reproduction and the author-PIS reproduction,
lists the original owned source files, and records historical execution status.
For the current GPT improvement candidate, read
[CONSOLIDATED_READINESS_20261014.md](CONSOLIDATED_READINESS_20261014.md).
The GPT smoke outcome and subsequent query handoff revision are recorded in
[GPT_CONSOLIDATED_TRIAL_20261015.md](GPT_CONSOLIDATED_TRIAL_20261015.md) and
[QUERY_FIRST_REVIEW_20261015.md](QUERY_FIRST_REVIEW_20261015.md).
The full query-first trial was canceled after registration failures; see
[GPT_QUERY_FIRST_BENCHMARK_20261015.md](GPT_QUERY_FIRST_BENCHMARK_20261015.md).
The subsequent fixes and local validation are tracked in
[REGISTRATION_REPAIR_20261015.md](REGISTRATION_REPAIR_20261015.md). That candidate
requires a fresh passing smoke; the earlier GPT smoke cannot validate changed code.
The October 20 duplicate-registration follow-ups and historical replay gate are
tracked in [REGISTRATION_V5_VALIDATION_20261020.md](REGISTRATION_V5_VALIDATION_20261020.md),
including failed intermediate candidates and the latest test status.
The bounded GPT-5.4 / Qwen3-32B test is tracked in
[GPT_REGISTRATION_V15_SMOKE_20261020.md](GPT_REGISTRATION_V15_SMOKE_20261020.md).

Importable Python modules remain under `prospective_memory/` so package imports,
tests, and historical manifests stay valid. Experiment-specific commands,
configuration, reports, and future result pointers belong here.

Before any inference, including smoke tests, implement and validate the
[output contract](OUTPUT_CONTRACT.md). It specifies the run directory layout,
raw and parsed responses, memory history, TOK/DUR, retries, checkpoints and
offline analysis exports. The historical runner does not yet meet this contract.
The instrumented `run.py` now preserves call/step/checkpoint bundles and validates
them offline. Inspect each run's manifest and source snapshot for its exact
behavior; older outputs do not automatically inherit newer instrumentation.

Legacy harness outputs that predate this contract were moved out of the active
runtime paths on 2026-10-01:

- `experiments/rgpm/legacy_outputs_archived_20261001/results/`
- `experiments/rgpm/legacy_outputs_archived_20261001/smoke_artifacts/`

Treat them as recoverable development history only. New RGPM smoke and full-run
artifacts should not be mixed with this archive.
