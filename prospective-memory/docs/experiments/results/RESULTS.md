# Results Snapshot

Artifact-derived snapshot: 2026-10-25 (America/Chicago).
Generated offline by `harness/export_team_context.py`; no model or embedding calls.

F1 values are percentages. N/A means no completed full result, not zero.
Run paths and source hashes are in [snapshot.json](snapshot.json) and the three CSV files.

## Base, PIS, and RGPM

RGPM uses the updated v15 method. For the 11 consistency targets, use that attempt
even if it scores lower or fails; never fall back to a higher FP8/original result.
All other local cells retain their original v15 run. These choices do not establish
identical serving hardware across all experiments. GPT providers also differ.

| Main Model | Base (Exp 1) | PIS (Exp 2) | RGPM h1.7B | RGPM h4B | RGPM h8B | RGPM h32B |
| --- | --- | --- | --- | --- | --- | --- |
| Qwen3-0.6B | 24.84 | 0.00 | 13.46 | 21.37 | 26.09 | 24.81 |
| Qwen3-1.7B | 29.81 | 29.87 | 15.00 | 34.78 | 39.75 | 38.51 |
| Qwen3-4B | 13.73 | 36.88 | 42.49 | 47.37 | 55.91 | 65.95 |
| Qwen3-8B | 41.98 | 33.22 | 41.54 | 44.27 | 34.19 | 62.37 |
| Gemma-4-E2B | 35.36 | 34.78 | 17.39 | 34.78 | 40.99 | 38.51 |
| Ministral-3-3B | 52.29 | 49.35 | 46.75 | 42.58 | 49.03 | N/A |
| Ministral-3-8B | 60.29 | 51.43 | 59.12 | 61.99 | 64.33 | N/A |
| Qwen3-32B | 50.70 | 47.24 | 55.68 | 55.95 | 63.04 | 66.67 |
| GPT-5.4 | 75.71 | 80.77 | 77.33 | N/A | N/A | 85.71 |
| Llama-3.3-70B | 69.33 | 63.08 | N/A | N/A | N/A | N/A |
| Qwen2.5-72B | 61.90 | 62.94 | N/A | N/A | N/A | N/A |

Two BF16 Ministral + 32B-helper reruns failed serving probes before PMBench.
GPT + 4B is interrupted at 73/80; GPT + 8B is interrupted in smoke (0 steps).
Their F1 is not reported. The original FP8 Ministral results remain below.

## Experiment 1: Four Baselines

44 complete full-week runs; SGLang local actors, OpenRouter GPT.

| Model | single_baseline | optional_heartbeat | todo_ledger | auto_heartbeat_30m |
| --- | --- | --- | --- | --- |
| Qwen3-0.6B | 24.84 | 18.63 | 21.12 | 19.88 |
| Qwen3-1.7B | 29.81 | 27.85 | 36.02 | 31.06 |
| Qwen3-4B | 13.73 | 8.60 | 17.02 | 20.80 |
| Qwen3-8B | 41.98 | 40.51 | 52.48 | 38.55 |
| Gemma-4-E2B | 35.36 | 30.53 | 20.07 | 29.27 |
| Ministral-3-3B | 52.29 | 48.75 | 24.30 | 53.06 |
| Ministral-3-8B | 60.29 | 60.29 | 52.54 | 61.76 |
| Qwen3-32B | 50.70 | 50.31 | 54.14 | 51.70 |
| GPT-5.4 | 75.71 | 73.13 | 68.09 | 71.83 |
| Llama-3.3-70B | 69.33 | 65.62 | 69.57 | 62.50 |
| Qwen2.5-72B | 61.90 | 58.46 | 57.85 | 59.54 |

## Experiment 2: Four Memory Methods

44 complete full-week runs from the sibling author-release workspace.

| Model | Mem0 | A-Mem | PIS-RAG | PIS |
| --- | --- | --- | --- | --- |
| Qwen3-0.6B | 2.44 | 2.27 | 11.48 | 0.00 |
| Qwen3-1.7B | 37.04 | 30.97 | 33.33 | 29.87 |
| Qwen3-4B | 34.11 | 35.06 | 29.17 | 36.88 |
| Qwen3-8B | 27.53 | 25.07 | 31.67 | 33.22 |
| Gemma-4-E2B | 24.84 | 24.66 | 19.88 | 34.78 |
| Ministral-3-3B | 37.14 | 23.36 | 7.48 | 49.35 |
| Ministral-3-8B | 49.70 | 40.46 | 36.90 | 51.43 |
| Qwen3-32B | 50.00 | 50.00 | 40.82 | 47.24 |
| GPT-5.4 | 70.59 | 65.33 | 60.56 | 80.77 |
| Llama-3.3-70B | 58.44 | 62.25 | 55.56 | 63.08 |
| Qwen2.5-72B | 54.43 | 56.76 | 53.24 | 62.94 |

## RGPM: Original 32-Pair Sweep

All 32 completed. Ministral rows here are FP8, not the BF16 consistency reruns.

| Main Model | h1.7B | h4B | h8B | h32B |
| --- | --- | --- | --- | --- |
| Qwen3-0.6B | 13.46 | 21.37 | 26.09 | 24.81 |
| Qwen3-1.7B | 15.00 | 34.78 | 39.75 | 38.51 |
| Qwen3-4B | 42.49 | 47.37 | 55.91 | 65.95 |
| Qwen3-8B | 41.54 | 44.27 | 34.19 | 62.37 |
| Gemma-4-E2B | 17.39 | 34.78 | 40.99 | 38.51 |
| Ministral-3-3B | 41.03 | 53.50 | 54.66 | 55.56 |
| Ministral-3-8B | 55.35 | 56.25 | 60.92 | 69.77 |
| Qwen3-32B | 38.67 | 43.66 | 50.36 | 66.67 |

Known original context-failure flags: Qwen0.6B + h1.7/h4/h32 and Qwen32B + h1.7/h4/h8.
These results include the empty/incorrect outcomes, not repaired predictions.

## RGPM: Follow-Up Attempts

| Job | Main | Helper | Cohort | Status | Steps | F1 |
| --- | --- | --- | --- | --- | --- | --- |
| 1553054 | Qwen3-32B | Qwen3-1.7B | consistency_v15 | complete | 80 | 55.68 |
| 1553055 | Qwen3-32B | Qwen3-4B | consistency_v15 | complete | 80 | 55.95 |
| 1553056 | Qwen3-32B | Qwen3-8B | consistency_v15 | complete | 80 | 63.04 |
| 1553057 | Ministral-3-3B | Qwen3-1.7B | consistency_v15 | complete | 80 | 46.75 |
| 1553058 | Ministral-3-3B | Qwen3-4B | consistency_v15 | complete | 80 | 42.58 |
| 1553059 | Ministral-3-3B | Qwen3-8B | consistency_v15 | complete | 80 | 49.03 |
| 1553060 | Ministral-3-3B | Qwen3-32B | consistency_v15 | serving_probe_failed | 0 | N/A |
| 1553061 | Ministral-3-8B | Qwen3-1.7B | consistency_v15 | complete | 80 | 59.12 |
| 1553062 | Ministral-3-8B | Qwen3-4B | consistency_v15 | complete | 80 | 61.99 |
| 1553063 | Ministral-3-8B | Qwen3-8B | consistency_v15 | complete | 80 | 64.33 |
| 1553064 | Ministral-3-8B | Qwen3-32B | consistency_v15 | serving_probe_failed | 0 | N/A |
| 1553051 | GPT-5.4 | Qwen3-1.7B | gpt_v15 | complete | 80 | 77.33 |
| 1553052 | GPT-5.4 | Qwen3-4B | gpt_v15 | interrupted | 73 | N/A |
| 1553053 | GPT-5.4 | Qwen3-8B | gpt_v15 | smoke_interrupted | 0 | N/A |
| 1537307 | GPT-5.4 | Qwen3-32B | gpt_v15 | complete | 80 | 85.71 |

## Interpretation

- These are single retained development traces, not replicated mean performance.
- PMBench v9 was repeatedly inspected during RGPM development; this is not a held-out validation claim.
- Compare checkpoint precision, serving capacity, backend, token limits and scenario before attributing a delta to methodology.
- Exp 2's 768-token actor limit does not cover its separate method-specific maintenance calls.
- Token and duration scopes differ; read the CSV fields and each experiment context before pooling costs.
- No claim of universal superiority, statistical significance, or production efficiency follows from this snapshot.
