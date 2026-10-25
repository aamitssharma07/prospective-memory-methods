# ARCHIVE — historical handoffs

**Not the current state.** See `STATUS.md` at the repo root for that.

This file records what was true when each run was executed, newest first.
Do not rewrite earlier entries to match the present.

---

# Current Work: Generic Prospective-Memory Module

Last updated: 2026-09-23, after the V5 run completed and was scored.

## ADOPTED 2026-09-23: pis_trigger_fair_v5 + span extraction, Set-F1 52.2%

Run `…pair-20260922-01/candidate-v5-02-spans`. TP 42 / FP 38 / FN 39,
precision 52.5%, recall 51.9%, 26.1 calls/step, 3.17M tokens. Beats PIS (42.9%)
and the ~40-42% no-store baseline. See that run's RESULTS.md and
`docs/PROPOSED_METHODOLOGY.md`.

Two fixes landed today and are part of the adopted config:
- `--memory-extract-spans`: prose announcements stored the whole narration as
  BOTH action and condition. Now the action and trigger are two verbatim spans
  selected from the request, substring-checked, with fallback to the unit.
- cost flags (`--memory-skip-unevidenced`, `--memory-reuse-stable-waits`,
  `--memory-assess-batch-size 6`): 27.3 -> 9.2 calls/step on the v3 variant.

**The earlier V5 rejection is reversed.** V5 was judged before span extraction
existed; on garbage registrations a correct assessor cannot fire. With clean
records it matches V3 on F1 with better precision.

**Cross-day is an open limitation at 1/7** (PIS 3/7, no-memory 7/7). Three
scaffolding fixes were each verified working without moving it. Next test:
whether an agentic-tuned checkpoint (Qwen3.5-4B) changes it — if not, it is a
model limit and should be reported as such.

**Cheaper alternative if cost dominates:** `v3 + spans`, 48.3% at 9.2
calls/step, identical TP/FN, 13 more false alarms.

## Measured 2026-09-23: PM-Bench single-trace spread is ~4 F1 points

Three identical-code baseline runs scored **52.44%, 52.44%, 48.48%** (spread
3.95). The server is not bit-deterministic at temperature 0: 80 of 265
byte-identical prompts produced different completions. **Every optimisation
tried today lands inside that range**, so none is distinguishable from noise.

Cost work is therefore adopted: `--memory-skip-unevidenced`,
`--memory-reuse-stable-waits` and `--memory-assess-batch-size 6` together give
**27.3 -> 7.3 calls/step and 3.55M -> 1.89M helper tokens (3.7x / 47%)** at
50.31% F1, inside the baseline band. Flags default off; enable explicitly.

`--memory-assess-workers` (concurrency) is implemented and tested but **not
recommended**: it only moves wall clock, and its two runs sit at the low end of
the band. Leave at 1.

**Retroactive warning: any prior comparison in this project resting on a single
trace with a gap under ~4 points is unsupported.** Future work needs >=3 runs
per configuration reported as mean and range. The V3-over-baseline claim
survives (48.5-52.4 vs 42.0 historical / 24.3 matched) but must be quoted as an
interval, never as 52.4%.

## Previous state: V5 completed and REJECTED by its own rule; V3 remains best

Verified from `metrics.json` on 2026-09-23 (not from a session log):

| Run | Policy | TP | FP | FN | Precision | Recall | Set-F1 |
|---|---|---:|---:|---:|---:|---:|---:|
| `candidate-v3-01` | `pis_source_bound_v3` | 43 | 40 | 38 | 51.81% | **53.09%** | **52.44%** |
| `candidate-v5-01` | `pis_trigger_fair_v5` | 40 | 40 | 41 | 50.00% | 49.38% | 49.69% |

The predeclared gate for V5 was **both F1 and recall above V3**. V5 is below V3
on both (-2.75 F1, -3.71 recall), so by the rule stated before the run, **V5 is
rejected and `pis_source_bound_v3` remains the candidate.** The V5 run is
complete, valid and preserved; it is a negative result, not a failed run.

The launch-identity block below is historical: PID 120840 has exited and the run
finished. Both model servers (helper PID 91400 port 30002, actor PID 95202 port
30003) were still resident on 2026-09-23 and were left running, since another
session may be using them.

### V5's loss is the most informative result of this cycle

`pis_trigger_fair_v5` **wins every helper suite** — smoke 10/10, transfer 10/10,
trigger-roles 8/8 (V3 scores 3/8), temporal 4/4, batch 4/5 — and still loses on
PM-Bench. Helper-suite performance does not predict benchmark score. Do not
select a candidate on suite results, and do not report suite passes as
improvements. This is worth stating explicitly in any write-up, because the
suites were built precisely to be the cheap proxy the benchmark is not.

### Open question before any publication claim: which baseline?

Historical released baseline 34/47/47 = 42.0%. Every fresh matched baseline
78/484/3 = **24.3%** (precision 13.9%, recall 96.3%) — near-perfect recall from
selecting about six tasks per step, on the same scenario hash, actor budget and
empty fallback. The actor behaves nothing like the released trace and the cause
is unexplained. V3 clears both (+10.4 historical, +28.1 matched), so the sign of
the result is safe; the margin is not. Settle the comparator before writing up.
Suggested probe: diff actor prompts and selection traces between the historical
run and `…pair-20260922-01/baseline`, since only the actor differs.

### Reproduction succeeded, and exposed a metric problem

`candidate-v3-02-repro` (2026-09-23, current tree, `--memory-query-handoff
legacy`) scored **TP/FP/FN 43/40/38, Set-F1 52.44% — identical to
`candidate-v3-01`.** The V5 drift did not break V3; build on the current tree.

The tie is coincidence, not determinism. The runs differ on **17 of 80 steps**
(often the same task shifted a step or two), used 2,482 vs 2,987 helper calls
and 3.5M vs 4.1M tokens, and differ on late, miss, false_alarm, wrong_content,
check_time and state queries. Most significantly **cross_day_hit 0 -> 2 and
cross_day_miss 7 -> 5**, with update_hit 1 -> 2: the rerun is better on exactly
the delayed, later-channel triggers that define prospective memory, and Set-F1
reports the two runs as equal. **Report cross-day and update counts alongside
Set-F1.** Set-F1 variance across repeats remains unmeasured.

### Superseded: the 52.4% run was not reproducible from the current tree

`candidate-v5-01`'s 16 source hashes all match the working tree, so the tree is
the V5 code. `candidate-v3-01` matches 8 of 11: `run_memory.py`,
`adapters/pmbench.py` (gained `_explicit_query_handoff`) and
`pis_v2_registration.py` changed during V5 development. Rerunning
`--memory-policy pis_source_bound_v3` now would exercise the V5 adapter, not the
one that scored 52.4%. All 11 files are preserved under `candidate-v3-01/source/`;
restore from there, because `pis_source_bound_v3.py` itself is unchanged and the
drift is in shared runtime.

### Open bug carried by the 52.4% run

The calendar-clause guard reads an unrelated verb ("drop off an item") as
dropping a weekday restriction. Confirmed synthetically;
`results/calendar_guard_diagnosis_20260923.md`. Unfixed in `candidate-v3-01`, so
52.4% was scored with the bug active. A repair needs a rerun before the number
can be quoted as the fixed system's score.

Full verified index of every run: `docs/results_ledger.md`.

## Preserved 02:30 UTC handoff: V4 passes; first V5 smoke fails one case

The earlier live/integration statements below are historical and superseded by
the launched-run checkpoint above; failed outcomes remain part of the record.

The latest completed full PM-Bench run is still source-bound V3:
**43 TP / 40 FP / 38 FN, 52.4390% set-F1, 53.0864% recall**. This improves F1
over historical our PIS (42.9066%) but loses 19 true positives. Recovering recall
remains the goal; no full V4 or V5 PM-Bench result exists at this handoff.

The unchanged eight-case trigger-role development diagnostic progressed as follows:

| Method / attempt | Passed cases | Registration | ACT TP / FP / FN | ACT alignment F1 |
| --- | ---: | ---: | ---: | ---: |
| V3 plus post-run calendar fix | 3/8 | 8/8 | 3 / 0 / 6 | 50.0% |
| V4 trigger projection, 01 | 7/8 | 8/8 | 7 / 0 / 2 | 87.5% |
| V4 trigger projection, 02 | 8/8 | 8/8 | 9 / 0 / 0 | 100.0% |

All three artifact-consistency audits pass in the
[preserved three-attempt comparison](../results/pis_trigger_role_comparison_20260923_02/README.md).
V4 caches a source/config-bound static distinction between the action still to
perform and the readiness question. Attempt02 adds a generic distinction between
independent repeated activation occasions (OR) and genuine joint prerequisites
(AND). Original expectations and failed attempts are retained. These are
development-tuned helper-only contracts, not PM-Bench scores, held-out validation,
actor uptake or execution success.

The selected next combined candidate is **`pis_trigger_fair_v5` plus explicit query
handoff** (`--memory-query-handoff explicit`). It retains V4 projection and the
bounded calendar repair, adds fair source-level CHECK arbitration, and explicitly
hands requested observations to the actor/host query path. Projection is not
evidence or completion; current-source, queryability and budget constraints remain.
Standalone `sentence_units` and partial-WAIT `advisory_guidance.py` are **not included**.
The integration checkpoint passes **499 core tests and 52 runner/audit tests**;
these scripted checks do not establish model-quality improvement.

V5 smoke01 completed at **02:30:20 UTC** (former tool session 73170): **9/10 cases**,
11/11 registrations, ACT **6 TP / 0 FP / 1 FN**, zero engine/protection/transport
errors, 57 calls including preflight, 54,984 tokens, 89.29 seconds. Raw artifacts:
`prospective_memory/results/qwen3-8b-pis-trigger-fair-v5-smoke-20260923-01/`.
The failed `multi_source_conjunction` case exposes a projection fidelity error:
an exact-time action conditioned on approval received by email became approval
strictly before that time, with an invented recipient/delivery method; the
assessor then rejected approval at the exact time. Zero runtime errors is not
semantic correctness. This helper smoke does not evaluate actor query uptake.

Root is refining only the generic projection guidance to preserve time operators
and distinguish evidence sources from action recipients/methods, then rerunning
the unchanged suites. No follow-up result is claimed here and **no full V5 run
has launched**. Runtime/harness sources remain root-controlled and frozen during
each live attempt; this handoff changes context documents only.

## Preserved 02:01 UTC handoff: completed V3; later integration status superseded above

The full-benchmark result below remains current. Statements about V4 being
untested or no next candidate being selected describe this earlier handoff only.

The full 80-step `candidate-v3-01` completed with exit 0. Independent source/hash,
snapshot-restoration and native-rescoring checks passed; the fresh baseline and
candidate have identical state-aware due occurrences. Evaluator PID 104037
(start ticks 44945442, session 18866) has finished; do not keep monitoring it as
active. Root is keeping helper server 91400 and actor server 95202 alive for the
next experiment. Recheck exact process identity before any control action.

| Completed method | TP | FP | FN | Precision | Recall | Set-F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Fresh matched plain baseline | 78 | 484 | 3 | 13.8790% | 96.2963% | 24.2613% |
| Historical authors' PIS, not rerun | 46 | 153 | 35 | 23.1156% | 56.7901% | 32.8571% |
| Historical our PIS, not rerun | 62 | 146 | 19 | 29.8077% | 76.5432% | 42.9066% |
| New source-bound v3 | 43 | 40 | 38 | 51.8072% | 53.0864% | 52.4390% |

V3 gains **9.53 F1 percentage points over our historical PIS**, but finds **19
fewer correct on-time occurrences** and misses 19 more. Relative to its fresh
plain baseline, F1 gains 28.18 points while TP falls by 35. This is an observed
precision/recall trade-off, not clean prospective-memory improvement or goal
closure. Historical arms were not rerun as matched controls for this candidate.

Audited report: [completed pair](../results/pis_source_bound_pmbench_20260923_01/README.md),
[experiment notes and next targets](../results/pis_source_bound_pmbench_20260923_01/EXPERIMENT_NOTES.md),
[method 3 archive entry](../results/baseline_comparison/METHOD_3_RESULTS.md).
Raw pair remains `harness/memory_results/qwen3-8b-pis-source-bound-pair-20260922-01/`;
the aborted v2 `candidate/` remains unscored and untouched.

Candidate cost: 5,372.587 seconds (89.54 min), 2,987 helper calls, 4,096,170 helper
tokens excluding grammar probe and actor tokens; 116 queries including 92 clock.
Adapter deliveries: 59 ACT / 147 CHECK / 7,641 WAIT across 196 cycles; these include
code decisions and cached ACT redelivery, not distinct successful actions. No
actor fallback/model-error steps, helper API/JSON errors, missing usage records
or length finishes. There are **32 engine guard/rejection events**: 21
`pis_decide`, 10 `v3_day_guard`, one `v3_clock_guard`; zero transport errors is
not zero semantic/engine failure. Final bank: 67 pending records, not 67 successes.

The predeclared exploratory exception remains part of the result: batch04 was
**4/5 strict FAIL**, 18/19 fully correct initial records, not a gate pass. Same-source
smoke04 and transfer01 each passed 10/10 before this one full run was allowed.
All failed development attempts and the original expectations are retained.
See the pair-root `PROTOCOL.md` and the notes for exact hashes/configuration.

Next target: recover recall through generic trigger/action-role interpretation,
query handoff and registration/gate correctness, without benchmark-specific
rules. Hidden-channel recall is 1/15; visible-event recall 26/42; time recall
16/24. These diagnostic counts do not establish which component caused a miss.
No next full-week candidate has been selected. The unchanged eight-case
trigger-role diagnostic on current V3 plus the post-run calendar fix completed
at 02:01:06 UTC: **3/8 cases**, 8/8 registrations, ACT TP/FP/FN **3/0/6**
(50% helper ACT-F1), 16 WAIT, zero engine/protection/transport errors. Cost:
36 calls **including preflight**, 35,469 tokens, 47.54 seconds. Raw run:
`prospective_memory/results/qwen3-8b-pis-source-bound-v3-trigger-roles-20260923-01/`.
Observed readiness-versus-completion misses motivate an opt-in V4 comparison on
the SAME frozen cases. V4 integration is now underway, but it has not been live
tested. This helper-only diagnostic is not another PM-Bench score or an isolated
measurement of the calendar repair's effect.

Future work remains separate from the evaluated v3:

- The [calendar-guard false-positive diagnosis](../results/calendar_guard_diagnosis_20260923.md)
  led to a bounded repair **integrated only after this completed run was audited**.
  `calendar_clause_guard.py` is now included in runner/diagnostic source snapshots;
  current V2-registration SHA is `c5dcb06266764268e73f0cd374d8707f3070962d68aaa1a32865be1701d365a6`.
  Frozen `candidate-v3-01` did not use this fix. The later helper diagnostic above
  uses it but does not isolate its effect; no repaired full-week score exists.
- V4 `trigger_projection.py` / `pis_trigger_projection.py` cache source/config-bound
  static action/readiness interpretations, not truth or completion. Opt-in diagnostic,
  runner and report integration is now underway; it remains live-untested and was
  not used by the completed full-week candidate.
- `advisory_guidance.py` is a standalone partial-WAIT formatter: retain ACT/CHECK,
  display at most four prioritized WAIT entries, distinguish uncertainty from
  falsehood, and treat absence from ACT as no ban. It is not imported by the
  adapter; no packaging ablation or measured benefit exists.
- The frozen [eight-case trigger-role diagnostic](../prospective_memory/TRIGGER_ROLE_PROTOCOL.md)
  has 19 rounds (9 ACT, 10 WAIT), eight obligations and 27 record checks, SHA-256
  `2494810e84cddae77bdcfeb919b9e0a971fdaa7ac9df7b8b322e6b97b0bcc8e5`.
  It is development data informed by known failure classes, not held-out validation.
  Its first live V3 result is recorded above; expectations remain unchanged.

The completed-result handoff had **420 core tests and 47 runner/audit tests**;
the subsequent calendar integration passes **425 core tests**.
These include unintegrated prototypes and do not measure model improvement. No
runtime/scorer, original baseline CSV, case expectation, or historical raw result
was changed by this documentation update.

## Archived 00:57 UTC handoff: candidate was running; superseded above

The following records the pre-completion state. Its monitoring instructions and
"no completed score" statements are historical, not current instructions.

At approximately 00:57 UTC, the candidate had reached about 39/80 steps and was
still running: PID **104037**, UID **1000**, start ticks **44945442**, tool session
**18866**. Root reverified all **11 runtime-source hashes unchanged**. These are
dated progress observations, not a live status endpoint or a completed score;
recheck identity before process control. The predeclared exploratory exception
below remains in force, and batch04 remains a strict 4/5 FAIL. Do not edit any
active runtime source, actor guidance, scenario or scoring while this run continues.

Two separate future-work findings are available without changing this candidate:

- Confirmed deterministic calendar-guard false positive, diagnosed with generic
  synthetic text/scripted metadata: an unrelated physical-action bullet such as
  "Drop the spare cable" contaminates a shared weekday heading and causes valid
  weekday gates to be removed. Report: `results/calendar_guard_diagnosis_20260923.md`.
  The proposed bounded clause-aware repair is **not implemented** while runtime
  is frozen. This diagnosis does not establish its effect on completed PM-Bench scores.
- An **unintegrated future V4 prototype** exists in
  `prospective_memory/trigger_projection.py`, `prospective_memory/method/trigger_engine.py`,
  `tests/test_trigger_projection.py` and `tests/test_pis_trigger_projection.py`.
  It caches static action-to-perform/readiness-question interpretations, not
  current readiness truth, with explicit model/config and source bindings.
  Authoritative active-status transitions can rebind without inference; closure
  or changed source/semantics invalidates the view. Missing/unsupported views
  fall back to V3 assessment. There have been **no live model calls**, no active
  runtime imports and no CLI selector for this prototype. All 379 scripted core
  tests pass; this is engineering validation, not measured memory improvement.
  It is not part of `candidate-v3-01`. Prior WAIT/actor-advisory ideas remain
  proposals only; no actor-guidance change has been integrated into the run.

V3 batch04 passes 4/5 strict cases, with 18/19 fully correct initial records,
stage TP/FP/FN 26/1/1 (96.30% registration F1), zero engine/API errors, 36 calls,
42,157 tokens and 60.5 seconds. All 19 complete requests were preserved separately
and lifecycle edits were correct. The sole failure is an extra available watched
`clock` source on a correctly recurring visible-event request, without a hard
clock gate. The strict batch result remains **FAIL**, not 5/5.

This compiler restores the batch01 implementation plus seven lines of generic
prompt clarification only: no metadata reason field, per-operation calls or
promoted-context payload. Compiler SHA-256:
`e44a29ced01cb0a4bcd5e72f5ae0f0e532b91a9c05c7348c8edb70f1ca5d6062`.
Smoke04 on the same source passes 10/10, 11/11 registrations, ACT 7/0/0,
6 WAIT/2 CHECK, zero errors, 45 calls, 43,037 tokens and 68.35 seconds.

Transfer01 completed at 00:24:37 UTC: 10/10 cases, 12/12 registrations,
ACT 11/0/0, 13 WAIT/3 CHECK, zero errors, 58 calls, 57,766 tokens, 93.99 seconds.
Raw run: `prospective_memory/results/qwen3-8b-pis-source-bound-v3-transfer-20260923-01/`.
It uses the same compiler and assessor as smoke04; all five completed V3 behavior
runs pass artifact-consistency checks in
`results/pis_source_bound_v3_behavior_20260923/README.md`.

Before candidate launch, root recorded an exploratory exception in the pair root
`PROTOCOL.md`: if unchanged smoke and transfer both pass on this SAME source,
permit one new 80-step run
despite the still-failed 4/5 batch gate. This is a disclosed departure from the
original 5/5 launch requirement, not a changed rubric or retroactive pass.
An extra clock source can spend query budget, affect evidence selection, or
permit fresh clock IDs to influence recurring-notification deduplication alongside
reused event evidence. Measure these risks; do not presume the extra source harmless.
Selection is development-tuned, not held-out validation or proof of correctness.

Full evaluation is now running in tool session **18866**, launched around
00:24:56 UTC, at
`harness/memory_results/qwen3-8b-pis-source-bound-pair-20260922-01/candidate-v3-01/`.
Verified evaluator identity: PID **104037**, UID **1000**, start ticks **44945442**;
recheck identity before any process-control action. `LAUNCH.json` records launch;
runtime hashes match batch04, smoke04 and transfer01. Do not edit runtime sources,
prompts, adapter, scenario or scoring during the run. Root manages evaluation.
Initial bank retains 10/10 public request lines with zero initial engine errors
(aborted v2 retained 1/10), but early assessment still confuses a breakfast trigger
with already-completed medication. These are partial observations, not a new score.
The v2 `candidate/` remains aborted and untouched. No completed v3 PM-Bench score
exists yet; do not report partial trajectories as completed performance.

Continue on the same Qwen3-8B BF16 model. The goal remains a generic plug-and-play
prospective-memory helper, not benchmark-specific trigger rules. No new completed
candidate PM-Bench result exists. The first v2 full-week candidate was aborted;
its fresh 80-step baseline remains complete at 24.2613% set-F1.

New opt-in `pis_source_bound_v3` visits every public layout unit and copies exact
source spans in code. The model classifies each unit; typed source choices are
restricted to advertised host capabilities. Updates/cancellations undergo an
independent same-obligation review. Visiting units is not proof of correct recall.

| Completed helper run | Full contracts | Required registrations | ACT TP/FP/FN | Calls | Tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| V3 transfer01 | 10/10 | 12/12 | 11/0/0 | 58 | 57,766 |
| V3 smoke04 | 10/10 | 11/11 | 7/0/0 | 45 | 43,037 |
| V3 smoke03 | 10/10 | 11/11 | 7/0/0 | 45 | 41,872 |
| V3 smoke02 | 7/10 | 11/11 | 6/1/1 | 42 | 37,189 |
| V3 smoke01 | 3/10 | 4/11 | 3/0/4 | 27 | 21,125 |

Smoke and transfer use their own unchanged cases, not one common test. Raw
directories for smoke01–03 are
`prospective_memory/results/qwen3-8b-pis-source-bound-v3-smoke-20260922-0N/`;
latest is `qwen3-8b-pis-source-bound-v3-smoke-20260923-04/` under the same root.
All five pass artifact-consistency audits in
`results/pis_source_bound_v3_behavior_20260923/README.md`. These are development
helper contracts and occurrence-aligned ACT counts, NOT PM-Bench scores,
semantic correctness guarantees, or demonstrated actor benefit.

Smoke01 misclassified conditional imperatives as docs/facts. A generic
reason-first classifier correction restored registration in smoke02, but valid
update/cancel target hints were rejected by an overly restrictive field contract;
the cancellation miss caused an extra ACT. The assessor also rejected a clear
paraphrase. Latest generic fixes accept known related-ID update/cancel hints
without bypassing independent target resolution/review, and explicitly assess
semantic entailment rather than requiring identical words. Smoke03 passed all
10 cases with 7 ACT, 6 WAIT, 2 CHECK, zero engine/API errors, and 48.7 seconds.

V3 also replaces generated short evidence quotations with local references
`e1`, `e2`, etc., mapped back to original host observation IDs before delivery.
This addresses a 171-character observation that the v2 run compressed into a
160-character quote with a non-verbatim ending. Original evidence text remains
unchanged in helper inputs and actor guidance. Valid IDs prove provenance only.
V2 runtime behavior is unchanged. Earlier pre-launch scripted verification was
314 core and 47 runner/audit tests, including an 80-step fake-model run; the new
379-core-test total above also covers the separate unintegrated prototype.
Smoke03 used an earlier compiler and did not validate batch02/batch03. Smoke04
and transfer01 are completed checks for the selected batch04 compiler.

The independently authored, frozen five-case batch/lifecycle suite contains
19 distinct obligations and 27 stage-record checks, including multiple requests
from one message. Its registration rubric is separate from ACT/PM-Bench F1.

| Completed batch run | Full cases | Fully correct first registration | Stage TP/FP/FN | Calls | Tokens | Engine errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| V3 batch04 | 4/5 | 18/19 | 26/1/1 | 36 | 42,157 | 0 |
| V3 batch03 | 2/5 | 13/19 | 18/11/9 | 49 | 59,132 | 4 |
| V3 batch02 | 3/5 | 13/19 | 17/10/10 | 36 | 45,281 | 0 |
| V3 batch01 | 3/5 | 17/19 | 25/2/2 | 36 | 41,659 | 2 |
| V2 batch01 | 1/5 | 11/19 | 17/2/10 | 15 | 10,596 | 10 |

All five have zero transport/decode errors. Batch03's model incorrectly privileged
host weekday over explicit source context; the guard removed four unsupported
day gates. Source/time fields and restatement/lifecycle handling also regressed.
Additional calls did not establish better correctness.

V3 batch02 completed in 87.1 seconds
with stage-record F1 62.96%, down from batch01's 92.59%. It fixed the event
alternative/repeated-occasion case and eliminated duplicate-row errors, but lost
shared Wednesday metadata on all four requests and incorrectly made two one-off
audio tasks recurring. Actual lifecycle targets/updates remained correct; failed
initial matching anchors caused repeated strict lifecycle failures. Zero runtime
errors therefore did not mean better semantics or permit benchmark promotion.
Report: `results/pis_source_bound_batch_development_20260923.md`.

Earlier V3 batch01 completed in 61.9 seconds. Its two substantive
metadata errors: an every-day obligation was marked nonrecurring, and a visible
event alternative acquired an extra clock source. Actual revision/cancellation
records were correct, but duplicate unchanged-target metadata rows were emitted
and rejected as two errors, so the strict lifecycle case still failed.

Raw first batch directories: `prospective_memory/results/qwen3-8b-pis-source-bound-v{2,3}-batch-20260922-01/`.
Later attempts: `prospective_memory/results/qwen3-8b-pis-source-bound-v3-batch-20260923-0{2,3,4}/`.
Frozen cases hash: `01a047af4dd6c329ff333f00ee31f482d6ddea40e458423c3945ffbfd184840f`.
V2 failures included non-exact quotations, source/recurrence errors and malformed
update IDs. Every first attempt remains intact; later batch tuning is development.

Root manages inference. Next: monitor the frozen new candidate, then independently
audit a completed 80-step trajectory against the unchanged actor/scenario/scorer
and existing completed baseline. Track false/missed choices, ACT/CHECK/WAIT,
queries, errors and helper costs. Preserve every failed attempt; never relabel
batch04 as a strict pass, change expectations, or overwrite the aborted run.

## Preserved aborted v2 candidate and prior launch history

Pair root: `harness/memory_results/qwen3-8b-pis-source-bound-pair-20260922-01/`.
The candidate launched at 23:32:05 UTC after v2 smoke04 and transfer03 each passed
10/10. Across those suites it had 23/23 registrations and 18 correct ACT
occurrences, no extra/missed ACT or engine errors. Transfer was development-tuned,
not untouched held-out validation. Eight prior diagnostics were independently
audited in `results/pis_source_bound_development_20260922/README.md`.
Smoke04 used 43 calls/30,237 tokens; transfer03 used 56 calls/43,168 tokens.

The full candidate was then explicitly stopped after 11 choose steps/28 memory
cycles, 140 logged helper calls/125,751 tokens: its initial bank retained only
1 of 10 explicit request lines. Source copying merged/changed whitespace, five
daily requests were omitted, and two used unavailable invented sources. Later
restatements became additions and a revision attached to a different action.
This demonstrated a blind spot in the earlier mostly single-origin fixtures.

`candidate/ABORTED.json`, console, public prompts, calls, memory snapshots and
frozen sources/scenario remain intact. No final trajectory or candidate score
was written. Evaluator 96290/start 44627747 was verified and terminated; its old
session 56382 is not active work. The completed baseline is 78 TP/484 FP/3 FN,
8 queries, zero fallback. Model/checkpoint/scenario/scorer stay unchanged;
actor output cap 768, helper cap 4096, check budget 1, step-query budget 2.

Previously recorded server identities (recheck before any process action): helper
parent 91400/start 44482907, worker 91676/start 44483931, GPU0/port30002; actor
parent 95202/start 44590922, worker 95477/start 44591939, GPU1/port30003. These
servers remain allocated for the root-managed repair workflow. No GitHub push.

Historical entries below describe state at the time and are superseded by this
handoff; their old "next" actions and process-status statements are not current.

## Earlier iteration: source-bound helper passes the unchanged smoke suite

User requested continued iterations until measured improvement. Added opt-in
`pis_source_bound` / `SourceBoundPISEngine`, policy `pis_source_bound_v2`;
previous policies and all historical results retained. Compiler now separates
full-source obligation extraction from typed compilation, with no ADD reviewer
requiring an old target. Revisions retain ID, original specification and exact
chronological update. The action field intentionally holds the complete request,
not a clean action-only summary. Clock grounding uses full source messages.
Assessment uses all_conditions_met plus an optional query source and exact current
evidence. Queries are schema-constrained to this cycle's legal host capabilities.

Same Qwen3-8B BF16 checkpoint, temperature0, nonthinking, helper4096 tokens.
Frozen original 10-case smoke expectations unchanged:

| Attempt | Cases passing | Registered origins | ACT TP/FP/FN | Errors |
|---|---:|---:|---:|---:|
| Prior grounded v1 | 0/10 | 6/11 | 3/1/4 | 1 unexpected + 5 protections |
| Source-bound 01 | 6/10 | 11/11 | 7/0/0 | 4 invalid requested sources |
| Source-bound 02 | 10/10 | 11/11 | 7/0/0 | 0 |

Runs under `prospective_memory/results/qwen3-8b-pis-source-bound-smoke-20260922-0{1,2}/`.
02 completed 23:18:32 UTC,43 calls,24,198 tokens,65.3s,7ACT/6WAIT/2CHECK.
This is helper-only diagnostic improvement, NOT a new PM-Bench score or proof
of generalization. First separately authored transfer test completed at
`prospective_memory/results/qwen3-8b-pis-source-bound-transfer-20260922-01/`.
Transfer cases SHA98d289d230b2ee4ad41d6d6b0094dfecbb0a4786871c2f76a1e8d0ec93499a5a;
10cases/12obligations/21ticks; expectations frozen before any live outputs.
Transfer01:8/10 contracts,12/12 registrations,11ACT TP/1FP/0FN,4CHECK/11WAIT,
56calls/33,798tokens/76.8s; no transport/unexpected errors,1clock protection.
Failures: equality incorrectly satisfies strict 'below'; insufficient elapsed
duration prompts an unnecessary wall-clock query. Compiler also invented weekday
restrictions absent from the relative-time request, not checked by that fixture.
Now refining generic numeric/duration assessment and source-grounded day gates.
Any transfer rerun is explicitly development-tuned; first-attempt evidence retained.
All225 core plus33 audit/runner scripted tests pass. Source/case snapshots and
all raw calls retained per attempt. A separate report/audit is being prepared.

Owned helper server is RUNNING on GPU0/port30002: parent91400/start44482907,
worker91676/start44483931. Do not use the stopped v1 server identities below.
GPU1 has not yet been allocated. Next: rerun/audit both unchanged diagnostics; if they
pass, fresh plain-baseline + full80-step PM-Bench candidate comparison using
GPU1 actor/port30003. No new PM-Bench result or GitHub push yet.

## Latest handoff: grounded PIS live smoke failed; do not launch PM-Bench yet

User approved the small live validation. Added `evaluate_pis_grounded.py`, a frozen
10-case generic fixture and 17 harness tests. Before freezing, fixed a real PIS
sidecar bug: a rejected second same-message revision could otherwise install its
clock over the accepted record. No prompt/policy tuning during/after the live run.

Run: `prospective_memory/results/qwen3-8b-pis-grounded-smoke-20260922-01/`.
Portable report: `results/pis_grounded_smoke_20260922/README.md`, with every case,
CSV, metrics, evidence excerpts and provenance. Raw calls, complete requests,
snapshots, frozen sources/protocol and independent audit remain in the run folder.

Qwen3-8B BF16, no quantization, same b968826 checkpoint, nonthinking/temp0,
4096 helper tokens, vLLM0.8.5.post1 compact xgrammar. Helper-only, no actor or
PM-Bench run. All10 cases completed in269.9s: **0/10 full contracts passed**,6/11
required origins registered,4 ACT/0 CHECK/4 WAIT. ACT origin/time alignment3TP,
1FP,4FN is NOT complete-action correctness or PM-Bench F1. All seven accepted
records (including an erroneous extra revision) contain generic/bare-verb actions.
35 model calls:14compile/12review/8assess/1probe;18,542tokens;no transport/decode
errors or length truncations. Six engine events:5protections+1invalid assessment.

Key failures: compiler loses objects/recipients; reviewer rejects new registrations
for lacking update targets; a09:45 revision becomes a new record alongside09:15,
causing duplicate ACT; missing evidence is mislabeled false with a query request.
The clock guard also removes a VALID09:15 from a conjunction because the helper's
quote omits that clause despite the original containing it. Do not call that an
invented-clock success. Cancellation, paraphrased-trigger ACT and unavailable-tool
WAIT worked, but those cases still fail initial action quality. Some quiet cases
have no registered intention and are correctly failed by the coverage gate.

All frozen source/case hashes, independent counts/token totals and10snapshot
restores pass.210software tests pass (179core/harness+31audit/adapter/runner), but
model competence does not. Owned helper server88520/worker88828 stopped with
identity checks; both GPUs verified2MiB/0%, no compute processes. No job running.

Next proposed work, NOT implemented: operation-specific ADD/REVISE review,
complete source-bound action extraction, complete-span clock grounding and clear
unknown-versus-false semantics. Revalidate the small suite with a separately named
attempt before a full PM-Bench comparison. Original baseline archive and previous
42.9% run are unchanged; method3 full-comparison slot remains pending. No push.

## Previous implementation handoff: opt-in `pis_grounded`, awaiting live validation

User approved improvements after the walkthrough and failure comparison. Added
`prospective_memory/pis_grounded.py` and portable runner flag `--memory-policy
pis_grounded`. Existing policies/defaults remain available; the consolidated first
two baseline reports and raw experiment results are unchanged. No GPU job launched.

Our own saved helper trace reveals two concrete issues: call1 invents 08:00/18:00
for breakfast/dinner, while call127 labels a supported 11:50 condition CHECK and
requests the already-observed clock. This is not the complete zero-ACT diagnosis.
The refinement removes unsupported literal hard-clock gates while retaining the
source quote, reviews proposed memory changes against original/target history,
and asks the helper for satisfied/not_satisfied/unknown with exact current-evidence
quotations. Code maps those assessments to ACT/CHECK/WAIT; it does not infer ACT
from contradictory free-text reasoning. Bad evidence/changes are logged/rejected.

Changed PISEngine only to add default no-op review and unchanged-decision extension
points plus policy-isolated restoration. The new variant retains existing budgets,
actor autonomy, menu exclusion and non-guessed completion. Source routing, batching,
forced checks and autonomous polling are NOT added. Review is same-model and can
reject legitimate requests; it adds cost and does not guarantee semantic fidelity.

Documentation: `prospective_memory/PIS_GROUNDED.md` includes exact trace references,
usage (not executed), limitations and next validation. Test suite: 161 core tests
plus 31 audit/adapter/runner tests, including a new scripted CHECK-response-ACT
cycle and full 80-step fake-model integration for the new policy. Scripted results
are software contract checks, not evidence Qwen now reminds correctly.

Next: live generic positive/negative registration and evidence-assessment checks
on the same model before the full week; require actual ACT, correct negative
silence, and adequate retained registrations. Then audit a new PM-Bench run and
add method 3 to the comparison folder only with measured results. Helper raw
output schema now uses assessments/reviews; delivered decisions remain in
memory.jsonl. Track review cost/rejections as well as F1. No new score or push.

## Latest documentation handoff: first two baselines archived together

User requested one easy-to-read comparison folder before adding our third method.
Created `results/baseline_comparison/` from the completed September 22 author-code
run: plain main-agent baseline and actual authors' PIS only. Start with README.md
and RESULTS.md. Includes all 38 missed-on-time occurrences and all 637 wrong/not-due
selections across both methods, Markdown/CSV tables, evidence status, proposed
improvements, a 160-step scored snapshot and source hashes. Detailed case studies
are archived separately; historical references to our candidate are not a third
method result. METHOD_3_PENDING.md reserves the future comparison.

Additional offline trace audit: of authors' 15 hidden-channel on-time misses,
10 had relevant CHECK guidance delivered to the actor but no required-channel
query at the due step, 4 lacked the guidance/query (one recall error), and 1
queried but still omitted the task. These are immediate pipeline observations,
not mutually exclusive underlying root causes. Report unknown causes explicitly.
No new experiment, model-policy change, server launch or GitHub push.

## Latest handoff: authors' GitHub PIS run and failure comparison completed

User requested the actual author implementation, not another run of our independent
PIS-inspired module. Cloned `ChengcanWu/prospective-memory-reaearch` into
`third_party/author_pis`, pinned `43e9b426a478bdd6b4e6fb12cb609ca26bd71ff9`.
Tracked upstream source is unchanged. Extracted only PMBench data/sim from the
bundled archive. The week is JSON-identical to ours; scorer functions match.
This released runner already uses empty selections on invalid model output,
not the original benchmark's ground-truth fallback.

Completed fresh baseline + author `--setup intention` using Qwen3-8B BF16,
no quantization, temperature0, nonthinking, actor768 tokens, same model snapshot
and scenario as our previous triplet. Retained author helper limits, compact actor
history, forced-clock policy, channel hints and done-on-selection behavior.
Local adaptations only: helper routing, thinking disabled, raw API logging.

| Method | TP | FP | FN | Precision | Recall | Set-F1 |
|---|---:|---:|---:|---:|---:|---:|
| Fresh author baseline | 78 | 484 | 3 | 13.9% | 96.3% | 24.3% |
| Actual author GitHub PIS | 46 | 153 | 35 | 23.1% | 56.8% | 32.9% |
| Our prior PIS-inspired run | 62 | 146 | 19 | 29.8% | 76.5% | 42.9% |

All 80 steps, identical 81 state-aware due occurrences, zero final actor-output
failures. Ours caught 20 occurrences theirs missed; theirs caught 4 ours missed;
both missed 15. Our higher F1 is a single-run observation, not a generalization
claim or cost-matched ablation. Actor queries: authors102 versus ours157.
The fresh baseline matches prior aggregate scores, not exact actions: 18 selected
sets and one query-count row differ despite temperature0.

Author PIS took 40.6 min; 111 helper calls / 410,951 helper tokens, plus 186 actor
calls / 398,902 actor tokens. 27 length-truncated replies (23 helper,4 actor),
with retries retained. Two memory errors occurred on Friday s10 (unsupported
channel at recall, unparseable output at encode); final actor choices remained
valid. Final store194 records, including110 excess exact copies; one pending
intention had23 identical copies. No safety abort occurred (297 total API calls).

Trace-backed findings:

1. At Monday10:20 the actor prematurely selects 11:00 medication; the author
   store marks it done. At11:00 its reminder is absent and the actor misses it.
   Our actor also selected it early but still selected it correctly at11:00.
2. A new Thursday referral-slip intention is applied as an override to the
   existing intake-form row. The form is lost, then missed; ours hits it.
3. The `override` code ignores `new_day`, so Thursday supplied by the model is
   not stored. The helper also mistakes a future trigger mention for observed
   evidence. Minimal offline replays confirmed premature-done/date-loss behavior.
4. Ordinary scene choices (Start dinner / Put a pan on / Rinse vegetables)
   become new intentions, and exact duplicate records accumulate.

Full artifacts: `harness/memory_results/qwen3-8b-author-pis-20260922-01/`:
RESULTS.md, FAILURE_CASES.md (expected/actual JSON), FAILURE_ANALYSIS.json,
failures.csv, raw calls, author bank snapshots, source snapshot and manifest.
Reproduction tools: `run_author_pis.py`, `summarize_author_pis.py` and
`AUTHOR_PIS_EXPERIMENT.md` in `harness/`.
All 172 local tests pass (141 core + 31 audit/runner), plus earlier 10 upstream tests.
After completion the wrapper's unused call-limit guard was hardened to SystemExit
so upstream exception recovery cannot swallow it; the archived run wrapper is
unchanged and the limit was never reached. Both owned servers stopped; both GPUs
verified 2 MiB / 0%, no compute processes. No experiment running, no push.

Next proposed work, NOT implemented: generic add-versus-revise/target validation,
preserved trigger fields, source-role-aware registration/deduplication, and
attempt-versus-confirmed-success lifecycle. Validate independently before another
PM-Bench ablation. Also fix our zero-ACT/repeated-CHECK problem: our prior run
generated no ACT and made no verifier call, so its score cannot establish a
successful reminding/verifier mechanism. Do not claim paper57.2% reproduced;
paper configuration/revision is not established as identical to this local run.

## Previous handoff: PIS F1 improved, but no ACT and no verification occurred

All three arms of `harness/memory_results/qwen3-8b-pis-triplet-20260922-03`
completed 80 steps, zero actor fallback. Baseline 78 TP / 484 FP / 3 FN,
F1 24.3%, recall 96.3%; PIS 62/146/19, F1 42.9%, recall 76.5%;
verifier-enabled 55/138/26, F1 40.1%, recall 67.9%. Runtime 1.9 / 43.1 / 42.5 min.
Helpers used 1,953 / 2,003 calls and 1,716,067 / 1,665,542 tokens, excluding probe
and all actor tokens. PIS had one truncated/JSON-failed registration call.

CRITICAL: both candidates emitted ZERO ACT proposals, even in raw helper output.
The verified flag was true, but zero verifier calls/verdicts occurred. Do NOT
attribute its lower score to verification. PIS raw decisions 497 WAIT / 1,211
CHECK; verified 525 WAIT / 1,230 CHECK. Invalid/exhausted CHECK rejections were
1,140 / 1,150. The actual interventions were query guidance and exhausted-budget
instructions; the actor independently selected actions. Accepted CHECK counts
151 / 160 include code-generated clock requests. Actor queries 157 / 160.

F1 gain is accompanied by 16 fewer on-time hits and 338 fewer FP. Selected tasks
562 → 208 (verified 193), so cardinality/precision–recall confounding remains.
No validated general memory improvement or exact paper reproduction. Same-payload
helper outputs first diverged in wording at call 7 despite temp0; cause not established.

All source/scenario hashes, independent rescoring and exact snapshot restore passed.
RESULTS.md and ANALYSIS.json saved; RESULTS.md includes this post-run interpretation.
Host check at 13:35 UTC: no experiment process; both GPUs 2 MiB, 0% utilization.
168 tests previously passed; no code changes or new experiment during result audit.
Next: diagnose zero ACT generation and invalid CHECK requests before more runs;
then validate a genuinely exercised verifier and selection-count control. No push.

## Previous setup handoff (superseded by completed results above)

User proposed Zhao/Wu's *Making Prospective Memory SLM-Shaped: Typed Intention
Stores for Small-Model Agents* (arXiv:2609.01272v1), then approved implementation
and comparison. PDF saved in `papers/making_prospective_memory_slm_shaped_2609.01272.pdf`.
This is an independent PIS-inspired plug-in, NOT author-code reproduction or a
claim to match the paper's Qwen3-8B 57.2% F1. Protocol: `prospective_memory/PIS_EXPERIMENT.md`.

Implemented opt-in `pis` / `pis_verified` policies in `prospective_memory/baselines/pis.py`:
typed Form/Revise, weekday/single-clock Filter, per-intention Decide, bounded
CHECKs, original input preservation and host-owned execution acknowledgement.
Verified arm alone adds a same-model judge of proposed ACTs against full original
messages and accepted revision history. It cannot recover missing registrations
or wrongly filtered intentions. PM-Bench exposes attempts, not success: no guessed
done-marking. The independent actor retains menu selection. Legacy defaults unchanged.

Engineering attempts under `harness/memory_results/`:

- `qwen3-8b-pis-triplet-20260922-01`: baseline completed; candidate interrupted
  during startup after an offline regression found missing typed slots in the
  duplicate key. Fixed; different weekdays/times remain distinct. Not a comparison.
- `qwen3-8b-pis-triplet-20260922-02`: baseline completed; candidate interrupted
  after two choices due to repeated wrong-channel actor queries. Helper requested
  appointment_portal; actor repeatedly queried course_portal. No completed score.
- **`qwen3-8b-pis-triplet-20260922-03`: current guarded run.** Baseline completed;
  PIS is running and verified arm is queued. Do not report final memory scores yet.

Both memory arms now count actual host query attempts, even wrong/repeated ones:
2 per decision step, 1 CHECK per assessment. Adapter calls begin_step/record_query
and supplies exhausted-budget guidance. Actor remains autonomous; over 12 queries
in one step explicitly aborts the run, never fabricates an action or score.
Grammar is stable across record/evidence IDs; runtime validates all identifiers.
168 tests pass (141 generic + 27 runner/adapter), including full-week fake-model
wiring of both policies and snapshot restoration. These are not semantic scores.

Launcher: `harness/run_pis_triplet.py`; audit/report generator:
`summarize_pis_triplet.py`. The launcher runs baseline, pis, pis_verified in order,
then independently re-scores, verifies source/scenario hashes, restores snapshots,
and writes ANALYSIS.json / RESULTS.md in the triplet directory. It is configured
to interrupt ONLY owned server PIDs 67596 (actor GPU1) and 67674 (helper GPU0)
after successful audit, validating process start identity before signalling.
If run/audit fails, servers may remain: inspect host PIDs before cleanup.
Model setup unchanged: Qwen3-8B BF16, same cached revision, no quantization,
actor output768, helper4096, temp0, seed0, empty actor fallback. Full baseline
rerun each attempt, no accuracy-driven tuning. Frozen protocol copied per attempt.

Next: inspect current run completion/errors (not older aborted directories),
finish result interpretation, update project archive and results ledger AFTER
completion, verify GPU release. Compare TP/FP/FN, recall, F1, selection cardinality,
all helper cost and queries. An output-count control is still required if the
candidate again collapses selections to one per step. No GitHub push.

## Latest handoff: PM-Bench F1 rose, but recall fell and output count collapsed

The user explicitly requested PM-Bench evaluation despite failed generic gates.
Implemented opt-in `IndexedMemoryEngine` plus `--memory-policy indexed` in the
portable runner: unchanged sentence-indexed extraction, preserved original-source
bank, new same-model target resolver, source-aware evidence-gated monitor, and
host-enabled persistence across day labels. This is a combined end-to-end
candidate, not an indexing-only ablation. No policy defaults were changed.

Completed matched runs under `harness/memory_results/`:

- `qwen3-8b-indexed-pair-baseline-20260921-01`: **78 TP / 484 FP / 3 FN,
  Set-F1 24.3%**, precision 13.9%, recall 96.3%; 562 selections, 8 queries.
- `qwen3-8b-indexed-pair-memory-20260921-01`: **34 TP / 46 FP / 47 FN,
  Set-F1 42.2%**, precision 42.5%, recall 42.0%; 80 selections, 25 queries.

Both completed all 80 steps, with zero actor fallback. Same running actor,
weights/config/scenario/empty fallback. **+17.97 F1 percentage points, but 44 fewer
correct on-time actions.** Candidate chose exactly one task on EVERY step;
baseline chose 3–8. This is strong evidence of an output-count/precision–recall
shift, not proof of better prospective memory. Historical 42.0% and earlier
portable 42.5% are NOT the matched comparator. No significance claim.

Candidate diagnostics: 318 helper calls, 599,784 helper tokens (excluding probe),
17.8 min vs baseline 2.0 min; reminders on 79/105 cycles, bank 37 entries.
17 monitor responses truncated at 1,536 output tokens (max input only 5,558).
It emitted many CHECKs despite the runtime's one-check-per-assessment budget;
the numeric budget is not exposed in the request and filtering is post-parse.
Four input messages failed registration, including Tuesday/Saturday/Sunday
daily plans; raw text retained, but no entries from those failed messages.
One resolver error and 20 decision rejections. The helper was not inert.

Next recommended controls/fixes, NOT performed: fresh at-most-one-task baseline
to test the cardinality alternative; budget-aware compact query output; partial
registration recovery that preserves unresolved clauses instead of rejecting a
whole daily plan. No broader model sweep yet. General execution acknowledgement
is not implemented in this experimental engine (PM-Bench only reports attempts).

Full report and paired audit are in the candidate run's `RESULTS.md` and
`PAIR_ANALYSIS.json`; integration documented in `prospective_memory/INDEXED_PMBENCH.md`.
Both trajectories independently re-scored, final adapter snapshot restored
without inference, source/scenario hashes verified. **147 tests pass** (122 + 25).
Both servers stopped; both GPUs free. No experiment pending, no GitHub push.

## Previous handoff: indexed gain did not generalize; linked follow-up regressed

Implemented two opt-in extractors in `indexed.py` and `linked.py`, selectable
through `evaluate_registration --extractor`. The bank now supports exact
discontiguous source spans while retaining original messages and all old
single-span snapshots. Revisions/cancellations remain staged for host resolution.
Neither extractor is wired into the existing monitor or PM-Bench runner.

Completed Qwen3-8B BF16 measurements, original 9-case/16-operation development set:

- Matched verbatim control, twice: **8 TP / 3 FP / 8 FN, 59.3% F1**, 3,940 tokens.
- Sentence/line indexed: **15/3/1, 88.2%**, 11,500 tokens. All 22 units reviewed;
  misgrouped reschedule constraint and a speculative fact registered as a request.
- Word-indexed linked ranges: **6/4/10, 46.2%**, 12,054 tokens. Eight messages
  rejected for coverage/anchor errors or uncertainty; no JSON decode failures.

Four additional development challenges (6 requests): indexed **0/6/6, 0%**;
linked **3/2/3, 54.5%**. Sentence boundaries broke abbreviations and cross-line
conditions, semicolon requests remained merged, and a nonadjacent exception was
misattached. Linked storage supports these shapes, but the model still fails
range coverage and semantic grouping. The linked variant was developed after
viewing those failures; do NOT call its challenge result held-out validation.

All registration gates failed. No three-way actor comparison or new PM-Bench
run. No policy defaults changed; `verbatim` is the registration CLI default and
portable policy `legacy` remains unchanged. Next candidate should reduce exact
range bookkeeping while jointly checking request/condition grouping and explicit
intent vs speculation. Do not claim end-to-end improvement from registration F1.

Full report/artifact index: `prospective_memory/results/INDEXED_REGISTRATION_20260921.md`.
Six completed run folders plus one failed connection preflight; hashes verified.
Both matched controls exactly reproduced the original result. The first server
disappeared before linked evaluation; cause unknown. It was restarted with the
same settings and a fresh same-server control was run. Final server stopped;
both GPUs free, nothing pending. **135 tests passed** (111 + 24). Old saved banks
restore/rescore unchanged. Project docs updated; no GitHub push.

## Previous handoff: preservation implemented; registration gate failed

User approved intention preservation first, then a controlled three-way
agent / agent+bank / agent+bank+monitor comparison on Qwen3-8B. Implemented a new
opt-in `prospective_memory/preservation.py`, not a replacement for the existing
engine or PM-Bench adapter. Raw messages persist before extraction (including
errors/no output). Entries select exact original spans; scope is host-owned.
Updates/cancellations are staged for explicit host resolution; accepted updates
append verbatim history instead of replacing the original. Automatic semantic
target resolution is not implemented. Snapshot/restore and defensive views work.

Completed live run:
`prospective_memory/results/qwen3-8b-preservation-registration-20260921-01`.
Nine development cases, 13 messages, 16 annotated operations. Complete-source
registration TP/FP/FN = **8/3/8**, precision 72.7%, recall 50.0%, F1 **59.3%**.
All 13 original messages retained, one non-exact quotation rejected, zero decode
errors; 14 calls including preflight, 3,940 tokens. Model merged independent
requests, omitted a request beside cancellation and called an ambiguous update
a new registration. Staged revision/cancellation correctness is not resolved
target accuracy or execution success. This metric is not comparable to prior
trigger F1 or PM-Bench. No matched legacy registration run was done.

The registration gate failed, so the three-way actor experiment was NOT run.
Its protocol is prepared in `prospective_memory/PRESERVATION_EXPERIMENT.md`;
actor harness, automatic update resolver and lossless-bank monitor integration
remain to implement. Next: test indexed source spans and explicit per-span
coverage accounting to avoid quotation rewriting and missed/merged requests.
Keep originals authoritative. No new PM-Bench run until generic gates pass.

All **113 tests passed** (89 generic + 24 adapter/runner). A post-run one-to-one
scorer fix was checked against saved snapshots; all counts unchanged. Exact run
code is snapshotted. Both GPUs are free; the server started for this run was
stopped. No experiment pending and no GitHub push performed. Full report is the
run's `RESULTS.md`.

## Previous handoff: candidate implemented, broader regression failed

Goal remains generic plug-and-play prospective memory with Qwen3-8B first.
New opt-in `grounded` / `verified` policies are implemented in
`prospective_memory/grounded.py`; `legacy` remains the default. Do not describe
the new candidate as a validated improvement or a completed solution.

The final code isolates extraction of new requests from unrelated stored
intentions, resolves only revisions/cancellations against existing targets,
processes explicit list items individually, reconstructs exact provenance from
source-line IDs, and optionally verifies ACT proposals in a separate same-model
call. No benchmark handles or ground truth enter these policies. Updated
launchers, CLI flags and source snapshots support reproducible comparisons.

Completed measurements (all raw artifacts retained):

- Fresh seven-case/20-tick suite: legacy 7/3/1 TP/FP/FN, F1 77.8%; first
  grounded candidate 7/3/1, 77.8%; with ACT verification 6/0/2, 85.7%.
- That first candidate failed on PM-Bench: 77/489/4, F1 23.8%, versus today's
  matched baseline 78/484/3, F1 24.3%. Its bank became effectively inert after
  one incorrect cancellation; no reminders were ever injected. Historical
  baseline 42.0% is not today's matched comparator. See run RESULTS.md.
- A generic probe isolated interference from an unrelated stored intention.
  The compiler was then changed to extract without the bank and resolve only
  update targets in a second pass. Two new incremental tests passed 5/0/0,
  F1 100%, but the broader suite regressed to 4/1/4, **61.5% F1**.

Remaining failures: model-invented routing scope (`this week`), lost reschedule
time (condition reduced to `reminder`), omitted evidence source, and numeric
trigger reasoning. The independent verifier can agree with an incorrect proposal.
Zero decoding failures do not imply semantic correctness. Registration recall
by instruction provenance does not guarantee intact conditions or active scope.

All 93 automated tests passed (69 core/evaluation + 24 adapter/runner). The final
candidate was NOT sent back to PM-Bench after failing the broader suite. Both
model servers were stopped; no experiment is pending. Results and limitations:
`prospective_memory/results/GENERIC_REPAIRS_20260921.md`.

Next: improve structured condition preservation and host-defined scope/source
binding using generic tests with existing memory, then consider another matched
PM-Bench run. This sequence used benchmark failures for development, so do not
call subsequent measurements untouched held-out validation. Keep new variants
opt-in and preserve legacy results. No GitHub push was performed.

## Previous experiment: first PM-Bench portable run (September 18)

Run: `harness/memory_results/qwen3-8b-portable-20260918-02`.
**Set-F1 42.5% (TP=41, FP=71, FN=40) vs historical baseline 42.0%
(34/47/47): no measurable difference.** Recall 50.6% vs 42.0% (+7 hits);
precision 36.6% vs 42.0% (+24 false positives). First memory method not to lose
to baseline; first to raise recall. Single trace, no effect size.

Setup that worked: two servers. Actor on GPU 1 under default `auto` backend
(historical conditions; PM-Bench's actor schema carries `maxItems`, which
xgrammar rejects, so the actor cannot use the whitespace-free server). Helper on
GPU 0 via `prospective_memory/serve.py` (`xgrammar:disable-any-whitespace`).
`run_memory.py` gained `--memory-base-url`. A first attempt with one server
(`...-01-ABORTED-actor-schema-400`) had 78 actor failures and was killed.

Helper was clean (211 calls, 1 error, 1 truncation) and **selective**: ACT on
24/110 cycles vs v2's 102/109. Final bank 29 intentions, all pending (no public
completion signal). 102 engine errors were rejected proposals, not actor input.
The FP increase is not reminder spam; candidate causes (30 state queries vs 0,
memory block in every actor prompt, never-acknowledged intentions re-firing) are
untested and need trace analysis. **Do not tune against this run.** Details in
its RESULTS.md.

Both servers were left running until 2026-09-21 and then stopped; GPUs free.

## Previous: isolated repairs, v7 (September 18)

Best run: `prospective_memory/results/qwen3-8b-semantic-v7-source-20260918-01`.
Same 10 cases/30 ticks, `cases_sha256` identical to every earlier run. Qwen3-8B
BF16, vLLM 0.8.5.post1 V1, server via `prospective_memory/serve.py` with
`xgrammar:disable-any-whitespace`, `whitespace_free_grammar_verified: true`.
Server stopped; GPUs released.

**TP=9, FP=1, FN=0, F1 94.7%, registration recall 1.00, decode errors 0.**

One change per run, so effects are attributable:

| Run | Change | TP/FP/FN | F1 | Queries | Reg. recall |
|---|---|---|---:|---:|---:|
| Sep 11 v1 | baseline | 7/1/2 | 82.4% | 0 | n/a |
| Sep 17 v2 | bundled | 6/2/3 | 70.6% | 3 | n/a |
| v3 | structured output repaired | 6/3/3 | 66.7% | 0 | 0.89 |
| v4 | CHECK paragraph narrowed | 8/3/1 | 80.0% | 3 | 0.89 |
| v5 | cancellation wording | 8/3/1 | 80.0% | 3 | 0.89 |
| v6 | stored quote hidden from compiler | 8/2/1 | 84.2% | 3 | 0.89 |
| v7 | source list re-anchored | 9/1/0 | 94.7% | 3 | 1.00 |

Lessons worth keeping. (a) v5 showed prompt instruction failing where v6's
structural change succeeded: the compiler kept copying `evidence_quote` out of
the intentions payload, so the fix was to stop showing it, not to forbid it.
(b) The v2 CHECK and source paragraphs were each over-corrections that destroyed
a working behaviour; narrowing them recovered both without losing their benefit.
(c) One change per run made all of this visible; the Sep 17 bundle did not.

Remaining failure: one FP, firing at -20 C for an "above minus 10" trigger. It
now correctly declines at -15 C and fires at -6 C, so it is no longer wrong in
both directions, but negative-number comparison is still a model-capability
limit. Four rejected CHECKs remain where nothing is queryable; removing them by
prompt previously cost a working case.

**Comparability warning.** v7 must be read against v3 (66.7%), the first
uncontaminated run, not against 82.4% or 70.6%. Seventeen Sep 11 assessments and
8 of 30 Sep 17 ticks never produced a decision, so part of their apparent
restraint was failure scored as correct silence.

**This is a reused 10-case development set with 9 scored occurrences, one case
overlapping a prompt example, and v4-v7 were written against its known failures.
Not held-out generalization evidence. One occurrence moves F1 by about five
points, so no effect size is established. Does not transfer to PM-Bench.**

Next: fresh unseen diagnostic cases to test whether the repairs generalize, then
the PM-Bench portable comparison.

## Earlier September 18 run: structured-output repair (v3)

Run: `prospective_memory/results/qwen3-8b-semantic-v3-20260918-01`. Same 10
cases/30 ticks, `cases_sha256` identical to both earlier runs. Qwen3-8B BF16,
vLLM 0.8.5.post1 V1 engine, server started via `prospective_memory/serve.py`
with `xgrammar:disable-any-whitespace`; probe recorded
`whitespace_free_grammar_verified: true`. Server stopped after the run.

TP=6, FP=3, FN=3, precision 66.7%, recall 66.7%, **F1 66.7%**, down from 70.6%
(Sep 17) and 82.4% (Sep 11). Mechanically the run is clean for the first time:
transport/decode errors 8 -> **0**, all engine errors 18 -> **2**, ticks whose
assessment failed **0**, completion tokens 9,032 -> 3,210, time 177 s -> 102 s.

**Root cause of the decode failures is now established, not inferred.** The
schemas carried `maxItems`, which xgrammar cannot compile, so under the default
`auto` backend vLLM fell back to a whitespace-permitting backend; greedy decoding
then reached a newline fixed point after a completed field and emitted separators
to the cap. `maxItems` was removed from the wire schemas and the bound kept in
`llm._rows`. **Do not use `guidance:disable-any-whitespace`**: it accepts the full
schema but returned `{"decisions":[]}` for all 30 assessments, including a trigger
the same model handled correctly ungrammared. This was tested, not assumed.

Two cases improved (conjunctive_condition premature ACT gone; buffered_event_timing
now correct). Three regressed, each traceable to one prompt edit in the same batch:
pull_only_status stopped issuing CHECK entirely (3 executed queries -> 0) because
the rewritten CHECK paragraph suppressed legitimate queries; explicit_cancellation
quoted the original registration instead of the cancelling message, so the cancel
was rejected and the intention fired; simultaneous_unrelated_intentions invented
the source `book_club_announcements` because the "list every plausible source"
edit overrode the "do not invent a source" rule. The freezer negative-number
comparison is unchanged and still wrong in both directions.

Earlier F1 values are not comparable on equal terms: 8 of 30 Sep 17 ticks and 17
Sep 11 assessments never produced a decision, so some apparent restraint was
failure. An unidentified part of the decline is removal of that contamination.
Registration recall 8/9; silent_drop_count 0. See the run's RESULTS.md.

Next: narrow the CHECK paragraph, fix cancellation quoting, and re-constrain
source selection to the advertised list, **one change at a time** so effects are
attributable. Then fresh cases, then PM-Bench.

## Repair details (applied 2026-09-18)

84 automated tests pass (60 core/evaluation, 24 audit); the scripted demo passes
10/10. Effects on the live diagnostic are recorded in the September 18 section
above: the structured-output repair worked, three prompt edits regressed.

Diagnosed from `qwen3-8b-semantic-v2-refined-20260917-01` raw outputs:

1. All 8 decode failures were assess-phase and identical in shape: a complete,
   semantically correct row followed by ~720 newlines until the 768-token cap.
   A JSON grammar permits unbounded whitespace, so greedy decoding settles on a
   separator fixed point after a finished field. This is a decoder property, not
   a prompt or token-budget problem. Raising the cap would only cost more tokens.
   Fix: the server must start with `--guided-decoding-backend
   'xgrammar:disable-any-whitespace'`. The per-request field is NOT equivalent;
   vLLM V1 builds one backend from server config and strips request options
   (`v1/structured_output/__init__.py` states per-request backends are
   unsupported). Both runners now probe the live server and refuse to start
   without the guarantee, overridable with `--allow-grammar-whitespace`. Shared
   probe: `prospective_memory/decoding.py`.
2. The assessor was never told which sources it could query: `available_sources`
   was sent, `queryable_sources` was not. Eight of nine rejected CHECKs asked for
   `events`, a push stream, in cases where nothing was queryable. The matcher
   contract is now `matcher(intentions, observations, sources, queryable_sources)`
   and the payload carries the queryable list.
3. The compile prompt contained "Use events for conditions observed in incoming
   text", which biased nearly every intention to `sources=['events']`. In
   `buffered_event_timing` this made valid inbox evidence unusable and turned the
   one legitimate CHECK into a rejection. The prompt now asks for every source
   that could plausibly carry the evidence.
4. `simultaneous_unrelated_intentions` lost its book-club intention to a bare
   `{"changes": []}` with no error anywhere. The compile prompt now names silent
   loss as the worst failure and states that a differing action or condition is
   never a duplicate.
5. Assessment prompt additions: paraphrased evidence is acceptable (the model had
   refused a correct -6 C trigger for not repeating the instruction's wording),
   and numeric thresholds compare by value, negatives included (it had fired at
   -15 C for a "above -10 C" trigger).

New scorer-only measurements, so these failures stop being invisible:
`silent_drop_instruction_ids`, `missed_registration_ids`, `registration_recall`,
`assessment_failed` per tick, `failed_assessment_ticks` and
`unscored_quiet_ticks`. The last two separate genuine restraint from a tick that
merely failed to decode; previously both read as a correct WAIT.

Caveats: changes are again bundled and cannot be separately attributed. Fixes 3-5
were written against known failures in this reused development set, so any
improvement there is not generalization evidence. The preflight adds one probe
inference call, logged under case_id `__preflight__`, to the run's token totals.

## Latest completed experiment: refined semantic diagnostic

Run: `prospective_memory/results/qwen3-8b-semantic-v2-refined-20260917-01`.
Same 10 cases/30 ticks as the earlier diagnostic, Qwen3-8B BF16 without
quantization on GPU 0. Driver issue resolved (580.178.04); model server stopped
after completion. No PM-Bench portable run has been performed.

Refinements tested concrete-action extraction, compact assessment output/omitted
WAIT rows, smaller schemas, and registration/assessment caps of 1024/768 tokens.
Results: TP=6, FP=2, FN=3, precision=75.0%, recall=66.7%, F1=70.6% (earlier
82.4%). Decode errors decreased 17 -> 8; generic actions decreased 9/10 -> 0/10;
pull-only case now succeeds with 3 status queries. Total tokens fell 94,028 ->
35,586. Overall trigger performance did not improve.

Remaining failures: missing second independent registration; premature ACT on
incomplete conjunction; incorrect negative-temperature comparison; source
registration excludes valid inbox evidence; repeated-newline/incomplete WAIT
JSON still hits output cap. Nine invalid CHECKs were rejected, plus one ACT
with evidence outside the registered source set. Total engine errors remain 18.

Action preservation heuristic reports 7/10, but three references include trigger
clauses and undercount concrete action text; do not report 70% as validated
semantic action accuracy. This is a reused development set, including overlap
with a prompt example, not held-out generalization evidence. See run RESULTS.md.

Next: investigate silence/JSON reliability, independent registration/source
coverage, and full-condition assessment, then evaluate fresh diagnostic cases
before PM-Bench. User wants refinement on this one model first. Large-bank
candidate selection was discussed but is not implemented: each tick still
assesses all pending in-scope intentions together.

## Goal and status

The user wants a plug-and-play solution to **generic prospective memory**, not
rules tailored to PM-Bench. Intentions can concern unrelated tasks, occur in any
order, be delayed/revised/cancelled, or never trigger. The paper-inspired v1/v2
pilots did not beat the historical baseline. The new module separates intention
registration, observation/monitoring, and action proposals; PM-Bench is one adapter.

Implementation and scripted validation are complete. Two live-model runs on the
small semantic diagnostic set are recorded here. **No PM-Bench portable experiment
has been launched; no PM-Bench F1 is available.** Test passes must not be
described as semantic generalization or improved memory accuracy.

## Implemented files

- `prospective_memory/core.py`: software-assigned IDs; quoted instruction
  provenance; revisions/cancellation; ACT/CHECK/WAIT; execution acknowledgements;
  recurrence; source capabilities; CHECK limits; evidence deduplication; persistence.
- `prospective_memory/llm.py`: provider-independent compiler and assessor using
  `request(system, payload, schema) -> dict`. No benchmark task/channel rules.
- `prospective_memory/adapters/pmbench.py`: public-message translation, dynamic
  channel discovery, menu stripping, scope/evidence handling, persistent ACT
  guidance during within-step queries, adapter snapshot/restore. No hidden state.
- `harness/run_memory.py`: `--mode selective --memory-version
  portable`, `--memory-check-budget`, source/scenario hashes, helper outputs/usage/
  errors, and `memory_snapshot.json`. Existing v1/v2 paths preserved.
- `prospective_memory/README.md`: API, limitations and proposed live-run command.
  Read this first when resuming.

## Completed verification

49 automated tests passed: 26 independent core/lifecycle, 11 adapter/policy,
4 runner, and 8 existing v1/v2 regression tests. Includes a complete 80-step
scripted portable integration and the older 80-step empty-fallback test.

The independent demo passed 10/10 scripted scenarios: delays/unrelated activity,
simultaneous intentions, cancellation, revision, absent trigger, stale/repeated
evidence, fabricated evidence, push/pull queries, persistence and recurrence.
These scenarios are also covered by the unit suite, not extra statistical trials.

Report: `prospective_memory/examples/event_stream_results.json`.
Verification notes: `prospective_memory/examples/VERIFICATION.md`.
No live model was used. The demo imports no benchmark code/data.

## Earlier independent live diagnostic (September 11)

Run `prospective_memory/results/qwen3-8b-semantic-v1-20260911-01` completed before
the requested kill landed; no evaluation process is still running. This was the
first actual-model test of the portable policy on 10 hand-authored event-stream
cases, not PM-Bench. It scored provenance-aligned trigger proposals only: TP=7,
FP=1, FN=2, precision=87.5%, recall=77.8%, F1=82.4%, exact ticks=27/30.

The result is encouraging but not clean. There were 17 assessment decode failures,
all length-truncated at 4096 tokens, consuming 69,632 of 71,935 completion tokens.
Several quiet ticks are therefore "failed closed," not successful reasoning. The
model also stored most actions as just `remind`, losing the full requested action
content. Pull-only monitoring failed: the `deployment_status` source was never
checked, causing one FN. See the run's RESULTS.md before any PM-Bench portable run.

## Limits before a real experiment

1. Provenance/identity validation is not semantic entailment. Quotes do not prove
   correct extraction, revision targeting or satisfaction of every trigger clause.
2. The host delivers events, schedules ticks, executes checks/actions and reports
   outcomes. This is a callable component, not an autonomous background service.
3. CHECK budgets are per helper assessment, not total actual actor queries.
   PM-Bench actors can ignore a check or make additional queries.
4. PM-Bench has no public semantic success feedback. Its adapter logs attempts
   without mapping paraphrased actions to handles or acknowledging completion.
   One-shot records can remain pending and reactivate on new evidence. Never use
   hidden scorer labels as runtime memory feedback.
5. A newly received channel reply can contain an older buffered event; it does not
   prove occurrence now. Clearing evidence at each PM-Bench step also discards
   some useful historical state.
6. Bounded bank/retrieval, total actor-token accounting and cost-matched comparisons
   remain unfinished. Snapshot is the last pre-action adapter state; there is no
   end-to-end simulator-resume CLI.

## Latest actual model results (unchanged)

All rows use Qwen3-8B on the 80-step synthetic week:

| Method | TP | FP | FN | Set-F1 | Actor queries |
|---|---:|---:|---:|---:|---:|
| Historical baseline, zero fallback | 34 | 47 | 47 | 42.0% | 0 |
| Selective v1, completed run 02 | 30 | 50 | 51 | 37.3% | 12 (11 clock) |
| Structured selective v2 | 33 | 47 | 48 | 41.0% | 29 (26 clock) |
| Portable | - | - | - | Not run | - |

V1 lost its knowledge bank at cycle 56 and was empty for the final 39/94 cycles;
89/94 cycles emitted reminders. V2 retained 35 final records but emitted 102/109
reminders and made semantic registration/revision mistakes. Neither beats baseline;
single runs do not establish effect estimates. RESULTS.md and FAILURE_ANALYSIS.md
files are under `harness/memory_results/`. Initial run 01 was
interrupted for helper formatting failures; it is not a completed result.

Completed pilots: Qwen3-8B BF16 without quantization, vLLM 0.8.5.post1, 32768
context, port 30002, actor max_tokens=768 and repaired helper=2048. The portable
README proposes helper=4096 explicitly; this is an unevaluated configuration
change to disclose. Historical server session was 4799; check present health
before running, not old session status. GPUs worked with sandbox escalation.

## Next work and maintenance

Validate the actual model on independent free-form event streams with paraphrases,
negation, timing ambiguity and multi-condition triggers. Freeze the generic
policy, then evaluate via PM-Bench with empty fallback. Report registration and
trigger errors, false alarms, misses, execution success, delay and cost separately.

Keep the historical baseline as a reference. Do not relabel counterfactual audit
scores as fresh corrected-policy runs, or repeat baseline runs merely to rebuild
existing artifacts. Rerun a matched baseline when changed inference conditions
require it for the intended comparison.

Per the user's preference, update this file and `project_context.md` after major
experiments complete, not with incremental running status. This file is the
current handoff; the project file retains durable history, audit interpretation,
precision caveats and paper background. Never overwrite previous run directories.
