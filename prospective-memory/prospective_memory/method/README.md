# SBPM — Source-Bound Prospective Memory

Policy name: `sbpm`. Ablations: `sbpm_no_arbiter` (no fair check arbitration),
`sbpm_no_projection` (no static trigger projection), `sbpm_minimal`
(source-bound assessment only).

Our method. Built as a chain on top of the PIS baseline in `../baselines/`, so
the boundary between "theirs" and "ours" is the class hierarchy itself:

```
Engine                          ../core.py            shared state machine
└── PISEngine                   ../baselines/pis.py   PIS baseline ends here
    └── SourceBoundPISEngine    source_bound.py       ours begins
        └── SourceBoundV3Engine source_bound_v3.py
            └── SourceBoundTriggerEngine  trigger_engine.py
                └── SourceBoundFairTriggerEngine  fair_trigger.py   ← ADOPTED
```

## What each stage adds

| Module | Contribution |
|---|---|
| `source_bound.py` | **Source-bound assessment.** An intention is judged only against its own trigger and its own watched sources; ACT requires cited evidence from one of them. Prevents one intention's evidence satisfying another. |
| `source_bound_v3.py` | **Evidence by ID.** Observations are cited by identifier and the code re-attaches their text, so a long observation cannot be mangled by output-length limits. |
| `registration.py` | **Layout-unit registration** (each item of a multi-item plan stored separately) and **verbatim span extraction** (action and condition are two substrings selected from the request, so prose narration is not stored as the obligation). |
| `trigger_engine.py` | **Static trigger projection.** Separates "what to do" from "what must hold first", and never asks whether the action itself is already done. |
| `projection_cache.py` | Caches those projections per intention revision. |
| `fair_trigger.py` | **Fair source-level CHECK allocation** across competing intentions. The adopted policy. |
| `fair_checks.py` | The arbiter used by `fair_trigger`. |
| `calendar_guard.py` | Bounded weekday-clause guard; refuses unsupported hard calendar gates rather than inventing them. |

## Design commitments

- **Lifecycle logic lives in code, language work in the model.** Identity,
  provenance, revision, cancellation, dedup and query budgets are enforced by
  `../core.py`; the model only interprets text.
- **Decisions are proposals.** ACT/CHECK/WAIT are handed to the host. An ACT is
  never a successful execution, and a CHECK never reads the environment.
- **Provenance is checked, not trusted.** Every registration quotes its source
  text and every span must appear verbatim in the request. A quote proves where
  text came from, not that the interpretation is correct.
- **Failures degrade to WAIT.** A malformed batch, an invalid span or an
  unresolvable decision keeps the intention pending rather than dropping it.

## Cost controls

All default off; enable explicitly.

| Flag | Effect |
|---|---|
| `--memory-skip-unevidenced` | Skip assessments that can only return WAIT (no watched evidence, no queryable source). ~32% of calls. |
| `--memory-reuse-stable-waits` | Within a step, reuse a prior WAIT when nothing on the watched sources changed. ~24% of calls. |
| `--memory-assess-batch-size N` | Judge N order-independent intentions in one prompt. |
| `--memory-assess-workers N` | Dispatch order-independent assessments concurrently. Wall-clock only; **not recommended** (no accuracy benefit). |

Measured together: **27.3 → 7.3 helper calls per step**, 3.55M → 1.89M tokens.

## Diagnostics

`evaluate_cases.py` and `evaluate_registration_cases.py` run frozen case
fixtures from `../examples/` without touching the benchmark. Useful for catching
a registration regression cheaply before spending a benchmark run.

**They do not predict benchmark score.** A variant that won every helper suite
(trigger-roles 8/8 vs 3/8) still scored lower on PM-Bench. Treat them as
regression tests, not as evidence.
