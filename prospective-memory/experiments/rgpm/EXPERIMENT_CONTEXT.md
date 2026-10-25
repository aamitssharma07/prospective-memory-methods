# Experiment 3 Context: RGPM

## Current Handoff: 2026-10-25

For current method settings, result selection, coverage and failures, use
[docs/experiments/exp3_rgpm_context.md](../../docs/experiments/exp3_rgpm_context.md)
and [the exported result matrices](../../docs/experiments/results/RESULTS.md).
The ownership/history sections below are retained, but their initial artifact
readiness and October 8 strict smoke-admission decision are historical. The
approved v15 sweep uses report-only semantic smoke admission while retaining
execution/artifact guards and internal grounding checks. The current instrumented
runner already preserves raw calls, parsed outputs, traces and checkpoints.

## Read This First

This is the authoritative context for Experiment 3. RGPM is the working name
**Relevance-Grounded Prospective Memory**. Existing documents also call the
newer implementation SBPM. Do not confuse this experiment with either of the
two comparison experiments below.

1. Experiment 1 is the PMBench reproduction in `PMBench/`. It is complete and
   documented in `PMBench/EXPERIMENT_CONTEXT.md`. Do not rerun or modify it.
2. Experiment 2 reproduces the prospective-memory paper's author PIS method.
   Its external source is `third_party/author_pis/`; author-run tooling is
   `harness/run_author_pis.py` and `harness/summarize_author_pis.py`. It runs on
   another machine. Do not modify or launch it from Experiment 3 work.
3. Experiment 3 is our method. It is inspired by *Remember When It Matters*
   and PIS, but it must be evaluated and described as a separate method.

No full Experiment 3 run is authorized by this file. Inspect and finalize the
methodology and evaluation design with the user before launching inference.

Before any new inference, including a single smoke run, implement and pass the
offline validation in [OUTPUT_CONTRACT.md](OUTPUT_CONTRACT.md). The user requires
structured, resumable outputs comparable to Experiments 1/2, with sufficient raw
data for later analysis without rerunning completed inference. This is a required
launch gate; the existing runner's artifact support is incomplete.

## Method Lineage

The repository contains several generations of our independently implemented
method. They are development history, not interchangeable final methods:

- `pis` and `pis_verified`: early typed intention-store baselines inspired by
  PIS, implemented independently of the authors' repository.
- `pis_grounded_v1`: evidence-first registration review and grounded trigger
  assessment. Its frozen live smoke failed its promotion gate.
- Source-bound variants: preserve original instructions, constrain evidence
  sources, and fail closed on unsupported registration or trigger claims.
- Trigger-projection and fair-trigger variants: separate static trigger
  projection from current evidence assessment and arbitrate bounded checks.
- SBPM: the current repository name for our newer source-bound prospective
  memory direction. RGPM is the working paper/experiment name until the user
  freezes the final contribution.

Do not report an older PIS-inspired score as an RGPM result. Earlier smoke runs
and PMBench candidates are development evidence only and have known failures.

## Canonical Experiment 3 Code

Core implementation:

- `prospective_memory/pis_grounded.py`
- `prospective_memory/evaluate_pis_grounded.py`
- `prospective_memory/method/registration.py`
- `prospective_memory/method/source_bound.py`
- `prospective_memory/method/source_bound_v3.py`
- `prospective_memory/method/projection_cache.py`
- `prospective_memory/method/trigger_engine.py`
- `prospective_memory/method/fair_checks.py`
- `prospective_memory/method/fair_trigger.py`
- `prospective_memory/method/calendar_guard.py`
- `prospective_memory/method/evaluate_cases.py`
- `prospective_memory/method/evaluate_registration_cases.py`

Shared runtime integration, not method ownership:

- `prospective_memory/core.py`
- `prospective_memory/grounded.py`
- `prospective_memory/llm.py`
- `prospective_memory/adapters/`
- `harness/run_memory.py`
- `harness/report_source_bound_pair.py`
- `harness/report_query_flow.py`

Historical PIS-inspired code retained for ablations:

- `prospective_memory/baselines/pis.py`
- `prospective_memory/baselines/pis_registration.py`
- `harness/run_pis_triplet.py`
- `harness/summarize_pis_triplet.py`

Experiment 2 reference code, explicitly not owned by RGPM:

- `third_party/author_pis/`
- `harness/run_author_pis.py`
- `harness/summarize_author_pis.py`
- `harness/test_author_pis.py`
- `experiments/exp2_pis_baseline.sh`

The importable modules stay in `prospective_memory/`. Moving them under this
directory would break public imports, tests, and source paths embedded in frozen
historical manifests. This folder is the single organizational entry point and
ownership map; future RGPM-only launchers and outputs should be created here.

## Tests

Primary Experiment 3 contracts include:

- `tests/test_pis_grounded.py`
- `tests/test_pis_grounded_evaluation.py`
- `tests/test_pis_source_bound.py`
- `tests/test_pis_source_bound_v3.py`
- `tests/test_pis_trigger_projection.py`
- `tests/test_pis_fair_trigger.py`
- `tests/test_trigger_projection_diagnostics.py`
- `tests/test_grounded_policy.py`
- `tests/test_trigger_role_cases.py`
- `tests/test_temporal_role_cases.py`

Scripted unit tests verify software contracts; they are not model-quality or
benchmark results.

## Protocols and Prior Evidence

Relevant design and validation documents:

- `docs/dev_protocols/PIS_GROUNDED.md`
- `docs/dev_protocols/PIS_GROUNDED_SMOKE_PROTOCOL.md`
- `docs/dev_protocols/PIS_SOURCE_BOUND_PROTOCOL.md`
- `docs/dev_protocols/PIS_SOURCE_BOUND_V3.md`
- `docs/dev_protocols/PIS_TRIGGER_FAIR_V5.md`
- `docs/dev_protocols/TRIGGER_ROLE_PROTOCOL.md`
- `docs/dev_protocols/TEMPORAL_ROLE_PROTOCOL.md`
- `docs/dev_protocols/TRANSFER_VALIDATION.md`

Historical context is in `docs/project_context.md` and `docs/current_work.md`.
Those files contain chronological notes and superseded states; this file should
be updated with the current Experiment 3 decision whenever they disagree.

## Required Evaluation Properties

Before a full run, freeze and record:

- the exact final RGPM variant and ablations;
- models, checkpoints, precision, server version, and full launch commands;
- datasets/scenarios and cryptographic hashes;
- baseline parity and prompt differences;
- output token limits, temperature, seeds, and invalid-response policy;
- registration, revision, cancellation, recurrence, trigger, query-budget, and
  action-acknowledgement semantics;
- headline and per-category metrics, including precision, recall, Set-F1,
  false positives, false negatives, invalid responses, TOK, and DUR;
- per-step prompts, raw responses, decisions, evidence, state snapshots,
  failures, checkpoints, and resumable intermediate results;
- cardinality controls so precision gains are not mistaken for memory gains;
- cost and latency for actor and helper calls separately.

Never use evaluator ground truth to repair a model response. Invalid outputs
must fail closed and remain visible in saved artifacts.

## Known Development Findings

- The first grounded-PIS live smoke did not pass its promotion gate: 0/10 full
  contracts and incomplete registrations/actions. It is not an RGPM result.
- Earlier PIS-inspired PMBench runs improved Set-F1 mainly while reducing
  selections and recall; they do not establish a general memory improvement.
- Some earlier candidates emitted zero ACT proposals, so their verifier was
  never exercised even when nominally enabled.
- Registration identity, retained constraints, source grounding, recurrence,
  query fairness, and confirmed completion are central unresolved dimensions.

## Smoke Gate Policy (2026-10-08)

The 66-pair actor/helper matrix surfaced two different failure classes that
looked similar in `sacct` (all `FAILED`) but have different causes and
different handling:

1. Infra bugs: the co-located single-GPU launch path's mem-fraction split
   was a flat default (0.25 actor / 0.55 helper) regardless of model size,
   so every pair touching Qwen3-32B OOM'd before inference started; and
   CUDA graph capture OOM'd near the mem-fraction margins needed for
   Qwen3-32B co-location and for both huge-homogeneous TP=2 pairs
   (Llama-3.3-70B, Qwen2.5-72B). Both are code/launch bugs, now fixed
   (`MEM_FRACTION_ACTOR`/`MEM_FRACTION_HELPER` sized per pair,
   `--disable-cuda-graph` added to `prepare_server.py` and wired through
   `run_one_model.sbatch`), and those pairs were resubmitted. The first
   fraction choice for the small-helper-with-Qwen3-32B-actor direction
   (`MEM_FRACTION_ACTOR=0.75`, `MEM_FRACTION_HELPER=0.88`) passed for
   Qwen3-8B and Qwen3-4B as helper but then OOM'd for Gemma-4-E2B and
   Ministral-3-3B as helper, mid-run rather than at startup
   (`torch.OutOfMemoryError` on a routine embedding-table allocation, with
   actor+helper combined already at ~92.4/93.1 GB). 0.88 left no real
   margin for a helper's actual footprint running slightly over its
   nominal mem-fraction-static budget; lowered to `MEM_FRACTION_HELPER=0.80`
   for that direction and resubmitted. That lower fraction then failed for
   Ministral-3-8B as helper -- its ~16GB weights OOM'd during weight-tensor
   creation itself (before KV allocation), since 0.80 of the ~22.7GB left
   after the actor (~20.4GB target budget before then) wasn't enough room
   even to materialize the weights. The right helper fraction tracks that
   helper's actual size, not a single constant for "small helper": raised
   back to `MEM_FRACTION_HELPER=0.90` for Ministral-3-8B specifically
   (matching the ~0.88 that already worked for the same-class Qwen3-8B)
   and resubmitted. That still failed (helper's weight-tensor allocation
   OOM'd immediately despite nominal headroom at 0.90) -- Ministral-3-8B
   needs more real margin than its ~16GB weight size alone suggests, for
   reasons not fully isolated. Rather than keep tuning the co-located split
   by trial and error, this one pair was routed instead to `gpu-res-01`
   with a dedicated GPU per role (the existing true-dual-GPU branch, no
   mem-fraction split needed). Note this makes this one result's card size
   (80GB) inconsistent with the rest of the matrix (96GB `gpu` cards); not
   expected to matter at this benchmark's context lengths, but flagged.
2. Smoke-gate failures: `smoke_gate.py` requires `memory_registered` and
   `stage_coverage` (all five helper phases, including `identity_review`)
   on a short deterministic scenario before the full benchmark runs at all.
   The weakest pairs (Qwen3-0.6B/0.6B, Qwen3-1.7B/1.7B homogeneous, and the
   Gemma-4-E2B-involving small pairs) fail this. Checked directly for the
   Gemma-4-E2B homogeneous case: `compile_typed` left `target_id: ""` on
   both the modify and cancel operations in the smoke scenario's step m2,
   so the method correctly raised "unresolved update" and never reached
   `identity_review`. This is genuine helper-model weakness at linking an
   update/cancellation back to its existing pending intention, not a gate
   or scenario-coverage bug (the smoke scenario does deliberately include
   both an override and a cancel referencing prior intentions).

Decision: the smoke gate is not bypassed for weak-helper pairs, and no
ungated/diagnostic side-run is produced either. A pair that fails the gate
is recorded as a gated failure, not scored. Reasoning: a Set-F1 computed
after forcing an ungated run would reflect the actor guessing against a
broken/incomplete memory trace, not the method's intended behavior, and
would be misleading to report as an RGPM result. The gate failure itself is
the finding for that pair (a helper-capability floor), not a defect to work
around.

## Current Status

2026-10-01 code review: see [SMOKE_READINESS.md](SMOKE_READINESS.md).
Selected initial actor and helper are both `Qwen/Qwen3-8B`. All 441 method and
33 portable integration tests passed using the existing Python 3.10-compatible
environment. Live smoke remains gated on artifact/resume implementation,
invalid-output scoring parity and actual serving configuration verification.

Legacy output cleanup on 2026-10-01: the old active harness output directories
`harness/results/` and `harness/smoke_artifacts/` were moved to
`experiments/rgpm/legacy_outputs_archived_20261001/`. They are retained only as
development history and must not be included in fresh RGPM analysis.

- Dedicated Experiment 3 directory created.
- Existing implementation and tests inventoried without modifying behavior.
- PMBench Experiment 1 and author-PIS Experiment 2 remain untouched.
- Final methodology definition, ablation matrix, and evaluation plan are not
  yet frozen.
- No Experiment 3 inference or full benchmark was launched during this setup.

## Matrix Results (2026-10-08)

41 actor/helper pairs completed from the planned 66-pair matrix (plus
Qwen3-14B/Qwen3-8B, added outside the official roster since it was already
cached from earlier development runs). The rest are recorded smoke-gate
failures for weak-helper pairs (see Smoke Gate Policy above), not pending
work. Set-F1 (%), verified from each run's `metrics.json`, not any prior
summary document:

| Actor \\ Helper | Qwen2.5-72B | Qwen3-32B | Qwen3-4B | Qwen3-8B | Llama-3.3-70B | Ministral-3-3B | Ministral-3-8B |
|---|---:|---:|---:|---:|---:|---:|---:|
| Qwen2.5-72B | 59.3 | — | — | — | — | — | — |
| Qwen3-0.6B | — | 14.9 | — | 11.4 | — | 11.4 | 15.8 |
| Qwen3-1.7B | — | 28.6 | 31.1 | 32.5 | — | 27.3 | 36.0 |
| Qwen3-14B | — | — | — | 58.5 | — | — | — |
| Qwen3-32B | — | 55.6 | 47.6 | 56.8 | — | — | 40.6† |
| Qwen3-4B | — | 51.7 | 39.8 | 52.4 | — | 39.8 | 48.0 |
| Qwen3-8B | — | 54.2 | 56.8 | 52.7 | — | 48.0 | 40.6 |
| Gemma-4-E2B | — | 36.0 | 44.7 | 34.8 | — | 37.3 | 36.0 |
| Llama-3.3-70B | — | — | — | — | 66.3 | — | — |
| Ministral-3-3B | — | 46.6 | 47.3 | 56.8 | — | 46.7 | 42.4 |
| Ministral-3-8B | — | 64.2 | 62.6 | 61.5 | — | 62.1 | 50.9 |

† Qwen3-32B actor / Ministral-3-8B helper (40.6%) is contaminated: this pair
runs on `gpu-res-01`'s 80GB cards (routed there after repeated co-location
OOMs on the 96GB `gpu` cards), whose smaller KV-cache budget truncated the
actor's context from day 5 onward (235 `invalid_response` steps, all
`Input length exceeds the maximum allowed length`). Not a model-quality
result; needs a rerun with a correctly-tuned co-located fraction on `gpu`
before it's trustworthy.

Helper comparison (mean Set-F1 across the 6 actors tested against all of
Qwen3-32B/8B/4B/Ministral-3-3B/8B as helper, for a controlled comparison):
Qwen3-8B 48.4% > Qwen3-4B 47.1% > Qwen3-32B 46.9% > Ministral-3-3B 43.5% >
Ministral-3-8B 42.3%. A bigger helper is not automatically better --
Qwen3-32B does not beat the much smaller Qwen3-8B/4B as helper, and model
family matters more than raw size (both Ministral helpers trail their
similarly- or larger-sized Qwen counterparts).

RGPM vs. Experiment 1's `single_baseline` (homogeneous actor=helper pairs
only, TP/FP/FN from each run's own `metrics.json` / `trajectory.score.md`,
not estimated):

| Model | Baseline TP/FP/FN | Baseline F1 | RGPM TP/FP/FN | RGPM F1 | Delta |
|---|---|---:|---|---:|---:|
| Qwen3-4B | 7/14/74 | 13.7% | 32/48/49 | 39.8% | +26.1 |
| Qwen3-8B | 34/47/47 | 42.0% | 44/42/37 | 52.7% | +10.7 |
| Qwen3-32B | 36/25/45 | 50.7% | 47/41/34 | 55.6% | +4.9 |
| Qwen2.5-72B | 39/6/42 | 61.9% | 51/40/30 | 59.3% | -2.6 |
| Llama-3.3-70B | 52/17/29 | 69.3% | 61/42/20 | 66.3% | -3.0 |
| Ministral-3-3B | 40/32/41 | 52.3% | 32/24/49 | 46.7% | -5.6 |
| Ministral-3-8B | 41/14/40 | 60.3% | 41/39/40 | 50.9% | -9.4 |

RGPM's one consistent effect is adding false positives (the helper proposes
ACT more often than the actor's native baseline judgment). Whether that
helps or hurts net F1 depends on the baseline's starting precision: models
with a noisy/low-recall baseline (Qwen3-4B, Qwen3-8B, Qwen3-32B) gain,
because there was recall headroom to capture; models whose baseline was
already precise with few false alarms (Qwen2.5-72B FP=6, Ministral-3-8B
FP=14) lose, because RGPM roughly triples their false-positive count for a
comparatively small recall gain. Ministral-3-3B is the exception: RGPM
suppresses activity there (lower TP and lower FP, not higher), losing
recall without a compensating precision gain. This points to the helper's
ACT-proposal threshold being tuned for noisy actors and over-triggering on
top of already-well-calibrated ones -- a concrete lead for anyone revisiting
the method, not yet acted on.

## GPT-5.4 as Actor (2026-10-09)

A separate, later experiment: GPT-5.4 (`openai/gpt-5.4`, OpenRouter) as actor
against the four Qwen3-1.7B/4B/8B/32B anchors as helper. GPT-5.4 was excluded
from the main 66-pair matrix above for a GPU-quota reason that does not apply
here (it needs no local GPU server as actor); this needed one small, narrow
code change (`run.py --actor-backend openrouter`, helper stays local-only)
rather than a quota increase.

Results, launch commands and full provenance are in
[runs/gpt_actor_anchor_helpers/RESULTS.md](runs/gpt_actor_anchor_helpers/RESULTS.md) --
that file is authoritative for these four results; do not re-quote them from
here. Headline: Qwen3-8B is the best helper (Set-F1 74.6%), all three working
pairs (4B/8B/32B; 1.7B gated as a weak-helper smoke-gate rejection) hold much
higher precision than typical elsewhere in the matrix, and the total
OpenRouter cost for all three full-week runs was $9.48.

## Maintenance Rule

Update this file whenever the method, model matrix, command, dataset, status,
or result changes. Every run must have an immutable manifest and intermediate
artifacts so later analysis never requires repeating inference unnecessarily.
