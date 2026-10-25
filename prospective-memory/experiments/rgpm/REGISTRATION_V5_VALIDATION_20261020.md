# Registration repair v5: validation and GPT smoke

User authorized fixes and a GPT test on October 20, 2026. The candidate policy is
`focused_resolved_partition_v5`. Full benchmark execution remains disabled.
No previous results are overwritten or removed.

## Candidate

- Provider duplicate review resolves concrete actions before comparing obligation
  identity and occasion. Trigger arrival is distinguished from an additional request.
- Thirteen synthetic registration cases include pronoun resolution, explicit
  activation, a different action sharing the same cue, and additional occasions.
- Eight historical registration inputs from canceled run 1535138 are replayed
  independently with their original public memory. Evaluator expectations are not
  sent to models. This is development diagnostics, not a resumed benchmark or F1.
- Hosted actor provenance no longer inherits the local helper's GPU metadata.
- All inference requests retain max_tokens=768, temperature=0. Raw responses,
  parsed responses, semantic decisions, errors, call usage/duration, source
  snapshots and hashes are retained in separate job directories.

## Local Validation

Job **1536925**, `exp3-registration-repair-local-v5`, uses Qwen3-8B locally for
both roles, query_first guidance and legacy handoff. Registration grounding,
source routing, scope grounding and bounded priority are enabled.
Action verification and gate reporting are disabled.

Before submission, 71 Experiment 3 unit tests passed. The job repeats the full
offline preflight, then runs routing, readiness, synthetic registration,
historical registration replay, and finally the six-step integrated smoke.
Any diagnostic failure stops the job. LOCAL_ONLY=1 and RUN_FULL=0 prevent GPT
calls or a full benchmark. Local smoke FP/FN limits are unset; execution success
alone is not a quality claim.

- Console: `jobs/exp3-registration-repair-local-v5-1536925.log`
- Diagnostics: `jobs/qwen3-8b-actor-helper-qwen3-8b-1536925/`
- Smoke: `smoke_artifacts/qwen3-8b-helper-qwen3-8b/sbpm/qwen3-8b-actor-helper-qwen3-8b-1536925/`

Outcome: job FAILED (exit 1:0, 00:02:05). Routing and readiness passed;
registration passed 12/13 cases. The duplicate cue case still failed: the
comparison returned resolved_reply_action="do it" and distinct_request.
Historical replay and integrated smoke were not reached. Zero GPT calls.

## Bounded Repair Follow-up (v6)

Policy `focused_resolved_partition_v6` rejects bare placeholder predicates in
resolved action fields. One logged comparison repair is allowed; a second
invalid response is rejected. This validation does not assign an identity,
invent an action, or force deduplication. A new regression covers both successful
repair and repeated-invalid failure. All 72 Experiment 3 unit tests pass.

Local job **1536926**, `exp3-registration-repair-local-v6`, repeats the same
gates including historical replay. Its artifacts are under
`jobs/qwen3-8b-actor-helper-qwen3-8b-1536926/`.
Outcome: FAILED (exit 1:0, 00:02:04). Registration remained 12/13.
The repair replaced "do it" with unsupported "process the signed form", still
classified as distinct. Historical replay and integrated smoke were not reached;
zero GPT calls. This attempt is not evidence of a repaired duplicate decision.

## Reference Resolution Follow-up (v7)

Policy `focused_resolved_partition_v7` replaces the placeholder repair with a
separate reference-resolution call. It selects a uniquely supported pending
record (or abstains), without generating a new action. A fresh comparison sees
that public record as the resolved reference, but still checks whether the
occasion is additional. The initial mistaken distinct-request decision is not
passed back as an anchor. All intermediate comparisons and reference decisions
are retained; a second placeholder is rejected. GPT remains gated.

Local job **1536927**, `exp3-registration-repair-local-v7`, submitted after
72 Experiment 3 unit tests passed. Diagnostics:
`jobs/qwen3-8b-actor-helper-qwen3-8b-1536927/`.

Outcome: FAILED (exit 1:0, 00:02:04), again 12/13 registration cases.
The reference resolver selected the correct pending action and the subsequent
comparison selected existing_request, but still emitted "do it now" in its
resolved-action field. Validation rejected that placeholder; no duplicate was
created, but the diagnostic correctly did not count the unresolved error as a
clean pass. No historical replay, integrated smoke or GPT inference occurred.

## Typed Occasion Follow-up (v8)

Policy `focused_resolved_partition_v8` retains the explicit reference selection,
then asks only for same/additional/uncertain occasion. It no longer asks for
another free-text rewrite of the already resolved action. Additional occasions
require a supporting verbatim quote. Ambiguous references are rejected; the
original failed comparison and all recovery decisions remain in the trace.

Local job **1536928**: all 13 synthetic registration cases passed; historical
replay passed 5/8. The return-book update still selected the pickup-hold record,
the missing budget-note update selected an appointment record, and the mixed
paragraph created a duplicate insurance-call task while missing cancellation.
The replay gate stopped execution before integrated smoke. Zero GPT calls.

## Action Identity Follow-up (v9)

Policy `focused_resolved_partition_v9` compares pending actions during target
selection, excluding trigger fields that caused incorrect topic matches. The
subsequent identity review retains the selected action and condition, without
the entire original multi-task plan. New requests receive duplicate review on
all public channels. Narrative withdrawal phrases trigger classification review;
their interpretation remains a model decision. Repeated accepted cancellations
of the same target in one message are applied once, with each coalesced source
change logged. These changes are restricted to the Experiment 3 candidate.

All 75 Experiment 3 unit tests passed before submitting local job **1537277**,
`exp3-registration-repair-local-v9`. Its diagnostics are under
`jobs/qwen3-8b-actor-helper-qwen3-8b-1537277/`. Outcome: FAILED (1:0,
00:02:40), 11/13 synthetic registration cases passed. Adding withdrawal wording
to every initial classification caused a new seating-plan task to be classified
as an update and a mixed cancellation/addition paragraph to be classified only
as cancellation. Replay and smoke were blocked; zero GPT calls.

Policy `focused_resolved_partition_v10` restores the earlier initial prompt and
moves withdrawal guidance into the targeted review. Other v9 changes remain.

Local v10 job **1537279**: 13/13 synthetic cases passed, historical replay 3/8.
The return-book target was fixed and co-op dues cancellation was recognized.
Broader review introduced paraphrased pending quotes and unnecessary abstentions
on new plan entries. Missing-target selection still guessed unrelated records;
the later identity guard rejected the budget update but incorrectly accepted the
manager update. The full trace remains under its job directory. No GPT calls.

Policy `focused_resolved_partition_v11` limits extra event duplicate review to
narrative units; explicit plan bullets retain their original registration path.
Withdrawal guidance is appended only for withdrawal cues. Pending comparison
quotes are constrained to actual stored specifications. Target selection is
followed by a separate action comparison using only the update and candidate
action; a negative match rejects the update. Every match response is logged.
All 76 Experiment 3 unit tests passed before the next local submission.

Local v11 job **1537282** failed the synthetic gate (9/13). The direct action
comparison rejected valid cue changes and cancellation as different obligations;
its own reason identified the same task but treated the changed trigger as an
identity difference. Replay and smoke were blocked; zero GPT calls.

Policy `focused_resolved_partition_v12` asks the direct comparison to extract
short verbatim action phrases without trigger clauses, explain identity, then
decide the match. It explicitly distinguishes a task's identity from its changed
conditions, recipient details, or cancellation. No evaluation expectation is
supplied to this comparison.

Local v12 job **1537286** failed the synthetic gate (10/13). Valid action
matches were recognized, but verbatim validation rejected inflection/case changes
such as "return" in place of source "returning". The decision and invalid quotes
remain in the trace. Replay and smoke were blocked; zero GPT calls.

Policy `focused_resolved_partition_v13` supplies the existing finite lexical span
grammar to direct action comparisons. Quote fields can select only exact source
spans for short inputs; semantic action identity remains the helper's decision.
Long inputs retain explicit validation. No task-specific answer or match is
encoded in this grammar. A regression verifies source and case preservation.

Local v13 job **1537288** passed 12/13 synthetic cases. The remaining explicit
recipient revision was rejected solely as "Different recipient". All action
quotes were valid. Replay and smoke remained blocked; zero GPT calls.

Policy `focused_resolved_partition_v14` names the direct verdict same_obligation
and explicitly covers a recipient substitution as a revision of the existing
obligation. Source quote constraints and rejection of unrelated tasks remain.

Local v14 job **1537289** passed 11/13 synthetic cases with Qwen3-8B.
The direct comparison rejected recipient substitution and cancellation despite
reasons identifying the targeted action. Historical replay and smoke remained
blocked; zero GPT calls. This is evidence of helper semantic instability, not a
successful repair or benchmark improvement.

The next local test keeps v14 code fixed and changes the helper to cached
Qwen3-32B (local actor also Qwen3-32B), one H100, BF16, nonthinking, temperature 0,
max_tokens=768. This is a distinct helper configuration and must be reported
separately from Qwen3-8B results. All historical artifacts remain intact.
If it passes, the authorized hosted smoke will use GPT-5.4 with Qwen3-32B and
the same usage and quality gates. No GPT calls are authorized through failed gates.
Local job **1537290**, `exp3-registration-local-v14-qwen32`, records diagnostics
under `jobs/qwen3-32b-actor-helper-qwen3-32b-1537290/`.
Outcome: stopped at routing (7/8). The helper assigned a visible loading light
to inspection_board without a requested provider report. Readiness, registration,
replay and smoke were not reached. Zero GPT calls.

The source-routing prompt now explicitly forbids inventing provider observation
capabilities from provider names and binds an ordinary visible physical condition
to events when no provider report is stated. This changes source routing only;
registration remains policy v14. Source hashes distinguish the configurations.

Local job **1537291** repeated the same 7/8 routing result. No other diagnostics
or hosted inference ran. The next configuration restores the original routing
prompt and moves reason to the first field of the routing response schema,
letting the model explain observation provenance before committing to sources.
The source set and diagnostic expectations are unchanged.

Local job **1537293** passed 8/8 routing, 14/14 readiness and 13/13 synthetic
registration cases with Qwen3-32B. Historical replay passed 7/8, fixing the return
update, all seven additions, cross-day registration and missing-target abstention.
The remaining mixed paragraph was correctly identified as compound, but both
classification attempts illegally linked the compound row to an existing ID.
The gate stopped before integrated smoke; zero GPT calls.

Policy `focused_resolved_partition_v15` enforces classification/target-ID
combinations with JSON-schema alternatives during decoding: only updates may
optionally link, restatements must link, and other classifications must use an
empty ID. Returned responses are never silently edited. The original semantic
validator and bounded repair remain; provider schema failures remain failures.
All 78 Experiment 3
unit tests pass, including valid and invalid branch combinations.
The installed xgrammar successfully compiled the exact alternative schema in a
CPU check before submission. Local job **1537296**,
`exp3-registration-local-v15-qwen32`, repeats all live gates and historical replay.

Outcome: **COMPLETED, exit 0:0, 00:12:45**. All offline checks, 8/8 routing,
14/14 readiness, 13/13 synthetic registration and 8/8 historical replay passed.
All ten local integrated smoke execution/trace checks passed, with zero schema
invalid responses and zero semantic errors. Smoke score with Qwen3-32B in both
roles: TP=2, FP=2, FN=0, F1=66.67%, exact steps 4/6. The actor selected the
canceled draft at Monday m4 and the reminder early at Tuesday t1. This is not a
quality-gated GPT result or evidence of full-benchmark improvement. Zero GPT calls.

Local smoke:
`smoke_artifacts/qwen3-32b-helper-qwen3-32b/sbpm/qwen3-32b-actor-helper-qwen3-32b-1537296/`.
Diagnostics: `jobs/qwen3-32b-actor-helper-qwen3-32b-1537296/`.

Before the hosted job, a logging-only change labels standalone registration-probe
routing calls by their schema signature instead of the first property name.
Earlier v15 probe calls labeled reason retain their complete routing schema,
requests and responses, so their source-routing phase is recoverable. This
change does not alter model requests. The hosted launcher repeats all local
diagnostics using the corrected logging code before any paid inference.

## Authorized GPT Test

Only after local checks pass: GPT-5.4 actor, the passing helper configuration
(currently testing Qwen3-32B), six-step smoke,
24 actor-call and 500,000 actor-token caps, zero allowed false positives and
false negatives, RUN_FULL=0. These are usage caps, not a guaranteed dollar cost.
The launcher repeats local diagnostics before any GPT inference.

GPT smoke job **1537306** has been submitted; its repeated local gates precede
paid inference. See [GPT registration v15 smoke](GPT_REGISTRATION_V15_SMOKE_20261020.md).
No full benchmark improvement is established.
