# Qwen3-8B first-run failure review

Evidence run: `runs/synthetic_week_v9/qwen3-8b/sbpm/qwen3-8b-1503009`.
Dataset: `benchmark/data/synthetic_week_v9.json`. This is development analysis
on an already evaluated dataset, not an independent held-out performance claim.

| Task group | Hit | Late | Miss | Total |
| --- | ---: | ---: | ---: | ---: |
| Routine | 27 | 0 | 1 | 28 |
| Irregular | 17 | 2 | 34 | 53 |
| Time | 19 | 0 | 5 | 24 |
| Event | 25 | 2 | 30 | 57 |
| Cross-day (overlapping group) | 2 | 0 | 5 | 7 |

Set precision 51.16%, recall 54.32%, F1 52.69% (44 TP, 42 FP, 37 FN).
Late responses do not recover the correct step's false negative. The 40 false
alarms metric differs from set FP=42; do not substitute one for the other.
Updated tasks: 2 hit, 7 miss, 2 canceled; 8 update violations. Cancellations are
not misses. Every non-clock monitoring channel has zero on-time hits; library
and calendar each have one late response. These categories overlap.

## Trace-backed findings

- Monday `d1_s1`, `memory.jsonl`, message_1: the two-time daily medication
  request was compiled with a single hard 11:00 gate, although its projection
  correctly says 11:00 OR 21:00. This can suppress the helper's evening reminder;
  the actor still achieved most routine hits, so it does not explain every miss.
- Monday `d1_s1`, message_2: all eight daily tasks were registered. Registration
  coverage alone did not produce correct routing or readiness. Grocery pickup
  watched appointment_portal; the hardware counter and return slot watched
  library_hold. The physical cue and a provider with related vocabulary are
  different evidence sources.
- Monday `d1_s2`, message_7: the replacement-filter correction became a new
  pm_000011 record instead of revising pm_000007. Speculation about a portal slot
  contaminated its condition and watched sources. The actual follow-up cue is
  at d1_s7; the earlier hardware-counter cue at d1_s6 is obsolete.
- Monday `d1_s8`, message_33: the library-book correction revised pm_000011,
  the filter record, rather than the library-return record. The identity review
  accepted the wrong obligation. This establishes a semantic error even though
  the response was valid JSON and no transport failure occurred.
- Monday `d1_s5`, `memory_calls.jsonl`: the kiosk assessment adds an after-11:50
  condition absent from its own request. That time belongs to the email task in
  the full original plan. The helper sees an action span plus a multi-task plan;
  supplying the selected record's condition explicitly reduces this ambiguity.
- Monday `d1_s5`: portal readiness was unknown and the helper proposed a portal
  check, but the saved calls show the clock response and no portal response in
  that step. With a two-query step cap, clock consumes one slot and competing
  providers must share the other. This is an observation-access bottleneck;
  increasing the cap changes the cost/budget comparison and needs a separate
  ablation rather than a hidden change.
- Monday library hold becomes ready at d1_s10 but is acted on at d1_s11. A later
  correct response still loses on-time recall. Fair provider rotation cannot
  guarantee observing every hidden cue at its first occurrence.

## Why these scenarios are difficult

Corrections mix an explicit directive with distracting speculation and later
reuse generic words such as pickup. Correct behavior requires retaining task
identity, replacing only the obsolete cue, rejecting the old cue, and recognizing
the paraphrased new cue. Cross-day requests insert a future intention into an
unrelated narrative, then require carrying it through day changes. Hidden-state
tasks require choosing an appropriate tool without a visible announcement;
multiple simultaneously pending providers compete for limited checks. Numeric
threshold tasks additionally require strict comparison rather than topic match.
Full plans make all of these harder when one task's timing or entity leaks into
another task's interpretation.

## First candidate changes

1. Explicit selected-record condition in trigger assessment inputs.
2. Clarify correction classification, obligation identity, provider routing and
   separation of speculative background from actual prerequisites.
3. Clarify projection isolation and weekend weekday gates.
4. Remove a single hard equality gate when the new request contains multiple
   clock values; retain the full source and clock capability for semantic review.

The last change conservatively relaxes a derived optimization, not the original
schedule: semantic readiness still has to establish the requested time. Multiple
times can also describe a conjunction or deadline, which must remain in source.
No task IDs, expected answers, hidden state, or ground truth enter runtime policy.
Keep max_tokens=768, the existing models and query budgets for this candidate.

## Validation and next measurement

Run method regression tests and portable adapter/runner tests first. Use a fresh
artifact directory for a live Qwen3-8B smoke with Qwen3-8B as helper and actor,
then compare a new one-model run to the preserved original. Include per-task
changes, paired step errors, cost, query timing, registration and update traces.
Do not claim improved F1 from scripted tests or replaying old model responses.
Evaluate generalized synthetic variants and a held-out scenario before claiming
the improvements generalize. Further monitoring-budget or identity-verification
changes should be separate ablations so their benefit and cost can be measured.
