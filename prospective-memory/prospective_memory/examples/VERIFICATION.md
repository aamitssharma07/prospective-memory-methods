# Portable memory verification — 2026-09-11

Completed software checks:

| Check | Result |
|---|---:|
| Benchmark-independent core/lifecycle tests | 26 passed |
| PM-Bench adapter/provider tests | 11 passed |
| Portable runner tests | 4 passed |
| Existing v1/v2 regression tests | 8 passed |
| Total automated tests | 49 passed |
| Independent scripted event-stream demo | 10/10 scenarios passed |

The runner tests include a complete 80-step PM-Bench simulation with mocked actor
and helper outputs. The older regression suite separately checks empty fallback
through all 80 steps. These are integration checks, not measured model runs.
Temporary integration artifacts are not retained as scientific result files.

The independent demo imports neither PM-Bench nor its data. Its report is
`event_stream_results.json` and is explicitly labelled as scripted validation.
The scenario checks are also exercised by the unit suite; they are not ten
additional independent statistical samples beyond those tests.

Review-driven regressions verify that push-only event streams cannot become
queries, reused trigger evidence cannot be retriggered by adding unrelated-source
context, and an ACT reminder remains available during an intervening actor query.
Restored state preserves provenance, capabilities, lifecycle and reminder state.

No portable-memory live-model experiment was launched in this implementation
session. There is no new F1, no evidence of an improvement over the historical
42.0% baseline, and no claim that these checks demonstrate semantic
generalization. The new runner records source/scenario hashes and helper usage
for a subsequent real experiment.
