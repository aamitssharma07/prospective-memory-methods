# Revised-handoff GPT smoke: 2026-10-15

User authorized the integrated smoke after the two-call saved-prompt comparison.
Slurm job: **1535096**, `exp3-gpt-query-first-smoke`. Smoke only: `RUN_FULL=0`.

Actor: `openai/gpt-5.4` via OpenRouter. Helper: local `Qwen/Qwen3-8B` via
SGLang, nonthinking. Both use temperature 0 and max_tokens=768.

The method uses the consolidated scope/registration grounding, source routing
and bounded priority, with `ACTOR_GUIDANCE=query_first`, `QUERY_HANDOFF=legacy`,
query budget 1 and step query budget 2. Gate reporting and action verification
are disabled. The change from GPT smoke 1534994 is the query-first handoff;
inspect archived source/configuration for all implementation provenance.

The job runs offline preflight and 22 local helper diagnostics before hosted
smoke calls. The six-step smoke exercises registration, a recipient revision,
cancellation, an approval email trigger and a next-day time trigger. Acceptance
requires all ten execution checks and zero false positives/false negatives.
No full benchmark follows, including when all checks pass.

Actor admission limits: at most 24 attempts, counting retries, and 500,000
observed/reserved tokens. This is a token control, not a monetary estimate.
Existing raw/parsed responses, usage, durations, retries, memory traces,
checkpoints, source snapshots and analysis exports remain preserved.

Artifacts:

- Console: `jobs/exp3-gpt-query-first-smoke-1535096.log`.
- Local diagnostics/provenance: `jobs/gpt-5-4-actor-helper-qwen3-8b-1535096/`.
- Smoke: `smoke_artifacts/gpt-5-4-helper-qwen3-8b/sbpm/gpt-5-4-actor-helper-qwen3-8b-1535096/`.

Compare this development smoke with GPT smoke 1534994 (TP 1, FP 1, FN 1,
F1 50%, report one step late), not with the full 80-step baseline. A passing
smoke would support a subsequent controlled benchmark, not establish that
the method beats baseline F1.

## Completed result

Job 1535096 completed successfully, exit 0:0, after 00:03:10. Offline preflight
passed 441 method tests, 33 adapter tests and 51 Experiment 3 tests (525 total),
plus syntax/artifact/strict-invalid checks. All eight routing and fourteen
readiness diagnostics passed before the GPT smoke.

All twelve smoke checks passed: ten execution checks and both quality limits.
All six steps exactly matched the expected task sets. No invalid actor steps,
failed calls, helper semantic errors, late actions, update violations or extra
selections were recorded. Artifact index SHA-256 checks passed.

| GPT smoke | TP | FP | FN | F1 | Exact steps | Actor calls | Actor tokens | Reported actor cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Original handoff, 1534994 | 1 | 1 | 1 | 50% | 4/6 | 14 | 19,629 | USD 0.053111025 |
| Query-first handoff, 1535096 | 2 | 0 | 0 | 100% | 6/6 | 15 | 24,965 | USD 0.066639375 |

The revised trajectory queried clock and email at Monday m3, observed approval,
and selected the report at that same step. The current public menu resolved
the report handle to sending it to Lee after the recipient revision. The
canceled draft was never selected. No report was repeated at m4. Tuesday's
reminder was omitted at 08:55 and selected at 09:00.

State queries rose from eight to nine: six clock queries and three email
queries in the new smoke. Hosted cost is summed from usage.cost on all 15 GPT
responses; every response supplies cost and token usage. The total excludes
the earlier two-call replay and previous smoke, and local helper compute is
separate. The new smoke used 100 local helper calls and 149,887 helper tokens,
excluding the separate local diagnostics. Both actor/helper caps remained 768.

This is a positive result on the same inspected six-step development scenario,
not a full PMBench result. The separated single trials and prior inspection
do not establish repeatability, a causal effect size or general superiority.
It supports evaluating the revised method in one controlled 80-step GPT run
against the matched baseline F1 75.71% and prior helper-method F1 74.65%.

The full benchmark directory was not created. No automatic full run or repeat
followed this smoke. All raw/parsed responses, queries, memory changes,
checkpoints, TOK/DUR, costs and source/configuration snapshots are preserved.
