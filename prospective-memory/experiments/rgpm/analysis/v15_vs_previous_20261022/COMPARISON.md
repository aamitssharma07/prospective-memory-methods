# Updated Versus Earlier Experiment 3

Compared on the same actor, helper and 80-step scenario. Earlier F1 is the **best retained previous full-run F1 per pair** under `runs/synthetic_week_v9`; this is a conservative historical comparison, not a single fixed prior version or a repeated-trial significance test.

Matched pairs: 11; improved: 9; regressed: 2. Excluding updated runs with identified context-capacity rejections: 10 matched pairs, 8 improved and 2 regressed.

| Main | Helper | Best Earlier F1 | Updated F1 | Delta (pp) | Updated Context Rejections |
|---|---|---:|---:|---:|---|
| Qwen3-0.6B | Qwen3-8B | 14.81% | 26.09% | +11.27 | No |
| Qwen3-0.6B | Qwen3-32B | 14.86% | 24.81% | +9.94 | Yes |
| Qwen3-1.7B | Qwen3-4B | 31.06% | 34.78% | +3.73 | No |
| Qwen3-1.7B | Qwen3-8B | 32.53% | 39.75% | +7.22 | No |
| Qwen3-1.7B | Qwen3-32B | 31.06% | 38.51% | +7.45 | No |
| Qwen3-4B | Qwen3-4B | 45.45% | 47.37% | +1.91 | No |
| Qwen3-4B | Qwen3-8B | 52.38% | 55.91% | +3.53 | No |
| Qwen3-4B | Qwen3-32B | 51.72% | 65.95% | +14.22 | No |
| Qwen3-8B | Qwen3-4B | 56.79% | 44.27% | -12.52 | No |
| Qwen3-8B | Qwen3-8B | 52.69% | 34.19% | -18.51 | No |
| Qwen3-8B | Qwen3-32B | 54.22% | 62.37% | +8.15 | No |

The remaining six completed updated pairs have no matching historical full result in the searched location. Do not infer improvement for them from a different helper pairing.

## Regression Detail

- Qwen3-8B / Qwen3-4B: TP 46 -> 58, FP 35 -> 123, FN 35 -> 23. Better recall is outweighed by incorrect selections.
- Qwen3-8B / Qwen3-8B: TP 44 -> 60, FP 42 -> 210, FN 37 -> 21. The false-positive increase outweighs the recall improvement.

The source metrics paths, job IDs, counts, and comparison choices are retained in `comparison.json`. Historical serving/input settings may differ; this table alone does not isolate the effect of each code change. No inference or job changes were made for this comparison.
