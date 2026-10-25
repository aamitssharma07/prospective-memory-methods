# Evidence-first PIS candidate (`pis_grounded`)

Implemented 2026-09-22 at the user's request. **First live smoke gate FAILED.**
This is a new opt-in candidate, not an overwrite of the two archived baselines
or a relabeling of the earlier 42.9% F1 run. Defaults and historical policies
remain available. The initial implementation launched no GPU job; the subsequent
user-approved helper-only smoke has now completed and its server was stopped.

## First live validation outcome

The frozen ten-case Qwen3-8B BF16 smoke passed 0/10 full contracts. Six of eleven
required origins registered; all seven accepted records (including an erroneous
extra revision record) have incomplete action fields. Four ACT proposals appeared
(three origin/time matches and one extra), but no CHECK. No API/JSON decode errors.
The new ACT pathway can occur, but successful complete reminders are not established.
The reviewer confuses ADD with UPDATE; a revision duplicates rather than changes a
record; unknown-versus-false remains confused; and a shortened source quote makes
the clock guard remove a legitimate time present in the full original instruction.
Do not proceed to the full week from this version. No prompt/policy tuning was
performed during or after the frozen run. [Full report](../results/pis_grounded_smoke_20260922/README.md).

The new `evaluate_pis_grounded.py` harness logs every request, review, response,
usage, error and state with source/case hashes; its ten cases are frozen in
`examples/pis_grounded_smoke_v1.json`. Gate scoring requires registration as well
as correct decisions, so an empty bank cannot pass as successful silence.
The preflight also fixed a separate state-consistency bug: a rejected second
revision can no longer overwrite the accepted record's typed clock sidecar.
This fix preceded source freezing and is covered by a regression test.

## Evidence motivating the changes

Source: `pmbench_fallback_audit/memory_results/qwen3-8b-pis-triplet-20260922-03/pis/memory_calls.jsonl`.
Call IDs below refer to the saved local helper trace, not new model outputs.

- Call 1 converts “Take antibiotic at breakfast and dinner” into hard 08:00 and
  18:00 gates and the condition “every day.” Neither time appears in the request.
  A gate can therefore suppress the semantic decision before the meal is assessed.
- Call 91 asks for calendar confirmation of a medication schedule despite the
  original user instruction and a current 11:00 clock reading.
- Call 127 labels its response CHECK even while its reason states that 11:50
  matches the library-email condition. It cites the clock but requests that same
  already-observed source. The runtime correctly rejects that invalid CHECK;
  it must not guess ACT from free-text reasoning.

These examples establish concrete errors, not the complete explanation for zero
ACT across the run. The author's wrong-target updates motivated an additional
preventive guard; they do not prove that our run made identical mutations.

## Changes and responsibilities

| Component | New behavior |
|---|---|
| Registration code | An unsupported hard clock is removed; the full supporting instruction quote becomes the semantic condition. A literal clock must appear in that quote to become a hard gate. |
| Memory-change reviewer (same model, separate call) | Reviews every proposed registration/revision/cancellation before mutation, including target originals and unchanged constraints. Unsupported changes leave the old store intact; inputs remain archived. |
| Evidence assessor (helper LLM) | Receives original instructions/revisions as specification, current observations as evidence, and the available query budget. Returns satisfied / not_satisfied / unknown, not a control-action label. |
| Decision code | Maps satisfied with valid current source evidence to ACT; unknown with a valid available source to CHECK; otherwise WAIT. Inconsistent or malformed assessments fail closed and are logged. |
| Evidence validation | Requires paired exact quotes and current observation IDs. Instruction IDs cannot masquerade as observation evidence; watched-source membership is checked. |
| Runner | Adds opt-in policy selection, source snapshotting and separately labeled change_review call logs. |

Clock normalization is conservative, not a universal temporal parser: for example,
natural-language/relative times can remain in the full condition for the semantic
assessor instead of becoming unsafe hard gates. Literal presence does not prove
the time belongs to the right action; the semantic reviewer must still check that.

Watched sources are possible providers of evidence, not extra prerequisites.
The prompt explicitly says a scheduled task does not need calendar confirmation
unless the original instruction actually asks for it. Multiple genuine trigger
conditions still all need support; a matching clock alone cannot satisfy them.

Unchanged: main-agent authority and original input, menu stripping, explicit
day/time eligibility rules, one-intention-at-a-time evaluation, one CHECK per
assessment by default, two actual-query-attempt step budget with guidance, and
the >12-query explicit abort. Selection is still not confirmation of completion.
Source routing, batching, autonomous polling and forced actor queries are NOT
implemented by this change. The optional old ACT verifier is not enabled by the
new CLI policy; the new mutation reviewer is a different component.

## Usage (not executed)

With appropriate actor/helper servers already running, use a **new** output
directory. This command is for a later approved live experiment:

```bash
.venv/bin/python pmbench_fallback_audit/run_memory.py \
  --mode selective --memory-version portable --memory-policy pis_grounded \
  --model Qwen/Qwen3-8B --memory-max-tokens 4096 \
  --base-url http://127.0.0.1:30003/v1 \
  --memory-base-url http://127.0.0.1:30002/v1 \
  --output pmbench_fallback_audit/memory_results/qwen3-8b-pis-grounded-01
```

This command does not launch servers or rerun the baseline. The historical
triplet launcher still runs its original arms and is not the new policy launcher.

For another host, instantiate `GroundedPISEngine` with a model callback and exposed
sources, and supply public instructions, observations, step/query callbacks and
actual success acknowledgements when available. No simulator internals, task IDs
or ground-truth due labels are used by the engine.

## Validation and next experiment

Scripted tests exercise positive ACT, negative WAIT, missing-evidence CHECK,
unsupported clocks, wrong-target/narration rejection, invalid/stale/fabricated
evidence, conjunctions, exhausted budgets, per-row review failures, deduplication,
completion boundaries and policy-specific atomic snapshot restoration. The runner
test executes all 80 simulated steps with fake helper/actor responses, checks
source snapshots/log phases and restores the adapter. These tests validate
software wiring; scripted reviewer verdicts do not establish model competence.

Before a scored week, run live positive/negative generic cases to check whether
the model now emits valid supported assessments and whether legitimate requests
survive review. Include new obligations, unrelated updates, multi-source conditions,
future mentions, paraphrases and unsupported tools. Do not proceed on a zero-ACT
or low-registration-coverage result merely because unit tests pass.

For a full comparison, report TP/FP/FN, precision/recall/F1, true reminder counts,
registration/review rejection rates, invalid evidence/checks and all helper costs.
Raw helper outputs now contain assessments/reviews, not decisions: count delivered
ACT/CHECK/WAIT from `memory.jsonl`, and assess model output separately. Do not reuse
the old raw-decision counter without accounting for this schema change.

## Limits

- A second call to the same model can share its errors. Quoted text proves
  provenance, not logical entailment; satisfied can still be semantically wrong.
- Review adds cost and may reject legitimate tasks, reducing recall. Rejected
  inputs are retained but are not automatically retried or repaired.
- Registration can still omit an intention entirely; there is no completeness
  guarantee. Original messages can grow long and must be included in cost accounting.
- No autonomous checking or completion feedback has been added to PM-Bench.
- This bundles registration and assessment changes. Any improvement must later
  be separated by ablations before claiming which component caused it.
- No new PM-Bench F1 score or generic plug-and-play effectiveness claim is justified.
