# Experiment 3 improvement handoff

Date: 2026-10-14. Status: implementation plan, not permission to launch GPT.

## Objective and constraints

Improve prospective-memory performance over the same actor's baseline and
baseline + PIS, while retaining a plug-and-play helper. The actor must retain
final action and query control. Do not promise that these changes will beat
baseline: they address observed defects and require evaluation.

Work from `/home/akumar3/ResearchProjects/prospective-memory/prospective-memory`.
Read the current worktree before editing: another model has also been working
here. Preserve unrelated changes, all old outputs, and Experiments 1 and 2.
Do not print `.env`, credentials, or secrets in manifests/source bundles.
Leave other Slurm jobs alone, including protected jobs 1502687 and 1502688.

The user now wants fixes and local validation batched before spending on GPT.
The previous source-routing job **1534704 was canceled before starting**:
recorded accounting state CANCELLED, Start None, elapsed 00:00:00. It produced
no live diagnostics or GPT calls. Do not resume or resubmit it automatically.

## Evidence to start from

Read [GPT_FAILURE_REVIEW_20261014.md](GPT_FAILURE_REVIEW_20261014.md),
[OUTPUT_CONTRACT.md](OUTPUT_CONTRACT.md), [README.md](README.md), and the
current runner and per-run source snapshots before modifying behavior.
Older methodology documents may describe configurations no longer in use.

Historical GPT-5.4 results on the matching 80-step scenario:

| Configuration | TP | FP | FN | F1 |
| --- | ---: | ---: | ---: | ---: |
| Current Exp1 baseline | 53 | 6 | 28 | 75.71% |
| Exp3, Qwen3-8B helper | 53 | 8 | 28 | 74.65% |
| Exp3, Qwen3-8B helper + ACT verification | 51 | 11 | 30 | 71.33% |
| Exp3, Qwen3-32B helper | 57 | 19 | 24 | 72.61% |

Baseline: `PMBench/runs/core-four/openai--gpt-5-4/single_baseline/`.
Original helper trials: `experiments/rgpm/runs/gpt_actor_anchor_helpers/`.
Verification trial: `experiments/rgpm/runs/verify_actions_test/`.
Scenario SHA-256:
`94a45937da1363be19ccfdc2c188d132f23093041e30abd3ec22d64d70da8f24`.

Do not substitute the older 72.46% GPT baseline. Locate the same-model Exp2
PIS result and verify scenario, scoring, token cap, completeness, and model
configuration before adding it to the comparison. A matched PIS score is not
established in this handoff; mark it unavailable if it cannot be verified.

The original 8B helper gains five correctly timed selections but loses five
relative to baseline. Cross-day hits fall from 7/7 to 5/7. Queries increase
from 12 to 44 without a net TP gain. Bigger helpers and extra verification
have not demonstrated a better precision/recall balance.

## Already implemented, not yet live-validated

An optional `--source-routing` candidate exists in `source_routing.py` and
`run.py`. It asks the helper to select evidence channels separately for new
requests with valid verbatim action/condition spans. It may change only
`watched_sources`; revisions and cancellations retain the existing path.
Invalid or failed routing retains compiler output and logs the failure.
This fallback does not establish that the original source binding is correct.

`test_source_routing.py`, runner resume coverage, and `routing_probe.py` exist.
The earlier offline preflight passed, including 16 RGPM tests, under
`preflight_source_routing_20261014/`. This is not a live helper or GPT result.
Rerun tests after further changes rather than treating this as final validation.

`run_gpt_actor.sbatch` supports `SOURCE_ROUTING=1`, but automatically proceeds
from local routing diagnostics to paid GPT smoke and then the full run.
**Do not use this launcher for local-only validation.**

## Proposed behavior

```text
Public request
    |
    v
Register or update the intention; preserve its original wording
    |
    v
Choose sources that can establish the trigger, not the action destination
    |
    v
At each step: current public context + permitted observations
    |
    +-- Trigger established ------------> ACT proposal
    +-- Evidence missing, query useful --> CHECK candidate
    +-- Trigger absent/ineligible ------> WAIT
                                            |
CHECK candidates -> budgeted fair selection  |
                    |                       |
                    v                       v
                  Actor chooses query/action/advance
                              |
                              v
             Save calls, decisions, transitions, and checkpoint
```

No runtime task IDs, answer keys, hidden event schedules, or ground-truth
fallbacks. Labels belong only in offline scoring and test expectations.

## Implementation order

### 1. Freeze provenance and spending controls

Record current relevant file hashes and tested configuration. Reconcile the
existing source-routing edits with other agents' work without reverting them.
Keep each fix independently configurable so local ablations remain possible.
Use a new run directory for every changed code/configuration combination.

Add a dedicated local-only diagnostic entry point or explicit launcher mode
that cannot transition to a hosted actor. Test it with a hosted-call stub that
raises immediately. Parse boolean environment flags explicitly: shell
`${VERIFY_ACTIONS:+...}` enables verification even for the string `0`.
Do the same audit for other boolean flags, including `REPORT_GATES`.

Acceptance: local mode makes zero hosted calls, including failure/retry paths;
resuming incompatible source/configuration is refused rather than mixed.

### 2. Validate and complete source binding

Audit `source_routing.py` against `prospective_memory/method/registration.py`.
Distinguish trigger evidence from delivery destinations and distracting text.
Example: an instruction to email a note when a physical cue appears should
watch the scene channel, not email merely because the action is an email.
Retain all required sources for conjunctions and preserve explicit clock gates.

Inspect updates that change prerequisites: currently only new requests get
the extra routing pass. If extending routing to modifications, first resolve
the target identity and accepted revised specification; never create a second
intention or silently alter cancellation semantics. Log old/new bindings and
the revision responsible. Do not expand this change without regression tests.

Acceptance: source-only edits cannot alter action text, trigger meaning,
identity, recurrence, cancellation state, or deadlines. Unsupported sources
and malformed replies produce explicit diagnostics, never invented evidence.

### 3. Repair scope-aware readiness

Inspect `source_bound_v3.py`, `trigger_engine.py`, and `projection_cache.py`
under `prospective_memory/method/`. Ensure assessment receives the selected
intention's actual condition, not only its action and broad original text.
Use current public scope to interpret current scene observations: a Friday
scene need not repeat the word Friday to satisfy a Friday-only instruction.
Name day constraints clearly, for example permitted days, without suggesting
that a seven-day recurrence excludes weekends.

Keep explicit time comparisons, deadlines, conjunctions, revisions, and source
requirements strict. A plan or prediction is not evidence of occurrence.
Do not treat the receipt time of a delayed channel response as its event time.
When the public response lacks an occurrence timestamp, record that uncertainty;
never recover it from the simulator's hidden schedule or fabricate it.

Acceptance: current-day scene positives pass, but wrong-day, absent-cue,
predicted-cue, unmet-conjunction, and expired-deadline negatives stay negative.
Leave optional ACT verification off until separately validated. Extra helper
passes are fallible and are not a substitute for correct readiness semantics.

### 4. Improve monitoring selection without expanding budgets

Inspect `fair_trigger.py` and `fair_checks.py`. Existing hard clock priority
can repeatedly outrank other channels. Design an opt-in policy with bounded
priority using only public eligibility, offer history, and actual query history.
Preserve `query_budget=1` and `step_query_budget=2` for the initial comparison.
Handle true clock dependencies explicitly; simply demoting all clock checks
could trade one class of failures for another.

Log why each candidate was eligible, selected, deferred, or budget-blocked.
Distinguish an offered check from an actor-executed query. Fairness guarantees
can apply to eligible offers, not to actions the actor chooses not to take.
Any scheduler age is time since an offer/query, not inferred event age.

Check snapshot restoration carefully: `fair_trigger.py` currently restores a
base `FairCheckArbiter`; a custom policy must survive restore and engine.fresh().
Acceptance: deterministic scheduling and resume equivalence, no starvation in
bounded synthetic cases, correct handling of capability changes, unchanged
query limits, and no forced actor query. Do not relabel late hits as on-time.

### 5. Make failures reconstructable

Extend existing artifacts instead of creating a parallel logging system.
Review `artifacts.py`, `analyze.py`, `adapter.py`, and the PMBench adapter.
For every phase preserve call/operation IDs, intention IDs where available,
input, raw response, parsed response, validation errors, retries, token usage,
duration, and relevant before/after state. Never log credentials.

Separate registration, target-resolution/update, source-routing, readiness,
query-selection, query-execution, actor-selection, and parsing failures.
Connect proposals and evidence IDs to the final actor response. Use an explicit
unknown attribution when a reliable mapping or causal explanation is absent.
An observed helper rejection does not prove what the actor would otherwise do.

Acceptance: an analyst can trace a failed task from the public request through
memory changes and evidence to the final selection without another model call.
Invalid outputs remain empty/incorrect. Interrupted attempts and retries remain
available; committed steps are not rerun on resume. Preserve the existing output
contract and append-compatible analysis fields where possible.

## Validation ladder: no GPT yet

1. Add regression tests for source/action confusion, multi-source triggers,
   changes/cancellations, current-day context, weekends, deadlines, recurrence,
   threshold equality versus strict inequality, and missing prerequisites.
2. Add scheduler and checkpoint tests, malformed/truncated-response tests,
   missing-usage handling, and the local-mode hosted-call prohibition test.
3. Run the offline suite and preflight from the repository root:

   ```bash
   PMBench/.venv-sglang/bin/python -m unittest discover -s experiments/rgpm -p 'test_*.py' -q
   PMBench/.venv-sglang/bin/python experiments/rgpm/preflight.py --output experiments/rgpm/preflight_consolidated_<unique-id>
   bash -n experiments/rgpm/run_gpt_actor.sbatch
   ```

4. Use the new local-only path with Qwen3-8B helper, max_tokens=768 and
   temperature=0. Test varied generic positive and negative fixtures, not just
   wording copied from the known failures. Expand the existing routing probe
   to cover readiness and monitoring contracts, preserving all raw results.
5. Replay saved helper inputs locally to compare old/new decisions on identical
   evidence. Mark these as development diagnostics, not end-to-end F1: changed
   actor actions and future observations are not simulated by a static replay.
6. Run a local-actor smoke if resources allow, using Qwen3-8B actor/helper with
   matched context and token settings. Check registration, update, cancellation,
   query, ACT/WAIT, invalid responses, output completeness, and resume behavior.
7. Produce a readiness report listing each fix, tests, live diagnostic outcomes,
   remaining failures, expected calls, and the exact frozen candidate config.
   Stop for user approval. Local success does not demonstrate GPT improvement.

Do not use local GPU resources outside site scheduling rules or interrupt
another model's jobs. If no allocation is available, finish offline validation
and report the live-helper gate as pending.

## Later paid trial: separate approval required

Proposed actor: `openai/gpt-5.4`. Proposed helper: `Qwen/Qwen3-8B`, local.
Keep max_tokens=768 for both, temperature=0, helper nonthinking,
actor_guidance=none, query_handoff=legacy, query_budget=1,
step_query_budget=2, report_gates=false, verify_actions=false.
Record actual provider/model identifiers and all new feature flags.

After approval, run one bounded GPT smoke, check its artifacts and gate, then
one full 80-step candidate run only within the approved spending limit.
Specify call/retry/token or monetary limits before launch; monetary limits
require verified pricing and reliable usage accounting. Do not silently use
missing usage as zero cost or auto-submit repeats/sweeps. Resume the same
frozen run after interruption, not after a code change.

Compare with the current baseline, incumbent Exp3, and verified matched PIS:
F1, precision, recall, TP/FP/FN, paired gained/lost hits, routine/event/time,
cross-day/update categories, on-time non-clock detections, invalid outputs,
query counts, actor/helper TOK and DUR, retries and cost. Trace new errors as
well as repaired ones. Existing comparison helpers may require identical
helper models; inspect those restrictions before reusing them across arms.

If the candidate regresses, retain the incumbent and analyze saved artifacts;
do not automatically launch another paid experiment. A consolidated run tests
the bundle, not each fix's causal contribution. Keep independent flags for
later approved ablations. This repeatedly inspected scenario is development
data: fresh matched controls, repeats, and untouched scenarios are needed
before claiming reproducible or generalizable superiority.

## Expected handoff from the implementing model

- Scoped code changes and a list of touched files, with unrelated work intact.
- Updated output-contract documentation and reproducible configuration.
- Offline/local test results with links to preserved artifacts.
- A failure report distinguishing observed defects from uncertain attribution.
- A frozen candidate and cost-bounded GPT plan awaiting explicit approval.

The source-routing candidate is already implemented; scope/readiness repairs,
monitoring-policy changes, stronger diagnostics, and spending controls above
are proposed work, not completed fixes.
