# Experiment 3 registration repair

## Evidence from canceled run 1535138

The run has 55 committed steps, not a completed benchmark. Its outputs remain
under `runs/query_first_v1/gpt-5-4-helper-qwen3-8b/sbpm/gpt-5-4-actor-helper-qwen3-8b-1535138/`.
The evidence below comes from `calls.jsonl` and `snapshots/000055.json`.

| Observed failure | Count | Interpretation |
| --- | ---: | --- |
| Invalid classification links | 10 | Nine NEW rows from extra review and one CONTEXT row from initial classification carried an old intention ID. |
| Unsupported positive readiness | 8 | Current watched-source evidence was missing or a missing-source request contradicted ACT. The existing guard correctly withheld ACT. |
| Rejected update identity | 1 | A manager check-in update was aimed at a library-return task. |
| Unresolved mixed paragraph | 1 | Cancellation, background intent and a new cross-day reminder were left unresolved together. |

Seven of the nine invalid NEW reviews were Tuesday's opening tasks. Their
initial classifications were valid. Review was triggered using the entire
message, allowing a word in one bullet to trigger reviews of unrelated bullets.
The separate review prompt did not restate the empty-ID rule for NEW requests.
Example call IDs: `4a6dcdd3c4d7482b800875b67be3e7ea` (prep plan),
`54ae0c3ae7b840edb7eff4fa65675a00` (manager check-in), and
`b5b023f06766406db60fac0bb4ba5f0e` (budget note).
The initial CONTEXT error is `be414e0c721f44259c8e540617de0016`.

There were also two visibly wrong accepted updates, which do NOT appear in the
error counter: Monday d1_s8 attached a return-library-book correction to
`pm_000006` (pickup hold); Tuesday d2_s7 attached a budget-note reschedule to
`pm_000005` (move appointment). The yes/no identity reviewer accepted both.
This is why reducing the error count alone is insufficient validation.

## Candidate changes

- Review cues come only from the focused unit. Provider-channel NEW requests
  still receive review to distinguish fresh instructions from trigger reports.
- Initial classifications and review responses both receive semantic validation.
  At most one helper repair is allowed across those stages. Invalid responses
  are retained and counted; code never clears an ID to make a response valid or
  substitutes an expected answer. A second invalid response rejects that unit.
- Updates/cancellations require independent target selection across all pending
  records, without showing the earlier target suggestion. Missing/ambiguous
  targets abstain. Compilation is constrained to the selected target, followed
  by the existing explicit-update identity check. These model judgments remain
  fallible; agreement is not proof of semantic correctness.
- Uncertain/compound units may receive one bounded, lossless source partition.
  Every non-whitespace character must survive exactly once in source order.
  Each child is classified separately; children are not recursively expanded.
  Layout-unit and operation caps remain enforced. Exact coverage prevents text
  omission but cannot prove that a proposed boundary preserves all semantics.
- A failed compiled operation cannot erase unrelated valid operations from
  the same message.
- Registration decisions and repairs persist in `registration_log` inside
  snapshots and memory traces. Calls use distinct repair, target-resolution
  and partition phases. Snapshot policy is versioned so older state cannot be
  resumed silently with different registration behavior.

The only shared runtime edit is an optional `expand_unit` callback in
`prospective_memory/method/registration.py`; its default is disabled. This
allows Experiment 3 to expand exact units without copying the shared compiler
or rewriting original messages. Existing shared tests remain applicable.

Current-watched-evidence validation is unchanged. The eight readiness errors
are not made to disappear by permitting unsupported reminders. Actor ownership
of tool queries/actions, query budgets, max_tokens=768, and empty invalid-answer
handling are unchanged. No benchmark labels or expected diagnostic outcomes
are passed to the model.

## Validation

Offline preflight `preflight_registration_repair_20261015_v1/` passed before
the last diagnostic additions. The final focused suite passed 63 Experiment 3
tests. Local-only Slurm job **1535148** repeats the full preflight, eight routing
cases, fourteen readiness cases, eight new real-compiler registration cases,
and the integrated six-step smoke with query-first guidance.

Actor and helper in that validation are Qwen3-8B, BF16, nonthinking, temperature
0, max_tokens=768. It cannot launch GPT or a full benchmark. Diagnostic inputs
use different objects/times from the inspected benchmark failures. They are
development regressions, not held-out evidence or an F1 improvement claim.

Validation artifacts: `jobs/qwen3-8b-actor-helper-qwen3-8b-1535148/`.
Console: `jobs/exp3-registration-repair-local-1535148.log`.
Job 1535148 passed seven of eight registration cases, then correctly stopped
before the integrated smoke. The failing case was a provider cue announcement
followed by "please do it now": both initial classification and the generic
review repeated NEW, registering a duplicate. Its raw responses and failed
results remain preserved.

The second revision uses an independent provider-message review focused on
whether the concrete action and occasion are already pending. It does not show
the first NEW label/reason. Two counterexamples were added: a genuine recipient
revision in a provider reply and a distinct additional occasion for the same
action. The missing-target diagnostic was also tightened so a transport error
cannot count as successful abstention. All 65 Experiment 3 tests pass.

Local-only job **1535149** is validating this revision with ten registration
cases and the same existing checks/smoke. Artifacts live under
`jobs/qwen3-8b-actor-helper-qwen3-8b-1535149/`; console is
`jobs/exp3-registration-repair-local-v2-1535149.log`. It finished with nine of
ten registration cases passing. Its provider review suppressed a genuine new
request, so it stopped before the integrated smoke.

## Status verified October 20

Job **1535150** tested revision 3 and passed eight of ten registration cases.
It correctly handled the crowded plan, target resolution, missing-target
abstention, mixed paragraph and trigger-announcement duplicate. However, it
rejected a distinct provider request because the comparison named a contrasting
pending task, and incorrectly revised an old request when an additional
occasion was requested. The gate stopped the job before the integrated smoke.
Its artifacts remain under `jobs/qwen3-8b-actor-helper-qwen3-8b-1535150/`.

The current code is `focused_resolved_partition_v4`. It separates update review
from provider duplicate detection. A duplicate comparison can identify a
contrasting pending action without treating it as a target; only an
existing-request verdict becomes a restatement. This duplicate check cannot
convert an additional request into a revision. Source-quote validation remains.

The current Experiment 3 offline suite passed **67 tests** on October 20.
Revision 4 has not yet been validated with a live model. No new GPT result or
F1 improvement is established. The next gate is local Qwen3-8B validation of all
ten registration cases, routing/readiness checks, and the integrated smoke.

Subsequent live validation **1536924** finished on October 20: 541 offline tests,
8 routing cases and 14 readiness cases passed; registration passed 9/10. A
trigger announcement with "please do it now" still became a duplicate task.
The failed gate prevented integrated smoke. See
[REGISTRATION_V4_VALIDATION_20261020.md](REGISTRATION_V4_VALIDATION_20261020.md)
for the final evidence and accounting. No GPT calls or full benchmark were launched.

## Before another full run

Inspect per-case accepted intentions as well as pass/fail and error counts.
Then replay the public failing inputs with their saved pending state and check
both recovery and unintended changes. A fresh bounded GPT smoke is required
because the canceled run and previous passing smoke used different source code.
Only a separately approved complete benchmark can establish a new full-run F1.
Compare on the same scenario against baseline 75.71%; do not score the canceled
55-step prefix as a full run or claim improvement from these unit tests.
