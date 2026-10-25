# Experiment 1 — PM-Bench baselines

`single_baseline` setup · `synthetic_week_v9` · 80 steps · 81 due occurrences ·
7 cross-day · 11 update-sensitive · vLLM 0.8.5.post1 V1 · bf16 ·
`temperature 0` · `enable_thinking false` · **`generation_config vllm`** ·
actor max_tokens 768 · **single trace per cell (no repeats yet)**.

Source: `harness/results/<model>/single_baseline/trajectory.score.md`.
Generated from run artifacts; do not hand-edit.

## 1. Headline set metrics

| Model | Params | Set-F1 | Precision | Recall | TP | FP | FN |
|---|---:|---:|---:|---:|---:|---:|---:|
| Qwen3-0.6B | 0.6B | **18.6** | 18.8 | 18.5 | 15 | 65 | 66 |
| Qwen3-1.7B | 1.7B | **31.1** | 31.2 | 30.9 | 25 | 55 | 56 |
| Ministral-3-3B | 3B | **49.4** | 52.1 | 46.9 | 38 | 35 | 43 |
| Qwen3-4B | 4B | **17.3** | 39.1 | 11.1 | 9 | 14 | 72 |
| Qwen3-8B | 8B | **42.0** | 42.0 | 42.0 | 34 | 47 | 47 |
| Ministral-3-8B | 8B | **59.7** | 75.5 | 49.4 | 40 | 13 | 41 |
| Qwen3-14B | 14B | **44.4** | 40.4 | 49.4 | 40 | 59 | 41 |
| Mistral-Small-24B | 24B | **53.0** | 68.6 | 43.2 | 35 | 16 | 46 |
| Qwen3-32B | 32B | **52.8** | 60.3 | 46.9 | 38 | 25 | 43 |
| Llama-3.3-70B | 70B | **58.0** | 76.0 | 46.9 | 38 | 12 | 43 |
| Gemma-4-E2B | — | *not run* | | | | | |
| GPT-5.4 | — | *not run* | | | | | |
| Claude Opus 4.6 | — | *not run* | | | | | |

## 2. Failure analysis

| Model | hit | late | miss | false alarm | wrong-content | overkill steps | selections | exact-set match | state queries |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen3-0.6B | 15 | 2 | 64 | 63 | 36 | 29 | 80 | 4 | 7 |
| Qwen3-1.7B | 25 | 3 | 53 | 52 | 26 | 29 | 80 | 12 | 80 |
| Ministral-3-3B | 38 | 2 | 41 | 33 | 10 | 26 | 73 | 21 | 20 |
| Qwen3-4B | 9 | 1 | 71 | 13 | 10 | 4 | 23 | 30 | 0 |
| Qwen3-8B | 34 | 4 | 43 | 43 | 18 | 30 | 81 | 15 | 0 |
| Ministral-3-8B | 40 | 2 | 39 | 11 | 3 | 10 | 53 | 40 | 0 |
| Qwen3-14B | 40 | 3 | 38 | 56 | 28 | 36 | 99 | 14 | 0 |
| Mistral-Small-24B | 35 | 4 | 42 | 12 | 6 | 9 | 51 | 40 | 8 |
| Qwen3-32B | 38 | 4 | 39 | 21 | 8 | 17 | 63 | 30 | 0 |
| Llama-3.3-70B | 38 | 0 | 43 | 12 | 3 | 9 | 50 | 42 | 0 |

## 3. Prospective-memory slices

Report these alongside Set-F1, never Set-F1 alone.

| Model | cross-day hit /7 | cross-day miss | update hit /11 | update miss | update violations | event hit % | time hit % |
|---|---:|---:|---:|---:|---:|---:|---:|
| Qwen3-0.6B | 2 | 5 | 2 | 6 | 18 | 21.1 | 12.5 |
| Qwen3-1.7B | 0 | 7 | 0 | 8 | 17 | 42.1 | 4.2 |
| Ministral-3-3B | 0 | 7 | 3 | 6 | 11 | 50.9 | 37.5 |
| Qwen3-4B | 0 | 7 | 0 | 9 | 3 | 15.8 | 0.0 |
| Qwen3-8B | 0 | 7 | 1 | 7 | 12 | 43.9 | 37.5 |
| Ministral-3-8B | 0 | 6 | 1 | 8 | 4 | 56.1 | 33.3 |
| Qwen3-14B | 1 | 5 | 2 | 7 | 18 | 56.1 | 33.3 |
| Mistral-Small-24B | 0 | 7 | 3 | 5 | 5 | 42.1 | 45.8 |
| Qwen3-32B | 0 | 7 | 1 | 8 | 9 | 56.1 | 25.0 |
| Llama-3.3-70B | 0 | 7 | 0 | 9 | 6 | 50.9 | 37.5 |

## 4. Fallback contamination

Original = PM-Bench's shipped `ground_truth` policy, which substitutes the
evaluator's due set when a model's structured output stays invalid after
retries. Corrected = same trace with fallback-inserted selections removed.

| Model | Setup | Fallback rate | Original Set-F1 | Corrected Set-F1 | Delta |
|---|---|---:|---:|---:|---:|
| Llama-3.2-1B | `single_baseline` | 100.0% | 100.0% | **0.0%** | -100.0 |
| Llama-3.2-1B | `heartbeat_proactive` | 100.0% | 100.0% | **0.0%** | -100.0 |
| Llama-3.2-1B | `heartbeat_auto30` | 100.0% | 100.0% | **0.0%** | -100.0 |
| Llama-3.2-1B | `heartbeat_auto60` | 100.0% | 100.0% | **0.0%** | -100.0 |
| Llama-3.2-3B | `single_baseline` | 98.8% | 99.4% | **2.4%** | -97.0 |
| Llama-3.2-3B | `heartbeat_proactive` | 98.8% | 99.4% | **2.4%** | -97.0 |
| Llama-3.2-3B | `heartbeat_auto30` | 98.8% | 99.4% | **2.4%** | -97.0 |
| Llama-3.2-3B | `heartbeat_auto60` | 98.8% | 99.4% | **2.4%** | -97.0 |
| Phi-4-mini | `single_baseline` | 82.5% | 87.3% | **2.2%** | -85.1 |
| Phi-4-mini | `heartbeat_auto60` | 83.8% | 90.6% | **6.7%** | -83.9 |
| Phi-4-mini | `heartbeat_auto30` | 85.0% | 90.1% | **6.5%** | -83.6 |
| Phi-4-mini | `heartbeat_proactive` | 83.8% | 88.3% | **6.4%** | -82.0 |
| Qwen3-8B | `heartbeat_proactive` | 51.2% | 72.7% | **32.8%** | -39.9 |
| Llama-3.3-70B | `heartbeat_proactive` | 12.5% | 62.7% | **52.8%** | -9.9 |
| Qwen3-1.7B | `heartbeat_proactive` | 2.5% | 32.7% | **31.6%** | -1.1 |
| Ministral-3-8B | `heartbeat_proactive` | 1.2% | 61.5% | **60.6%** | -1.0 |
| Qwen3-14B | `heartbeat_proactive` | 1.2% | 48.5% | **47.6%** | -0.9 |

17 of 52 audited runs change under correction; the other 35 had zero
fallback events, so original and corrected coincide exactly.

**Fallback concentrates in `heartbeat_proactive`**, where the agent must also
emit `set heartbeat` and structured-output failures spike. `single_baseline`,
`auto30` and `auto60` are clean for every model except the three below.

## 5. Excluded from method comparisons

These never produced valid structured output, so nearly every score was
fallback-supplied. There is nothing for a memory module to improve. Retained
as evidence for the fallback artifact only.

| Model | Params | Original Set-F1 | Corrected Set-F1 | Fallback rate |
|---|---:|---:|---:|---:|
| Llama-3.2-1B | 1B | 100.0% | **0.0%** | 100.0% |
| Llama-3.2-3B | 3B | 99.4% | **2.4%** | 98.8% |
| Phi-4-mini | 3.8B | 87.3% | **2.2%** | 82.5% |

## 6. Known gaps

1. **Single trace per cell.** Measured spread on unchanged code is 3.95 Set-F1
   points, so no gap under ~4 points here is interpretable. Needs 3 repeats.
2. **Three models unrun**: Gemma-4-E2B, GPT-5.4, Claude Opus 4.6.
3. **Llama-3.3-70B is 4-bit bitsandbytes**; every other model is bf16. Rerun
   at bf16 before using it as a scale anchor.
4. **4 of PM-Bench's 8 setups.** Missing `todo_ledger`, `multi_baseline`,
   `multi_union_query`, `multi_majority_vote`.
5. **False alarms are unattributed.** PM-Bench's scorer records them as a
   single scalar with no task identity. Misses are attributed by cross-day,
   update, modality, monitoring category and channel; false alarms are not.
6. **Corrections are same-trace recomputations**, not re-executed runs. For
   the three excluded models a fallback action can alter later simulator
   state, so their corrected scores are lower bounds.
7. **`generation_config` must be `vllm`.** With `auto`, vLLM loads Qwen3's
   own `generation_config.json` (`do_sample true, temperature 0.6, top_k 20,
   top_p 0.95`) and the actor selects ~7 tasks per step instead of ~1,
   collapsing Qwen3-8B's baseline from 42.0% to 24.3%.
