# Trigger-role development diagnostic v1

Authored and frozen on 2026-09-23 before any live V3/V4 run on these cases.
File: `examples/trigger_role_cases_v1.json`.

Frozen case SHA-256:
`2494810e84cddae77bdcfeb919b9e0a971fdaa7ac9df7b8b322e6b97b0bcc8e5`.

These are independently authored **development cases informed by known failure
classes**, not an external held-out benchmark. The author knew the prospective
memory interface and reviewed the existing harness/fixture format. No benchmark
scenario or benchmark gold labels were consulted for case construction. No model
calls were made while authoring or validating these files. Subsequent tuning
after inspecting their outputs must be disclosed as development tuning.

## Coverage and counts

Eight cases contain eight separately supplied obligations, 19 ticks/decision
rounds, and 19 expected decisions: 10 WAIT and 9 ACT. Eight initial record checks
plus 19 tick record checks total 27. All eight instruction IDs and 19 observation
IDs are globally unique. Each case contains at least one negative and one positive.

| Case | Intended distinction |
|---|---|
| Paddle rack | A conditional imperative registers; an open gate makes moving the still-unmoved paddles due |
| Tea timer | Prepositional “On hearing…” supplies a cue; pouring is the next action, not evidence required beforehand |
| Toy train | Yesterday's sketch is not today's cue; the train reaching the exit can trigger a sketch while the page is blank |
| Counter and table | A different earlier action is a genuine prerequisite, even though both actions use the verb “wipe” |
| Puppet acts | One action is explicitly requested at two separate endings; the first does not wait for the second |
| Bicycle cover | One OR branch is sufficient while the other remains false |
| Drying towel | Each single-true AND condition is insufficient; both are needed |
| Bread dough | A future prediction is not an occurrence; directly observed rising above the mark is |

## Frozen host and scoring contract

- Use the unchanged version-1 `evaluate_pis_grounded.py` case format. Each case
  gets a fresh bank and exactly one instruction/origin. This is not a batch
  registration, query-planning, revision, or cancellation test.
- All supplied observations are current `events` evidence. There are no
  queryable channels or pull fixtures. This intentionally isolates interpretation
  of observable cues from channel selection, polling, or hidden-state uncertainty.
- A tick is one decision boundary with its own current evidence set. Puppet-act
  endings are distinct fresh occurrences; the in-progress update supplies no new
  ending. No past observation is automatically carried into the next tick.
- Expected records/rounds are scorer-only. The helper receives public
  instructions, capabilities, source-bound records, and current observations;
  never the expected decision or lexical rubric.
- ACT means a reminder proposal. The host never executes an action or sends an
  acknowledgment, and must not infer completion from an ACT. Every record stays
  pending and unchanged throughout these tests.
- Keep exact expected rounds and registration checks. Report case passes,
  registration coverage, occurrence-aligned ACT precision/recall/F1, unexpected
  errors, protection events, calls, tokens, and latency separately. Any transport
  or decoding abort remains an abort, not a completed result.

## Explicit limits

The two-occasion case tests two ACT opportunities and an intervening WAIT from
one preserved record. The existing scorer does **not** directly inspect recurrence
metadata, and the host does not acknowledge the first action. It therefore does
not prove correct repeat flags, completion lifecycle, or repeated execution.

Record source checks are required-source inclusion, not equality; lexical
fragments are narrow diagnostics, not proof every condition survived a rewrite.
The existing harness may permit labeled protective guard events while reporting
them separately. These rules remain unchanged, and must not be confused with the
stricter batch-registration diagnostic. Passing these small, direct-evidence cases
does not establish actor uptake, generalization, or PM-Bench improvement.

## Validation and any future comparison

`validate_cases` passes. Six new offline tests in
`tests/test_trigger_role_cases.py` check the frozen hash, counts/IDs, original-text
support, positive/negative coverage, two distinct occasion cues, and feasibility
in the unchanged harness. The last test uses a deliberately scripted oracle from
the fixture answers: it checks wiring and absence of automatic completion, **not
model quality**. It also checks that expected fields never enter request payloads.

Before any live comparison, preserve the exact case file, this protocol, both
implementations' sources/configuration, full call logs, and all result attempts in
new non-overwriting output folders. Compare the same frozen cases and model/
decoding settings. Keep first-attempt failures; do not change expectations to fit
outputs. A fixture correction requires a separately versioned suite and an
explicit erratum retaining the original result.

The existing CLI accepts these cases for its already supported policies via
`--cases prospective_memory/examples/trigger_role_cases_v1.json`. V4 is currently
unintegrated and requires separate explicit runner support or a configured engine
factory; this task adds neither. No acknowledgment/execution behavior, existing
harness, policy, scorer, or runtime file was changed to create this diagnostic.
The suite may remain unrun if further ablation is unnecessary.
