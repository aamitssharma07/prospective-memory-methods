# Registration repair v4: local validation

User authorized local validation on October 20, 2026. Slurm job **1536924**,
`exp3-registration-repair-local-v4`, tests `focused_resolved_partition_v4`.

Actor and helper: `Qwen/Qwen3-8B`, local SGLang, BF16, nonthinking, temperature
0, max_tokens=768. The cached revision and serving command are recorded in
the job's helper provenance. Actor guidance is query_first, handoff legacy,
query budget 1, step query budget 2. Source routing, scope grounding, bounded
priority and registration grounding are enabled. Action verification and gate
reporting are disabled.

`LOCAL_ONLY=1` and `RUN_FULL=0` prevent hosted inference and a full benchmark.
The job runs the full offline preflight, eight routing cases, fourteen readiness
cases, ten registration cases, and only then the six-step integrated smoke.
Any failed diagnostic stops the job before smoke. The local smoke gate checks
execution and trace health; its FP/FN limits are unset, so inspect its score
separately. Passing this gate alone cannot establish an F1 improvement.

- Console: `jobs/exp3-registration-repair-local-v4-1536924.log`.
- Preflight and diagnostics: `jobs/qwen3-8b-actor-helper-qwen3-8b-1536924/`.
- Smoke: `smoke_artifacts/qwen3-8b-helper-qwen3-8b/sbpm/qwen3-8b-actor-helper-qwen3-8b-1536924/`.

All earlier run outputs remain in place. The new job records its own source
snapshots, raw/parsed model calls, tokens/durations, semantic decisions,
per-case results, memory snapshots, and artifact hashes.

## Outcome

Slurm finished **FAILED, exit 1:0**, elapsed **00:01:59**, because the
registration gate failed. The integrated smoke was never started.

| Check | Result |
| --- | --- |
| Offline tests | 541 passed: 441 method, 33 adapter, 67 Experiment 3 |
| Routing | 8/8 passed |
| Readiness | 14/14 passed |
| Registration | 9/10 passed |
| Integrated smoke | Blocked by registration gate |
| GPT calls | 0 |

The remaining failure is `provider_cue_is_not_new_request`. The helper treated
"Approval for the signed form has arrived. Please do it now." as distinct from
the already pending "Send the signed form when approval arrives by email."
Its comparison reason says the immediate command differs from the conditional
request. That reasoning fails to resolve the pronoun and recognize that arrival
of the existing trigger activates the same obligation. The compiler created
a second record. Both cached projections then produced the same concrete action,
"Send the signed form.", providing further evidence of duplication.

All other registration cases passed, including seven crowded-plan additions,
correct update targets, missing-target abstention, mixed cancellation/addition,
multiple occasions, a genuine new provider request, a recipient revision, and
an additional provider-requested occasion.

The registration diagnostic preserved 73 helper calls, 85,289 tokens and
36.307 seconds of summed call duration, with zero schema-invalid calls. These
totals cover registration diagnostics only, excluding routing/readiness probes
and serving/preflight time. The deliberate missing-target abstention is recorded
as unresolved; it is an expected protective outcome in that case. Schema validity
does not imply semantic correctness.

Next: address action reference resolution and same-occasion duplication, retain
the new-request/additional-occasion counterexamples, then repeat local validation.
A fresh passing live smoke and saved-failure replay remain prerequisites for
spending on the next GPT test. No benchmark F1 improvement is established.
