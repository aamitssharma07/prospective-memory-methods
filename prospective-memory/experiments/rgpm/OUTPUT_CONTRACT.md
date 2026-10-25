# Experiment 3 output contract

Status: required before any new inference, including smoke tests. This document
defines the target artifacts; it does not certify that the historical runner
already produces them. Output instrumentation and offline validation must pass
before a live run. Full experiment execution additionally requires user approval.

## Layout

Use the Experiment 1 analysis filenames and preserve the call-level cost detail
used by Experiment 2. Every run has a unique immutable identity:

```text
experiments/rgpm/
  smoke_artifacts/<model>/<variant>/<run_id>/
  runs/<scenario>/<model>/<variant>/<run_id>/
    manifest.json
    scenario.json
    source/
    status.json
    trajectory.jsonl
    calls.jsonl
    prompts.log
    memory.jsonl
    memory_calls.jsonl
    memory_snapshot.json
    snapshots/<step_index>.json
    checkpoints/<step_index>.json
    events.jsonl
    console.log
    server.log
    metrics.json
    steps.csv
    failures.csv
    failure_attribution.jsonl
    query_uptake.csv
    per_task.csv
    cost.json
    ANALYSIS.md
    artifact_index.json
  analysis/<analysis_id>/
    provenance.json
    results.json
    results.csv
    RESULTS.md
```

Smoke outputs never enter benchmark aggregates. A model slug is only a directory
label; record the exact actor and helper model IDs in the manifest. Different
helpers, configurations, seeds, or repeats always receive distinct run IDs.
Do not overwrite earlier runs, including failed or interrupted attempts.

## Provenance and joins

Version every machine-readable schema. The manifest records run ID, scenario
raw and canonical JSON hashes, actor/helper checkpoint revisions, serving stack
and versions, precision, hardware, decoding parameters, seeds when supported,
all method flags and budgets, sanitized launch commands, dependencies, source
hashes and snapshots, and start time. Record actor and helper output limits
explicitly; the requested Experiment 3 limit is 768. Missing provider metadata
is null with a reason, never an invented value.

Use stable run, step, cycle, call, attempt, intention and revision IDs to join
artifacts. A step key includes its day and scenario step ID. Registration or
startup calls without a step have a null step key and a named phase. Calls link
to their parent operation so retries can be distinguished from new decisions.

Never capture .env contents, credentials, authorization headers, or secrets in
URLs. Sanitize configuration and logs while retaining model-visible task data.

## Durable raw artifacts

- `trajectory.jsonl`: each completed step's actor output, selected task IDs,
  queries, invalid-response status and timing, written as the run progresses.
- `calls.jsonl`: every actor/helper attempt, including registration, projection,
  assessment, queries, warm-up, parsing repairs, transport retries and failures.
  Preserve the exact model-visible messages, schema and generation options,
  raw content and other returned response fields, parsed response (or null),
  parse/validation outcome, finish reason, error type/message, timestamps,
  duration, provider request ID when available, and token usage. Record a
  call-start event before dispatch so an interrupted attempt remains visible.
- `memory.jsonl` and `snapshots/`: source instructions, accepted/rejected store
  changes, revisions, cancellations, trigger projections, evidence references,
  ACT/CHECK/WAIT proposals, arbitration, actual queries, actor injections and
  completion acknowledgements. Preserve state at every committed step.
- `memory_calls.jsonl`: retain the existing helper diagnostic format, linked to
  canonical call IDs. It is an additional view, not extra billable calls.
- `events.jsonl`: startup, resume, call lifecycle, errors, retries, checkpoint
  commits and termination events. Retain console and server logs; for an
  externally managed server, record availability and provenance instead of
  fabricating a server log.

Ground truth belongs only to scenario/evaluation artifacts. It must never enter
model requests, memory state or invalid-response repair. Invalid predictions
remain empty and incorrect, including exact-match scoring on empty-answer steps.

## Failure tracing

The 2026-10-14 candidate also records `candidate_config`, `readiness_log`, and
`monitoring_log` in engine snapshots. Monitoring distinguishes offers, deferred
sources, priority yields, and actual query attempts. Scope-aware assessment
requests contain intention/revision IDs, the selected condition, and observation
receipt context; receipt time is never an invented event time.
Instruction intake also retains its public source channel. Registration-grounded
classification/compilation receive this provenance, derived from public `State`
messages. It is rebuilt from conversation history after resume. A cancellation
does not by itself count as successful modification coverage in the smoke gate.
Targeted classification reviews are named `registration_review` in call logs.
Their inputs retain the first classification and the same public source unit.
Compilation continues to require its existing target identity check.
Dynamic schemas record conservative slot options, exact-source span choices for
short requests, and response/citation bounds in the saved request. These are
generation constraints, not evidence of semantic correctness or scored success.

Offline `failure_attribution.jsonl` includes `observed_stages` with memory row
and call references. These are recorded behaviors, not automatic causal verdicts.
Unknown task-to-intention mappings remain explicit. Source-routing events retain
both the enclosing operation UUID and a separate `compiler_operation_id`.

Manifests record optional actor call/token limits and local-only execution.
Limits count retries and prior sessions. Unknown token usage or an interrupted
attempt prevents further actor calls when a token ceiling is active. The next
call uses a conservative byte-based prompt reservation plus its 768-token output
cap; this is an execution control, not exact provider billing. Cost reports
identify per-field known usage counts and partial token totals.

For every task outcome, retain enough evidence to follow the full path from
instruction receipt through registration, revision, assessment, injection and
actor response. A final memory snapshot alone cannot explain earlier failures.
Keep successful stage events too, so an analyst can locate the earliest observed
divergence and any later contributing failures.

Every stage event records its input references, call/attempt IDs when applicable,
intention ID and revision, before/after state or lossless state delta, output,
validation result, and machine-readable disposition/reason. Distinguish attempted,
accepted, rejected, deferred, skipped, not applicable and unknown. A skipped
stage records the gate, cache entry, budget or upstream condition responsible.

Required trace coverage:

| Stage | Evidence needed to diagnose a failure |
|---|---|
| Instruction intake | Exact received text, scope, source units and whether each unit reached the helper |
| Registration | Unit classification, proposed action/condition/sources, parse errors, validation rejection and actual insertion; retain units that produced no intention |
| Update/cancellation | Update text, candidate and selected targets, identity review, accepted/rejected patch and before/after revisions; retain unresolved targets |
| Retention/lifecycle | Expiry, deduplication, recurrence resets and completion acknowledgements, including who initiated each state change |
| Trigger/projection | Projection and cache binding, active day/time gates, supplied observations, cited evidence and ACT/CHECK/WAIT decision |
| Query handling | Requested source, remaining budget, arbitration/defer reason, actual execution and returned observation |
| Reminder delivery | Proposed reminder, exact injected content and the actor request that received it; distinguish proposal from delivery |
| Actor action | Actual response, parsed task selection, retries and scored outcome after receiving the reminder |

Produce `failure_attribution.jsonl` offline with run/day/step/task references,
linked intention revisions (possibly none or multiple), observed failed stages,
reason codes, evidence pointers and an attribution status: established by trace,
hypothesis, or unresolved. Keep task-to-intention alignment method and ambiguity
explicit; source spans are the join anchor when registration produced no record.
Evaluator task labels and expected updates are added only during offline analysis.

Examples of useful reason codes include `registration_not_inserted`,
`registration_parse_error`, `registration_rejected`, `update_target_unresolved`,
`update_rejected`, `stale_revision_used`, `day_gate_blocked`, `check_deferred`,
`trigger_wait`, `reminder_not_delivered` and `actor_omitted_task`. These describe
observable behavior, not automatically a defect: WAIT or rejecting an update
can be correct. Link a behavior to a scored failure only with supporting
evaluation evidence; do not invent a single root cause where several stages
could explain the outcome. A helper's stated reason is retained as its claim.

This must support questions such as: which instructions were never registered,
which updates failed and why, whether a correct reminder reached the actor,
and which failures followed query-budget exhaustion. Answers must be inspectable
from saved traces without repeating model calls. Version later human annotations
or revised attribution rules without modifying the underlying raw artifacts.

## Resume and completion

Atomically checkpoint at every completed step, retaining conversation, actor,
adapter and memory state, cursor, query budgets, recurrence/lifecycle state,
random state when applicable, and committed log offsets. A consistent commit
boundary must prevent duplicate scoring or skipped steps after interruption.
Retain previous checkpoints and unfinished attempts for audit.

Resume validates scenario, model, decoding, method and source fingerprints.
Configuration changes create a new run. Resume skips committed steps; any
repeated unfinished call receives a new attempt ID and remains in the cost log.
Record actual inference wall time separately from downtime between sessions.

`status.json` distinguishes running, interrupted, failed and complete. Completion
requires all expected unique steps, successful artifact validation, final memory
state and offline scoring. File existence alone never means a run is complete.
`artifact_index.json` lists artifact paths, sizes, hashes and schema versions
after finalization; partial runs remain explicitly incomplete.

## Offline analysis

All derived outputs must be rebuildable from saved artifacts without inference:

- `metrics.json`: scorer output, precision, recall, Set-F1, exact-match rate,
  TP/FP/FN, invalid responses, completion coverage and per-day/category metrics.
- `steps.csv`: Experiment 1-compatible day/step IDs, expected/selected IDs,
  TP/FP/FN, exact match, invalid details and query counts; add actor/helper
  calls, TOK, DUR and links to memory decisions and snapshots.
- `failures.csv`: every FP, FN, invalid or missing step, with evidence pointers.
  Model explanations are recorded claims, not established failure causes.
- `per_task.csv`: task/category labels and outcomes, including cross-day,
  updates, recurrence, hit/late/miss and linked steps. Record label provenance.
- `cost.json`: actor/helper and phase totals, prompt/completion/total tokens,
  retry/failed-call usage, call counts, latency distribution, inference wall
  duration and per-step costs. Keep unknown usage null with coverage counts.
  Separate warm-up overhead from scored workload and report both. Do not equate
  summed parallel call durations with wall time or double-count mirrored logs.
- `ANALYSIS.md`: readable score, cost, category and failure summaries.

Aggregates retain every repeat and variant, expose incomplete/failed coverage,
and compare base, base + author PIS, and base + RGPM using explicit run pointers.
Read Experiment 1/2 artifacts in place. Record scenario/configuration mismatches;
never silently pool unlike runs or select the best repeat as the headline.
Each analysis version records its input artifact hashes, code version and metric
definitions. Future plots and tables can be added without changing raw runs.

This supports new analyses of the recorded observations and decisions. It does
not provide counterfactual model responses or unrecorded provider internals.

The registration-repair candidate also stores `registration_log` within engine
snapshots and the before/after memory traces. Entries identify the instruction,
step and exact source unit, rejected classifications, bounded repair outcomes,
independent target selections, exact paragraph partitions, and per-operation
compiler failures. Helper calls distinguish `registration_repair`,
`registration_target_resolution`, `registration_target_action_match`,
`registration_reference_resolution`, `registration_occasion_comparison`, and
`registration_partition`. Comparison and reference-resolution responses are
retained separately, including rejected placeholder actions. Coalesced duplicate
cancellations retain each source change in the registration log. Recovered errors
remain visible; they are not necessarily final registration failures. Inspect
accepted changes and final intentions alongside the diagnostic entries.

Local registration gates have their own job-scoped directory with source hashes,
helper serving provenance, cases, raw/parsed calls and TOK/DUR, incremental
per-case results, complete memory snapshots, final status and an artifact index.
They are development diagnostics and must not be pooled with scored benchmarks.
Historical registration replays also retain the input memory-trace hash, source
line and step for each case, seeded public memory, and evaluator-only expectations.
Each case starts independently; these results are not counterfactual benchmark F1.

## Required offline validation before inference

1. A scripted fake-model run produces the complete bundle with joinable IDs.
2. Malformed and empty responses remain incorrect and preserve raw attempts.
3. Transport/parse failures preserve retries, token accounting and error rows.
4. Interrupt/resume yields the same committed trajectory and memory state as an
   uninterrupted scripted run, without replaying completed steps.
5. Regenerating analyses reproduces scores and costs from raw artifacts alone.
6. Completion validation rejects missing/duplicate steps and missing artifacts.
7. Scripted registration omissions, rejected updates, stale revisions, deferred
   queries and actor omissions can each be traced to their saved stage evidence.
   Ambiguous task alignment or insufficient evidence remains unresolved.

The historical `harness/run_memory.py` already writes source/scenario snapshots,
prompts, helper responses, memory logs, a final memory snapshot and metrics.
It does not yet satisfy this contract: unified attempt linkage, incremental
checkpoint/resume, complete step/task/cost exports and validation still require
implementation. Treat those as launch blockers, not completed capabilities.
