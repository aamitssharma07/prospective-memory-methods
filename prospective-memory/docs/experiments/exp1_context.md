# Experiment 1: PMBench Controls

Snapshot date: **2026-10-25**. [Team entry point](../../TEAM_CONTEXT.md) |
[Results table](results/RESULTS.md#experiment-1-four-baselines) |
[Downloadable CSV](results/experiment1.csv).

## Purpose and Scope

Establish how the main models perform before adding our RGPM helper. This is
the current SGLang reproduction, separate from the older vLLM development runs
in `paper_tables/` and the earlier category-analysis documents.

Eleven models completed all four approved controls, for **44 full-week runs**:
Qwen3-0.6B/1.7B/4B/8B/32B, Gemma-4-E2B, Ministral-3-3B/8B, GPT-5.4,
Llama-3.3-70B and Qwen2.5-72B. The last two are BF16 TP=2 extensions, not the
older quantized Llama result. Claude Opus and Mistral Small 24B are excluded.

| Control | Meaning |
| --- | --- |
| `single_baseline` | Main model without an added memory helper; our primary "base" comparator |
| `optional_heartbeat` | Agent-controlled heartbeat monitoring |
| `todo_ledger` | PMBench's explicit TODO-ledger control |
| `auto_heartbeat_30m` | Automatically scheduled 30-minute heartbeat |

## Protocol

- Released `synthetic_week_v9.json`: seven days, 80 steps, 81 due occurrences.
- Raw scenario SHA-256: `94a45937da1363be19ccfdc2c188d132f23093041e30abd3ec22d64d70da8f24`.
- Local models: SGLang 0.5.20, BF16; inspect each manifest for checkpoint/TP details.
- GPT-5.4: OpenRouter, not direct OpenAI.
- Actor limit: 768 output tokens; temperature 0.
- Invalid/unparseable model actions fail closed to empty selections. No ground-truth answer repair.
- These are single retained traces, not replicated averages.

The old vLLM `--generation-config vllm` warning is specific to the historical
vLLM path. It is not a current SGLang launch requirement.

## Results and Interpretation

Use [the generated matrix](results/RESULTS.md#experiment-1-four-baselines) for
all 44 values. Examples for `single_baseline`: Qwen3-8B **41.98%**, GPT-5.4
**75.71%**, Llama-3.3-70B **69.33%**. Do not substitute whichever heartbeat or
ledger score is highest when labelling a row "base".

Set-F1 alone is insufficient: the snapshot also retains TP/FP/FN, cross-day
and update hits, invalid-response counts, tokens and run duration where saved.
For example, selecting many tasks can buy recall at a high false-positive cost.

## Files and Reproduction

| Responsibility | Path in This Workspace |
| --- | --- |
| Detailed experiment history | `PMBench/EXPERIMENT_CONTEXT.md` |
| Frozen roster/protocol | `PMBench/models.json`, `PMBench/experiment.json` |
| Canonical matrix runner | `PMBench/sim/run_experiment_matrix.py` |
| Model-server launcher | `PMBench/scripts/run_local_model.sbatch` |
| Completed bundles | `PMBench/runs/core-four/<model>/<setup>/` |

Each selected bundle contains `manifest.json`, `metrics.json`, `trajectory.jsonl`,
prompt logs, score report, `steps.csv`, `failures.csv` and `ANALYSIS.md`.
The team exporter reads the individual bundles, not the stale nine-model
aggregate that predates the large-model extension.

Read-only command preview, requiring the separately published/local PMBench checkout:

```bash
cd PMBench
python sim/run_experiment_matrix.py --model Qwen3-8B
```

Do not add `--execute` merely to inspect or regenerate results. The compact
GitHub snapshot can be refreshed without inference using the command in
[Team Context](../../TEAM_CONTEXT.md#updating-this-handoff).
