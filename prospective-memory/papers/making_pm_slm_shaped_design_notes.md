# "Making Prospective Memory SLM-Shaped" — models and design

Zhao & Wu, Peking University, arXiv:2609.01272v1, 1 Sep 2026.
Extracted 2026-09-23. This is the source of the `pis` family in this repo.

## Models: four backbones, and **no separate memory model**

| Backbone | Class |
|---|---|
| DeepSeek-Chat (V3) | large hosted chat |
| Qwen3.5-4B | small, **agentic-tuned** |
| Qwen3-8B | small, chat-tuned — *our current model* |
| Gemma-E2B | on-device class, deliberate small-model extreme |

All backbones are **frozen**: no selector LoRA, no distillation, training-free.
Critically, PIS uses **one model for everything** — the "memory" is a typed code
store (Form–Decide operators), not a second model. This is the opposite of Wu et
al., where a frontier Opus memory agent runs beside the action agent.

Comparison is one scaffold against seven retrospective memory systems (Naive
RAG, Mem0, A-Mem, Letta/MemGPT, LightMem-style, MemoryOS-style) plus a no-store
`single` baseline, on the same PM-Bench week, per backbone.

Metrics: Set-F1, **update miss**, **cross-day miss**, **FA/step** — they report
the same secondary metrics we found Set-F1 was hiding.

## Results (Set-F1 / update miss / cross-day miss / FA per step)

| Backbone | `single` (no store) | + PIS |
|---|---|---|
| DeepSeek-Chat | 67.7 / 55.6 / 57.1 / 6.3 | **82.9** / 22.2 / **0.0** / 8.8 |
| Qwen3.5-4B | 57.4 / 88.9 / 85.7 / 18.8 | **70.1** / 33.3 / 28.6 / 38.8 |
| Gemma-E2B | 4.2 / 100 / 85.7 / 13.8 | **66.2** / 77.8 / 28.6 / 15.0 |
| **Qwen3-8B** | **39.8** / 55.6 / 100 / 60.0 | **57.2** / 55.6 / 57.1 / 47.5 |

Cost for one week (duration / main-prompt Mtok): PIS is 16.4m/2.08 DeepSeek,
4.7m/1.23 Gemma, 6.5m/1.48 Qwen3.5-4B, 5.6m/1.39 Qwen3-8B. A-Mem and Letta cost
15-35 min and 3-8M tokens for worse scores.

## Four consequences for our experiment design

**1. Our fresh matched baseline is the anomaly, not the historical one.**
Published Qwen3-8B `single` is **39.8%**, close to our historical 42.0% and
nothing like our fresh matched 24.3%. Their `single` also has **cross-day miss
100% and FA/step 60%**; our fresh baseline has cross-day miss **0%** and 484
false alarms from ~6 selections per step. Two independent sources now put a
Qwen3-8B no-store baseline near 40%, so the 24.3% run is behaving unlike any
published PM-Bench baseline and should be treated as suspect until explained.
Do not launch a multi-model sweep against it.

**2. We are below the published PIS on our own backbone.** Paper: Qwen3-8B+PIS
57.2%, cross-day miss 57.1%, update miss 55.6%. Ours: `pis_source_bound_v3`
52.4%, cross-day miss 71.4% (5/7), update miss 63.6% (7/11). Our best variant
trails the published result on the same model on all three. Reproducing 57.2%
is a cheaper and more informative next step than another policy iteration.

**3. Model size is the wrong axis; agentic tuning is the right one.**
Gemma-E2B (2B-class) + PIS = **66.2%** beats Qwen3-8B + PIS = **57.2%**.
Qwen3.5-4B beats Qwen3-8B on both `single` (57.4 vs 39.8) and PIS (70.1 vs
57.2). The authors attribute this to the 3.5-4B checkpoint being built for
agentic workloads, while Qwen3-8B is a chat model. **Qwen3-8B is close to the
worst choice available for this task per unit of size.**

**4. The store carries the competence — which is our hypothesis, already
evidenced.** Gemma-E2B goes 4.2% -> 66.2% (about 16x) with a frozen store and no
training. If a 2B model with a typed store beats an 8B without one, then a cheap
monitor plus good structure is the right architecture, and that is the claim our
project should be testing directly.
