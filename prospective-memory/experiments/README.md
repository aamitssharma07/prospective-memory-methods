# Experiments

For current experiment ownership, settings and results, use
[Team Context](../TEAM_CONTEXT.md) and the
[three experiment summaries](../docs/experiments/README.md). Experiment 1's
current runs live in `PMBench/runs/core-four/`; Experiment 2's canonical runs
live in the sibling `prospective-memory-reaearch` workspace; current RGPM runs
live under `experiments/rgpm/`.

The launcher table and vLLM instructions below describe the historical harness
workflow. In particular `exp2_pis_baseline.sh` is our reimplementation, not the
author-release Experiment 2 comparator, and is not the current execution path.

Each experiment is one script plus the frozen config it ran with. Results land
in `harness/results/` (Experiment 1) or a run directory you name.

| Script | Experiment |
|---|---|
| `exp1_pmbench_baselines.sh` | PM-Bench baselines for every action agent |
| `exp2_pis_baseline.sh` | PIS baseline (paper-inspired reimplementation) |
| `exp3_method.sh` | our source-bound method |

## Before any run

Two server settings are mandatory and are the difference between reproducing
published numbers and being ~18 points off.

```bash
# helper: JSON grammar must forbid repeatable whitespace
CUDA_VISIBLE_DEVICES=0 python -m prospective_memory.serve \
  --model <MODEL> --dtype bfloat16 --gpu-memory-utilization 0.9 --port 30002

# actor: must use vLLM's generation defaults, NOT the checkpoint's
CUDA_VISIBLE_DEVICES=1 python -m vllm.entrypoints.openai.api_server \
  --model <MODEL> --dtype bfloat16 --gpu-memory-utilization 0.9 \
  --generation-config vllm --served-model-name <MODEL> --port 30003
```

`--generation-config vllm` is not optional. With `auto`, vLLM loads the
checkpoint's `generation_config.json` — for Qwen3 that is `do_sample true,
temperature 0.6, top_k 20, top_p 0.95` — and the actor selects ~7 tasks per step
instead of ~1. Qwen3-8B's baseline collapses from 42.0% to 24.3%.

The actor cannot share the helper server: PM-Bench's action schema uses
`maxItems`, which xgrammar cannot compile.

## Protocol

- **Three repeats minimum.** Measured single-trace spread on unchanged code is
  **3.95 Set-F1 points**, so any gap under ~4 points is uninterpretable.
- **Fallback policy is always `empty`.** PM-Bench's shipped `ground_truth`
  policy substitutes the evaluator's due set on unparseable output.
- **Report four numbers**, not one: Set-F1, cross-day hits, update hits, false
  alarms per step. Set-F1 alone has rated a spam strategy above a memory one.
- **One change per run.** Bundled edits have hidden regressions here before.
