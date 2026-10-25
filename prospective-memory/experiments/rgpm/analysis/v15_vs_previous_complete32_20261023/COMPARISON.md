# Experiment 3: Complete 32-Pair Comparison

All updated runs completed 80 steps. Earlier F1 is the best retained older full-run F1 for the same pair and scenario, not necessarily its latest run. Helper sizes refer to Qwen3.

| Main Model | Helper | Earlier F1 | Updated F1 | Change (pp) |
|---|---:|---:|---:|---:|
| Qwen3-0.6B [C] | 1.7B | N/A | 13.46% | N/A |
| Qwen3-0.6B [C] | 4B | N/A | 21.37% | N/A |
| Qwen3-0.6B | 8B | 14.81% | 26.09% | +11.27 |
| Qwen3-0.6B [C] | 32B | 14.86% | 24.81% | +9.94 |
| Qwen3-1.7B | 1.7B | N/A | 15.00% | N/A |
| Qwen3-1.7B | 4B | 31.06% | 34.78% | +3.73 |
| Qwen3-1.7B | 8B | 32.53% | 39.75% | +7.22 |
| Qwen3-1.7B | 32B | 31.06% | 38.51% | +7.45 |
| Qwen3-4B | 1.7B | N/A | 42.49% | N/A |
| Qwen3-4B | 4B | 45.45% | 47.37% | +1.91 |
| Qwen3-4B | 8B | 52.38% | 55.91% | +3.53 |
| Qwen3-4B | 32B | 51.72% | 65.95% | +14.22 |
| Qwen3-8B | 1.7B | N/A | 41.54% | N/A |
| Qwen3-8B | 4B | 56.79% | 44.27% | -12.52 |
| Qwen3-8B | 8B | 52.69% | 34.19% | -18.51 |
| Qwen3-8B | 32B | 54.22% | 62.37% | +8.15 |
| Qwen3-32B [C] | 1.7B | N/A | 38.67% | N/A |
| Qwen3-32B [C] | 4B | 55.41% | 43.66% | -11.74 |
| Qwen3-32B [C] | 8B | 56.95% | 50.36% | -6.59 |
| Qwen3-32B | 32B | 55.94% | 66.67% | +10.72 |
| Gemma-4-E2B | 1.7B | N/A | 17.39% | N/A |
| Gemma-4-E2B | 4B | 44.72% | 34.78% | -9.94 |
| Gemma-4-E2B | 8B | 34.78% | 40.99% | +6.21 |
| Gemma-4-E2B | 32B | 36.02% | 38.51% | +2.48 |
| Ministral-3-3B | 1.7B | N/A | 41.03% | N/A |
| Ministral-3-3B [V] | 4B | 47.30% | 53.50% | +6.21 |
| Ministral-3-3B [V] | 8B | 56.77% | 54.66% | -2.12 |
| Ministral-3-3B [V] | 32B | 46.58% | 55.56% | +8.98 |
| Ministral-3-8B | 1.7B | N/A | 55.35% | N/A |
| Ministral-3-8B [V] | 4B | 62.59% | 56.25% | -6.34 |
| Ministral-3-8B [V] | 8B | 61.54% | 60.92% | -0.62 |
| Ministral-3-8B [V] | 32B | 64.15% | 69.77% | +5.62 |

[C]: Updated run has confirmed context-window/capacity rejections; affected predictions remain empty/incorrect.
[V]: Previous Ministral checkpoint is BF16, updated checkpoint is standard FP8. Numerical comparison only; not matched-checkpoint evidence of method improvement.
N/A: No older completed same-pair result found in the searched results directory; not zero F1.

Exact checkpoint matches: 17; 12 improved and 5 declined. Checkpoint-mismatched comparisons: 6. Missing older matches: 9.

Source paths and comparison choices are retained in comparison.json and comparison.csv. No models were rerun, no original results modified, and current GPT follow-up jobs are not included in this local 32-pair table.
