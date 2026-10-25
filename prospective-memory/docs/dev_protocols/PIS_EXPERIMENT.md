# PIS-inspired three-arm pilot (2026-09-22)

Source: Zhao and Wu, *Making Prospective Memory SLM-Shaped: Typed Intention Stores
for Small-Model Agents*, arXiv:2609.01272v1, https://arxiv.org/pdf/2609.01272.
This is an independent paper-inspired implementation, NOT author-code reproduction.
No claim of recovering their published 57.2% Qwen3-8B result or novel typed memory.

## Frozen comparison before running

1. Fresh agent-only control, original actor settings, corrected empty fallback.
2. `pis`: typed Form/Revise, structural weekday/clock eligibility board, one
   scoped semantic judgment per eligible intention, distinct-source query budget.
3. `pis_verified`: identical pipeline plus an original-instruction verifier for
   each proposed ACT. This tests source verification as ONE additional component.

Qwen3-8B BF16, same cached checkpoint, temperature 0, seed 0 server, thinking off.
Actor max output 768; helper max output 4096; check budget 1 per assessment and
2 actual host query attempts per decision step (including wrong/repeated channels).
After two queries, no further memory CHECK is proposed and the actor receives a
budget-exhausted instruction to choose using current evidence. This is a shared
plug-in safety budget in BOTH memory arms, not a change to the agent-only control.
The actor still has final authority; the budget does not forcibly modify actions.
If it nevertheless exceeds 12 queries in one step, the run aborts explicitly;
no artificial action, ground-truth fallback, or completed score is created.
All 80 steps of the same scenario. No tuning based on intermediate scored results.
Source/scenario snapshots, raw helper outputs, usage, decisions and errors retained.
Measure TP/FP/FN, precision/recall/F1, actor selection cardinality, fallback,
query counts, all helper tokens/calls, duration. Actor tokens are not currently
logged; do not claim end-to-end token totals. Single trajectories, no significance.
Reused development benchmark, not held-out generalization evidence.

## What we implement and what differs

Core borrows Form/Revise/Filter/Decide from PIS. Form and Revise share a compact
slot-filling call per incoming public message. New rows/updates are validated
individually; original inputs persist on failure. Typed slots are weekdays,
single exact/not-before wall-clock constraints, watched sources and recurrence.
Other trigger language remains semantic. Unknown times are NOT converted to
invented thresholds; unsupported complex temporal expressions require the judge.
Code filters only explicit weekday mismatches and definite clock mismatches.
Clock-gated rows without a clock remain CHECK targets. The judge must establish
all other conditions; a satisfied clock alone is not sufficient. Hidden channels
are ordinary host queries, counted by PM-Bench. One row per judgment prevents
long bank-sized JSON responses; the cost of many calls is measured, not hidden.

Our existing adapter strips task menus before helper calls. A separate unchanged
actor chooses actual menu actions. Thus this tests a plug-in, unlike the paper's
direct due-set decoder. PM-Bench exposes attempts, not authoritative execution
success; the adapter does NOT mark suggestions/attempts completed. The generic
engine supports host acknowledgement using core lifecycle, but PM-Bench cannot
exercise success feedback. These differences may affect performance.

`pis_verified` supplies original messages and chronological revisions to a
same-model second judge. Typed summaries are hypotheses, not truth. Verification
may catch false positives but cannot recover requests never registered or those
incorrectly filtered. It may reduce recall and increases compute. This is an
ablation, not a claim of independent-model verification or guaranteed correctness.

Weekday slots are a limited pilot, not a complete calendar/timezone scheduler.
The host owns current scope and clock observations; no hidden simulator time is
read. Requests can be unrelated; there is no same-goal or fixed-order assumption.
Runtime filtering reduces semantic calls but still scans pending metadata; no
sublinear scalability claim. Query budgeting needs host begin_step/record_query
callbacks; this is not a global cap on the independent actor's tool calls.
No default policy changes. Prior indexed experiments remain intact.

## Engineering attempts before the full comparison

Attempt 01 was interrupted before a candidate score after an offline regression
found typed day/time slots missing from the core duplicate key. Fixed and tested.
Attempt 02 was interrupted after only two actor choices: the helper requested
appointment_portal while the actor repeatedly queried course_portal. The former
per-assessment budget did not bound this loop. Added actual-attempt step budgeting
and explicit exhausted-budget guidance, applied equally to both memory arms.
Neither attempt supplies a completed memory score. No candidate accuracy results
were used to tune the implementation. Partial artifacts remain intact.

## Interpretation guard

The last indexed experiment forced a one-selection-per-step pattern, while its
baseline chose 3–8. Track the full distribution again. If a similar shift occurs,
F1 alone cannot establish better prospective memory; a fresh prompt-level
cardinality control remains necessary (not post-hoc ground-truth selection).
