# Experiment plan

Master plan for the multi-model prospective-memory study. Built step by step;
sections are added as they are decided. Numbers cited here are traceable to
`docs/results_ledger.md` or to the three source papers.

Source papers:
- **PM-Bench** — Liu & Gabriel, COLM 2026 (`papers/pmbench.pdf`)
- **PIS** — Zhao & Wu, *Making Prospective Memory SLM-Shaped*, arXiv:2609.01272,
  1 Sep 2026 (`papers/making_prospective_memory_slm_shaped_2609.01272.pdf`)
- **RWIM** — Wu et al., *Remember When It Matters*, arXiv:2607.08716, 10 Jul 2026
  (`papers/remember_when_it_matters.pdf`). Uses Terminal-Bench 2.0 and tau^2-Bench,
  **not** PM-Bench; methodological reference only.

Hardware: 2 x RTX 6000 Ada (48 GB each) + a 200 GB machine for large models.

---

## 1. Models

Cut to the minimum set that supports every claim. Full candidate list retained
in the appendix. Tier = capability/size class. "Published Set-F1" is the
single-agent baseline; "-> X" is that paper's memory result.

### 1.1 Action agents (9 core + 2 frontier)

| # | Model | HF id / access | Size | Tier | Source | Published Set-F1 | Why it is in |
|---|---|---|---:|---|---|---|---|
| 1 | Qwen3-0.6B | `Qwen/Qwen3-0.6B` | 0.6B | Small | ours | 18.6 | sub-1B floor; also the helper floor probe |
| 2 | Qwen3-1.7B | `Qwen/Qwen3-1.7B` | 1.7B | Small | ours | 31.1 | small end; also the distillation student |
| 3 | Qwen3-4B | `Qwen/Qwen3-4B` | 4B | Small | ours | 17.3 | fills the 1.7-8B gap; also a helper point |
| 4 | **Qwen3-8B** | `Qwen/Qwen3-8B` | 8B | Small | **PM-Bench + PIS** | 42.0 / 39.8 -> **57.2** | **anchor** — only model in both papers; all existing runs use it |
| 5 | Gemma-4-E2B | `google/gemma-4-E2B-it` | ~2B | Small | PIS (different checkpoint) | PIS reports 4.2 -> **66.2** for *their* Gemma-E2B | third family at ~2B; fills the 1.7-3B gap. **Not** the PIS checkpoint — see 1.2 |
| 6 | Ministral-3-3B | `mistralai/Ministral-3-3B-Instruct-2512` | 3B | Small | ours | **49.4** | family replication at 3B — beats Qwen3-8B despite being smaller |
| 7 | Ministral-3-8B | `mistralai/Ministral-3-8B-Instruct-2512` | 8B | Small | ours | **59.7** | same size, different family — isolates tuning from scale |
| 8 | Qwen3-32B | `Qwen/Qwen3-32B` | 32B | Mid | PM-Bench | 51.4 | mid anchor |
| 9 | Llama-3.3-70B | `meta-llama/Llama-3.3-70B-Instruct` | 70B | Large | PM-Bench | 64.4 (ours 58.0 @ 4-bit) | scale anchor; bf16 removes our only precision confound |
| 10 | GPT-5.4 | API | — | Frontier | PM-Bench | **72.5** | frontier ceiling; general-purpose and cheaper than the Codex tier, and still a published PM-Bench model |
| 11 | Claude Opus 4.6 | API | — | Frontier | RWIM | — | frontier actor **and** the frontier helper (matches RWIM design) |

Span: **0.6B -> 70B -> frontier**, across **four open families**.

- **Scale axis**: Qwen 0.6 / 1.7 / 4 / 8 / 32B — one family, controlled. No
  published work covers PM-Bench below ~2B.
- **Family replication**: Ministral 3B + 8B against Qwen at matched sizes, so
  every scale claim gets a cross-family check.
- **Further families**: Gemma-4-E2B at ~2B and Llama-3.3-70B at 70B, so the
  small end and the large end each have non-Qwen coverage.

This matters because family dominates scale in our own measurements:
Ministral-3-3B (49.4) beats Qwen3-8B (42.0), and Ministral-3-8B (59.7) beats
Qwen3-32B (52.8). A single-family ladder would support only a claim about Qwen,
and the Qwen curve is not even monotonic - Qwen3-4B (17.3) scores below
Qwen3-1.7B (31.1) because it under-selects, emitting just 23 selections over 80
steps. Cross-family coverage turns that confound into a reportable result.

### 1.2 Helper axis (the novel dimension)

`Qwen3-0.6B -> Qwen3-4B -> Qwen3-8B -> Claude Opus 4.6`

Swept on **two actors only** (Qwen3-8B plus one other), not all eight. Neither
PM-Bench nor PIS varies the helper at all; RWIM has two helper points and never
crosses them with actor strength. This axis is the contribution.

Gemma-4-E2B is included so the helper curve is not a single-family artifact: a
flat Qwen-only curve could not distinguish "helper size does not matter" from
"Qwen helpers all behave alike". It is the same argument applied to actors in
1.1. **It is NOT the PIS checkpoint** - PIS describes their Gemma-E2B as
short-context, while the cached `gemma-4-E2B-it` has a 131k window - so its
results must not be presented as reproducing their 66.2%.

| Helper | HF id / access | Size | Role |
|---|---|---:|---|
| Qwen3-0.6B | `Qwen/Qwen3-0.6B` | 0.6B | floor probe |
| Qwen3-4B | `Qwen/Qwen3-4B` | 4B | mid |
| Qwen3-8B | `Qwen/Qwen3-8B` | 8B | parity with actor |
| Gemma-4-E2B | `google/gemma-4-E2B-it` | ~2B | **non-Qwen small helper** — breaks the single-family confound on this axis |
| Claude Opus 4.6 | API | — | frontier ceiling (~$16 per 3 runs at current cost) |
| *(later)* distilled Qwen3-1.7B | — | 1.7B | learnability tier |

### 1.3 Fallback-artifact evidence only — no new runs

Already measured; excluded from all method comparisons because they never
produced valid structured output, so there is nothing for memory to improve.

| Model | Original -> Corrected | Fallback rate |
|---|---|---:|
| Llama-3.2-1B | 100% -> **0.0%** | 100% |
| Llama-3.2-3B | 99.4% -> **2.4%** | 98.8% |
| Phi-4-mini | 87.3% -> **2.2%** | 82.5% |

### 1.4 Run-count budget

| Stage | Runs |
|---|---:|
| Experiments 1-3, 9 open actors x 3 conditions x 3 repeats | 81 |
| Frontier actors (baseline + one memory condition, API) | ~12 |

| Helper sweep, 2 actors x 4 helpers x 3 repeats | 24 |
| **Total** | **~123** |

The three smallest actors (0.6B, 1.7B, 4B) are cheap: each run is far shorter
than an 8B+ run, so the added cost is well under the row count suggests.

API cost is not the constraint people expect. A frontier **actor** run is ~806k
input and ~4k output tokens: roughly **$2.50 per run**, about **$7.50** for three
repeats. A frontier **helper** is the expensive role - ~2,088 calls and ~3.0M
input tokens, roughly **$11 per run** - because it is invoked several times per
step rather than once. Budget the helper, not the actor.

Three repeats are the minimum: measured single-trace spread on unchanged code is
**3.95 Set-F1 points**, so any gap under ~4 points is not interpretable.

### 1.5 Notes

- Tier-3 runs load actor and helper together. 70B actor + 8B helper ~171 GB
  fits the 200 GB box; 70B + 32B (~219 GB) does not.
- Models 1-3 have **no published PM-Bench numbers** in any paper; results for
  the sub-8B range are a contribution of this work.
- Verify HF ids before downloading anything not already cached.

### 1.6 Appendix — considered and deferred

| Model | Size | Source | Why deferred |
|---|---:|---|---|
| GPT-5.3-Codex | — | PM-Bench | highest published single-agent score (78.9) but a code-specialised, higher-priced tier; cite the number rather than re-run |
| Qwen3.5-4B | 4B | PIS | same; HF id unverified |
| Qwen3-14B | 14B | PM-Bench | sits between 8B and 32B on an already-dense curve |
| Mistral-Small-3.2-24B | 24B | PM-Bench | as above |
| Qwen3.5-27B | 27B | RWIM | our own distilled 1.7B is the better trained-helper comparator |
| Qwen3.5-122B-A10B | 122B | RWIM | ~244 GB bf16, exceeds 200 GB |
| DeepSeek-V3 | 671B | PIS | ~1.3 TB, API only |
| Mistral-Large-3-675B | 675B | PM-Bench | ~1.35 TB, API only |

---

## Per-experiment context files

Detailed results live in `docs/experiments/`, one file per experiment, written
alongside that experiment's code. See `docs/experiments/README.md`.

| Experiment | Context file |
|---|---|
| 1 — PM-Bench baselines | `docs/experiments/exp1_task_taxonomy.md` (categories)<br>`docs/experiments/exp1_category_analysis.md` (results) |
| 2 — PIS | *pending* |
| 3 — SBPM (ours) | *pending* |
| 4 — learnability | *pending* |

## 2. Experiment 1 — PM-Bench baselines

**Goal.** Establish a corrected-fallback PM-Bench baseline for all 11 action
agents, on one serving stack, with full metric and failure detail retained.
This is the reference every later experiment is measured against.

### 2.1 What to run

All 11 action agents from 1.1, on `benchmark/data/synthetic_week_v9.json`
(80 steps, 81 due occurrences), **3 repeats each**.

Setups: at minimum `single_baseline`. PM-Bench defines 8; we already hold 4 for
9 models (see 2.3). Decide explicitly whether Experiment 1 covers 1, 4 or all 8
setups before starting - it multiplies the run count by that factor.

Fallback policy **`empty`**, never `ground_truth`. Record `fallback_triggered`,
`fallback_policy` and `fallback_reason` per step.

### 2.2 What to save per run

Beyond Set-F1, PM-Bench's own scorer already emits most of this; keep the whole
score report plus the raw trajectory.

**Headline:** set_tp, set_fp, set_fn, set_precision, set_recall, **set_f1**.

**Diagnostic counts:** hit, late, miss, false_alarm, commission, wrong_content,
dependency_violation, overkill_steps, chosen_tasks, exact_set_match_steps /
mismatch_steps.

**Prospective-memory slices — report these alongside Set-F1, never Set-F1
alone:** cross_day_total / hit / late / miss, update_total / hit / late / miss /
violation / canceled, and per-modality (event vs time) and per-regularity
(regular vs irregular) hit rates.

**Cost:** wall-clock duration, actor input/output tokens, state_query_calls,
check_time_calls.

**False-alarm attribution (a gap in PM-Bench's own scorer).** The released
scorer attributes **misses** richly - cross-day, update, modality, monitoring
category and per channel - but records **false alarms as a single scalar**
(`metrics["false_alarm"] += 1`), with no record of *which* task was wrongly
selected or what kind it was. Since our method's whole profile is trading false
alarms against hits, we must attribute them ourselves.

This is derivable from artifacts we already save. The scenario supplies metadata
for 59 tasks (`type` event/time, `regular`, `cross_day`, `cue` channel, `day`)
plus 74 lure entries, `pm_bench.compute_due_now` is importable, and
`trajectory.jsonl` records the selected ids per step. For every
selected-but-not-due id, classify it as:

- **lure** - id not in the task list at all (confirmed to occur: several ids
  Qwen3-8B selected are absent from task metadata)
- **right task, wrong time** - genuinely due at a different step or day
- **cross-day task fired early**
- **already-satisfied task re-selected** - the re-firing failure mode our
  adapter is known to have, since it gets no completion signal
- and cross-cut each by modality (event vs time) and regularity

Report this as a per-model false-alarm breakdown table alongside the miss
breakdown the scorer already gives. It is a contribution in its own right: no
published PM-Bench result attributes false alarms.

**Where failures happen (the point of this experiment):**
- per-step `trajectory.jsonl` with `step_id`, `task_ids`, `choice`,
  `state_queries`, `check_time`, `fallback_triggered`, `fallback_reason`
- the full `prompts.log` so any decision can be re-read in context
- selections-per-step distribution - it distinguishes a model that spams the
  action menu from one that reasons (see the vLLM/SGLang note in 2.4)
- fallback rate per model, and original vs corrected Set-F1 for each

### 2.3 Coverage already in hand

`harness/results/summary.csv` holds **4 of PM-Bench's 8 setups**
(single_baseline, heartbeat proactive/auto30/auto60) for 9 of the 11 agents.

| Agent | Status |
|---|---|
| Qwen3-0.6B, Qwen3-1.7B, Qwen3-4B, Qwen3-8B | have 4 setups |
| Ministral-3-3B, Ministral-3-8B | have 4 setups |
| Qwen3-32B | have 4 setups |
| Llama-3.3-70B | have 4 setups, but **4-bit bitsandbytes** - rerun at bf16 |
| **Gemma-4-E2B** | **missing - must run** |
| **GPT-5.4** | **missing - must run** (API) |
| **Claude Opus 4.6** | **missing - must run** (API) |

Never run for any model: `todo_ledger`, `multi_baseline`,
`multi_union_query`, `multi_majority_vote`.

### 2.4 Blocking issue: the existing results are on a different serving stack

The runs in `summary.csv` reproduce PM-Bench closely - Qwen3-8B matched
34/47/47 exactly, and three other models landed within 1.4 points. **The current
vLLM setup does not**: the same Qwen3-8B single baseline now scores **24.3%**
(78 TP / 484 FP), because the actor selects ~7 tasks per step instead of ~1.
PM-Bench's own runner reproduces that 7.03 figure on our server, so it is the
stack, not our harness.

**Existing and new results therefore cannot be mixed.** Resolve this before
Experiment 1, or every model runs twice. Two options:

1. Identify and restore whatever differed in the older stack, verify by
   reproducing Qwen3-8B at 42.0%, then run only the missing models.
2. Accept the current stack as the reference and rerun all 11 agents on it,
   treating `summary.csv` as historical.

Option 1 is far cheaper and keeps comparability with both papers; option 2 is
only justified if the older configuration cannot be recovered.

### 2.5 Run-count

| Scope | Runs |
|---|---:|
| 11 agents x single_baseline x 3 repeats | 33 |
| If all 4 held setups are refreshed | 132 |
| If all 8 PM-Bench setups | 264 |

Decide the setup scope in 2.1 first.

## 3. Experiment 2 — PIS

*To be specified.*

## 4. Experiment 3 — our methodology

*To be specified.*

## 5. Experiment 4 — learnability (distillation / fine-tuning)

*To be specified.*
