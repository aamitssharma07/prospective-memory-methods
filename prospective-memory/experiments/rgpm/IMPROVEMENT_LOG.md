# Experiment 3 improvement log

## Objective and comparison

Continue authorized Qwen3-8B iterations until a completed candidate improves
on the best prior Experiment 3 development result. Verified target:
qwen3-8b-1503009, synthetic_week_v9, 80 steps, set F1
0.5269461077844311, precision 0.5116279069767442, recall
0.5432098765432098, TP 44, FP 42, FN 37. Retain base and author-PIS
comparisons, checking scenario and scoring compatibility before presenting them.

These are iterative development evaluations of an inspected scenario, not
held-out evidence. Do not insert scenario identities or answers into runtime
logic. Beating this target does not establish generalization or statistical
superiority. Validate a selected candidate on untouched scenarios separately.

## Current measurement

Smoke 1503139 and dependent benchmark 1503140 measure balanced_v2 with the
12-query empty/incorrect recovery described in QUERY_RECOVERY_20261002.md.
Keep runtime sources fixed while this pair is pending/running so the smoke
and benchmark test the same implementation. Both actor and helper are
Qwen3-8B, max_tokens=768. Preserve all prior outputs.

## Iteration procedure

1. Check smoke health and full-run completeness before comparing scores.
2. Compare paired task/step outcomes, TP/FP/FN, routine/irregular tasks,
   corrections, cross-day requests, channel queries, invalid steps and cost.
3. Read raw actor/helper evidence for representative regressions. Distinguish
   registration, update identity, source routing, readiness and actor failures.
   Mark causal explanations unresolved when traces do not establish them.
4. Choose a small general change supported by those traces. Record hypothesis,
   changed files and configuration; avoid combining unrelated interventions.
5. Run regression checks and a live smoke; benchmark only on smoke success.
6. Preserve a fresh source-hashed artifact bundle and compare to the incumbent.
   Reject regressions; do not claim improvement from partial runs or smoke F1.

## Evidence to prioritize

The incumbent achieves 27/28 routine hits but only 17/53 irregular hits.
Updated tasks have two hits, seven misses, two canceled tasks and eight update
violations. Non-clock monitoring has no on-time hits. Earlier trace reviews
identify wrong update targets, source routing and missed CHECK uptake.
An overly permissive revision reached recall 0.9012 but F1 0.2885 due to 352
false positives. Therefore increasing action volume alone is not progress.

References: FAILURE_REVIEW_QWEN3_8B.md, PRECISION_REVIEW_20261002.md,
BALANCED_REVIEW_20261002.md and the immutable per-run source/call bundles.

## Historical comparator verification

Recomputed with benchmark/sim/pm_bench.py score_log(strict_invalid=True),
excluding trajectory metadata records. Both have 80 scored steps and zero
recorded fallback steps:

| Method | TP | FP | FN | Set F1 |
| --- | ---: | ---: | ---: | ---: |
| Base | 34 | 47 | 47 | 0.4197530864 |
| Base + author PIS | 47 | 155 | 34 | 0.3321554770 |

Base trajectory:
`benchmark/runs/all_results_v9/qwen3-8b/single-baseline-qwen3-8b-v9-20260328-155332/single-baseline-qwen3-8b-v9-20260328-155332.jsonl`.

PIS trajectory (sibling repository):
`../prospective-memory-reaearch/data/PMBench/runs/exp2_anchor_qwen3_8b/results/Qwen-Qwen3-8B/intention-Qwen-Qwen3-8B-v9-20260930-170352/intention-Qwen-Qwen3-8B-v9-20260930-170352.jsonl`.

These are historical comparisons with differing runtime configurations, not
controlled method-only ablations. The primary development target remains the
best complete Experiment 3 run. Original comparator files were read only.

`analysis_tools/compare_runs.py BEFORE AFTER --output NEW_DIRECTORY` exports
paired changes, overlapping category counts, costs and trace references. It
requires complete matching scenarios/model/token settings and verifies analysis
input hashes. It writes only a new comparison directory. The running candidate
does not import this tool.
