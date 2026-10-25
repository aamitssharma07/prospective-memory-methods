# Independently authored transfer diagnostic v1

Authored 2026-09-22, before this suite's first live-model run. The suite is
`examples/pm_transfer_cases_v1.json`, in the existing version-1 format accepted by
`evaluate_pis_grounded.py`. No model requests were made while authoring it, and no
candidate outputs on these cases were inspected. This file and the case data are
the only changes made for this task.

This is an **independent authored development transfer diagnostic**, not a truly
external held-out benchmark. The author knew the prospective-memory interface and
failure classes, and inspected the earlier smoke suite to understand its format.
New domains and distinct examples reduce direct reuse of smoke fixtures; they do
not establish broad generalization or eliminate researcher-selection bias.

Frozen case-file SHA-256:
`98d289d230b2ee4ad41d6d6b0094dfecbb0a4786871c2f76a1e8d0ec93499a5a`.
Pre-inference validation passed `validate_cases` and additional source/ID checks:
10 cases, 12 obligations, 21 ticks, 24 rounds, and 27 expected decisions
(13 WAIT, 3 CHECK, 11 ACT). There are three frozen pull replies. All 15 public
instruction IDs and 33 observation IDs are globally unique within the suite.

## Frozen coverage

| Case | Behavior being tested |
|---|---|
| Greenhouse | Strict numeric threshold; equality is not below |
| Render job | Supported CHECK then negative evidence; later CHECK then positive evidence |
| Instrument | Both observable conditions required; correct sample identity |
| Glaze timer | Relative elapsed duration retained semantically, without an invented clock time |
| Simulation output | Explicit time revision preserves identity and validation requirement |
| Meteor video | Cancellation suppresses an otherwise due task |
| Three obligations | Unrelated additions preserve the original record and remain separate |
| Dome beacon | Push-only source cannot be queried; historical evidence is not current |
| Rehearsal | A future announcement does not add an intention or satisfy its trigger |
| Build logs | Inclusive numeric threshold plus a separately checked prerequisite |

Each obligation is supplied in its own instruction with a distinct origin ID,
matching the existing scorer's one-record-per-origin contract. This deliberately
does not test splitting several obligations from one message. It tests 12 distinct
obligations over 21 ticks; the two additional obligations arrive during a tick.

## Run and scoring rules

1. Before the first scored run, freeze the suite and record its SHA-256 alongside
   candidate code hashes. Preserve the runner's `cases.json`, `source/`, full raw
   requests and replies, trace, manifest and scores in a new run directory.
2. Expected records and decisions are **scorer-only**. The model sees original
   instructions, available source capabilities, bank state and observations, not
   expected decisions, thresholds outside the original instruction, or gold labels.
3. A deterministic diagnostic host supplies the frozen pull reply only after a
   supported CHECK. It replaces that source's current observation for the round.
   It does not represent an autonomous main agent following guidance.
4. ACT is a reminder proposal, not execution. The host does not acknowledge success
   or automatically complete records. Pending records can therefore remain after
   an ACT. New ticks provide a fresh current evidence set; old evidence is not
   automatically carried forward.
5. Report case pass count, registration coverage, exact decision sequences,
   occurrence-aligned ACT precision/recall/F1, boundary failures, unexpected errors,
   helper calls, tokens and latency separately. Record lexical checks are bounded
   diagnostics, not a semantic equivalence oracle. These scores are not PM-Bench
   scores or end-to-end actor-performance measurements.
6. Do not alter expectations after seeing live outputs. Any malformed fixture
   discovered later requires a documented erratum and separately versioned suite;
   retain the original results. A candidate tuned after inspecting this suite is
   development-tuned on it; do not present its rerun as untouched transfer evidence.
7. Freeze one candidate before its first run on this suite. Report its first
   attempt, including failures and infrastructure aborts. A comparison requires
   identical frozen inputs, host policy and inference configuration for both
   implementations, with each implementation's source hashes retained.

Validation before live execution uses the existing `validate_cases` function;
no engine, scorer, prompt or live-inference settings are changed by this suite.
The standard runner can select the suite with
`--cases prospective_memory/examples/pm_transfer_cases_v1.json`. An independent
read-only check of expected counts and source/ID consistency accompanies the
schema check. No GPU work is required to author or validate these files.
