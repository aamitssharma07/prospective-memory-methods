# V15 Runtime Audit

## Blocking Findings

### 1. Actor Context Rejections Affect Four Completed Runs

The stored F1 values rescore correctly, but some actor requests were rejected
by the server rather than answered by the model. These failures remain
empty/incorrect; the scores must not be described as pure model-quality
comparisons without disclosing the context failures.

| Job | Main | Helper | Rejected actor attempts |
|---|---|---|---:|
| 1538265 | Qwen3-0.6B | Qwen3-1.7B | 44 |
| 1538266 | Qwen3-0.6B | Qwen3-4B | 8 |
| 1537334 | Qwen3-0.6B | Qwen3-32B | 6 |
| 1538279 | Qwen3-32B | Qwen3-1.7B | 74 |

Attempts include retries and are not distinct failed-step counts. Exact
affected-step counts are in `report.json`. The source errors are preserved
in each run's `calls.jsonl`, `console.log`, and actor server logs.

Two different limits are involved:

- Qwen3-0.6B requests exceed the checkpoint's configured 40,960-token total
  context allowance. Example: 40,687 input tokens plus the required 768-token
  output reservation. This needs an explicit input-context policy or a
  documented supported-context extension; simply allocating more GPU memory
  does not establish a valid fix.
- Qwen3-32B job 1538279 has a 40,960-token model context but only 16,753
  effective KV-cache tokens; the server reports a maximum input of 16,747.
  Saved requests reach over 25,000 input tokens. Serving capacity is smaller
  than the advertised model window on this allocation.

Do not enable silent auto-truncation, silently increase the output cap, use
ground truth, or relabel the failed attempts. Replaying representative long
public inputs under a validated serving configuration should precede new full
runs. Any input-compaction policy changes the protocol and needs separate
regression tests and clearly versioned comparisons. Keep all original results.

### 2. Pending Ministral Checkpoints Differ From Prior BF16 Experiments

Queued jobs 1538287 through 1538294 request standard Ministral-3-3B/8B
`Instruct-2512` model IDs. Their cached `config.json` files specify FP8
quantization. Earlier Experiment 3 runs used `Instruct-2512-BF16` model IDs.
`prepare_server.py` resolves the requested repository and passes
`--dtype bfloat16`, but that flag alone is not proof of unquantized BF16
weights. Its provenance currently labels every checkpoint BF16.

Both explicit BF16 checkpoints are fully cached, with all indexed shards:

- 3B revision: `b6d637bef2393152b3da2b2fde72eecdee30557e` (two shards).
- 8B revision: `f6fae9795746f63c9be8344932f01275f3c63734` (four shards).

Correct and verify the checkpoint selection and actual quantization metadata
before resubmitting these eight pairs. Preserve model identity and correction
history in the finalized target map; do not silently call FP8 results BF16.

## Verification Performed

The separate, read-only audit script is
`experiments/rgpm/analysis_tools/audit_finalized_runs.py`. It does not regenerate
or overwrite original run outputs. Its machine-readable output is `report.json`.

- Seventeen completed runs checked, plus metadata/source checks on active run
  1538280. Thirty-two finalized targets accounted for.
- Completed trajectories have all 80 steps in scenario order, with per-step
  checkpoints and snapshots.
- Recomputed TP/FP/FN and F1 match saved metrics.
- Invalid-response fallback remains empty/incorrect.
- Actual call models, temperature zero, and 768-token caps match manifests.
- Method-relevant source hashes match the completed GPT-v15 run; saved source
  snapshots match their manifest hashes.
- Key artifact hashes, call-ID uniqueness, cost call counts, and unfinished
  attempt records checked without mismatches.
- Model semantic errors and malformed outputs are present, especially with
  1.7B helpers. These are measured quality outcomes, not grounds for excluding
  pairs from full-dataset evaluation.
- All 83 existing offline tests pass. They do not exercise GPU capacity or
  maximum-context workloads and therefore could not catch these limits.

Scope limit: full memory/event files were not all rehashed, and this audit is
not a complete proof of correctness or an exhaustive causal failure analysis.

## Job State and Recovery

At audit completion, jobs 1538281 through 1538294 are temporarily held before
execution. Active job 1538280 was left running; all completed work remains
untouched. No job was canceled, no experiment result was overwritten, and no
additional GPT inference was launched during this audit.

Before releasing the remaining jobs:

1. Validate a serving configuration against representative long actor inputs,
   including actual KV capacity on the allocated GPUs.
2. Decide and test any native-window overflow policy separately; do not hide
   context-budget changes inside this sweep.
3. Correct the eight pending Ministral jobs to the prior BF16 checkpoints and
   record actual checkpoint quantization/provenance.
4. Verify the active run for context rejections when it completes. Retain and
   flag the four identified affected runs; plan separately versioned recovery
   runs where appropriate, not selective replacement of low-F1 results.
5. Recheck the full 32-pair mapping, release corrected jobs, and continue with
   report-only smoke quality admission. Persist errors and costs for every pair.

Repeated helper assessment remains a major efficiency issue, but optimizing
the inference algorithm mid-sweep would confound this evaluation. Treat it as
a separately versioned follow-up.

## Subsequent User Decision

After reviewing the findings, the user requested: finish the current sweep
unchanged, then try improvements. All 14 audit holds were released; job
1538281 was verified running and the remaining jobs pending dependencies.
No inference, serving, or checkpoint settings were changed. The recovery
recommendations above are deferred follow-up work, not current admission
requirements. Retain the audit flags in all result interpretation, including
context-capacity failures and actual Ministral checkpoint quantization.
