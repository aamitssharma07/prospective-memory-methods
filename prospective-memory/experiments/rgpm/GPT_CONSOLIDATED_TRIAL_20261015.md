# Consolidated GPT trial: 2026-10-15

User authorized one GPT trial after reviewing the local validation results.
Slurm job: **1534994**, `exp3-gpt-consolidated`.
Submitted with `sbatch --parsable experiments/rgpm/run_consolidated_gpt.sbatch`.

Actor: `openai/gpt-5.4` through OpenRouter. Helper: `Qwen/Qwen3-8B`,
local SGLang on one H100. Both use temperature 0 and max_tokens=768;
the helper uses nonthinking mode.

Source routing, scope grounding, bounded priority and registration grounding
are enabled. Actor guidance is `none`; query handoff is `legacy`; query budget
is 1 and step query budget is 2. Gate reporting and action verification are off.
These memory/model settings match the locally validated consolidated candidate.

The launch adds optional smoke quality limits, without changing model logic.
All execution checks and both quality checks must pass before the full run:
zero false positives and zero false negatives on the six-step smoke. A failure
stops the job and preserves the diagnostic bundle. No automatic repeat or
parameter sweep is authorized by this launcher.

Actor admission limits, including retries:

| Stage | Maximum actor attempts | Actor token limit |
| --- | ---: | ---: |
| Smoke | 24 | 500,000 |
| Full 80-step benchmark | 160 | 2,000,000 |

Token limits use observed usage plus a conservative reservation for the next
request. They are not a dollar budget or exact provider billing. A limit stop
preserves checkpoints and records an interrupted run, not an incorrect answer.

Prelaunch offline preflight passed in `preflight_gpt_launch_20261015_v1/`.
The new regression verifies that an extra action or a miss blocks the quality
gate. The job repeats offline preflight, eight local routing diagnostics and
fourteen local readiness diagnostics before any hosted smoke calls.

Artifacts:

- Job console: `jobs/exp3-gpt-consolidated-1534994.log`.
- Job metadata and local diagnostics: `jobs/gpt-5-4-actor-helper-qwen3-8b-1534994/`.
- Smoke: `smoke_artifacts/gpt-5-4-helper-qwen3-8b/sbpm/gpt-5-4-actor-helper-qwen3-8b-1534994/`.
- Full: `runs/consolidated_v1/gpt-5-4-helper-qwen3-8b/sbpm/gpt-5-4-actor-helper-qwen3-8b-1534994/`.

The full directory is created only after all smoke gates pass. Per-run source
copies, configuration fingerprints, raw and parsed responses, calls, memory
traces, TOK/DUR, retry records, step checkpoints and analysis exports follow the
existing output contract. Existing results remain available.

Compare a completed full run with the matched GPT baseline (F1 75.71%, TP 53,
FP 6, FN 28) and the previous 8B-helper result (F1 74.65%, TP 53, FP 8, FN 28).
Include paired task changes, monitoring, updates, cross-day outcomes and costs.
The repeatedly inspected benchmark remains development data; one new score
does not establish reproducibility or held-out superiority.

## Observed result

Job 1534994 finished after 00:02:34 with exit 1:0 because the smoke quality gate
rejected the trajectory. The smoke itself completed all six steps. All ten
execution checks passed; both zero-error quality checks failed. Eight local
routing and fourteen local readiness diagnostics passed beforehand.

Smoke metrics: TP 1, FP 1, FN 1; precision 50%, recall 50%, F1 50%.
There was one on-time hit and one late action. Invalid actor steps and recorded
helper semantic errors were both zero. These six-step diagnostics are not
comparable with the historical full 80-step baseline score.

At Monday m3, the public scene mentions a new email notification. The actor
first queries clock. The next helper handoff explicitly proposes CHECK email
for the revised report request, but GPT chooses to advance with no task
selection. At m4 it queries email, observes the approval and selects the report.
That genuine delayed observation produces a late action: a missed on-time
selection at m3 and an extra selection at m4. This establishes actor failure to
take the offered check in this trace. It does not prove which alternative prompt
or query schedule would have succeeded. The memory update itself was accepted;
the problem was not an unregistered or stale-recipient request.

Actor usage: 14 calls, 19,629 total tokens. All 14 responses include usage and
cost. Their OpenRouter `usage.cost` fields sum to USD 0.053111025. This is
provider-reported cost for this smoke, not an estimate from published pricing.
Local helper diagnostics and calls incur local compute separately.

The full benchmark directory was never created. No further hosted call or
automatic retry was submitted. All smoke and diagnostic outputs are preserved.
Before another paid run, investigate query selection and actor uptake of CHECK
using these saved prompts and traces. This trial provides no new full-run F1.
