# Experiment 3 Evaluation Tasks

## Full Local Pair Coverage

The [October 22 runtime audit](analysis/v15_runtime_audit_20261022/FINDINGS.md)
found actor context-capacity rejections and FP8/BF16 checkpoint differences.
The user subsequently requested finishing the current sweep unchanged before
trying improvements. All 14 temporary holds (jobs 1538281 through 1538294)
were released; job 1538281 was verified running. Defer serving, context,
checkpoint, and behavioral changes until after this sweep. Preserve and flag
the identified limitations in the final report; do not describe standard
FP8 Ministral checkpoints as unquantized BF16 or omit context failures.

- [x] Obtain full 80-step results for all 32 finalized actor/helper pairs.
- [ ] Verify each result's scenario hash, model identities, method flags,
  completion status, metrics, and artifact integrity.
- [ ] Track infrastructure failures and incomplete runs for recovery; do not
  count a failed smoke or a queued submission as a completed benchmark.
- [ ] Compare every completed pair with available matched baseline, PIS,
  and previous-method results. Report missing comparisons explicitly.
- [ ] Publish all pairs, including low F1, invalid outputs, registration/update
  errors, TOK/DUR, retries, and smoke diagnostics. Never hide poor performers.

The authoritative roster and selected original/replacement job mapping are in
[launches/v15_finalized_targets.json](launches/v15_finalized_targets.json).
Coverage means 32 complete full-dataset results, not merely 32 submissions.
If a genuine infrastructure blocker persists, report it explicitly rather
than inventing a score or silently dropping that pair.

## Deferred GPT Follow-Up

Task ID: `EXP3-GPT-V15-REMAINING-HELPERS`.
Status: submitted after the user requested running the GPT follow-up. Jobs
`1553051` (1.7B helper), `1553052` (4B), and `1553053` (8B) run sequentially;
the first was verified running and the other two pending dependencies.
The actual commands, authorized caps, job IDs, and result directories are in
[launches/gpt_v15_remaining_helpers_submitted_20261023.json](launches/gpt_v15_remaining_helpers_submitted_20261023.json).
The preparation record retains the exact model flags, budgets, submission arguments,
result-directory templates, source hashes, and launch checklist are saved in
[launches/gpt_v15_remaining_helpers_prepared_20261023.json](launches/gpt_v15_remaining_helpers_prepared_20261023.json).

- [x] Prepare the three job definitions without submitting or calling an API.
- [x] Add explicit report-only smoke admission and optional synthetic helper
  probes to the GPT launcher, preserving strict defaults for other launches.
- [x] Run the offline regression suite: 85 tests passed.
- [x] Verify unchanged preparation hashes, OpenAI authentication, and no duplicate
  completed/active updated-method runs, then submit all three authorized jobs.
- [x] Verify actual one-GPU partition/QoS and sequential dependency links.

- [ ] GPT-5.4 main + Qwen3-1.7B helper, updated methodology, full dataset.
- [ ] GPT-5.4 main + Qwen3-4B helper, updated methodology, full dataset.
- [ ] GPT-5.4 main + Qwen3-8B helper, updated methodology, full dataset.

Reuse the completed updated-method GPT-5.4 + Qwen3-32B result, job `1537307`;
do not rerun that pair. Earlier GPT/4B and GPT/8B results use older methods
and do not complete these tasks. The earlier updated GPT/8B trial was partial
and does not supply a complete 80-step result.

Before launching later: review the local sweep, recheck for completed matching
results, confirm paid-run timing and explicit call/token budgets, and use the
direct OpenAI GPT-5.4 actor with local helpers. Use the finalized v15 inference
settings and 768-token caps for both roles. Save all artifacts in fresh run
directories. Quality failures must remain visible without selectively
excluding pairs; retain execution and artifact checks. The prepared jobs set
`SMOKE_ADMISSION_POLICY=report_only` and `RUN_HELPER_PROBES=0`, matching the
local sweep. The live six-step smoke still runs with full response logging;
offline preflight, artifact validation, and budget guards remain mandatory.
No context-window, efficiency, or over-selection fixes are included.

Authorized per-pair budgets for this submission: smoke 24 actor calls /
500,000 actor tokens; full dataset 300 actor calls / 4,000,000 actor tokens.
Across all three pairs these caps sum to 972 calls and 13,500,000 tokens,
including smoke, not a dollar estimate. Keep missing usage unknown; stop when
the budget guard requires it. Sequential dependencies must be resolved and
verified at actual submission, after the local sweep, without duplicating work.

## Selective Serving-Consistency Reruns

User approved rerunning only mismatched-setting pairs while keeping v15.
Details and limitations:
[launches/V15_SELECTIVE_CONSISTENCY_RERUNS_20261023.md](launches/V15_SELECTIVE_CONSISTENCY_RERUNS_20261023.md).

- [x] Identify eight Ministral FP8/BF16 mismatches and three Qwen3-32B
  serving-capacity mismatches; keep the other 21 pair results unchanged.
- [x] Record historical serving references, exact expected checkpoint
  revisions, graph/memory settings, and explicit family-template exceptions.
- [x] Add optional GPU/serving checks and recorded public long-request probes;
  keep the inference algorithm unchanged. 89 offline tests passed.
- [x] Submit jobs 1553054-1553064, one 96GB-class NVL GPU per job, sequentially
  after GPT job 1553053. Verify resource requests and dependencies.
- [ ] Complete and validate all 11 reruns; preserve every original output.
- [ ] Compare rerun F1 and context errors with both original v15 and historical
  results, reporting all outcomes regardless of improvement.
