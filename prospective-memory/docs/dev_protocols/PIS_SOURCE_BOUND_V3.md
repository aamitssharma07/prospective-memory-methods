# Source-bound v3: layout coverage and reference-based evidence

Opt-in `pis_source_bound_v3`, engine `SourceBoundV3Engine`. Prior v2 and all
frozen outputs remain unchanged. This is a development candidate, not a measured
PM-Bench improvement until a new complete benchmark run establishes one.

Status updated 2026-09-23: selected compiler passes smoke04 and transfer01, but
strict batch04 remains FAIL at 4/5. A predeclared exploratory exception permits
the new full-week candidate now running; no completed PM-Bench score exists yet.

## Current selected candidate and exploratory exception

Batch04 restores the best earlier batch01 implementation plus seven generic
prompt-clarification lines, without the metadata reason field, per-operation
calls or promoted-context payload. Compiler SHA-256:
`e44a29ced01cb0a4bcd5e72f5ae0f0e532b91a9c05c7348c8edb70f1ca5d6062`.
Batch04 passes 4/5 cases, 18/19 fully correct first records, stage TP/FP/FN
26/1/1 (96.30% registration F1), zero errors, 36 calls/42,157 tokens/60.5 seconds.
All 19 complete requests were separately retained and lifecycle edits were
correct. One extra available watched clock source on a recurring visible-event
request fails the exact-source contract; no hard clock gate was invented.

On the same compiler, smoke04 completed 10/10 cases, 11/11 registrations,
ACT 7/0/0, 6 WAIT/2 CHECK, zero errors, 45 calls/43,037 tokens/68.35 seconds.
Transfer01 completed 10/10 cases, 12/12 registrations, ACT 11/0/0, 13 WAIT/3 CHECK,
zero errors, 58 calls/57,766 tokens/93.99 seconds at 00:24:37 UTC. All five V3
behavior runs pass artifact-consistency audits in
`../results/pis_source_bound_v3_behavior_20260923/README.md`. This is not a batch
gate pass, semantic proof, or held-out validation; all suites are development.

Before launch, the pair-root `PROTOCOL.md` declared a departure from the original
5/5 batch launch gate: allow one explicitly exploratory full 80-step run after
unchanged same-source smoke and transfer pass. Batch04's strict FAIL remains.
The extra clock source may consume query budget, enter evidence selection, or
affect recurring-notification deduplication when fresh clock IDs accompany reused
event evidence. It is not assumed harmless. Measure choices, queries and errors;
preserve every failed/tuned attempt and disclose development-based selection.

Full candidate `candidate-v3-01/` under
`../pmbench_fallback_audit/memory_results/qwen3-8b-pis-source-bound-pair-20260922-01/`
launched around 00:24:56 UTC, tool session 18866. Actor, baseline, scenario,
scorer and fallback remain unchanged. Do not edit runtime sources during the run
or report partial scores as a completed comparison.

## Why the revision exists

V2 passed 20 generic single-origin cases but stored only 1 of 10 initial requests in
its first full PM-Bench attempt. Whole-list extraction merged source lines,
omitted items, and invented unavailable sources. The run was aborted after 11
steps and retained without a completed score. This exposes a validation blind
spot: one intention per message did not test multi-request plans.

V3 processes each public layout unit separately: complete bullet entries with
indented continuations, headings, and paragraphs. Code—not the model—copies exact
source spans. The model classifies every unit as a request, update, cancellation,
restatement, context, fact, speculation, uncertain or unresolved compound. A
shared typed-metadata call uses only advertised source names. Only updates and
cancellations require an additional same-obligation identity check. Originals
remain authoritative; no status is completed from model selection.

Conditional imperatives are requests even without a "remind me" wrapper. A
classification can carry a known related-ID hint for an update/cancellation;
the compiler still independently resolves a typed target and performs identity
review. A hint is not automatic permission to mutate the referenced record.
Restatements, speculation, status reports and future announcements remain distinct
from new obligations. No benchmark task IDs or scored labels enter this process.

The assessor retains the v2 trigger-readiness semantics but cites current
observation references instead of generating text quotations. In the aborted
run, a 171-character observation was reproduced into a 160-character field with a
non-verbatim ending and rejected. V3 local e1/e2 references map back to original
host IDs; the adapter preserves exact original evidence text. Local handles also
avoid a new grammar-cache key for every host observation ID. Source/query/evidence
membership is constrained and revalidated in code. References establish
provenance, not that the evidence logically entails every prerequisite.
Generic entailment guidance accepts clear paraphrases and distinguishes requested
actions from their prerequisites; it does not treat identical words as necessary
or a future mention as present evidence. Numeric/readiness constraints still apply.

## Completed development attempts

Unchanged smoke expectations; every attempt has its own frozen sources and calls:

| Attempt | Full cases | Registered | ACT TP/FP/FN | Calls | Tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| V3 smoke01 | 3/10 | 4/11 | 3/0/4 | 27 | 21,125 |
| V3 smoke02 | 7/10 | 11/11 | 6/1/1 | 42 | 37,189 |
| V3 smoke03 | 10/10 | 11/11 | 7/0/0 | 45 | 41,872 |
| V3 smoke04 | 10/10 | 11/11 | 7/0/0 | 45 | 43,037 |

Smoke01 misclassified conditional imperatives as context/facts. Smoke02 recovered
registration, but rejected valid update/cancel hints and missed a clear paraphrase;
the failed cancellation produced an extra ACT. Smoke03, after the generic repairs
above, has 7 ACT, 6 WAIT, 2 CHECK and zero engine/API errors. Completed September 22
at 23:58:54 UTC. All three pass artifact-consistency checks in
`../results/pis_source_bound_v3_smoke_20260923/README.md`; an audit pass means
consistent saved artifacts, not a claim that a failed method passed its contracts.

The separate frozen batch/lifecycle rubric uses 19 distinct obligations and 27
stage-record checks. V2 batch01: 1/5 cases, 11/19 fully correct first registrations,
stage TP/FP/FN 17/2/10, 15 calls, 10,596 tokens, ten engine errors. V3 batch01:
3/5 cases, 17/19 fully correct first registrations, stage TP/FP/FN 25/2/2,
36 calls, 41,659 tokens, two engine errors; completed September 23 at 00:00:08 UTC.
Both have zero transport/decode errors. This is registration-contract scoring,
not trigger accuracy, ACT alignment or PM-Bench set-F1.

V3 batch01 failures motivated generic metadata refinement: preserve explicit
daily recurrence, avoid adding a clock source to a visible event alternative,
and return metadata only for the proposed operations rather than extra unchanged
targets. Actual revision/cancellation records were correct, but two rejected
duplicate metadata rows failed the strict zero-error lifecycle contract.

V3 batch02 then completed with 3/5 cases, 13/19 fully correct initial requests,
stage TP/FP/FN 17/10/10 (62.96% registration F1), 36 calls, 45,281 tokens and
87.1 seconds. Engine/transport/decode errors were zero. The event-alternative/
repeated-occasion case and duplicate-row errors were fixed, but all four shared
Wednesday restrictions were lost and two one-off audio tasks acquired recurrence.
Actual lifecycle target identity remained correct; initial strict-match failures
caused downstream stage failures. Thus the score regressed from batch01, and
zero runtime errors must not be equated with correct semantics. All five batch
attempts are retained in `../results/pis_source_bound_batch_development_20260923.md`.

The per-operation/promoted-context refinement was tested as batch03: 2/5 cases,
13/19 fully correct initial requests, stage 18/11/9, four day-guard events,
49 calls/59,132 tokens/123.9 seconds, zero transport/decode errors. It was not
selected. Batch04 and same-source smoke04/transfer01 above record the subsequent
smaller prompt-only candidate. Expectations and all failed attempts are unchanged.

## Validation and limits

Use frozen batch-registration cases plus the unchanged smoke/transfer suites.
Retain v2 batch results and every v3 attempt, full calls, errors, sources and
case hashes. The transfer suite is already development-tuned. The batch suite
was frozen before its first outputs and must remain unchanged; subsequent batch
tuning is also development. Its SHA-256 is
`01a047af4dd6c329ff333f00ee31f482d6ddea40e458423c3945ffbfd184840f`.
No benchmark labels enter prompts. Passing supports another full 80-step
comparison, not a generalization claim. The original gates were 10/10 smoke,
10/10 transfer and 5/5 batch; the predeclared exploratory exception above is an
explicit launch-policy deviation, not a weakened batch scoring rule.

Mechanical layout is not semantic task segmentation. Multiple independent actions
inside an unstructured paragraph may remain unresolved. Unit coverage does not
guarantee correct classifications, sources, metadata or target selection. The
compiler supports at most 64 units/32 operations per message; it does not establish
200-task efficiency. Cost grows with units and pending eligible intentions.
Complex calendars remain semantic after conservative hard-gate removal. Host
adapters still supply observations/capabilities and execute/acknowledge actions.
