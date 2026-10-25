# GPT registration v15 smoke

User authorized fixes and a bounded GPT test on October 20, 2026.
Slurm job **1537306**, `exp3-gpt-registration-v15-smoke-h32`.

## Configuration

- Actor: `openai/gpt-5.4`, hosted through OpenRouter.
- Helper: `Qwen/Qwen3-32B`, local SGLang, BF16, nonthinking, temperature 0.
- Both roles: max_tokens=768, temperature=0.
- Registration policy: `focused_resolved_partition_v15`.
- Guidance: query_first; handoff: legacy; query budget: 1; step query budget: 2.
- Source routing, scope grounding, bounded priority, registration grounding: on.
- Action verification and gate reporting: off.
- Actor caps: 24 call attempts and 500,000 tokens. These are admission/usage
  limits, not a guaranteed dollar cost.
- Smoke quality limits: FP=0 and FN=0. RUN_FULL=0.

The helper changed from the originally planned Qwen3-8B because local tests
showed repeated semantic errors on valid revisions and cancellations. This is
a distinct helper configuration; its results must not be pooled with 8B runs.

## Prerequisites

Local job **1537296** completed successfully (0:0, 00:12:45), with Qwen3-32B
in both roles: full offline preflight passed, routing 8/8, readiness 14/14,
synthetic registration 13/13, historical registration replay 8/8. All ten
integrated smoke execution/trace checks passed, with zero invalid responses and
zero semantic errors. Its local actor scored TP=2, FP=2, FN=0 (F1=66.67%),
acting on a canceled task and acting early. This execution pass is not a GPT
quality pass. Detailed history: [registration validation](REGISTRATION_V5_VALIDATION_20261020.md).

A subsequent logging-only fix identifies source-routing probe calls by schema
signature instead of property order. All 78 Experiment 3 unit tests passed
after that change. The hosted job repeats offline and local live diagnostics
with its exact source snapshot before any paid inference.

## Artifacts

- Console: `jobs/exp3-gpt-registration-v15-smoke-h32-1537306.log`.
- Preflight, helper provenance and diagnostics:
  `jobs/gpt-5-4-actor-helper-qwen3-32b-1537306/`.
- GPT smoke:
  `smoke_artifacts/gpt-5-4-helper-qwen3-32b/sbpm/gpt-5-4-actor-helper-qwen3-32b-1537306/`.

Each bundle retains source/scenario hashes and snapshots, raw and parsed
responses, retries and failures, semantic decisions, call tokens/durations,
memory history, per-step scores and aggregates. API secrets are not copied.

## Outcome

Interrupted after **4/6 committed steps**. There were 11 schema-valid GPT
responses and one rejected request, 15,924 known actor tokens, and $0.04295115
reported actor cost. The rejected request returned HTTP 402 with
in_flight_budget_exhausted and no response usage. The budget guard then stopped
with actor_usage_unknown. Its missing usage remains null; it is not fabricated
as zero. All partial outputs and checkpoints remain intact. There is no complete
smoke score or passing GPT quality gate, and no full benchmark ran.

## Full-Run Authorization

The user subsequently authorized the full dataset. Read-only account checks on
October 20 confirmed total credits=105 and total usage=105.104506215, leaving
approximately -$0.1045. The key has no separate spending limit; account funding
is the blocker. No new GPU job or paid inference was submitted after this check.

The concrete full submission is saved in
[gpt_v15_full_20261020.json](launches/gpt_v15_full_20261020.json).
It uses the same GPT-5.4 / Qwen3-32B method, the matching seven-day, 80-step
synthetic_week_v9 dataset, max_tokens=768, a fresh strict smoke gate, and full-run
caps of 300 actor calls and 4,000,000 actor tokens. These are usage caps rather
than a dollar estimate. The existing launcher starts the full dataset only
after all enabled diagnostics and the zero-FP/zero-FN smoke pass. New outputs
will be job-scoped under runs/registration_v15_full; old runs are retained.

Current status: full run authorized and prepared, blocked on provider credits.
Recheck funding and source hashes before submission. No renewed run approval
is needed once funded; a passing smoke remains required.
