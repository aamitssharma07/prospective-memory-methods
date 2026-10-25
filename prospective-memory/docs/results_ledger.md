# Results ledger

**Current three-experiment results (2026-10-25):** use the
[team snapshot](experiments/results/RESULTS.md),
[machine-readable provenance](experiments/results/snapshot.json), and
[RGPM context](experiments/exp3_rgpm_context.md). The ledger below is chronological
development history. Its opening Qwen3-8B/vLLM settings and adopted variants
are not the configuration or complete result set of the current v15 sweep.

Index of every completed live-model run. Each run directory holds its own
detail; this file is the single place to look up a number. All rows: Qwen3-8B
BF16, no quantization, vLLM 0.8.5.post1, temperature 0, actor max_tokens 768,
scenario `synthetic_week_v9.json` (`94a45937…`), empty actor fallback.

Verified from `metrics.json` / `manifest.json` on 2026-09-23.

## PM-Bench (80 steps, 81 due occurrences)

| Run (under `harness/memory_results/`) | Policy | TP | FP | FN | Set-F1 | Helper tok cap |
|---|---|---:|---:|---:|---:|---:|
| `…pis-source-bound-pair-20260922-01/candidate-v3-01` | **pis_source_bound_v3** | 43 | 40 | 38 | **52.4%** | 4096 |
| `…pis-source-bound-pair-20260922-01/candidate-v3-02-repro` | pis_source_bound_v3 (rerun, current tree) | 43 | 40 | 38 | **52.4%** | 4096 |
| `…pis-source-bound-pair-20260922-01/candidate-v5-01` | pis_trigger_fair_v5 | 40 | 40 | 41 | 49.7% | 4096 |
| `qwen3-8b-pis-triplet-20260922-03/pis` | pis | 62 | 146 | 19 | 42.9% | 4096 |
| `qwen3-8b-portable-20260918-02` | portable v7 | 41 | 71 | 40 | 42.5% | 1024 |
| `qwen3-8b-indexed-pair-memory-20260921-01` | indexed | 34 | 46 | 47 | 42.2% | 1536 |
| `qwen3-8b-selective-v2-20260911-01` | structured v2 | 33 | 47 | 48 | 41.0% | 2048 |
| `qwen3-8b-pis-triplet-20260922-03/pis_verified` | pis_verified | 55 | 138 | 26 | 40.1% | 4096 |
| `qwen3-8b-selective-20260911-02` | selective v1 | 30 | 50 | 51 | 37.3% | 2048 |
| **matched fresh baselines** (`…pair-…/baseline`, `matched-baseline-20260921-01`, `indexed-pair-baseline`, `pis-triplet-*/baseline`) | none | 78 | 484 | 3 | **24.3%** | — |
| `qwen3-8b-verified-20260921-01` | verified | 77 | 489 | 4 | 23.8% | 1024 |
| historical released trace | single baseline | 34 | 47 | 47 | **42.0%** | — |

Aborted, preserved, not results: `qwen3-8b-portable-20260918-01-ABORTED-actor-schema-400`
(actor schema rejected by xgrammar), `…pair-20260922-01/candidate` (batch
registration stored 1 of 10 requests; stopped deliberately at 28 cycles).

### The two baselines disagree by 18 points — resolve before publishing

The historical baseline is 34/47/47 = 42.0%. Every fresh baseline run on the
matched two-server setup is 78/484/3 = 24.3%: near-perfect recall (78 of 81)
bought by selecting roughly six tasks per step. These are the same scenario,
the same actor token budget and the same empty fallback, so the actor is
behaving completely differently from the released trace and the difference is
not yet explained. **Which baseline is the correct comparator is an open
question**, and no improvement claim should be written up until it is settled.

`candidate-v3-01` at 52.4% exceeds both (+28.1 over the matched baseline, +10.4
over the historical one), so the direction of the result does not depend on
which is chosen — but the margin does. Single traces throughout; no repetitions,
no effect size. Helper cost is not matched across rows (1024-4096 token caps).

### Reproducibility: the working tree is V5, not V3

Checked 2026-09-23 by comparing each run's `manifest.json` `source_sha256`
against the files on disk.

| Run | Files hashed at launch | Match current tree |
|---|---:|---|
| `candidate-v5-01` (49.7%) | 16 | **16/16 — the tree is exactly this run** |
| `candidate-v3-01` (52.4%) | 11 | 8/11; 3 changed since |

The three files that drifted after the 52.4% run are shared runtime, changed
during V5 development: `harness/run_memory.py` (new policy
registrations, additive), `prospective_memory/adapters/pmbench.py` (adds
`_explicit_query_handoff`, a behavioural change in the shared adapter) and
`prospective_memory/baselines/pis_registration.py` (calendar guard wiring).

**Resolved 2026-09-23 by rerunning on the current tree** (`candidate-v3-02-repro`,
`--memory-query-handoff legacy`, which is the default and matches V3):
**Set-F1 52.44%, TP/FP/FN 43/40/38 — identical to the original.** The result
survives the drift; no restoration is needed to build on V3.

The identical score is aggregate coincidence, not determinism: the two runs chose
different tasks on **17 of 80 steps**, used 505 fewer helper calls and 550k fewer
tokens, and differ on late/miss/false_alarm/wrong_content and — importantly —
cross_day_hit 0 vs 2 and cross_day_miss 7 vs 5. **Set-F1 rates both runs equal
while the rerun is clearly better on the delayed cross-day triggers this project
exists to study.** Report cross-day and update counts alongside Set-F1.
Set-F1 variance across repeats is still unmeasured; every row here is one trace.
All 11 V3 files also remain preserved under `candidate-v3-01/source/`.

## ADOPTED configuration (2026-09-23)

`…pis-source-bound-pair-20260922-01/candidate-v5-02-spans` —
`pis_trigger_fair_v5` + `--memory-extract-spans` + the three cost flags.
**TP 42 / FP 38 / FN 39, Set-F1 52.2%, precision 52.5%, recall 51.9%,
26.1 helper calls/step, 3.17M tokens.**

| Method | TP | FP | FN | Set-F1 | cross-day | update | calls/step |
|---|---:|---:|---:|---:|---:|---:|---:|
| no memory | 78 | 484 | 3 | 24.3% | 7/7 | 9/11 | 0 |
| PIS (paper) | 62 | 146 | 19 | 42.9% | 3/7 | 6/11 | 24.4 |
| v3 original | 43 | 40 | 38 | 52.4% | 2/7 | 2/11 | 31.0 |
| v3 + spans | 42 | 51 | 39 | 48.3% | 2/7 | 2/11 | **9.2** |
| v5 (no spans) | 40 | 40 | 41 | 49.7% | 1/7 | 1/11 | 23.8 |
| **v5 + spans (adopted)** | 42 | **38** | 39 | **52.2%** | 1/7 | 3/11 | 26.1 |

Against `v3 + spans` the adopted run has identical TP and FN and 13 fewer false
alarms; that precision gain is the defensible difference. The 3.9-point Set-F1
gap is inside the ±4 noise band. `v3 + spans` remains the choice if cost
dominates: 2.8x fewer calls for the same recall.

**Cross-day remains unsolved (1/7).** Three scaffolding fixes were each verified
working at the mechanism level without moving it — implicit weekday gate
(5,589 → ~111 gate blocks), prose span extraction (6/7 cross-day intentions
correctly registered) and the trigger-role assessor (8/8 on that suite). Report
as a limitation; the next test is whether an agentic-tuned checkpoint moves it.

## PM-Bench single-trace variance measured (2026-09-23) — read this first

Three runs of **identical code and identical configuration**
(`pis_source_bound_v3`, serial, legacy handoff, 4096/1, same scenario hash):

| Run | TP | FP | FN | Set-F1 |
|---|---:|---:|---:|---:|
| `candidate-v3-01` | 43 | 40 | 38 | 52.44% |
| `candidate-v3-02-repro` | 43 | 40 | 38 | 52.44% |
| `candidate-v3-07-baseline3` | 40 | 44 | 41 | **48.48%** |

**Spread 3.95 points on unchanged code.** The two matching 52.44% scores were a
coincidence, not determinism: those runs already differed on 17 of 80 steps
internally. The underlying cause is that the server is not bit-deterministic at
temperature 0 — 80 of 265 byte-identical prompts in one run produced different
completions, because continuous batching changes reduction order.

**Every optimisation measured today falls inside that range**, so none of them
is distinguishable from noise:

| Variant | Set-F1 | calls/step | Mtok | Inside baseline range? |
|---|---:|---:|---:|---|
| baseline | 48.48-52.44 | 27.3 | 3.55 | — |
| parallel (x2 runs) | 49.70, 49.70 | 27.3 | 3.65 | yes |
| A+B | 48.59 | 13.2 | 2.28 | yes |
| **A+B+batch6** | **50.31** | **7.3** | **1.89** | yes |

Consequences, all of which apply retroactively to this file:

1. **Cost reductions are free at current precision.** `A+B+batch6` gives 3.7x
   fewer calls and 47% fewer tokens with no detectable accuracy change.
2. **Earlier single-trace conclusions in this ledger are unreliable.** Gaps
   smaller than ~4 points mean nothing. That includes portable 42.5% vs indexed
   42.2% vs structured v2 41.0%, and `pis` 42.9% vs `pis_verified` 40.1%.
3. **The headline claim survives but needs an interval.** V3 at 48.5-52.4%
   still exceeds the historical 42.0% baseline and the matched 24.3% one, but
   "52.4%" must not be quoted as a point estimate.
4. **Future comparisons need repeats.** A single trace cannot support any claim
   at this scale. Budget at least three runs per configuration, and report
   mean and range.

## Method comparison beyond Set-F1 (added 2026-09-23)

Same 80 steps, 81 due occurrences, 7 cross-day and 11 update occurrences.
`chosen` is total task selections made across the run.

| Method | TP | FP | F1 | Prec | Rec | cross-day hit/7 | update hit/11 | chosen | helper calls | helper Mtok |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline (no memory) | 78 | 484 | 24.3% | 13.9% | 96.3% | **7** | **9** | 562 | 0 | 0.00 |
| `pis` | 62 | 146 | 42.9% | 29.8% | 76.5% | 3 | 6 | 208 | 1,953 | 1.72 |
| `pis_verified` | 55 | 138 | 40.1% | 28.5% | 67.9% | 3 | 4 | — | 2,003 | 1.67 |
| `pis_source_bound_v3` | 43 | 40 | **52.4%** | 51.8% | 53.1% | 0-2 | 1-2 | 83 | 2,482-2,987 | 3.55-4.10 |
| `pis_trigger_fair_v5` | 40 | 40 | 49.7% | 50.0% | 49.4% | 1 | 1 | — | 1,904 | 2.99 |
| portable v7 | 41 | 71 | 42.5% | 36.6% | 50.6% | 2 | 2 | — | 211 | **0.40** |
| indexed | 34 | 46 | 42.2% | 42.5% | 42.0% | 2 | 4 | — | 318 | 0.60 |
| structured v2 | 33 | 47 | 41.0% | 41.2% | 40.7% | 1 | 1 | — | 218 | 0.73 |
| selective v1 | 30 | 50 | 37.3% | 37.5% | 37.0% | 1 | 6 | — | 188 | 0.28 |

### Three results the F1 ranking hides

**1. No memory method beats the baseline on cross-day or update retention.**
The unaided actor catches **7/7 cross-day and 9/11 update** occurrences; the
best-F1 method catches **0-2 and 1-2**. Cross-day triggers are the delayed,
later-channel cues this project exists to study. The baseline achieves this
trivially by selecting 562 tasks (about 6 per step) rather than by remembering,
so it is not evidence that no memory is better — but it does mean **every memory
method trades away the capability the project is about, and the headline metric
does not show it.** Any prospective-memory claim must report cross-day and
update counts, not Set-F1 alone.

**2. Among memory methods, higher F1 means worse cross-day.** `pis` has the
lowest precision (29.8%) and a lower F1 (42.9%) yet retains the most cross-day
(3/7) and updates (6/11) of any memory method. `pis_source_bound_v3` wins F1 by
becoming conservative — 83 selections against `pis`'s 208 — and loses most of
its cross-day and update retention doing so. **Optimising Set-F1 has been
selecting against the research target.**

**3. The cost trend is backwards for the project's own hypothesis.** Portable v7
scores 42.5% for 0.40M helper tokens and 211 calls. `pis_source_bound_v3` scores
52.4% for 3.55-4.10M tokens and 2,482-2,987 calls: roughly **9x the tokens and
12x the calls for +10 F1 points**, because it assesses each pending intention in
its own sequential call. The stated long-term hypothesis is a *cheap* monitor
escalating selected cases to a stronger model; the current direction is the
opposite. Cost-matched comparison remains unimplemented and now matters.

## Helper suites (not PM-Bench; frozen cases, scorer-only labels)

| Suite | Cases | pis_source_bound (v2) | pis_source_bound_v3 | pis_trigger_fair_v5 |
|---|---:|---|---|---|
| Original smoke (development) | 10 | 10/10 | 10/10 | 10/10 |
| Independent transfer | 10 | 10/10 | 10/10 | 10/10 |
| Batch registration | 5 | 1/5 | 4/5 | 4/5 |
| Trigger roles | 8 | — | 3/8 | **8/8** |

Batch registration was added after the aborted candidate revealed that combined
daily plans collapsed into a single record; it requires one correct record per
request and is why v2 scores 1/5 there despite passing both 10-case suites.
Trigger roles separates "the cue occurred" from "the action is already done".

**v5 wins every helper suite but loses on PM-Bench (49.7% vs 52.4%).** Helper
suite performance is therefore not a reliable predictor of benchmark score, and
suite results must not be reported as improvements.

## Earlier semantic diagnostic (10 cases, 30 ticks, 9 expected ACTs)

Fixture `semantic_cases_v1.json`, identical `cases_sha256` across rows.
Development set; v4-v7 were tuned against its known failures.

| Run (under `prospective_memory/results/`) | Change | TP | FP | FN | F1 |
|---|---|---:|---:|---:|---:|
| `qwen3-8b-semantic-v7-source-20260918-01` | source list re-anchored | 9 | 1 | 0 | 94.7% |
| `qwen3-8b-semantic-v6-quote-20260918-01` | stored quote hidden from compiler | 8 | 2 | 1 | 84.2% |
| `qwen3-8b-semantic-v5-cancel-20260918-01` | cancellation wording (no effect) | 8 | 3 | 1 | 80.0% |
| `qwen3-8b-semantic-v4-check-20260918-01` | CHECK paragraph narrowed | 8 | 3 | 1 | 80.0% |
| `qwen3-8b-semantic-v3-20260918-01` | structured output repaired | 6 | 3 | 3 | 66.7% |
| `qwen3-8b-semantic-v2-refined-20260917-01` | bundled refinements | 6 | 2 | 3 | 70.6%\* |
| `qwen3-8b-semantic-v1-20260911-01` | first live run | 7 | 1 | 2 | 82.4%\* |

\* Contaminated: 17 (Sep 11) and 8 (Sep 17) assessments never decoded and were
scored as correct silence. Compare v7 against v3, the first clean run.

## Established root causes

1. **Whitespace decode loop.** Schemas carried `maxItems`; xgrammar cannot
   compile it; under `auto` vLLM fell back to a whitespace-permitting backend;
   greedy decoding then looped on newlines to the token cap. Fixed by dropping
   `maxItems` from wire schemas (bound kept in `llm._rows`) and serving with
   `xgrammar:disable-any-whitespace` via `prospective_memory/serve.py`.
   `guidance:disable-any-whitespace` returns empty decisions — do not use.
   PM-Bench's own actor schema also carries `maxItems`, so the actor must run on
   a separate default-backend server (`--base-url` vs `--memory-base-url`).
2. The assessor was never told which sources were queryable.
3. The compiler copied the stored `evidence_quote` into cancellations; hiding
   the field fixed what prompt instruction could not.
4. **Calendar-clause guard bug** (open): an unrelated verb such as "drop off an
   item" is read as dropping a weekday restriction. Confirmed with a synthetic
   example; diagnosis in `results/calendar_guard_diagnosis_20260923.md`.
   Present in `candidate-v3-01`, so that 52.4% was scored with the bug active.

## Policy renaming (2026-09-25)

Code now uses SBPM (Source-Bound Prospective Memory) names. Historical records
in this file, `current_work.md`, `project_context.md` and `docs/dev_protocols/`
keep the names those runs were actually executed under, so the record is not
falsified. Mapping:

| Old policy string | New | Role |
|---|---|---|
| `pis_trigger_fair_v5` | **`sbpm`** | **adopted method** |
| `pis_trigger_projection_v4` | `sbpm_no_arbiter` | ablation: no fair check arbitration |
| `pis_source_bound_v3` | `sbpm_no_projection` | ablation: no static trigger projection |
| `pis_source_bound_v2` / `pis_source_bound` | `sbpm_minimal` | ablation: source-bound assessment only |
| `pis` | `pis` | unchanged — the PIS baseline |

## Experiment 3 on SGLang (2026-10-01 / 02) — a separate runtime from everything above

Every row above ran on **vLLM 0.8.5.post1** through `harness/memory_results/`,
now archived under `experiments/rgpm/legacy_outputs_archived_20261001/`. The runs
below are a different runtime and a different runner: **SGLang 0.5.20**, BF16,
`policy=sbpm`, `extract_spans=True`, actor and helper both Qwen3-8B,
max_tokens 768, temperature 0, fail-closed empty fallback, scenario
`synthetic_week_v9.json` (`94a45937…`), checkpoint `b968826d…`. Do not compare
these numbers against the vLLM rows as if the runtime were held constant.

Run directories: `experiments/rgpm/runs/synthetic_week_v9/qwen3-8b/sbpm/<run_id>`.
Slurm job id is the run id suffix. All on partition `gpu`, 1x H100, 13-25 min.

| Run | actor_guidance | handoff | TP | FP | FN | Set-F1 | cross-day | update | chosen | helper calls | invalid |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `qwen3-8b-1503009` | (none) | legacy | 44 | 42 | 37 | **52.69%** | 2/7 | 2/11 | 86 | 2,189 | 0 |
| `qwen3-8b-1503073` | (none) | legacy | 73 | 352 | 8 | 28.85% | **7/7** | **8/11** | 425 | — | 0 |
| `qwen3-8b-1503118` | readiness_v1 | explicit | 36 | 44 | 45 | 44.72% | 2/7 | 2/11 | 80 | 1,498 | 0 |
| `qwen3-8b-1503127` | balanced_v2 | explicit | — | — | — | **no score** | — | — | — | — | — |
| `qwen3-8b-1503140` | balanced_v2 | explicit | 37 | 38 | 44 | 47.44% | 1/7 | 1/11 | 75 | 2,932 | 4 |
| `qwen3-8b-1503190` | **none** | explicit | 34 | 46 | 47 | 42.24% | 2/7 | 0/11 | 80 | — | 0 |
| `qwen3-8b-1505890` | none | legacy | 42 | 42 | 39 | 50.91% | 2/7 | 2/11 | 84 | — | 0 |
| `qwen3-8b-1505891` | none | legacy | 41 | 42 | 40 | 50.00% | 1/7 | 1/11 | 83 | — | 0 |
| `qwen3-8b-1505900` | none | legacy | 40 | 42 | 41 | 49.08% | 2/7 | 1/11 | 82 | — | 0 |
| `qwen3-8b-1505903` | none | legacy | 37 | 42 | 44 | 46.25% | 1/7 | 2/11 | 79 | — | 1 |

`1505890` = HEAD + the 21 prompt clarifications from
`helper-prompt-candidate-20261002` (the full diff minus the clock-gate removal).
`1505891` = HEAD + the restatement guard (branch `restatement-guard-20261002`).
`1505900` = HEAD + `query_budget=2`. All three are single changes off the
triple-verified `1503193` baseline, all three scored **below** it, and all three
sit inside the churn band — none is evidence against its own change.

Isolating the 28.85% collapse: HEAD 52.69% -> clarifications only 50.91% ->
clarifications + clock-gate removal 28.85%. **The clock-gate removal is the
catastrophic component**; the clarifications cost ~1.8 points.

`1503127` failed at 58 of 80 committed steps (actor looped on clock queries).
Artifacts preserved; **it has no benchmark score and must not be cited as a
complete run.** It produced the 12-query recovery policy in
`experiments/rgpm/QUERY_RECOVERY_20261002.md`, which is why `1503140` records 4
invalid steps instead of aborting — that count is the policy working as designed,
not a new defect. The underlying actor stall is still unexplained.

**`1503009` remains the best complete Experiment 3 result.** Neither guided run
beat it. Per-run analysis: `FAILURE_REVIEW_QWEN3_8B.md` (1503009),
`PRECISION_REVIEW_20261002.md` (1503073), `BALANCED_REVIEW_20261002.md` (1503118),
and `IMPROVEMENT_LOG.md` for the iteration procedure and the standing target.

### Comparators, recomputed (see `IMPROVEMENT_LOG.md`)

Recomputed with `benchmark/sim/pm_bench.py score_log(strict_invalid=True)`,
trajectory metadata records excluded. Both have 80 scored steps, zero fallbacks.

| Method | TP | FP | FN | Set-F1 | cross-day | update |
|---|---:|---:|---:|---:|---:|---:|
| Base (`single_baseline`, Qwen3-8B) | 34 | 47 | 47 | 41.98% | 0/7 | 1/11 |
| Base + author PIS (Experiment 2) | 47 | 155 | 34 | 33.22% | **4/7** | **5/11** |

The author-PIS trajectory lives in the **sibling repository**:
`../prospective-memory-reaearch/data/PMBench/runs/exp2_anchor_qwen3_8b/results/Qwen-Qwen3-8B/intention-Qwen-Qwen3-8B-v9-20260930-170352/`.
Experiment 2's full matrix is 9 models x 4 methods (Mem0, A-Mem, PIS-RAG, PIS);
Qwen3-8B scores there are Mem0 27.5%, A-Mem 25.1%, PIS-RAG 31.7%, PIS 33.2%.

These are **historical comparisons with differing runtime configurations, not
controlled method-only ablations.** The development target stays the best
complete Experiment 3 run, not the base or PIS number.

### Query uptake is set by `query_handoff`, not by actor guidance (2026-10-02)

`1503190` is a **clean one-variable ablation** of `1503140`: only
`experiments/rgpm/{adapter,run}.py` differ, only `actor_guidance` changes in the
manifest, identical scenario hash and checkpoint.

| Run | handoff | guidance | Set-F1 | **state queries** | chosen |
|---|---|---|---:|---:|---:|
| `1503009` | legacy | none | **52.69%** | **104** | 86 |
| `1503073` | legacy | none | 28.85% | 99 | 425 |
| `1503118` | explicit | readiness_v1 | 44.72% | 26 | 80 |
| `1503140` | explicit | balanced_v2 | 47.44% | 141 | 75 |
| `1503190` | explicit | **none** | 42.24% | **0** | 80 |

With the explicit handoff and no actor guidance the actor issues **zero** state
queries across all 80 steps and ignores every helper CHECK, even though the base
adapter still tells it how to query. The explicit handoff renders queries as
`optional_query_actions ... (advisory, not executed)`, and the actor treats that
as optional. The verbose actor guidance exists to undo this.

**The legacy handoff gets 104 queries with no actor guidance at all.** So query
uptake does not require host prompt surgery; it requires not framing the request
as advisory. The guidance branch (`readiness_v1`, `balanced_v2`) has been
compensating for a self-inflicted regression, and never beat `1503009`.

Side effect: the `actor_query_limit` livelock vanished (4 invalid steps -> 0)
because an actor that never queries cannot loop on queries. That is not a fix.

### The best run is reproducible from git HEAD; every later run is not

`1503009` ran the **committed** versions of four method files. `1503073` and
every run after it carry an **uncommitted 26-line addition** to the same four:

```
prospective_memory/method/projection_cache.py  +5
prospective_memory/method/registration.py     +13
prospective_memory/method/source_bound_v3.py   +1
prospective_memory/method/trigger_engine.py    +7
```

Verified by `source_sha256`: HEAD matches `1503009` exactly for all four, and
the working tree matches `1503073`/`1503140`/`1503190` exactly. Config fields
between `1503009` and `1503073` are **identical** — the only difference is this
diff. It is the "First candidate changes" list from `FAILURE_REVIEW_QWEN3_8B.md`,
almost entirely added helper-prompt sentences.

That diff coincides with Set-F1 **52.69% -> 28.85%** and selections **86 -> 425**.
`IMPROVEMENT_LOG.md` already describes `1503073` as "an overly permissive
revision", so the regression was noticed — but the response was to add actor
guidance, and **the method change has never been reverted or retested.** Four
runs of host-side tuning have been spent clawing back from it, peaking at 47.44%.

**Measured 2026-10-02 (`1503193`, `1503194`, `1503195`):** method files reverted
to HEAD (branch `helper-prompt-candidate-20261002` holds the 45-line diff),
`legacy` handoff, no actor guidance, three repeats. **All three are
byte-identical to `1503009` and to each other** — same `trajectory.jsonl`
SHA-256, same TP/FP/FN (44/42/37), same Set-F1 (52.69%), same chosen (86),
same cross-day/update (2/7, 2/11). Spread 0.00 points, not ~3.95.

The three repeats are the **same code and config** run three times — the
"3 repeats minimum" protocol, not three different configurations. They test
this one cell's reproducibility only; they say nothing about whether
`1503118`/`1503140`/`1503190` would replicate if rerun.

Mechanism, not luck: every job gets its own **private SGLang server**, nothing
else's traffic ever reaches it, and `assess_batch_size` /
`compile_batch_size` / `projection_batch_size` are all **1** with no worker
concurrency — every request arrives alone. The documented 3.95-point spread
was attributed to continuous batching changing reduction order, which requires
multiple requests sharing a batch. At batch size 1 that mechanism cannot occur.
**This is determinism from batch-size-1 serial execution, not a general
property of the method** — turning on `--memory-assess-batch-size N` or
`--memory-assess-workers N` (method/README.md's cost controls) reintroduces
the exact condition that caused the original spread, and any run using them
needs its own repeats, not an inherited assumption of zero variance.

52.69% is confirmed for this exact configuration, not a single lucky trace, and
this is simultaneously the best-scoring and least host-coupled setup measured
so far.

**Next:** bisect the 45-line diff on the branch to find which lines caused
28.85% to find the specific regression, now that the floor it regressed from is
solid.

### Determinism is not stability: ~3 points of chaotic churn per code change

Three variants on HEAD, all `legacy` handoff, no actor guidance, one variable each:

| Run | Variant | Set-F1 | TP | FP | FN | cross-day | update |
|---|---|---:|---:|---:|---:|---:|---:|
| `1503193/94/95` | HEAD (baseline, x3 identical) | **52.69%** | 44 | 42 | 37 | 2/7 | 2/11 |
| `1505890` | + the 21 prompt clarifications | 50.91% | 42 | 42 | 39 | 2/7 | 2/11 |
| `1505891` | + restatement guard (code, 35 lines) | 50.00% | 41 | 42 | 40 | 1/7 | 1/11 |

**The restatement guard worked exactly as designed and still lost 2.69 points.**
It fired 4 times, cut intentions 66 -> 60 and narration-style actions 9 -> 4.
Its four target tasks were **completely unaffected** —
`check_transit_times_1_d5` hit->hit, `check_lab_portal_2_d7` hit->hit,
`check_in_manager_1_d2` hit->hit, `confirm_pickup_window_1_d4` miss->miss. The
suppressed records were genuinely redundant, exactly as intended, and FP did not
move (42 in every variant).

The -3 TP came from **nine unrelated tasks on other days** (Saturday, Sunday,
Tuesday, Wednesday): 2 improved, 5 degraded, 2 shifted late/miss. Cause: the
entire pending-intentions list is serialised into every `classify_unit` and
`assess` prompt, so removing any record perturbs the context of every later
model call and reshuffles unrelated decisions.

**Consequence for the protocol.** Repeats measure run-to-run variance, which is
**zero** here (byte-identical trajectories). They do *not* measure sensitivity
to perturbation, which is roughly **+/-3 Set-F1 points for any change touching
the pending list**. So repeats of one scenario give no information about whether
a code change helped, and a 2-3 point difference between two variants on this
scenario **is not attributable to the change**. Evaluating a change of this size
requires **multiple scenarios**, not repeats of `synthetic_week_v9`. The three
rows above cannot distinguish a real regression from churn, and none of them
should be reported as evidence for or against the guard.

The guard itself is defensible on correctness grounds independent of score: it
removes duplicate untimed obligations that competed with their timed originals,
including one (`pm_000065`) that had been assigned all 12 sources and could draw
"evidence" from any channel. Kept in the tree with 4 regression tests.

### Hidden-channel detection is structural, not a bug (2026-10-02)

Baseline `1503193` scores **0 hits on 15 non-clock occurrences**, across every
hidden channel, while clock scores 19/24. Regular tasks 27/28 (96%), irregular
17/53 (32%) — 34 of 37 false negatives are irregular.

| Channel | mode | hits |
|---|---|---:|
| clock | snapshot | 19/24 |
| library_hold, appointment_portal, calendar | delta | 0/9 |
| email, course_portal | delta | 0/3 |
| bank_balance, shipment_status | snapshot | 0/3 |

**Two hypotheses tested and falsified.**

1. *Query budget.* `step_query_budget=2` is only **66% utilised** (105 of 160;
   45 steps used one query, 5 used none), so capacity was never the limit.
2. *Arbiter capacity.* `fair_checks.arbitrate` ranks priority sources first and
   keeps only `groups[:budget]`, converting the rest to WAIT. With
   `query_budget=1` clock wins the single slot on the first cycle of every step,
   so 75 hidden-channel CHECK requests became 20 queries. Raising it to 2
   (`1505900`) moved hidden-channel queries **20 -> 22**, hidden-channel hits
   **0/15 -> 0/15**, and *reduced* clock hits 19 -> 14 for **Set-F1 49.08%**.
   Offer capacity is not the constraint either.

`run.py` had never actually passed `query_budget`/`step_query_budget` to the
engine — it relied on constructor defaults that happened to match the recorded
manifest values. Now wired, with defaults preserved.

**The real mechanism.** Delta channels flip state in one step. Catching that
on time requires querying *that* channel in *that* step. Trace for
`library_hold`: ready at `d1_s10`; the actor queried it at `d1_s11`; the helper
then assessed correctly — *"The library notice says the hold is ready (e3), and
today is Monday. Both conditions are satisfied"*, `trigger_ready_now: true` —
and the actor acted at `d1_s11`. Scored **late**, no on-time credit. Ready
states reached the helper 47 times and were assessed correctly; the loss is
detection latency, not helper semantics and not observation delivery.

With ~2 queries per step over 7 hidden channels, on-time detection is
combinatorially unlikely. **This is the cost of evidence-bound action**: our
method must observe a flip before acting, so it cannot act on state it did not
happen to poll. Author PIS reaches 4/7 cross-day by selecting **202 tasks vs
our 86** — it fires speculatively and needs no observation. The 0/15 is
therefore not reachable by tuning budgets or prompts; it needs cross-step
retention of per-channel state (see below) or acceptance of the trade-off.

**Separate real defect, not the cause here.** `adapters/pmbench.py:300` applies
snapshot semantics to every channel:

```python
# A newer snapshot supersedes the old state from the same source.
self.current_observations = [i for i in self.current_observations if i.source != source]
```

Six of eleven channels are `delta` (`email`, `calendar`, `course_portal`,
`library_hold`, `reservation_waitlist`, `appointment_portal`). For those,
`(no updates)` (emitted at `benchmark/sim/pm_bench.py:109`, and only by delta
channels — snapshot channels always return a value) means "nothing new since
the last read", not "the observed state is void". It currently erases a
previously observed flip within a step. Worth fixing for correctness; it does
not explain the 15 occurrences, since ready states did reach the helper.

### The actor has a fixed error rate the memory layer cannot shift (2026-10-02)

Five single-variable interventions off the triple-verified `1503193` baseline,
all `legacy` handoff, no actor guidance:

| Run | Intervention | TP | FP | FN | Set-F1 |
|---|---|---:|---:|---:|---:|
| `1503193` | none (baseline) | **44** | 42 | 37 | **52.69%** |
| `1505890` | +21 prompt clarifications | 42 | 42 | 39 | 50.91% |
| `1505891` | +restatement guard | 41 | 42 | 40 | 50.00% |
| `1505900` | `query_budget=2` | 40 | 42 | 41 | 49.08% |
| `1505903` | +gate reporting (`--report-gates`) | 37 | 42 | 44 | 46.25% |

**FP is 42 in all five. TP absorbs every bit of the variation.** No intervention
touched the false-positive count; each one cost true positives instead.

`1505903` targeted the FPs directly. 36% of them were two clock-gated daily
medications (`asthma_1100` x8, `antibiotic_dinner` x5, `asthma_2100` x2) firing
at the wrong time, while the helper correctly held them — `pm_000002` logged
**174 WAITs against 7 ACTs**, the engine computing `now != due` every time. WAIT
decisions are withheld from the actor by design, so it never learned this. The
run surfaced only the two *code-computed* WAIT reasons ("Outside explicit clock
gate", "Outside explicit weekday gate") — deterministic arithmetic, not model
opinion, so both existing WAIT-withholding contract tests still pass unchanged.
Result: targeted FPs reshuffled (`asthma_1100` 8->4, `calendar_call_move_d2`
4->1) while others rose to replace them (`asthma_2100` 2->4, `antibiotic_dinner`
5->6). **Total FP: 42 -> 42.** TP fell 44 -> 37.

**Why FP is pinned at 42: it is a coincidence of composition, not a fixed set.**
Only **5 of the 42** FP selections are shared across all five runs; the union
over the five runs is **100 distinct (day, step, task) false positives**. The
actor makes ~42 wrong selections regardless of the intervention, but *which*
ones vary almost completely. Prompt size does not explain the TP loss either:
`1505890` and `1505900` had **smaller** median actor prompts than baseline
(12,822 and 12,876 vs 12,952 tokens) and still lost TP; only `1505903` was
clearly larger (14,008) and it was the worst.

**Conclusion.** The false-positive rate is a property of the actor, not of the
memory layer, and advice cannot move it — five interventions reshuffled errors
without reducing them. Combined with the churn finding above, the memory layer's
reachable influence on this scenario appears exhausted at `1503193`. Further
adapter/arbiter/registration tuning is not a good use of runs.

The remaining levers are outside the memory layer:

1. **A stronger actor.** Experiment 2's matrix shows actor capability dominates
   everything measured here (GPT-5.4 70.6-80.8% vs Qwen3-8B 25.1-33.2%).
2. **Less actor discretion** — filtering or ranking the menu rather than
   advising. This collides directly with the design commitments in
   `prospective_memory/method/README.md` ("Decisions are proposals", "You retain
   the final action choice") and with `PRECISION_REVIEW_20261002.md` ("No action
   is filtered using task truth, and no menu entries are removed"). Changing it
   is a methodology decision, not a tuning step.

`1503193` (= `1503009`) at **52.69%** remains the best complete Experiment 3
result, and is reproducible byte-for-byte from git HEAD.

### Qwen3-32B: the architecture's contribution halves as the actor improves (2026-10-02)

`qwen3-32b-1505915`, SBPM on **Qwen3-32B** (actor and helper), identical config
to the verified `1503193` baseline — `legacy` handoff, no actor guidance,
`query_budget=1`, max_tokens 768, temperature 0, SGLang bf16, one H100,
76 minutes. Run dir `runs/synthetic_week_v9/qwen3-32b/sbpm/`.

| Arm (Qwen3-32B) | Set-F1 | TP | FP | FN | cross-day | update |
|---|---:|---:|---:|---:|---:|---:|
| `single_baseline` (control) | 50.70% | 36 | 25 | 45 | 0/7 | 1/11 |
| author PIS (Exp 2) | 47.20% | — | — | — | — | — |
| `todo_ledger` (competing method) | 54.14% | 36 | 16 | 45 | — | — |
| **SBPM (ours)** | **55.62%** | 47 | 41 | 34 | 2/7 | **4/11** |

**Gain over the matched no-memory control shrinks with actor capability:**

| Actor | base | SBPM | gain |
|---|---:|---:|---:|
| Qwen3-8B | 41.98% | 52.69% | **+10.71** |
| Qwen3-32B | 50.70% | 55.62% | **+4.92** |

Update retention is the best of any SBPM run (**4/11**, previous best 2/11).
Cross-day stays at 2/7, consistent with the structural observability limit above
— a stronger actor does not help where the state was never observed.

**Error attribution explains why Set-F1 gains compress.** Same matcher and
thresholds as the 8B analysis (stable 0.4-1.0):

| | Qwen3-8B | Qwen3-32B |
|---|---|---|
| FP from helper (proposed when not due) | 19 | **11** |
| FP from actor (selected unprompted) | 23 | **30** |
| FN from helper (never proposed) | 24 | 25 |
| FN from actor (ignored a proposal) | 13 | **9** |
| total | 79 (helper 43 / actor 36) | 75 (helper 36 / actor **39**) |

Scaling the model improved exactly what it should: helper false ACTs fell 19->11
and actor non-compliance fell 13->9. But **actor-initiated false positives rose
23->30** — the stronger actor selects more tasks on its own authority, ignoring
the layer. Those cancel, which is why total FP is ~41 on both models (42 vs 41)
despite a 4x larger actor. On 32B the actor is now the **majority** error source
(39 of 75), inverting the 8B split.

**Reading.** Part of what SBPM buys on a weak actor is compensation for weak
actor capability, and that headroom shrinks as the actor improves. The layer
still beats the control at both scales and beats every Exp 2 memory method by a
wide margin, but `+10.7 -> +4.9` is the trend to report honestly rather than
quoting the 8B figure alone. Against `todo_ledger` the margin is +1.48 on 32B
and +0.21 on 8B — both inside the churn band.

### Selection volume predicts retention almost perfectly

Across Experiment 3's own five runs, cross-day and update retention track the
number of task selections, not the method's sophistication:

| Run | chosen | Set-F1 | cross-day | update |
|---|---:|---:|---:|---:|
| `1503073` | 425 | 28.85% | 7/7 | 8/11 |
| `1503009` | 86 | 52.69% | 2/7 | 2/11 |
| `1503118` | 80 | 44.72% | 2/7 | 2/11 |
| `1503140` | 75 | 47.44% | 1/7 | 1/11 |

Monotonic in `chosen`. This reproduces, inside our own method, the effect the
"Three results the F1 ranking hides" section above found across methods: the
only Experiment 3 run that retained cross-day obligations is the one that
selected roughly five tasks per step. **No Experiment 3 run has yet shown
selective retention** — retention so far is a by-product of selection volume,
which is the capability claim the project needs and does not have.
Author PIS at 4/7 and 5/11 with 202 selections is currently the strongest
retention result from any method we have run, Experiment 3 included.
