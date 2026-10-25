# GPT-5.4 failure review

Read-only inference analysis; no new model calls or runtime edits. Recomputed
all listed trajectory scores with benchmark/sim/pm_bench.py score_log using
strict_invalid=True, excluding metadata records. Baseline and candidate manifests
identify scenario SHA-256 94a45937da1363be19ccfdc2c188d132f23093041e30abd3ec22d64d70da8f24.
All listed full runs have 80 steps and zero recorded invalid actor steps.
Actor is openai/gpt-5.4 through OpenRouter; actor/helper output caps are 768.

## Results

| Arm | TP | FP | FN | Set F1 | Cross-day hits / 7 | Update hits / 11 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Exp 1 current baseline | 53 | 6 | 28 | 75.71% | 7 | 6 |
| RGPM, Qwen3-4B helper (1515078) | 50 | 9 | 31 | 71.43% | 5 | 4 |
| RGPM, Qwen3-8B helper (1515079) | 53 | 8 | 28 | 74.65% | 5 | 6 |
| RGPM, Qwen3-32B helper (1515080) | 57 | 19 | 24 | 72.61% | 7 | 6 |
| RGPM, Qwen3-8B + action verification (1534695) | 51 | 11 | 30 | 71.33% | 5 | 5 |

The current baseline is PMBench/runs/core-four/openai--gpt-5-4/single_baseline.
An older released baseline has 72.46% F1; using it instead changes the headline.
The 8B helper is 1.07 percentage points below the current baseline; verification
is 3.32 points below that helper run. These are historical single-run comparisons,
not paired contemporaneous controls or causal estimates of an intervention.

Original helper runs are under runs/gpt_actor_anchor_helpers; verification is
under runs/verify_actions_test. See their manifests and per-run source bundles
for the tested implementation, rather than assuming current code is identical.
Qwen3-1.7B was smoke-gated and has no full score.

## What gains and losses cancel

Against baseline, the original 8B helper gains five correctly timed selections
and loses five. Routine hits remain 22/28. Time hits rise 14 -> 17, but event
hits fall 39 -> 36. Irregular hits remain 31. Cross-day falls 7 -> 5; updates
remain six hits. State queries rise 12 -> 44 with no net TP gain.

All non-clock monitoring channels have zero on-time hits in the 8B helper and
verification runs. The baseline has one bank-balance hit. Additional checks
are therefore not providing the hoped-for hidden-state recall benefit.

## Trace-backed findings

1. Wrong source binding: original 8B memory.jsonl row 100, Wednesday d3_s6,
   pm_000022 stores 'Email the room change note' when the lab cubby is noticed,
   but watches calendar. Its source contains distracting speculation about a
   calendar shift. The matching current lab-cubby cue is narrative evidence;
   the decision is WAIT ('Unresolved decision error'), and the actor omits the
   request. Baseline selects it. Source contamination and a failed helper
   proposal are established; the actor's counterfactual behavior is unknown.
2. Over-strict readiness: original 8B memory.jsonl row 184, Friday d5_s9,
   pm_000031 correctly stores 'Carry the laundry soap' and watches events.
   The observation describes an empty laundry-room cart and current_scope is
   Friday. The helper nevertheless requires the observation itself to confirm
   Friday and returns WAIT. Actor selects only the other cart-related action;
   baseline selects both. This is a semantic assessment failure, not failed
   registration or absent evidence.
3. Delayed monitoring: Tuesday vendor email appears at d2_s9, but actor checks
   email at d2_s10 and executes then. Wednesday grade release appears at d3_s4,
   but course_portal is queried at d3_s7. Delta channels return past events
   since the previous query. These responses are genuine observations, not
   future-state leakage; actions are late and contribute FP on the later step.
   The grade ACT is explicitly present in the saved actor handoff at d3_s7.
4. Missing useful check: Sunday d7_s7, bank-balance task is pending and proposes
   a deferred CHECK while the handoff offers clock. Actor advances without a
   bank query and misses the $92 threshold event that baseline handles. Budget
   arbitration and actor uptake both matter; which alternative schedule would
   help requires a new evaluation.
5. Verification quality: the verification snapshot records 50 supported and
   12 unsupported verdicts. Several unsupported reasons dispute weekend use
   despite the original request saying every day, or demand a date inside an
   observation despite current_scope. This is another fallible semantic model
   pass. It verifies helper ACT proposals, not every final actor selection.
   The measured run still gains two hits and loses four against the original
   8B helper, with FP rising 8 -> 11. Individual verdicts do not alone prove
   causation for that aggregate change.

## Cost and experimental limits

Original 8B: 124 actor calls / 1,286,772 tokens, 1,516 helper calls /
2,289,757 tokens. Verification: 125 actor calls / 1,337,028 tokens,
1,524 helper calls / 2,268,693 tokens. Verification adds an assessment phase
but total helper cost also depends on changed downstream decisions.

Temperature zero does not prove deterministic API or server behavior. Trials
are separated in time. Multiple revisions have inspected this same dataset.
Report observed scores and trace failures, not a proven fundamental actor
limit or held-out method superiority. Aggregate helper/actor attribution
requires explicit alignment; do not infer it solely from score differences.

## Next improvement hypotheses

1. Tighten evidence-source selection around the request's actual prerequisite,
   retaining distracting surrounding text only as context. Test unseen paraphrases.
2. Make current_scope authoritative for observation timing and distinguish an
   explicit deadline from an invented requirement to restate the day in a cue.
3. Review CHECK scheduling for hidden channels and event freshness. Preserve
   the query budget for a controlled trial; any budget expansion is a separate
   cost/accuracy ablation. Earlier unseen events cannot be repaired by relabeling
   a late action as an on-time hit.
4. Keep optional verification off for the incumbent until its false-rejection
   cases pass targeted diagnostics and it improves a new benchmark trial.
5. Evaluate one change per run, offline tests then live smoke, and compare a
   fresh GPT baseline plus repeats before claiming a reproducible improvement.

No production patch or experiment submission is part of this review.
