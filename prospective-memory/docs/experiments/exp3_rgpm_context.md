# Experiment 3: RGPM

Snapshot date: **2026-10-25**. [Team entry point](../../TEAM_CONTEXT.md) |
[Comparison and matrices](results/RESULTS.md) |
[All RGPM attempt rows](results/experiment3.csv).

## Goal and Method

RGPM, **Relevance-Grounded Prospective Memory**, is our proposed plug-and-play
helper beside a main action agent. It is inspired by PIS and *Remember When It
Matters*, but is a separate method. It aims to improve the same main model's
performance over both base and author-release PIS without fine-tuning that agent.
SBPM is an earlier implementation name, not a fourth experiment.

```text
Public instruction / observation
              |
              v
Helper splits requests and classifies each one
  new / update / cancel / restatement / background
              |
              v
Ground quoted actions and resolve references to existing intentions
              |
              v
Store or revise a source-bound intention and its future condition
              |
              v
At each step: assess the condition against observed public evidence
              |
       +------+-------+
       |              |
 Evidence missing   Condition supported
       |              |
 Offer bounded      Offer an action reminder
 state/time check     |
       +------+-------+
              v
Main agent receives guidance and makes the final choice
              |
              v
Record attempted actions, lifecycle changes, calls and step checkpoint
```

The helper cannot see hidden benchmark labels. An offered reminder is not a
ground-truth answer or an enforced action whitelist. Main-agent over-selection
can therefore still produce false positives even when the helper is cautious.

## Current Candidate

Updated registration policy: **`focused_resolved_partition_v15`**. The full
configuration lives in each run manifest and the selected launch records.

- Main-agent guidance: `query_first`; handoff: `legacy`; query budget: 1.
- Source routing, scope grounding, bounded priority and registration grounding enabled.
- Action verification and extra report gates disabled in this sweep.
- Both main and helper response limits: 768 tokens; temperature 0.
- Local models use SGLang; GPT actor uses direct OpenAI `gpt-5.4` with `reasoning_effort=none`.
- Invalid responses and unsupported memory operations fail closed; no ground-truth fallback.
- Smoke semantics are recorded under **report-only admission** for this approved sweep. Execution/artifact failures still block; semantic smoke failure is not relabelled a pass.

The current report-only policy supersedes the October 8 strict quality-admission
decision retained in the historical RGPM context. It does not bypass the
method's internal source/identity checks or repair poor model predictions.

## Coverage and Results

Eight local main models x four Qwen helpers (1.7B, 4B, 8B, 32B) completed the
**original 32-pair sweep**. Large 70B-class main models are outside that sweep.

Eleven pairs were then selected for serving/checkpoint consistency, while
keeping the updated methodology: three Qwen32 main-model pairs on the prior
96GB-class co-located setup and eight Ministral pairs using explicit BF16
checkpoints. **Nine completed; the two Ministral + 32B-helper attempts failed
their serving probes before PMBench.** Their recorded helper error is
`APIConnectionError`; the underlying server failure requires separate diagnosis.
Do not describe the failed attempts as scored zero-F1 runs.

The [combined comparison](results/RESULTS.md#base-pis-and-rgpm) always selects
those planned consistency attempts for the affected cells, including lower
scores and failures. It does not cherry-pick the best observed score. The
original FP8/checkpoint-mismatched cohort remains separately visible.

Completed GPT combinations:

| Qwen Helper | F1 | State |
| --- | ---: | --- |
| 1.7B | 77.33% | 80/80 complete |
| 4B | N/A | Interrupted at 73/80 after credit rejection |
| 8B | N/A | Smoke interrupted at 0 completed steps |
| 32B | 85.71% | 80/80 complete; reused, not rerun |

GPT base is 75.71% and author-release PIS is 80.77%. Thus the 32B-helper
result exceeds both numerically; the 1.7B-helper result does not exceed PIS.
Provider and development/repeat caveats still apply. The scheduled one-shot
retry, job 1553091, checked credits after midnight October 25 and stopped
without starting experiments. It is not a running retry loop.

## Code and Ownership

| Responsibility | Canonical Path |
| --- | --- |
| Current instrumented runner | `experiments/rgpm/run.py` |
| Main-agent adapter | `experiments/rgpm/adapter.py` |
| Updated method engine | `experiments/rgpm/improved_engine.py` |
| Registration guards and evidence routing | `experiments/rgpm/registration_guard.py`, `source_routing.py` |
| Shared registration and trigger primitives | `prospective_memory/method/registration.py`, `fair_trigger.py`, related method modules |
| Durable traces/checkpoints | `experiments/rgpm/artifacts.py` |
| Offline metrics and failure exports | `experiments/rgpm/analyze.py` |
| Local / GPT launchers | `experiments/rgpm/run_one_model.sbatch`, `run_gpt_actor.sbatch` |
| Original selected run mapping | `experiments/rgpm/launches/v15_finalized_targets.json` |
| Consistency attempt mapping | `experiments/rgpm/launches/v15_consistency_reruns_20261023.json` |
| GPT follow-up mapping | `experiments/rgpm/launches/gpt_v15_remaining_helpers_submitted_20261023.json` |
| Credit-gated recovery | `experiments/rgpm/operations/` |

`experiments/exp3_method.sh` is a historical entry point; do not use it to
infer the current v15 sweep configuration. Shared code also supports older
variants: a source directory alone does not identify which variant was run.

## Failure Analysis Without Rerunning

Raw bundles retain `manifest.json`, frozen `source/`, `calls.jsonl`,
`memory_calls.jsonl`, `memory.jsonl`, `events.jsonl`, prompts, snapshots,
checkpoints, `steps.csv`, `per_task.csv`, `failures.csv`,
`failure_attribution.jsonl`, `cost.json`, `metrics.json` and an artifact index.

To investigate a failed action, find its step in `steps.csv`/`failures.csv`,
follow its call IDs and memory-row references, then inspect registration,
update/cancel, trigger evidence, query uptake and the actor's actual response.
The same bundle preserves failed/retried calls and usage uncertainty. Observed
failure stages are evidence, not proof that one stage alone caused the miss.

See the [output contract](../../experiments/rgpm/OUTPUT_CONTRACT.md) and
[offline comparison tool](../../experiments/rgpm/analysis_tools/compare_runs.py).
Raw data needs a separately supplied archive; it is not included in this GitHub
context package. Do not launch inference merely because that archive is absent.

## Limitations and Next Work

- Original Qwen32/weak-helper cells suffered serving-capacity rejections; those three reruns now have separate complete results.
- Some Qwen0.6B cells still hit their native context limit. Failures remain in the score; no silent truncation or ground-truth repair was applied.
- The original Ministral sweep used unsuffixed FP8 checkpoints despite BF16 runtime dtype. Those results are not checkpoint-matched BF16 evidence.
- Some Qwen8 pairs regress through excess false positives; user-directed behavioral fixes were deferred.
- Sequential per-intention helper assessment can be very expensive. F1 gains alone do not establish production practicality.
- PMBench was repeatedly inspected during development. Freeze a candidate and add independent validation/repeats before generalization claims.
- Complete the missing GPT and two BF16 serving-failed cells only with explicit execution/paid-run authorization. Do not silently add models or change settings.

Offline checks, using a compatible installed Python environment:

```bash
python -m unittest discover -s experiments/rgpm -p 'test_*.py'
python -m unittest discover -s experiments/rgpm/operations -p 'test_*.py'
```

As verified October 24: 89 main RGPM tests and 9 recovery tests passed. These
are software checks, not evidence of model-quality improvements.
