# Prospectus Memory: Project Context

Last updated: 2026-09-23

## September 23, 02:48 UTC: full V5 launched under disclosed exploratory exception

The full 80-step `candidate-v5-01` launched **02:48:41 UTC** and is active at this
handoff, with **no completed V5 benchmark score**. Evaluator launch identity:
PID **120840**, UID **1000**, start ticks **45807334**, tool session **14400**.
Reverify identity before process control. Runtime, adapter, runner and fixtures
remain **FROZEN during inference**. Exact configuration and authorization are
preserved in the pair-root
[LAUNCH_DECISION_V5_01.md](../harness/memory_results/qwen3-8b-pis-source-bound-pair-20260922-01/LAUNCH_DECISION_V5_01.md)
and [LAUNCH_IDENTITY_V5_01.json](../harness/memory_results/qwen3-8b-pis-source-bound-pair-20260922-01/LAUNCH_IDENTITY_V5_01.json).

This is a combined `pis_trigger_fair_v5` intervention: cached action/readiness
projection, fair source-level CHECK scheduling, explicit optional query handoff
and the bounded calendar fix. It includes no standalone sentence splitter,
partial-WAIT guidance, forced query/action, automatic completion or added ACT
verifier. The actor/helper remain Qwen3-8B BF16, temperature0/nonthinking; detailed
token, query, decoding and source configurations are retained in the launch record.

Final same-source preflights completed: smoke03 **10/10**, transfer02 **10/10**,
trigger-role01 **8/8**, temporal-v2-01 **4/4**, batch01 **4/5 strict FAIL**. ACT
TP/FP/FN for the four behavior suites are respectively 7/0/0, 11/0/0, 9/0/0 and
4/0/0. Batch has 18/19 fully correct initial obligations and 26/1/1 across 27
registration-stage checks. All five have zero engine/API/decode errors and pass
[independent artifact consistency](../results/pis_trigger_fair_v5_preflight_20260923_01/README.md).
All 17 common/23 union source files match frozen/current hashes. Scripted tests
pass **506 core and 53 adapter/runner/full-pair reporter checks**.

The launch uses the narrow predeclared exception for an extra available `clock`
watcher on `ceramic_tray`, without a hard clock gate; it is **not** a 5/5 batch
pass. A separate semantic review also finds `repeat=false` for "for each pottery
batch"; the fixed temporal rubric omits recurrence/later-batch testing, so its
4/4 score does not prove recurring lifecycle correctness. Neither limitation was
erased or patched into this frozen candidate. Earlier V5 smoke01/02 remain 9/10,
and transfer01's 10/10 used the earlier projector; all are preserved in the
[development report](../results/pis_trigger_fair_v5_development_20260923_01/README.md).

Latest completed full PM-Bench result remains V3: **52.4390% F1, 53.0864% recall,
43 TP / 40 FP / 38 FN**. Judge V5 only after complete native rescoring/audit:
both F1 and recall must exceed V3; historical 62 TP is an aspiration. These tuned
development gates and a combined reused-scenario experiment do not establish
isolated causality or general plug-and-play improvement. Prior dated sections
below preserve history and are superseded for current process/integration status.

## Preserved September 23, 02:30 UTC: trigger-role improvement and next candidate

The source-bound V3 full run remains the latest completed PM-Bench result:
**43 TP / 40 FP / 38 FN; 52.4390% F1 and 53.0864% recall**. Its higher F1 but
19 fewer true positives than historical our PIS motivates continued recall work.
There is no completed full V4/V5 benchmark result at this checkpoint.

On the SAME frozen eight-case trigger-role development diagnostic, V3 plus the
post-run calendar repair passes **3/8** (ACT 3/0/6), V4 projection attempt01
**7/8** (7/0/2), and V4 attempt02 **8/8** (9/0/0); all register 8/8 obligations
and have zero unexpected errors. Artifact-consistency audits pass for all three:
[comparison and provenance](../results/pis_trigger_role_comparison_20260923_02/README.md).
V4 caches full-source/config-bound action-to-perform versus readiness-question
views, not readiness truth or completion. The second attempt adds a generic
independent-occurrence OR versus prerequisite AND clarification. These are tuned
helper-only diagnostics with unchanged expectations, not held-out generalization,
actor uptake or PM-Bench performance; failed attempts remain preserved.

The selected next combined candidate is **`pis_trigger_fair_v5` with explicit
query handoff**: V4 projection plus fair source-level CHECK scheduling and explicit
delivery of query requests to the actor/host, retaining source/evidence/budget
constraints and the bounded calendar repair. Standalone `sentence_units` and
partial-WAIT advisory formatting are excluded. Integration checks pass **499 core
and 52 runner/audit tests**, which are software checks rather than quality results.

Its first helper smoke completed at 02:30:20 UTC: **9/10 cases**, 11/11 registrations,
ACT **6 TP / 0 FP / 1 FN**, zero engine/protection/transport errors, 57 calls including
preflight, 54,984 tokens, 89.29 seconds. Raw run:
`prospective_memory/results/qwen3-8b-pis-trigger-fair-v5-smoke-20260923-01/`.
The remaining failure is projection semantic drift: an exact-time action with
approval-by-email prerequisite becomes approval strictly before the time, and the
projection invents recipient/delivery details. Root is tightening generic
time-operator and evidence-source/action-role preservation before rerunning the
unchanged suites. **No full V5 run has launched and no follow-up result is claimed.**
Runtime/harness remain frozen during live attempts. Only documentation changed
in this context update; earlier dated states below are preserved historical records.

## Preserved 02:01 UTC handoff: completed v3 precision/recall trade-off

Benchmark counts below remain current; its then-current integration/process
statements are superseded by the later checkpoint above.

`candidate-v3-01` completed all 80 PM-Bench steps and exited 0. The independent
[completed-pair audit](../results/pis_source_bound_pmbench_20260923_01/README.md)
verifies frozen sources/scenario, restored v3 snapshot, native rescoring and
identical state-aware due occurrences versus its fresh plain baseline.

| Method | TP | FP | FN | Precision | Recall | Set-F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Fresh plain baseline | 78 | 484 | 3 | 13.9% | 96.3% | 24.3% |
| Historical authors' PIS, not rerun | 46 | 153 | 35 | 23.1% | 56.8% | 32.9% |
| Historical our PIS, not rerun | 62 | 146 | 19 | 29.8% | 76.5% | 42.9% |
| Source-bound v3 | 43 | 40 | 38 | 51.8% | 53.1% | 52.4% |

V3 gains 9.53 F1 points over our prior PIS but loses 19 true positives; it is not
an unqualified memory improvement or completion of the research goal. Historical
arms are reference results, not newly matched causal controls. Full notes, exact
costs/errors and provenance: [EXPERIMENT_NOTES.md](../results/pis_source_bound_pmbench_20260923_01/EXPERIMENT_NOTES.md).
The first two archived baseline tables/CSVs remain unchanged; a separate
[method 3 entry](../results/baseline_comparison/METHOD_3_RESULTS.md) links this result.

The run used the predeclared exploratory exception: batch04 remains strict FAIL
at 4/5, while same-source smoke04 and transfer01 pass 10/10 each. It is a tuned
development result, not held-out validation. Cost: 5,372.587 seconds, 2,987 helper
calls, 4,096,170 helper tokens excluding probe/actor; 116 queries including 92 clock.
No actor fallbacks or helper API/JSON errors; 32 engine events (21 evidence/source
rejections, 10 day guards, one clock guard). ACT/CHECK/WAIT deliveries are
59/147/7,641, including code decisions and cached ACTs, not successful executions.

Evaluator 104037 is finished. Servers 91400/95202 are retained for root's next
experiment; no next full-week candidate has been chosen. Next targets are generic recall,
query handoff and trigger/action-role interpretation. Hidden-event TP is only
1/15; visible-event TP 26/42 and time TP 16/24. These observations motivate
diagnosis, not a proven causal explanation for each failure.

The confirmed calendar false-positive repair was **integrated after the completed
run was audited**, with its helper included in source snapshots. Current V2 compiler
SHA starts `c5dcb062`; frozen `candidate-v3-01` did not use the repair and no live
full-week validation of the repair exists yet. The later helper diagnostic below
does not isolate its effect. V4 static trigger-projection opt-in integration is now
underway for a same-case comparison, but has no live result. Partial-WAIT advisory
formatting remains unintegrated. A frozen eight-case trigger-role development
suite has 19 rounds (9 ACT/10 WAIT), SHA
`2494810e84cddae77bdcfeb919b9e0a971fdaa7ac9df7b8b322e6b97b0bcc8e5`;
[its protocol](../prospective_memory/TRIGGER_ROLE_PROTOCOL.md) explicitly excludes
held-out/generalization claims. Its first V3-plus-calendar-fix diagnostic completed
02:01:06 UTC: 3/8 cases, 8/8 registrations, ACT 3 TP/0 FP/6 FN, 16 WAIT, zero
engine/protection/transport errors, 36 calls including preflight, 35,469 tokens,
47.54 seconds. Raw directory: `prospective_memory/results/qwen3-8b-pis-source-bound-v3-trigger-roles-20260923-01/`.
Readiness-versus-completion misses motivate V4 on these same unchanged development
cases; no next full-week candidate is selected. The completed-result handoff
had 420 core +47 runner/audit tests; subsequent calendar integration passes 425 core
tests. Software correctness is not measured model benefit.

Earlier dated entries below preserve history and are superseded by this section
for current process state, completed results and next actions.

## Archived September 23, 00:57 UTC: active v3 remained frozen

The exploratory `candidate-v3-01` full-week run is still running at roughly
39/80 steps, with no completed score. Evaluator identity remains PID 104037,
UID 1000, start ticks 44945442, session 18866; root verified all 11 runtime hashes
unchanged. Recheck this dated identity/progress before acting. The predeclared
exception still permits this exploratory run despite strict batch04 FAIL at 4/5;
it is not held-out validation or a relabelled gate pass. Runtime remains frozen.

A deterministic calendar-guard bug is now confirmed independently of model output:
an unrelated physical-action verb such as "Drop" in another bullet can invalidate
a valid shared weekday heading. Generic scripted reproduction and bounded proposed
repair are in `results/calendar_guard_diagnosis_20260923.md`. No fix is implemented
in the active runtime; impact on completed PM-Bench performance remains unmeasured.

Separately, an unintegrated future V4 prototype adds cached source-bound static
action/readiness-question views, explicit model/configuration bindings, and
inference-free rebinding for authoritative active-status changes. Files are
`prospective_memory/trigger_projection.py`, `prospective_memory/method/trigger_engine.py`
and their two corresponding tests. These views are fallible interpretations, not
current evidence, readiness truth or completion. There are no live model calls,
no active-runtime imports and no CLI selector; the running candidate does not
use it. All 379 core scripted tests pass, not a live quality evaluation. Earlier
WAIT/actor-advisory ideas also remain proposals, not a change to the frozen run.

## September 23: selected v3 full-week candidate launched under exploratory exception

Restoring batch01 plus seven generic prompt-clarification lines produced batch04:
4/5 strict cases, 18/19 fully correct initial records, stage TP/FP/FN 26/1/1
(96.30% registration F1), zero engine/API errors, 36 calls and 42,157 tokens.
All 19 full requests were preserved separately and lifecycle edits were correct.
The sole failure is an extra available clock watched source on a correctly
recurring visible-event request; no hard clock gate was invented. Strict batch
status remains FAIL. Compiler SHA prefix `e44a29ce`; no metadata reason field,
per-operation calls or promoted payload. All five batch attempts are preserved.

Smoke04 on this same compiler completed at 00:22:25 UTC: 10/10 cases, 11/11
registrations, ACT 7/0/0, 6 WAIT/2 CHECK, zero errors, 45 calls, 43,037 tokens,
68.35 seconds. Transfer01 completed at 00:24:37 UTC on the same compiler/assessor:
10/10 cases, 12/12 registrations, ACT 11/0/0, 13 WAIT/3 CHECK, zero errors,
58 calls, 57,766 tokens and 93.99 seconds. Artifact-consistency audits pass for
all five V3 behavior runs in `results/pis_source_bound_v3_behavior_20260923/`;
this does not convert the batch gate into a pass.

Before launching a candidate, root amended the pair-root `PROTOCOL.md` to permit
one explicitly exploratory 80-step run if unchanged smoke and transfer pass on
this same source, despite the remaining strict 4/5 batch failure. This is a
predeclared departure from the original 5/5 launch gate, not a changed rubric or
a gate pass. Extra clock watching can consume query budget, enter evidence
selection and affect recurring-notification deduplication when fresh clock IDs
accompany reused event evidence. These risks require measurement, not dismissal.
Development-tuned selection is not held-out validation; no new complete candidate
PM-Bench score exists. Actor, scenario, scorer and baseline remain unchanged.

The full exploratory run launched around 00:24:56 UTC in pair directory
`qwen3-8b-pis-source-bound-pair-20260922-01/candidate-v3-01/`, tool session 18866.
Runtime hashes match batch04/smoke04/transfer01 and are frozen: no runtime edits
during evaluation. The initial bank retains 10/10 public request lines without
engine errors, but early assessment still confuses a trigger with action already
completed. This is partial diagnostic evidence, not a completed PM-Bench score.
The earlier v2 aborted candidate and completed baseline remain intact. Root owns
monitoring and the eventual full-trajectory audit; process identity is in current_work.

## September 23 earlier state: per-operation batch03 failed

V3 batch03 (`qwen3-8b-pis-source-bound-v3-batch-20260923-03`) completed at
00:16:17 UTC: 2/5 cases, 13/19 fully correct initial registrations, stage-record
TP/FP/FN 18/11/9 (64.29% F1), four day-guard events, zero transport/decode errors,
49 calls, 59,132 tokens and 123.9 seconds. Per-operation metadata and promoted
public headings/scope did not fix weekday interpretation; source/time fields
and restatement/lifecycle behavior also regressed. This variant is not selected.

All four batch attempts remain in `results/pis_source_bound_batch_development_20260923.md`.
At that handoff no evaluator was running. The compiler agent restored the best
batch01 code, adding minimal generic prompt clarifications while preserving its
schema and batched metadata-call shape. No metadata reason field, per-operation
calls or promoted-context payload. Batch04 above records the outcome; the strict
5/5 scoring requirement remains, with a separately disclosed exploratory launch
exception. Prior failures and expectations are preserved.

## September 23 earlier state: batch02 regressed despite eliminating runtime errors

Latest completed run `qwen3-8b-pis-source-bound-v3-batch-20260923-02` passed 3/5
cases, but fully correct initial registrations fell from 17/19 to 13/19 and
stage-record TP/FP/FN changed from 25/2/2 to 17/10/10 (F1 92.59% to 62.96%).
It completed at 00:07:10 UTC with 36 calls, 45,281 tokens, 87.1 seconds and zero
engine/transport/decode errors. The event-alternative/repeated-occasion contract
and duplicate metadata problem were fixed, but shared Wednesday metadata was
lost on four requests and two one-off audio tasks became incorrectly recurring.
Actual lifecycle target identity remained correct; missing initial strict-match
anchors caused repeated downstream failures. Zero errors is not semantic success.

The first three batch attempts were preserved in
`results/pis_source_bound_batch_development_20260923.md`. No evaluator is running
at that handoff. The next generic change compiled metadata per source operation
with explicit applicable public headings and current host scope, retaining the
full original message; batch03 above records its subsequent failed validation.
The earlier smoke03 10/10 result predates batch02 and must be rerun with the final
candidate, together with the unchanged transfer/batch gates. Last verified
software suites before this refinement: 314 core and 47 runner/audit tests.

## September 23 earlier state: v3 smoke recovered; batch01 exposed metadata errors

The new opt-in layout-unit compiler is implemented without changing v2. Generic
smoke progression is 3/10, then 7/10, then 10/10 full contracts. Smoke01 retained
4/11 required intentions because conditional imperatives were mistaken for
docs/facts. Smoke02 retained 11/11, but valid related-ID update/cancel hints
were rejected and a clear paraphrased cue was missed. Smoke03, completed on
September 22 at 23:58:54 UTC, retains 11/11 with ACT TP/FP/FN 7/0/0, 2 CHECK,
6 WAIT, zero engine/API errors, 45 calls and 41,872 tokens. All three pass
artifact-consistency audits in `results/pis_source_bound_v3_smoke_20260923/`.
Expectations and prior attempts remain unchanged; these are development-tuned
helper results, not a PM-Bench gain or proof of semantic action correctness.

Generic repairs: classify conditional future instructions explicitly; permit
known target hints on updates/cancellations while still independently resolving
and reviewing identity; judge semantic entailment without exact-word matching.
V3 also cites local observation references mapped back to original host IDs,
instead of regenerating text within a 160-character quote field. The adapter
retains the complete original evidence. This prevents source-copying loss, but
reference validity alone does not prove trigger satisfaction.

The separate frozen multi-request/lifecycle diagnostic tests 19 obligations and
27 stage-record contracts across five cases. V2 batch01 passed 1/5 cases, with
11/19 fully correct initial registrations and stage TP/FP/FN 17/2/10; 15 calls,
10,596 tokens, 10 engine errors. V3 batch01 completed September 23 at 00:00:08 UTC:
3/5 cases, 17/19 fully correct registrations, stage TP/FP/FN 25/2/2, 36 calls,
41,659 tokens, two engine errors. Both have zero transport/decode errors.
The registration F1 values are separate from ACT alignment and PM-Bench set-F1.

V3 still mis-set explicit daily recurrence and added an unnecessary clock source
to a visible event alternative. Actual lifecycle records were correct, but
duplicate unchanged-target metadata rows were rejected and failed the strict
zero-error contract. Generic metadata refinement is underway; no evaluator is
running at this handoff. Subsequent batch tuning is development, not untouched
transfer. See `docs/current_work.md` for current gates. At that checkpoint,
307 core scripted tests passed, not a language-model competence measurement.

The first full-week v2 candidate remains aborted and preserved without a score.
Its matched plain baseline is complete at 24.2613% F1. A new complete PM-Bench
candidate, not helper-only diagnostic F1, is required to establish improvement.

## September 22: passing small tests did not ensure batch-plan coverage

First source-bound PM-Bench candidate was STOPPED after11steps: initial compiler
retained1of10explicit requests, merging/rephrasing source quotes, omitting5plan
requests and inventing2observation channels. Later restatements/speculation became
ADDs and a same-topic revision chose the wrong action. Partial artifacts and an
explicit abort record are preserved; there is NO new completed candidate score.
The previously passing20generic cases mostly use one intention per message; this
is a documented validation blind spot, not a claimed methodology success.
This motivated the v3 source-unit compiler and generic batch/lifecycle diagnostic
reported above. V2 and all prior results remain intact. Fresh 80-step baseline
24.2613% F1 is complete; no GitHub push.

## September 22 historical launch: v2 generic gates passed, full run later aborted

After preserving first failed attempts, the final source-bound candidate passes
both unchanged10-case suites:23/23registered requests,18correct ACT occurrences,
no extra/missed reminders or engineerrors. Transfer reruns are development-tuned,
not held-out validation. Complete attempt history, provenance and independent
artifact audit: `results/pis_source_bound_development_20260922/README.md`.
New full80-step plainbaseline again gives24.2613%F1 (78TP484FP3FN,8queries,
no fallback). Full candidate launched23:32:05 UTC in
`harness/memory_results/qwen3-8b-pis-source-bound-pair-20260922-01/candidate/`.
That candidate was subsequently aborted as documented above; it has no completed
PM-Bench score. Same Qwen3-8B BF16/model/checkpoint/scenario,
actor768/helper4096. Goal remains generic plug-and-play prospective memory, not
benchmark-specific rules. Both GPUs are currently occupied by owned actor/helper
servers at launch; see current_work for the latest process handoff and safe continuation.

## September 22: source-bound helper iteration improves generic checks

User requested continued refinement. New opt-in `pis_source_bound` preserves full
quoted obligations instead of lossy verb summaries, separates extraction from
typed metadata, preserves same-record identity through chronological source
updates, and constrains requested checks to legal current host capabilities.
Existing methods and raw results remain intact. Generic smoke progression:
grounded v1 0/10 contracts and6/11 registrations; source-bound attempt01 6/10,
11/11; attempt02 10/10,11/11 with7correct ACT occurrences,0extra/0missed,
2CHECK,6WAIT and no errors. Attempt02:43calls/24,198tokens/65.3s. Same model
and unchanged ten-case expectations. This is helper-only development improvement,
not an end-to-end actor/PM-Bench result. Independently authored transfer cases
were frozen before live outputs; first run passed8/10 with12/12 registrations,
11correct ACT occurrences and1extra. Strict numeric equality and unnecessary
wall-clock checking caused failures; unsupported weekday metadata was also found.
Generic refinements are underway; subsequent transfer results are development-tuned,
not untouched transfer validation. First attempt remains archived.
See current_work and results_ledger; original baseline archive is unchanged.

## September 22: first grounded-PIS live smoke failed

Following user approval, tested `pis_grounded_v1` with the same Qwen3-8B BF16
checkpoint on ten frozen generic helper cases, not a PM-Bench/actor run.
0/10 full contracts passed;6/11 required origins registered;4 ACT/0 CHECK/4 WAIT.
All seven accepted records have incomplete actions (one is an erroneous extra
revision record). ACT origin/time3TP/1FP/4FN must not be interpreted as semantic
action correctness or compared to PM-Bench F1. Cancellation, paraphrased triggering
and waiting without an available query worked, but their registration/action
quality was deficient. The new method is NOT ready for full-week promotion.

Actual failures: missing/generic action content; reviewer applies update-target
requirements to new registrations; a time revision adds a second active record;
missing evidence is confused with false evidence. Quote-only clock grounding also
removes a legitimate time when the compiler omits its clause from the quote.
These findings replace any assumption that the new review or guard is reliably
protective. No tuning during/after the run; subsequent repairs require a new run.

Raw run: `prospective_memory/results/qwen3-8b-pis-grounded-smoke-20260922-01/`.
Versionable report/CSV/evidence: `results/pis_grounded_smoke_20260922/`.
35calls/18,542tokens/269.9s, no API/JSON failures; hashes, token/count audit and
all10snapshot restores passed.210software tests, including17new harness tests.
Pre-run review fixed rejected-revision/clock-sidecar inconsistency with regression.
Server stopped; both GPUs verified free. No PM-Bench run or new baseline-table
score; method3 stays pending and old results remain unchanged. No GitHub push.

## September 22: evidence-first PIS refinement implemented, no live score

Following the comparison and step-by-step walkthrough, the user approved a targeted
implementation change. New opt-in `GroundedPISEngine` (`pis_grounded`) adds a
conservative source-quote hard-clock guard, same-model review before memory
mutations, and original-instruction/current-evidence assessment. The model returns
satisfied/not_satisfied/unknown with exact observation quotes; code maps to
ACT/CHECK/WAIT with source/budget validation. Historical PIS and baseline settings
are preserved. No forced queries, batching or autonomous polling was added.

Motivation from OUR saved trace: invented breakfast/dinner times in helper call1,
and CHECK despite an explicitly matching clock in call127. No automatic conversion
of old CHECK text into ACT: the new model contract must actually assess evidence.
These observations do not establish every reason for zero ACT. Mutation review
also addresses the generic wrong-target risk seen in author traces, but is not
proof our candidate made the same specific overwrites.

See `prospective_memory/PIS_GROUNDED.md` for design, provenance and limitations.
161 core + 31 audit/runner tests validate contracts, snapshot policy isolation and
80-step fake-model integration. No new live-model/GPU run or score. Review can
increase cost and reject legitimate tasks; live generic positive/negative tests
must precede a new full-week comparison. The third-method results slot stays
pending. Original baseline archive and experiment artifacts remain unchanged.

## Consolidated baseline comparison archive

`results/baseline_comparison/` is the user-facing archive for the first two
baselines: plain main agent and actual authors' GitHub PIS, using the completed
`qwen3-8b-author-pis-20260922-01` run. It contains summary metrics, complete missed
and wrong-selection tables (Markdown/CSV), per-row evidence/uncertainty and
possible improvements, trace-backed case studies, a scored-step snapshot and
source hashes. The 3 + 35 misses and 484 + 153 extra selections reconcile with
the original scoring. Our third method is explicitly pending, not populated
with an older candidate score. Raw experiment artifacts remain unchanged.

Hidden-channel audit: authors missed 15 on-time occurrences. For 10, CHECK guidance
was present in actual actor requests but the required channel was not queried at
that step; 4 had no relevant logged guidance/query, including one recall error;
1 queried but still omitted the action. This diagnoses immediate pipeline gaps,
not the full causal contribution of store corruption or model behavior. Suggested
fixes remain unimplemented and require independent and matched-ablation testing.
This archive is documentation of existing runs, not a new experiment.

## September 22: actual author-code PIS comparison completed

At the user's request, ran the actual GitHub implementation from
`https://github.com/ChengcanWu/prospective-memory-reaearch`, revision
`43e9b426a478bdd6b4e6fb12cb609ca26bd71ff9`, not our independent PIS-inspired code.
Local clone in `third_party/author_pis` is ignored; upstream tracked code unchanged.
The bundled week is semantically identical to ours (formatting changes its raw
hash); scorer functions are AST-identical. Their current runner already avoids
ground-truth fallback. Extracted only bundled PMBench data/sim, not archive .git.

Fresh baseline and author `intention` runs: Qwen3-8B BF16, no quantization,
nonthinking, temperature0, actor768, same weights/scenario as our prior triplet.
An external transport wrapper routes helper calls to the local compact-grammar
server, disables thinking and logs raw calls. Author memory logic, compact prompts,
forced clock checks, channel hints and attempted-action done marking are retained.

| Method | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| Fresh author baseline | 78 | 484 | 3 | 13.9% | 96.3% | 24.3% |
| Actual author GitHub PIS | 46 | 153 | 35 | 23.1% | 56.8% | 32.9% |
| Our prior PIS-inspired | 62 | 146 | 19 | 29.8% | 76.5% | 42.9% |

All80 steps,81 identical state-aware due occurrences, zero final actor failures.
Both missed15; authors-only misses20; ours-only misses4. Author runtime40.6min,
102 actor queries versus ours157. Author helper111calls/410,951tokens and actor
186calls/398,902tokens.27 replies truncated (23helper,4actor), recovered except
one post-action memory parsing error. Friday s10 also had an unsupported-channel
recall error. Those are memory errors, not actor-output fallback. Final store194
records with110 excess exact copies; largest duplicate group23.

Failure examples established: premature selection marks future medication done
and suppresses its later reminder; an unrelated new intention overwrites the
intake-form row; `override` ignores a supplied `new_day`; future conditions are
misrepresented as current scene evidence; ordinary action choices become memory
obligations. Offline replay confirmed premature-done and date-loss code behavior.
The reports separate direct evidence from causal hypotheses; not every miss is
assigned a root cause. Our higher F1 does not cure our zero-ACT failure, nor prove
a generic memory benefit. Paper57.2% was not reproduced under identical settings.
Architectures, history, query budgets and costs differ; only one run each.

Artifacts: `harness/memory_results/qwen3-8b-author-pis-20260922-01/`
(RESULTS.md, FAILURE_CASES.md with expected/actual JSON, FAILURE_ANALYSIS.json,
all FP/FN in failures.csv, complete raw calls, snapshots, manifests).
Protocol/tooling: `harness/AUTHOR_PIS_EXPERIMENT.md`,
`run_author_pis.py`, `summarize_author_pis.py`, `test_author_pis.py`.
Independent rescoring agrees with native reports; hashes verified.172 local tests
and10 upstream tests passed. Hardened the external call-limit guard after the run;
it was never triggered and did not alter these results. Both owned model servers
stopped; GPUs verified free. No source fixes to either memory policy and no push.

Proposed next direction: generic identity-aware registration/revision validation,
preservation of trigger constraints, source-role-aware deduplication, and host
success acknowledgement. Exercise real ACT generation and verification before
claiming their benefits; test safeguards on independent streams before PM-Bench.

## September 22: PIS-inspired pilot completed; verifier not exercised

User proposed Zhao/Wu's *Making Prospective Memory SLM-Shaped: Typed Intention
Stores for Small-Model Agents*, arXiv:2609.01272v1. Saved the PDF under `papers/`.
Implemented independent opt-in `pis` and `pis_verified` plug-ins, not author-code
reproduction: typed Form/Revise, weekday/clock gates, per-intention language judge,
actual-query step budgets, and optional original-source ACT verification.
The actor retains action authority; PM-Bench supplies no verified success feedback.
No policy defaults changed. Protocol: `prospective_memory/PIS_EXPERIMENT.md`.

Two early attempts were interrupted for a typed-slot deduplication defect and
a non-advancing wrong-channel query loop. Logs retained, no candidate scores.
Fixed deduplication and added a two-query step budget with explicit exhausted
guidance, plus abort above 12 queries; 168 tests passed before the final run.

Completed triplet `harness/memory_results/qwen3-8b-pis-triplet-20260922-03`:
baseline 78/484/3 TP/FP/FN, F1 24.3%; PIS 62/146/19, F1 42.9%; verifier-enabled
55/138/26, F1 40.1%. All 80 steps, zero actor fallback. Recall 96.3% / 76.5% /
67.9%; selected tasks 562 / 208 / 193. Runtime 1.9 / 43.1 / 42.5 minutes.

Crucial post-run audit: ZERO raw or accepted ACT proposals in BOTH candidates;
zero verifier calls, although enabled in arm three. Thus this did not exercise
the verification ablation. Do NOT conclude the verifier harmed performance.
The actual intervention was checking/budget guidance. Most semantic CHECK proposals
were rejected for unavailable/exhausted sources (1,140 / 1,150 rejections).
Helper costs 1.72M / 1.67M tokens excluding probes and actor use. PIS had one
truncated registration output; the other arm had zero JSON/API errors.
No validated reminder competence/generalization or causal attribution from F1.

Independent rescoring, source/scenario hashes and snapshot restores passed;
saved RESULTS.md contains the zero-ACT/verifier caveat. Both GPUs released,
confirmed 13:35 UTC. Next: investigate why due cases never yield ACT and why
the judge requests unavailable checks; validate the extension only when exercised.
No new implementation/run or GitHub push during the result audit.

## September 21: user-requested PM-Bench trial of indexed memory

User chose an exploratory PM-Bench evaluation despite failed generic registration
gates. Added opt-in `IndexedMemoryEngine` and runner `--memory-policy indexed`:
source-indexed bank, same-model update resolution, source-aware monitor and
cross-day persistence with original/current host labels. No hidden benchmark
state, due-task labels or oracle target assignment enter the helper. This newly
integrated pipeline has not inherited the registration-only 88.2% score.

Fresh baseline and candidate used the same running Qwen3-8B BF16 actor, pinned
weights/config, scenario and corrected empty fallback. Baseline 78/484/3 TP/FP/FN,
F1 24.3%; indexed 34/46/47, F1 42.2%. All 80 steps completed, zero actor fallback.
The +17.97-point F1 gain accompanied recall falling from 96.3% to 42.0%.
Candidate always selected exactly one task per step, versus baseline's 3–8;
do not attribute the improvement to remembering without an output-count control.
It is not a fair comparison to historical 42.0% or earlier portable 42.5%.

Helper: 318 calls, 599,784 tokens excluding probe, reminders on 79/105 cycles.
Runtime 17.8 min vs baseline 2.0 min. Seventeen output-limit/JSON failures;
monitor generated many separate CHECKs while runtime only permits one per
assessment, after parsing. Four failed registration messages included three
daily plans. Bank remains lossless at source level, not semantically complete.
Next: output-count-matched baseline control, budget-aware query emission and
preserving usable registrations when other clauses are unresolved. No broader
model sweep or general-improvement claim yet. Legacy defaults unchanged.

Run/report: `harness/memory_results/qwen3-8b-indexed-pair-memory-20260921-01/RESULTS.md`;
control `qwen3-8b-indexed-pair-baseline-20260921-01`. Both trajectories independently
re-scored; snapshot restored and hashes verified. 147 tests pass; GPUs released.

## September 21: indexed coverage and multi-span follow-up

User approved replacing free quotation extraction with source indexing/coverage,
then continued after the first candidate exposed sentence-boundary failures.
Added opt-in `IndexedExtractor` (one review per sentence/line unit) and
`LinkedExtractor` (joint word-range coverage and continuation links). The lossless
bank now supports discontiguous exact spans, retains full original context and
restores older single-span snapshots. Neither candidate changes the PM-Bench
policy or supplies an automatic update-target resolver.

On the same 9-case/16-operation source-coverage diagnostic, matched verbatim was
8/3/8 TP/FP/FN, F1 59.3%; sentence indexed 15/3/1, 88.2%; linked 6/4/10, 46.2%.
On four added development challenges (six requests), indexed failed 0/6/6;
linked recovered 3/2/3 (54.5%) but failed both abbreviation/cross-line cases.
The linked candidate was developed after observing those failures: reused
development, not held out. Raw inputs always survived, but classification/range
coverage did not establish complete intentions. No registration gate passed and
no new PM-Bench or three-way actor experiment was launched.

Full evidence: `prospective_memory/results/INDEXED_REGISTRATION_20260921.md`.
Both verbatim controls exactly reproduced prior results, including after a server
restart. All 135 software tests pass; both GPUs released. Next research step:
reduce exact ID/range generation burden and evaluate clause grouping plus explicit
intent discrimination; keep source authority and unresolved input. Do not mistake
the 88.2% registration score for a general prospective-memory improvement.

## September 21: preservation before monitoring

The next research direction separates intention preservation from cue detection.
User approved keeping original instructions authoritative, traceable updates,
registration-fidelity evaluation, and then a three-way same-model comparison:
agent alone, agent plus bank, and agent plus bank plus selective monitoring.

Implemented opt-in `prospective_memory/preservation.py`: retain raw inputs even
on failed extraction; exact selected spans with full source context; host scope;
immutable origin plus appended updates; staged cancellations/revisions; explicit
host resolution with revision checks; validated snapshot restoration. It is not
yet integrated with the old monitor/PM-Bench runner, and does not automatically
resolve update targets. The legacy policy is unchanged.

The first Qwen3-8B BF16 registration gate on nine frozen development cases failed:
8 TP / 3 FP / 8 FN, F1 59.3%. Raw inputs retained 13/13, but the model still
merged requests, rewrote a multiline quotation and missed a request beside a
cancellation. Thus lossless storage does not imply accurate intention extraction.
This new source-coverage metric is not a trigger/PM-Bench score. Three-way run
held at the failed gate; protocol prepared, actor harness not implemented yet.
Next candidate should use source indexing/coverage accounting rather than free
quotation regeneration. Do not silently drop uncertain input or use gold targets
to resolve updates. Keep later validation separate from these development cases.

Run: `prospective_memory/results/qwen3-8b-preservation-registration-20260921-01`.
All 113 software tests pass; GPUs released. See that run's `RESULTS.md` and
`prospective_memory/PRESERVATION_EXPERIMENT.md` for limitations and next protocol.

## September 21: generic repairs, matched baseline, and rejected candidate

Implemented opt-in source-referenced compilation and same-model ACT verification
in `prospective_memory/grounded.py`, selectable through the generic evaluator and
portable runner. The final compiler extracts new requests without the existing
bank, then resolves only updates/cancellations against existing targets. This
addresses observed cross-intention interference without dataset-specific rules.
List items receive separate calls and code reconstructs exact source quotations.
The helper launcher now defaults to the validated whitespace-free xgrammar
backend. New runs snapshot source files as well as recording their hashes.

Fresh seven-case diagnostic: legacy and registration-only both scored 77.8% F1;
the first verifier-enabled candidate scored 85.7% (6 TP, 0 FP, 2 FN). On PM-Bench
that candidate failed to maintain an active bank and injected zero reminders:
77 TP / 489 FP / 4 FN, F1 23.8%. A fresh baseline on the SAME actor server and
pinned weights scored 78/484/3, F1 24.3%, with zero fallback in both. Its excessive
option selection shows the historical 42.0% baseline is not a matched comparator
for these runs; the cause of historical inference differences remains unresolved.

A generic fern/violin probe reproduced suppression of a new request by an
unrelated existing intention. Removing the target-ID enum did not help. Isolated
extraction then passed two incremental cases (5/0/0), but regressed on the broader
suite to 4/1/4, F1 61.5%. Remaining errors involved routing scope, condition/time
preservation, source omission and numeric reasoning. The final version was not
rerun on PM-Bench. All 93 automated tests passed, but these validate software
boundaries rather than general semantic accuracy. Keep `legacy` as default.

Both GPUs were released. Full chronological findings and run links are in
`prospective_memory/results/GENERIC_REPAIRS_20260921.md` and
`docs/results_ledger.md`. This remains research, not an established method
improvement. Benchmark failures informed development; do not call subsequent
iterations untouched held-out measurements. Source/condition/scope fidelity on
fresh generic inputs is the next gate before more PM-Bench runs.

## September 22-23: PIS source-bound line beats the baseline for the first time

Verified from run artifacts 2026-09-23. Index: `docs/results_ledger.md`.

**First result above the historical baseline.** `pis_source_bound_v3`
(`…pis-source-bound-pair-20260922-01/candidate-v3-01`) scored PM-Bench Set-F1
**52.4%** (TP 43, FP 40, FN 38, recall 53.1%), against the historical released
baseline of 42.0% and the previous best portable run of 42.5%. 80 steps, zero
actor fallback, matched two-server setup recorded in the pair's
`environment.json`. Earlier steps in the same line: `pis` 42.9%, `pis_verified`
40.1%, `indexed` 42.2%.

**A combined successor was rejected by a predeclared rule.**
`pis_trigger_fair_v5` was required to beat V3 on both F1 and recall before being
adopted; it scored 49.7% / 49.4%, below V3 on both, and was rejected. It is a
valid negative result, preserved as `candidate-v5-01`.

**The methodologically important finding is that V5 wins every helper suite and
still loses the benchmark** — smoke 10/10, transfer 10/10, trigger-roles 8/8
(V3: 3/8), temporal 4/4, batch 4/5. Frozen helper suites, including independently
authored transfer cases, do not predict PM-Bench score. Any claim resting on
suite performance is unsupported; the suites are diagnostic instruments, not
proxies for the benchmark.

**Batch registration was the decisive diagnostic.** A first candidate was
deliberately aborted at 28 cycles after storing 1 of 10 requests from combined
daily plans: it merged source text, omitted requests and invented source names.
A frozen 5-case, 19-request batch suite was then added that requires one correct
record per request. The preserved v2 policy scores 1/5 on it while passing both
10-case suites, so the earlier suites had been blind to plan-level registration.
v3 reaches 4/5.

**Open comparator problem.** Every fresh matched baseline scores 78/484/3 =
24.3% (precision 13.9%, recall 96.3%), against the historical released
baseline's 34/47/47 = 42.0%, on the same scenario hash, actor token budget and
empty fallback. The unaided actor now selects about six tasks per step instead
of behaving like the released trace, and the cause is unexplained. V3 exceeds
both, so the direction of the result is robust, but the reported margin depends
entirely on which baseline is correct. This must be resolved before publication,
and the resolution belongs in the paper regardless of outcome: it is a second
instance of PM-Bench's measured baseline depending on inference conditions the
released numbers do not document, alongside the fallback artifact.

**Open bug in the winning run.** The calendar-clause guard reads an unrelated
verb such as "drop off an item" as dropping a weekday restriction, confirmed
with a synthetic example (`results/calendar_guard_diagnosis_20260923.md`). It
was active during the 52.4% run, which therefore understates or overstates the
repaired system by an unmeasured amount.

Practice that produced these results and should continue: one change per run,
every attempt preserved including aborted ones, frozen fixtures with scorer-only
labels, independent artifact audits reproducing scores from raw outputs, and
predeclared adoption rules that can reject a candidate the authors favour.

## September 18-21: structured-output root cause, isolated repairs, first PM-Bench portable run

Full index of runs: `docs/results_ledger.md`.

**Root cause of every helper decode failure since September 11.** The compiler
and assessor schemas carried `maxItems`. xgrammar cannot compile such a schema,
so under vLLM's default `auto` backend every helper request silently fell back
to a backend permitting arbitrary whitespace between JSON tokens; greedy decoding
then reached a newline fixed point after a completed field and emitted
separators to the token cap. All 8 September 17 failures were complete, correct
rows followed by ~720 newlines. Fix: `maxItems` removed from the wire schemas
(bound kept in `llm._rows`), server started with
`xgrammar:disable-any-whitespace` through `prospective_memory/serve.py` (vLLM's
CLI rejects the option form; the V1 engine ignores per-request backends). Both
runners now probe the server and refuse to start without it.
`guidance:disable-any-whitespace` was tested and returned empty decisions for
all 30 assessments; it must not be used. PM-Bench's own actor schema also
carries `maxItems` and therefore depends on the same silent fallback; this is
worth stating in any write-up of the benchmark.

**Diagnostic, one change per run** (same 10 cases, `cases_sha256` identical):
v3 66.7% (clean measurement) -> v4 80.0% (CHECK paragraph narrowed) -> v5 80.0%
(cancellation wording, no effect) -> v6 84.2% (stored quote hidden from the
compiler: structural fix succeeded where instruction failed) -> v7 94.7%
(source list re-anchored). Registration recall 1.00, decode errors 0, one
remaining FP from negative-number comparison. The earlier 82.4%/70.6% are
contaminated by undecoded assessments scored as silence. Development set; not
generalization evidence.

**PM-Bench portable run** (`qwen3-8b-portable-20260918-02`): Set-F1 **42.5%**
(TP 41, FP 71, FN 40) vs historical baseline 42.0% (34/47/47). No measurable
difference; first memory method not to lose to baseline and first to raise
recall (+7 hits), at the cost of +24 false positives. Helper clean (211 calls,
1 error); selective (ACT on 24/110 cycles vs v2's 102/109); 30 state queries;
zero actor fallback. Required two servers: actor on default `auto` (historical
conditions) on GPU 1, helper whitespace-free on GPU 0; `run_memory.py` gained
`--memory-base-url`. The FP increase is not reminder spam and is unexplained;
candidates are query-surfaced content, the memory block in every actor prompt,
and never-acknowledged intentions re-firing. Single trace. Held-out: not to be
tuned against. New harness metrics: `silent_drop_instruction_ids`,
`registration_recall`, `assessment_failed` per tick.

## September 17: refined generic-memory diagnostic

Completed `prospective_memory/results/qwen3-8b-semantic-v2-refined-20260917-01`
on the same 10 cases / 30 ticks as September 11, using Qwen3-8B BF16 without
quantization, vLLM 0.8.5.post1, one RTX 6000 Ada. Driver repaired to 580.178.04.
Server stopped after evaluation. This was not PM-Bench.

Stronger action extraction, compact assessment instructions, smaller schema
limits and separate 1024/768 registration/assessment token caps produced TP=6,
FP=2, FN=3, F1=70.6%, down from TP=7/FP=1/FN=2 and 82.4%. Generic action
descriptions fell from 9/10 to 0/10; decoding failures from 17 to 8; total tokens
from 94,028 to 35,586. Pull-only monitoring succeeded with three actual queries.
Initial registration still omitted one of eleven intentions.

Remaining problems include malformed WAIT output, incomplete conjunctions,
negative-temperature comparisons, missed independent registration and incorrect
source assignment blocking valid evidence. Total engine errors remain 18,
including nine invalid CHECKs and one source-mismatched ACT. The action-text
keyword heuristic undercounts three concrete actions because its reference
contains trigger clauses; it is not a semantic accuracy measure.

This reused development diagnostic cannot establish generalization or superiority
over the PM-Bench baseline. Changes were bundled; one prompt example overlaps a
case. Full results and caveats are in the run's RESULTS.md. Next work focuses on
registration/source coverage, output reliability and trigger reasoning before
fresh diagnostic cases and PM-Bench. Candidate filtering for large intention
banks was discussed but remains unimplemented; monitoring still assesses all
pending in-scope intentions on each host call.

## Research objective

This project studies **prospective memory in language-model agents**: an agent's
ability to retain an intention and act when its future time- or event-based cue
occurs while the agent is occupied with other tasks.

The motivating long-term problem is externally triggered, persistent intention
monitoring. For example: “When Bob sends the budget, forward it to Sarah.” The
agent must continue unrelated work, monitor external channels, recognize the cue
when it eventually arrives, and execute the intended action. This differs from
retrospective memory or within-task state maintenance: the central problem is not
merely retrieving past information, but noticing when a future condition becomes
true and acting at the correct time.

## Long-term research direction

The current methodology inspiration is Wu et al., “Remember When It Matters:
Proactive Memory Agent for Long-Horizon Agents” (arXiv:2607.08716), downloaded to
`papers/remember_when_it_matters.pdf`. A proposed PM-Bench mapping is documented
in `papers/remember_when_it_matters_pmbench_plan.md`. It motivated bank maintenance
and selective reminders for pending intentions and channel-check recommendations.
V1/v2 pilots have now been run without establishing an improvement. The user's
subsequent clarification is that the method must address generic prospective
memory, with unrelated tasks and arbitrary timing; PM-Bench is only a testbed.
The paper's main memory agent runs every step; silence suppresses a reminder but
does not avoid that memory-model call. Its ablations do not show selective
reminders winning every aggregate metric.

The broader hypothesis is that prospective monitoring can be separated from the
main action agent. A specialized, inexpensive model could continuously monitor
events and pending intentions, escalating plausible matches to a stronger model.
This could reduce inference cost and interference with the action agent while
preserving recall.

The intended research progression is:

1. Establish trustworthy prospective-memory evaluation.
2. Measure how model scale and monitoring scaffolds affect performance.
3. Separate monitoring ability from general agent-loop ability.
4. Develop a dedicated monitoring or escalation architecture.
5. Evaluate recall, false alarms, latency, and compute cost under realistic event
   streams and long time horizons.

## PM-Bench

The current empirical testbed is PM-Bench, a cognitive-science-inspired benchmark
based on the event-based versus time-based prospective-memory distinction. Its
synthetic week contains 80 interaction steps and 81 due task occurrences per
configuration. Agents must continue an ongoing A/B/C activity while remembering
pending intentions, deciding when to query hidden channels, and selecting task
handles when intentions become due.

PM-Bench evaluates task selections using accumulated true positives, false
positives, and false negatives. Its headline Set-F1 is:

```text
Set-F1 = 2TP / (2TP + FP + FN)
```

The A/B/C ongoing-activity choice is not scored. It provides an interfering task;
the scored output is the set of selected `task_ids`.

## Discovered evaluation artifact

The original single-agent PM-Bench runner expects structured JSON. If a model
still produces an invalid response after its retries, the original terminal
fallback replaces the model's task selection with `sorted(due_now)`. Here,
`due_now` is the evaluator's ground-truth set of tasks due at that step.

Consequently, an invalid response can receive perfect task-selection credit. A
model that always emits invalid output can theoretically obtain 100% Set-F1. The
artifact is especially dangerous when comparing models with different structured-
output compliance because weaker format compliance creates more opportunities to
receive ground-truth answers.

The exact fallback applies to `single_baseline` and `single_heartbeat`, including
optional/proactive, automatic-30-minute, and automatic-60-minute heartbeat modes.
TODO-ledger and hierarchical runners use different recovery paths and require
separate audits.

## Corrected evaluation protocol

A first memory-intervention pilot was implemented in
`harness/memory_intervention.py` and `run_memory.py`, with an
optional visible-message adapter hook in PM-Bench. It supports baseline,
heartbeat, full-bank, always-remind, and selective-reminder modes. Completed
selective v1/v2 results are recorded below. Other modes being available does not
mean a complete intervention comparison was run.

The project adds two selectable invalid-response policies without otherwise
changing PM-Bench's scenario, prompts, retries, agent logic, or scoring:

- `ground_truth`: reproduces the original behavior by inserting due tasks.
- `empty`: treats terminal invalid output as inaction with `task_ids: []`.

Instrumented trajectories record `fallback_triggered`, `fallback_policy`, and
`fallback_reason`. Paired rescoring removes fallback-inserted selections from the
same trajectory to isolate immediate score inflation. A separate end-to-end run
with the corrected policy is preferred whenever a fallback action could influence
later runtime state.

## Main findings so far

The historical Qwen3-8B single baseline has TP=34, FP=47, FN=47, F1=42.0% and zero
actor fallback or channel queries. Its zero-fallback trace is a useful baseline
reference. Most other audit "corrected" scores are same-trace counterfactuals,
not independently executed corrected-policy runs.

Structured-intention v2 pilot completed: F1=41.0% (TP=33, FP=47, FN=48), versus
v1 37.3% and historical baseline 42.0%. It preserves a nonempty bank (35 final
records), but emits reminders on 102/109 cycles and directs 26/29 queries to the
clock. Two edits cycles rejected unobserved evidence quotes; zero actor fallback.
These single runs suggest improved implementation behavior, not established
superiority over baseline. The v2 results and diagnostics are under
`harness/memory_results/qwen3-8b-selective-v2-20260911-01/RESULTS.md`.

Trace analysis of the first completed memory pilot found semantic bank failures:
day-specific handles used as persistent IDs, lost trigger conditions, stale
cross-day reminders, and an empty knowledge bank for the last 39/94 cycles.
Procedural memory was unused. These observations motivate enforcing intention
structure before attributing failure to model size or selective memory itself.
See the completed pilot's FAILURE_ANALYSIS.md for evidence and limitations.

Completed first selective-reminder pilot: Qwen3-8B actor/helper, empty fallback,
80 steps; Set-F1 37.3% (TP=30, FP=50, FN=51), compared with the historical
single baseline's 42.0%. No improvement was observed. After repairing helper JSON
output (constrained schema, thinking disabled, 2048-token allowance), all 94
cycles parsed but 89 emitted reminders. The policy was rarely silent. Of 12
state queries, 11 were clock checks. Results are in
`harness/memory_results/qwen3-8b-selective-20260911-02/RESULTS.md`.
The initial run `qwen3-8b-selective-20260911-01` was interrupted and preserved
because helper reasoning text violated its JSON parser. It has no completed
performance result. V1 run 02 and v2 completed on a local Qwen3-8B BF16 model,
without quantization, using vLLM 0.8.5.post1 and a 32768-token context. The actor
allowance remained 768 and the repaired helper allowance was 2048 tokens.
Local GPUs were accessible with sandbox escalation; initial sandbox driver errors
were not evidence that the host GPUs were unavailable.

Across the evaluated configurations, fallback contamination is highly dependent
on model family and structured-output compliance rather than parameter count
alone. Some small Qwen and Ministral models generated parseable but often wrong
JSON and therefore had almost no fallback. Llama-3.2 and Phi-4 Mini frequently
failed parsing and received very large artificial gains.

The clearest anchor result is Qwen3-8B with proactive heartbeat:

- Released PM-Bench Set-F1: 71.9%.
- Instrumented reproduction with original fallback: 72.7%.
- Same-trace score after removing fallback credit: 32.8%.
- Fallback triggered on 41 of 80 steps and inserted 42 due task selections.

The released and reproduced raw values differ slightly because LLM inference is
not guaranteed to be identical across runs, model revisions, inference-engine
versions, hardware, and chat templates. Their true-positive and false-negative
counts matched in this case; our run produced two fewer false positives.

For the four-configuration aggregate, quantized Llama-3.3-70B and Qwen3-32B have
nearly identical corrected Set-F1 (54.2% versus 54.4%) but different operating
profiles. Llama is more precise and conservative; Qwen finds more due tasks but
also selects more incorrect tasks. This is not evidence that performance strictly
decreases from 32B to 70B.

## Reproducibility cautions

- Our Llama-3.3-70B run used 4-bit BitsAndBytes weight quantization with BF16
  computation and tensor parallelism across two GPUs.
- The PM-Bench paper states that Llama-3.3-70B was accessed through OpenRouter but
  does not document provider, weight precision, quantization, hardware, exact
  model revision, or inference-engine version.
- Therefore, our Llama-70B evaluation is useful for fallback analysis but is not a
  precision-matched reproduction of the paper's Llama run.
- A 0% fallback rate means valid structured output, not good prospective memory.
  A model can consistently return valid but incorrect JSON.
- Wrong extra selections are false positives and are separate from missed due
  tasks; both can happen at the same step.

## Archived audit interpretation

`results/fallback_interpretation_table.md` under `harness/` aggregates
four configurations per model: single baseline, proactive heartbeat, automatic
30-minute heartbeat and automatic 60-minute heartbeat. Each aggregate has 320
steps and 324 due occurrences. The summary CSV retains configuration-level data.

| Llama-3.3-70B aggregate | Correct | Missed | Wrong extra selections | Set-F1 |
|---|---:|---:|---:|---:|
| Original fallback | 149/324 (46.0%) | 175/324 (54.0%) | 53 | 56.7% |
| Same-trace corrected | 140/324 (43.2%) | 184/324 (56.8%) | 53 | 54.2% |

Nine apparent successes were fallback-supplied. Corrected misses are 175 ordinary
omissions plus nine removed fallback-supplied successes. Wrong extras are separate
false positives, not a subset of missed tasks. For the Qwen3-8B proactive anchor,
original TP/FP/FN=64/31/17 and corrected=22/31/59: 42 due selections were supplied
on 41/80 fallback steps (51.25%).

Reporting identities: original correct = corrected correct + fallback-supplied
correct; corrected missed = original missed + fallback-supplied correct. Report
these counts alongside Set-F1 and fallback-step rate. Fallback frequency is not
prospective-memory ability. Terminal invalid-response handling can also include
validation/transport problems; do not attribute every occurrence to free-text
JSON formatting without inspecting its logged reason. The actor parser can
extract structured content from some larger responses.

Historical settings to preserve: `benchmark/data/synthetic_week_v9.json`, temperature
0.0, 768 actor output tokens, two invalid retries, SGLang-compatible local API.
One trace per model/configuration cannot establish uncertainty. Pending audit
extensions include repetitions, uncertainty intervals, precision-matched 70B
evaluation and separate TODO-ledger/hierarchical recovery audits. These are not
completed experiments.

## Generic module milestone — completed 2026-09-11

Following the user's request for a generic, plug-and-play methodology, implemented
`prospective_memory/` independently of benchmark task rules. It separates:

1. Instruction compilation into stable, quoted, revisable/cancellable intentions.
2. Condition assessment against host-provided observations, returning ACT, CHECK
   or WAIT without inferring hidden state.
3. Host execution/acknowledgement and environment-specific adapters.

The core provides persistence, recurrence, evidence-identity deduplication,
push/pull capability restrictions and per-assessment CHECK proposal limits. The
policy is a model-provider-independent callable. PM-Bench integration discovers
public channels, strips menus/options, resolves no hidden task IDs, and leaves
current handle selection to the actor. Review fixed invalid push-stream queries
and disappearing ACT reminders during intervening actor queries. The runner
accepts `--mode selective --memory-version portable`; prior v1/v2 behavior remains
available. Full contract and proposed live-run command: `prospective_memory/README.md`.

Completed validation: 49 automated tests, including an 80-step scripted portable
integration, and 10/10 independent scripted event-stream scenarios (covered by the
unit suite too). The demo includes delayed and unrelated tasks, simultaneous
intentions, cancellations, revisions, absent triggers, stale/fabricated evidence,
push/pull queries, persistence and recurrence. Results and caveats are saved in
`prospective_memory/examples/event_stream_results.json` and
`prospective_memory/examples/VERIFICATION.md`. This is software validation using
scripted providers, **not a real-model result**.

First independent live-model diagnostic: `prospective_memory/results/qwen3-8b-semantic-v1-20260911-01`
completed on 2026-09-11 before an attempted interruption. It used Qwen3-8B BF16
with no explicit quantization flag on 10 hand-authored non-PM-Bench event streams.
The scorer aligns ACT proposals to original instruction provenance only, not
action fidelity or execution success. Result: TP=7, FP=1, FN=2, precision=87.5%,
recall=77.8%, F1=82.4%, exact ticks=27/30. Major caveats: 17 assessment calls
hit the 4096-token limit and failed JSON decoding, consuming most completion
tokens, and most registered action fields collapsed to `remind` instead of the
full requested action. The pull-only case missed because the model never emitted
CHECK for `deployment_status`. This diagnostic supports next-step debugging; it
is not a PM-Bench improvement claim.

Important outstanding issues: quoted provenance is not semantic entailment;
model interpretation can still be wrong. Hosts must supply events/scheduling and
actual execution feedback. PM-Bench's adapter logs attempts without inferring
completion from task handles; its one-shot intentions may remain pending.
Newly received delta replies do not establish event occurrence time. The budget
is per helper assessment, not enforced total actor queries. Bank/history growth,
total token accounting, cost-matched comparisons and real-model semantic
validation remain unfinished. The README proposes helper=4096 for the next run;
this differs from prior pilots and has not yet been evaluated.

The next scientific test should use independent natural-language event streams,
then freeze the generic policy for PM-Bench evaluation, measuring trigger recall,
false alarms, execution success, delay and compute cost separately. Do not tune
benchmark-specific trigger/channel rules or use hidden scorer success as runtime
memory feedback. Update both context files after completed major experiments,
not with live progress, per the user's preference.

## Repository map

- `benchmark/`: upstream benchmark code, scenario, released runs, and scorer.
- `harness/`: instrumentation, paired rescoring, matrix runner, and
  audit results.
- `prospective_memory/`: generic core, model policy, host adapter, independent demo
  and validation report; start with its README for the current method.
- `tests/test_prospective_memory.py`: benchmark-independent core/lifecycle tests.
- `harness/results/summary.csv`: configuration-level audit results.
- `harness/results/fallback_interpretation_table.md`: aggregated,
  human-readable model comparison.
- `claude-history.md`: chronological record of earlier exploration and decisions.
- `docs/current_work.md`: short operational handoff for the work in progress.
- `docs/results_ledger.md`: one-table index of every completed live run with paths.

## Publication framing

The defensible near-term contribution is not merely a small-model scaling study.
It is the identification, instrumentation, and quantification of an evaluation
artifact that rewards invalid responses with ground-truth actions, followed by a
clean comparison of prospective-memory performance under the corrected protocol.
A later full paper can use these trustworthy measurements to motivate and assess
a dedicated prospective-memory monitor.
