# Query handoff revision: 2026-10-15

## Evidence and scope

The GPT smoke in job 1534994 missed the approval event at Monday m3 and selected
the report at m4. At m3, cycle 7, the helper had offered CHECK email, the actor
had observed only clock and events, and one query remained. GPT chose to advance.
All ten execution checks passed; the quality gate prevented the full benchmark.

This revision targets actor uptake of an offered CHECK. It leaves registration,
projection, readiness, source ranking, query budgets and scoring unchanged.
Runtime edits are confined to `experiments/rgpm/`.

## Implemented change

Opt in with `--actor-guidance query_first`. The adapter adds a short plan for
the first eligible selected CHECK, with an exact query_state action, the accepted
request/revision, current observed sources, actual query attempts and remaining
step budget. It recommends inspecting an outstanding prerequisite before
advancing and reassessing after the reply. It distinguishes a prior-step reply
from current state and tells the actor to decline fulfilled one-shot requests.

The plan does not execute a query, force an actor response, mark an action
completed, infer readiness or use task labels/answers. The actor retains both
query and final action choices. An available action menu is never trigger
evidence. Existing `none` and `balanced_v2` modes retain their behavior.

No plan is generated for an observed/attempted source, exhausted budget, WAIT,
ACT, canceled request or wrong scope. Existing capability validation rejects a
forged source. Wrong and repeated attempts consume the same budget as before.
Snapshot/config fingerprints continue to control resume; the plan is recomputed
from restored state rather than becoming a new hidden state variable.

## Diagnostics

New memory-cycle records contain `query_plan`. Offline `query_uptake.csv`
correlates each offered plan with the actor call at the same step and cycle:
`followed`, `advanced_without_offered_check`, `different_action`, or
`invalid_actor_response`. Failed-step attribution includes the same evidence
pointers. These are observed choices, not automatic causal explanations.

`query_uptake_probe.py` replays saved public actor prompts against a loopback
local model. Original and revised prompts differ only by the appended plan in
the final memory-handoff message. Original raw responses remain untouched.
The replay records both responses and all usage/durations. It is a next-action
diagnostic, not a simulator rollout or proof of better F1. Taking every CHECK
is not a correctness criterion: fulfilled or irrelevant requests may be declined.

Four saved skipped-CHECK contexts are available from job 1534994, including
the failure at m3. Some later contexts involve a report already selected in the
public conversation; their outcomes must be interpreted separately.

## Validation

Offline preflight `preflight_query_first_20261015_v4/` passed:
441 method tests, 33 adapter tests, 48 Experiment 3 tests (522 total), all
launcher syntax checks, strict-invalid scoring and a scripted artifact bundle.
Coverage includes query limits, current/stale observations, source validation,
no automatic execution, diagnostic cycle matching and resume equivalence.
Earlier preflight attempts are preserved, including a corrected test assertion.

Local-only validation job **1535046**, `exp3-query-first-local`, uses Qwen3-8B
as actor/helper, skips `.env` and cannot launch a full benchmark. It runs offline
preflight, existing routing/readiness probes, paired saved-prompt replay, and
the integrated smoke with `ACTOR_GUIDANCE=query_first`, `QUERY_HANDOFF=legacy`.
Both models keep max_tokens=768. No additional GPT call was used to implement
or validate the change up to this submission.

Artifacts:

- Console: `jobs/exp3-query-first-local-1535046.log`.
- Job and replay: `jobs/qwen3-8b-actor-helper-qwen3-8b-1535046/`.
- Smoke: `smoke_artifacts/qwen3-8b-helper-qwen3-8b/sbpm/qwen3-8b-actor-helper-qwen3-8b-1535046/`.

The replay's `passed` flag means valid diagnostic responses, not that all checks
were taken or useful. Inspect the paired m3 actions and integrated smoke before
deciding whether another bounded GPT smoke is justified. No F1 gain is claimed
from offline tests.

## Observed local outcome

Job 1535046 completed with exit 0:0 after 00:02:31. All eight routing cases,
fourteen readiness cases and ten integrated smoke execution checks passed.
The saved-prompt replay completed four pairs of valid local responses.

Integrated smoke: TP 2, FP 4, FN 0; precision 33.33%, recall 100%, F1 50%.
There were no invalid actor steps, failed schema calls or helper semantic errors.
The report was selected at m3, when approval arrived, but four other extra
selections remain. This is the same aggregate F1 as the previous local Qwen3-8B
smoke in job 1534765. State queries rose from 11 to 12; known actor tokens rose
from 23,705 to 29,580. The new smoke used 18 actor calls and 113 helper calls,
with 172,386 helper tokens. These counts exclude separate diagnostics and replay.

On the four saved GPT prompts, local Qwen3-8B took the offered email check in
2/4 original handoffs and 4/4 revised handoffs. At the actual missed-cue context
(m3), both local variants queried email. The additional uptake occurs at two
Tuesday contexts after the report had already been selected in the public
history. These results do not show that the fix improves the failed GPT choice,
and the extra checks may be redundant. The report's memory record remains
pending in this host because it does not acknowledge execution to the memory
engine; adding simulator-based completion acknowledgements would violate the
plug-and-play boundary. No such acknowledgement was added.

The final v4 preflight also covers an analysis-only refinement made after the
live job: correlate actor calls with both session ID and cycle/step, so retries
from an interrupted session cannot be misattributed after resume. The replay
lookup uses the same session boundary. Prompt/model behavior is unchanged since
job 1535046; its source snapshot retains the exact live version.

No additional hosted GPT calls or full benchmark were launched. Before paying
for another complete rollout, the most direct next diagnostic is a bounded GPT
next-action replay of the saved m3 prompt, comparing the original and revised
handoffs. A full run should retain the zero-FP/zero-FN smoke gate. Neither local
uptake nor execution-health checks establish superiority over baseline.

## Files

Updated: `adapter.py`, `run.py`, `artifacts.py`, `analyze.py`,
`run_gpt_actor.sbatch`, `run_local_validation.sbatch`, `test_adapter.py`,
`test_runner.py`, `test_launcher.py` and documentation.
New: `query_uptake_probe.py` and this report.

## Subsequent GPT replay

The user approved a two-call GPT check after local validation. Results are in
`analysis/gpt_handoff_m3_20261015_v1/`, with an `ANALYSIS.md` explaining limits.
The original handoff produced choose with no task, reproducing the skipped
email query. The revised handoff produced query_state email. Both responses
were valid; exactly two calls used 3,079 tokens and provider-reported cost
USD 0.00825165. No rollout or full benchmark followed this diagnostic.

`gpt_handoff_probe.py` provides this explicit hosted diagnostic separately from
the loopback-only local replay. It selects one saved call, retains generation
settings, enforces two actor calls and a 20,000-token admission limit, disables
SDK retries and preserves partial results if a call fails. Its three offline
tests passed before inference. The result supports testing the change in a
bounded GPT smoke; it does not establish better F1 or repeated success.

The subsequently authorized integrated GPT smoke **1535096** passed all twelve
checks with TP 2, FP 0, FN 0, F1 100% and exact task sets on all six steps.
It queried email and selected the revised report at the approval step, and
handled cancellation and the next-day reminder correctly. Reported hosted
cost was USD 0.066639375. The full benchmark remains unlaunched. See
`GPT_QUERY_FIRST_SMOKE_20261015.md` for the matched smoke comparison, artifacts
and limits on interpretation.
