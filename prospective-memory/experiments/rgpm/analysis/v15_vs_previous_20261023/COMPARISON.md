# Completed Experiment 3 F1 Comparison

Snapshot: 27 complete 80-step runs. Earlier = highest retained previous F1 per pair on the same scenario, not necessarily the most recent run. This compares previous development variants, not one prespecified earlier version.

| Main | Qwen3 Helper | Best Earlier F1 | Updated F1 | Delta (pp) |
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

[C]: Updated run has confirmed actor context-window/capacity rejection(s); the score includes empty/incorrect fallback on affected requests.
[V]: Earlier Ministral checkpoint is BF16; updated checkpoint is the standard FP8 variant. Numerical comparison only, not a matched-checkpoint methodology comparison.
N/A: No complete historical same-pair result found in the searched directory. Missing matches do not imply zero F1.

Exact checkpoint matches: 17; improved: 12; lower: 5. Two additional Ministral comparisons have checkpoint differences; 8 pairs lack older matched scores.

Each source metrics path and selected historical checkpoint identity is preserved in comparison.json. Existing runs are unchanged. The table does not establish statistical significance or isolate effects of individual method changes.
