# Consolidated Experiment 3 candidate

Implementation date: 2026-10-14. Offline validation passed. Live validation
**passed in job 1534765**, completed with exit 0 after 00:02:12.
No GPT calls have been launched by this implementation work.

## Implemented behavior

1. Existing optional source routing is integrated with the candidate. New
   requests use validated action/trigger spans to select evidence sources.
   Revision/cancellation routing remains with the existing identity-reviewed
   compiler, with an explicit skipped-stage event. A speculative pre-review
   source-only call cannot safely rewrite an accepted revision.
2. `--scope-grounding` supplies the selected condition and permitted days to
   assessment. Its prompt accepts current public day context for present scene
   cues, preserves explicit prerequisites and revisions, and separates receipt
   context from occurrence timestamps. Both projected and fallback paths use it.
3. `--bounded-priority` lets competing sources get the next offer after a
   persistent hard-gate priority offer. Ranking among those sources uses existing
   offer/query recency. Budgets remain one CHECK source per assessment and two
   actual attempts before CHECK proposals are suppressed. The actor still owns
   queries: this proposal budget does not enforce the actor's actual query count.
   The existing 12-query safety limit remains separate.
4. Candidate snapshots preserve policy flags, scheduler history, readiness and
   monitoring traces. Resume restores the bounded scheduler, with no regeneration
   of committed steps. Different source/configuration hashes require a new run.
5. Local-only execution rejects hosted backends and non-loopback URLs before
   client construction. The local launcher skips `.env`, uses a local actor, and
   always stops after validation. Boolean `0`/`false` flags no longer enable an
   option through shell nonempty-string expansion.
6. Optional actor call/token limits cover retries and resumed sessions. Exhaustion
   stops the run instead of becoming an incorrect scored step or a retry loop.
   Missing usage blocks further calls under a token limit. Byte-based prompt
   reservations are conservative controls, not precise monetary accounting.
7. Analysis exports recorded stage behaviors and evidence pointers while leaving
   uncertain causal attribution explicit. Token totals indicate missing fields
   and partial coverage. Routing logs preserve parent operation UUIDs.
8. `--registration-grounding` supplies public channel provenance and reinforces
   the distinction between a new request, an explicit change to an existing
   request, and a cue announcement. Identity review still controls acceptance.
   Registration retains complete multi-occasion schedules and avoids importing
   the current day as an unstated restriction. Source routing can use the public
   origin of a quoted channel reply.
9. Scope-aware generation identifies watched evidence and
   forbids a positive assessment when no watched observation is present. Its
   prompt forbids inferring named activities from typical clock times. These
   constraints retain the original semantic guard; valid references alone still
   do not prove that evidence entails a trigger.
10. Compiler schemas restrict typed slots to conservative public-source options.
    Unrelated dates and the current day cannot introduce a new hard restriction;
    multi-time schedules fall back to full-source assessment rather than being
    reduced to the first time. Short-request extraction fields use finite verbatim
    spans of the focused quote, preventing cross-unit copying. Long requests keep
    the existing span validator and original-source fallback.
11. Response arrays have bounded cardinality, including evidence citations, to
    prevent repetition from exhausting the fixed 768-token output cap. References
    to other current sources remain expressible so the runtime can reject an
    invalid support claim instead of forcing the model to a legal-looking ID.
12. A new-request classification gets a targeted second review when the public
    context suggests an update or a provider reply with pending obligations.
    This is a fallible helper review, not an automatic conversion. Accepted
    modifications/cancellations still require the original identity reviewer.
    Both responses are saved, with the second named `registration_review`.

The optional ACT verifier stays off. The prior verifier run degraded F1 and
showed false rejections; adding another semantic pass is not a demonstrated fix.

## Validation

`preflight_consolidated_20261014_v12/status.json` reports passed:

- 441 method tests.
- 33 adapter tests.
- 38 Experiment 3 tests, including consolidated resume equivalence, priority
  rotation/restoration, hard-day/time negative gates, evidence validation,
  local transport restrictions, boolean parsing, and budget recovery.
- Launcher syntax checks, strict-invalid scoring, and a source-hashed scripted
  candidate artifact bundle.

Earlier preflight versions and failed attempts are retained. Offline scripted
tests verify execution contracts; they do not prove model semantic accuracy.

The final offline check additionally verifies an export-only correction: the
smoke gate now refreshes the artifact index after rewriting derived analysis and
saving its verdict, so those file hashes remain consistent. Memory/model logic
has not changed since live job 1534765. Its immutable source bundle records the
exact live version; the subsequent index correction was tested without inference.

Local job 1534765 runs eight source-routing cases, fourteen readiness cases,
bounded monitoring checks, then the six-step PMBench smoke and smoke gate.
Readiness cases include present-day cues, wrong-day/absent/future cues, weekend
recurrence, strict threshold equality, conjunctions, historical email, deadlines,
and useful missing-source checks. Expected labels are saved only in diagnostic
artifacts and never included in helper requests. Direct fixture registration
isolates readiness; the smoke separately exercises the live compiler and actor.

Expected job directory:
`experiments/rgpm/jobs/qwen3-8b-actor-helper-qwen3-8b-1534765/`.
Expected smoke directory:
`experiments/rgpm/smoke_artifacts/qwen3-8b-helper-qwen3-8b/sbpm/qwen3-8b-actor-helper-qwen3-8b-1534765/`.
Slurm console:
`experiments/rgpm/jobs/exp3-qwen8-consolidated-local-1534765.log`.
Inspect `routing_probe/results.json`, `helper_probe/results.json`, and the
smoke's `smoke_gate.json`; their absence means those stages have not completed.

Observed live outcomes:

- Eight source-routing diagnostics passed, including a quoted provider fact.
- Fourteen readiness diagnostics passed; bounded monitoring coverage passed.
- All ten integrated smoke-gate checks passed. The six-step trajectory is
  complete; no invalid actor steps, failed calls, or helper semantic errors.
- Registration, actual recipient revision, cancellation, source routing,
  projection, assessment, identity review, and state queries were exercised.
- Smoke scoring: TP 2, FP 4, FN 0, F1 50%. The local actor still selects actions
  prematurely; this is an execution-health result, not evidence of F1 improvement
  over baseline or a prediction of GPT performance.
- Smoke calls: actor 17, helper 108; all use max_tokens=768. Known total tokens:
  actor 23,705 and helper 163,533. These exclude the separate diagnostic/preflight
  bundles and all earlier attempts. No hosted GPT calls ran.

The paid GPT smoke and full PMBench evaluation remain unlaunched.

Preserved live attempts:

- 1534719: source router added an extraneous events source to a provider-only
  condition. The routing gate stopped execution; the instruction was tightened.
- 1534729: all seven routing cases and thirteen readiness cases passed. The
  integrated smoke failed the semantic gate: a meal was inferred from a clock,
  a recipient update was misclassified as new, and a channel cue directive
  produced a separate intention with the wrong source. Registration provenance,
  stronger classification guidance, and watched-evidence generation constraints
  address these defects in the next candidate. The update gate now requires an
  actual non-canceled revision, so cancellation alone cannot satisfy it.

Additional preserved local attempts:

- 1534753: update/cancellation and readiness handling improved, but unsupported
  typed hints were rejected by the original guards. Public-source slot options
  were added to the compiler generation schema.
- 1534758: isolated cases passed; a helper repeated an evidence ID until output
  truncation. Citation and response cardinality bounds address that failure.
- 1534759: the compiler copied a neighboring request's cue. The span validator
  retained the original quote and stopped the gate. Focused verbatim generation
  constrains short-request extraction.
- 1534761: a recipient update was again classified as new and rejected when the
  compiler named an old target. Targeted classification review now addresses this
  inconsistency without bypassing identity validation.

All attempts used local Qwen3-8B only. Their raw calls, failures and snapshots
remain available; passing isolated cases did not waive the integrated smoke gate.

## Configuration for later GPT evaluation

Actor: `openai/gpt-5.4`; helper: `Qwen/Qwen3-8B`, local SGLang.
Actor/helper max_tokens=768; temperature=0; helper nonthinking.
Use source_routing=true, scope_grounding=true, bounded_priority=true,
registration_grounding=true,
actor_guidance=none, query_handoff=legacy, query_budget=1,
step_query_budget=2, report_gates=false, verify_actions=false.

`run_gpt_actor.sbatch` defaults to validation only (`RUN_FULL=0`). A later
approved full run must explicitly set `RUN_FULL=1`, `MAX_ACTOR_CALLS`, and
`MAX_ACTOR_TOKENS`. Smoke has separate limits, defaulting to 24 actor attempts
and 500,000 reserved/observed actor tokens. Account for both stages when choosing
an overall authorized budget; these defaults are not a dollar spending estimate.
Use a fresh `RUNS_ROOT`, for example `experiments/rgpm/runs/consolidated_v1`.

Historical targets are baseline F1 75.71% and incumbent 8B-helper F1 74.65%.
Verify a matched same-model PIS artifact before adding it to comparison. Compare
TP/FP/FN, paired gains/losses, cross-day/update and monitoring outcomes, invalid
responses, queries, tokens, durations, and retries alongside F1.

The bundle has no new end-to-end GPT score yet. A later consolidated run tests
the bundle; independent flags permit separately approved ablations. Saved-call
semantic replay and held-out evaluation remain follow-up diagnostics, not claims
already established by the scripted preflight. This inspected scenario remains
development data.

## Changed files

All runtime edits are under `experiments/rgpm/`; shared method code is untouched.

- New: `improved_engine.py`, `helper_probe.py`, `launcher_options.sh`,
  `run_local_validation.sbatch`, `test_improved_engine.py`, `test_launcher.py`.
- Updated: `run.py`, `artifacts.py`, `source_routing.py`, `routing_probe.py`,
  `analyze.py`, `run_gpt_actor.sbatch`, `smoke_gate.py`, `preflight.py`,
  `test_runner.py`, `adapter.py`, `test_source_routing.py`, and this directory's documentation.
- Existing source routing and its tests remain part of the candidate.

Raw responses, parsed responses, TOK/DUR, failures, retries, and checkpoints
continue to use the existing output structure. No old result directory was
deleted or rewritten.
