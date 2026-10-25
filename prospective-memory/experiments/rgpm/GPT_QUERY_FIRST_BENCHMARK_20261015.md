# Query-first GPT benchmark: 2026-10-15

The user authorized the full benchmark after the successful integrated smoke.
Slurm job: **1535138**, `exp3-gpt-query-first-full`.
Submitted with `sbatch --parsable experiments/rgpm/jobs/run_query_first_benchmark.sbatch`.

Actor: GPT-5.4 (`openai/gpt-5.4`) through OpenRouter. Helper: Qwen3-8B
(`Qwen/Qwen3-8B`), local SGLang, BF16, nonthinking. Both use temperature 0
and max_tokens=768. One H100 is allocated for the helper.

Configuration matches passing smoke 1535096: source routing, scope grounding,
bounded priority and registration grounding enabled; actor guidance query_first;
query handoff legacy; query budget 1; step query budget 2; gate reporting and
action verification disabled. No model/memory/adapter logic changed for launch.

## Reused validation

The six-step GPT smoke passed all twelve checks, with TP 2, FP 0, FN 0 and exact
task sets on all six steps. Hosted smoke inference is not repeated.

The full launcher verifies all indexed smoke artifact hashes, the complete
55-file runtime source map, exact configuration, six-step trajectory, an
independent strict-invalid rescore and both zero-error quality limits. The new
helper projector identity must match the passing smoke's model revision,
precision, decoding settings and SGLang version. No API request is permitted
by this launcher before these checks pass.

Offline validation of the launch wrapper passed five tests: unchanged successful
reuse, changed source rejection, changed helper rejection, independent score
rejection, and forwarding benchmark configuration/limits without smoke calls.
The Slurm job repeats the existing 525-test offline preflight as well.

## Limits and artifacts

This is one 80-step run of `benchmark/data/synthetic_week_v9.json`, scenario
SHA-256 `94a45937da1363be19ccfdc2c188d132f23093041e30abd3ec22d64d70da8f24`,
matching the current GPT baseline.

Actor limit: 240 total attempts (including retries) and 3,000,000 actor tokens.
These bounds allow up to two queries and a choose action per step, without
guaranteeing completion if retries exhaust the limit. Token admission combines
known usage with conservative next-call reservation; it is not a dollar budget.
Budget exhaustion preserves an interrupted run and checkpoints. The launcher
does not automatically restart, sweep configurations or raise the limits.

- Console: `jobs/exp3-gpt-query-first-full-1535138.log`.
- Job provenance/preflight: `jobs/gpt-5-4-actor-helper-qwen3-8b-1535138/`.
- Reuse verification: that job directory's `reused_smoke.json`.
- Full outputs: `runs/query_first_v1/gpt-5-4-helper-qwen3-8b/sbpm/gpt-5-4-actor-helper-qwen3-8b-1535138/`.

Raw/parsed responses, provider IDs, TOK/DUR, actual query attempts, retries,
registration/revision/cancellation traces, per-step checkpoints, source snapshots,
query uptake and failure analysis follow the existing output contract. The
model runner supports resume; use the same source/configuration and output
directory. The launch wrapper also accepts --resume and retains the same caps.
The completed smoke and previous experiment outputs are not rewritten.

The launch-only scripts live under `jobs/`; their changes do not alter the
method's runtime source map. `reused_smoke.json` records the Python launcher hash
and links the exact passing smoke. Serving and actor provenance are explicit.

## Comparison

Compare only after all 80 steps finish. Historical matched targets:

| Arm | TP | FP | FN | Set F1 |
| --- | ---: | ---: | ---: | ---: |
| GPT-5.4 baseline | 53 | 6 | 28 | 75.71% |
| Previous Qwen3-8B helper method | 53 | 8 | 28 | 74.65% |

Report TP/FP/FN, exact sets, paired gains/losses, monitoring, cross-day/update
outcomes, invalid responses, queries, tokens, durations and provider-reported
cost alongside F1. Verify a matched PIS artifact before reporting that arm.
This inspected development dataset and one trial do not establish repeatability
or held-out superiority. No full result is claimed at submission.

## Canceled by user

The user requested cancellation after investigation exposed registration failures
in the additional classification review. Only job 1535138 was canceled with
`scancel 1535138`. Slurm confirms `CANCELLED by 1004`, elapsed 00:30:10, and
the job is no longer present in the active queue.

The run stopped with 55 of 80 steps checkpointed. All partial trajectories,
raw/parsed calls, memory history and checkpoints remain available. The stale
running status was archived as `status.before_user_cancel.json` before marking
the run interrupted. `cancellation.json` records the external stop separately.

Recorded GPT responses: 163, with 1,539,901 known tokens and provider-reported
cost USD 1.914268455. There were 164 actor call-start records: one request had
no saved response at cancellation, so its usage/billing is unknown. Report the
recorded cost as partial, not a final billing total.

This partial diagnostic must not be presented as a completed benchmark or
compared as a full-run F1. No restart or modified-code rerun was launched.
