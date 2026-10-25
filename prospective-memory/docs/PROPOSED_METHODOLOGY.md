# Proposed methodology

Written 2026-09-23 from measured results. Every number here is traceable to a
run directory indexed in `docs/results_ledger.md`.

## 1. The method to propose

**Adopted: `sbpm` with span extraction.** PM-Bench Set-F1
**52.2%** (TP 42 / FP 38 / FN 39), 26.1 helper calls per step. Lifecycle logic
lives in code; the model does only scoped language work.

- **Registration**: layout-unit compilation — each item of a multi-item message
  is registered separately, with its text copied and its source restricted to
  the host's advertised list. This exists because a batch-registration failure
  once stored 1 of 10 requests from a combined daily plan.
- **Typed triggers**: weekday and clock gates are enforced in code, before any
  model call. They filtered 5,781 would-be assessments in one week.
- **Span extraction**: the action and the trigger condition are two verbatim
  spans selected from inside the request, so a prose announcement stores
  "Carry the prescription receipt" / "you notice the lab drop box" rather than
  the surrounding narration. Spans are substring-checked; anything else falls
  back to the whole unit, so no intention is lost.
- **Assessment**: per-intention, source-bound, with a static trigger projection
  that asks whether the *cue* has occurred and never whether the action is
  already done. An intention is judged only against its own trigger and its own
  watched sources. Evidence is cited by observation ID; code re-attaches text.
- **Decisions**: ACT / CHECK / WAIT. ACT requires cited evidence from a watched
  source; CHECK may name only a source the host advertises as queryable.
- **The store carries the competence, not the model.** Zhao & Wu show Gemma-2B
  going 4.2% -> 66.2% on a frozen store with no training.

### Frozen run configuration

Cheaper alternative: `sbpm_no_projection` with the same span fix reaches
48.3% at **9.2** calls per step (2.8x cheaper). It has identical TP and FN;
the adopted configuration buys 13 fewer false alarms. The Set-F1 gap between
them is inside the measured noise band, so choose on precision and cost, not F1.

```bash
# helper server (whitespace-free grammar is mandatory)
CUDA_VISIBLE_DEVICES=0 python -m prospective_memory.serve \
  --model Qwen/Qwen3-8B --dtype bfloat16 --max-model-len 32768 \
  --gpu-memory-utilization 0.85 --port 30002

# actor server: default backend; PM-Bench's own actor schema uses maxItems,
# which xgrammar rejects, so it cannot share the helper server
CUDA_VISIBLE_DEVICES=1 python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen3-8B --dtype bfloat16 --max-model-len 32768 \
  --gpu-memory-utilization 0.85 --port 30003

python harness/run_memory.py \
  --mode selective --memory-version portable --memory-policy sbpm_no_projection \
  --base-url http://127.0.0.1:30003/v1 --memory-base-url http://127.0.0.1:30002/v1 \
  --memory-max-tokens 4096 --memory-check-budget 1 --memory-query-handoff legacy \
  --memory-policy sbpm \
  --memory-projector-id '<model@revision;dtype;temperature;decoding;engine>' \
  --memory-projection-batch-size 4 --memory-extract-spans \
  --memory-skip-unevidenced --memory-reuse-stable-waits --memory-assess-batch-size 6 \
  --output <run dir>
```

The three cost flags are **adopted**: 27.3 -> 7.3 calls/step, 3.55M -> 1.89M
helper tokens, with no accuracy change detectable at current precision.

## 2. Evaluation protocol

1. **Three runs minimum per configuration.** Report mean and range, never a
   point estimate. Measured single-trace spread on unchanged code is **3.95
   Set-F1 points** (52.44 / 52.44 / 48.48). The server is not bit-deterministic
   at temperature 0.
2. **Paired baseline**, run on the same servers on the same day, with the
   action agent unchanged between conditions. This follows Wu et al.
3. **Report four numbers, not one**: Set-F1, cross-day hit rate, update hit
   rate, and false alarms per step. Set-F1 alone rated two runs identical while
   one was strictly better on cross-day, which is the capability under study.
4. **Report cost alongside accuracy**: helper calls per step and helper tokens.
   Both papers use ~1 memory call per step; report where we sit against that.
5. **One change per run.** Bundled edits hid three regressions on 2026-09-17.
6. **Preserve every run**, including aborted ones, with source hashes.

## 3. What to drop

- **`sbpm`** — rejected by its own predeclared rule (below V3 on
  both F1 and recall). Keep as a reported negative result.
- **Assessment concurrency** (`--memory-assess-workers`) — moves wall clock
  only, no accuracy benefit. Leave at 1.
- **Helper suites as a selection criterion.** V5 won every suite (smoke 10/10,
  transfer 10/10, trigger-roles 8/8 vs V3's 3/8) and still lost the benchmark.
  Suites are diagnostics, not proxies.

## 3b. Cross-day is an open limitation, not a solved problem

Adopted configuration: **1/7 cross-day**, against PIS's 3/7 and the no-memory
baseline's 7/7. Three scaffolding fixes were each verified working without
moving the metric: the implicit weekday gate, prose span extraction, and the
trigger-role assessor. State this openly as a limitation. The next test is
whether it is a model limit: run the same scaffold on an agentic-tuned
checkpoint (Qwen3.5-4B) and see whether cross-day moves.

## 4. Must be resolved before any publication claim

1. **The baseline discrepancy.** Historical 42.0% vs matched fresh 24.3%
   (78 TP / 484 FP — the unaided actor selects ~6 tasks per step). Zhao & Wu
   publish 39.8% for Qwen3-8B with no store, which agrees with 42.0% and not
   with 24.3%, so the fresh baseline is the outlier. Only the actor differs:
   diff its prompts and selection traces.
2. **Reproduce the published 57.2%** for Qwen3-8B + PIS. We sit at 48.5-52.4%
   on the same backbone. Until this closes, our scaffold is a confound in every
   cross-model comparison.
3. **The calendar-clause guard bug** — an unrelated verb ("drop off an item")
   is read as dropping a weekday restriction. Active during every run to date.

## 5. Model strategy for the multi-model study

Neither paper varies the **memory** model with the action model fixed; Wu et al.
vary the action agent with a frontier memory agent, Zhao & Wu use one backbone
for both. **That cross is the open gap and matches our hypothesis.**

- Action agent: keep **Qwen3-8B** as the anchor (both papers publish it), add
  **Qwen3.5-4B** to show the agentic-tuning effect.
- Memory helper: go small — **Gemma-2B / Qwen3-4B class**. Zhao & Wu's evidence
  that a 2B model with a store beats an 8B without one is the case for a cheap
  monitor.
- Expect the untrained small memory model to be weak: their base Qwen3.5-27B
  memory *degraded* reward until SFT/GRPO. Treat that as the finding.

Sequence: fix (4.1) and (4.2) first, then the memory-model sweep at 3 runs per
cell. At 7.3 calls/step, three runs now cost less than one did before.
