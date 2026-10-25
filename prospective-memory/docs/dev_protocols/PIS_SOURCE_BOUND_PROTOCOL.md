# Source-bound PIS iterative validation

2026-09-22. Opt-in `pis_source_bound`, snapshot policy `pis_source_bound_v2`.
This is a new candidate, not a replacement for frozen `pis_grounded_v1` results.

Changes: extract full quoted obligations separately from typed compilation;
retain chronological revision source text under the same intention ID; ground
hard clock slots in complete original messages; use a boolean trigger assessment
with an explicit optional missing source. Quotation is content preservation, not
a semantic oracle. The helper still chooses sources and interprets conditions.
The host still decides whether to follow CHECK/ACT and confirms any completion.

Keep Qwen3-8B snapshot b968826d9c46dd6066d109eabc6255188de91218, BF16,
nonthinking, temperature 0, 4096 helper output tokens, 32768 context, seed 0 and
compact xgrammar. All cases and expectations remain unchanged. Each attempt uses
a new output directory, freezing candidate source files and preserving raw calls,
errors, tokens, latency and per-case traces. Never modify a running candidate.

First use the existing 10-case development smoke suite and its full-contract
pass gate. Independently authored transfer cases have their own frozen protocol
in `TRANSFER_VALIDATION.md`; they are development diagnostics, not an external
held-out benchmark. Record first-attempt transfer results, including failures.
Later tuning against transfer outputs must be disclosed as development tuning.

Do not conflate helper-only ACT alignment with action correctness, actor uptake
or PM-Bench scores. If either diagnostic gate fails, inspect and preserve that
attempt, refine the generic mechanism, and rerun a separately named attempt.
Passing supports an end-to-end PM-Bench comparison; it cannot guarantee improvement.
Retain prior baselines, unchanged labels/scoring, actor autonomy, budgets and
non-guessed completion. No benchmark-specific trigger rules or test-label access.

## Development iterations preserved

- Smoke01: 6/10 full contracts, 11/11 registrations, 7 correct ACT occurrences,
  no extra/missed ACT, but four invalid source requests. Raw errors are retained.
- Smoke02: same candidate with legal query sources encoded in the output schema;
  10/10 contracts, no errors. This constrains capabilities, not semantic truth.
- Transfer01 (first attempt): 8/10 contracts, 12/12 registrations, 11 correct ACT,
  one extra ACT at equality for a strict inequality, and one unnecessary clock
  query despite an insufficient elapsed-time observation. A fabricated hard clock
  was removed; unsupported weekdays were also found in the saved typed metadata.
- The next candidate explicitly evaluates comparisons before its boolean answer,
  distinguishes known-false from missing evidence, and guards unsupported hard-day
  restrictions. Both frozen suites must be rerun. Transfer reruns are development-
  tuned, not untouched validation. No individual fixture threshold or task name
  is encoded into the policy; case data and expectations remain unchanged.

Environment for these attempts is recorded in
`results/qwen3-8b-pis-source-bound-environment-20260922.json`.
