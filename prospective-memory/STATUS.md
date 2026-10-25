# Current Team Handoff

**Updated: 2026-10-25, America/Chicago.** Start with
[TEAM_CONTEXT.md](TEAM_CONTEXT.md) and the artifact-derived
[results snapshot](docs/experiments/results/RESULTS.md).

| Experiment | Verified State |
| --- | --- |
| 1: PMBench controls | 11 models x 4 controls, 44 complete runs |
| 2: Author-release memory methods | 11 models x 4 methods, 44 complete runs in the sibling workspace |
| 3: RGPM v15 | Original 32 local pairs complete; 9/11 consistency reruns complete, 2 failed serving probes |
| 3: GPT follow-up | 1.7B/32B helpers complete; 4B interrupted at 73/80, 8B interrupted in smoke; midnight credit gate blocked |

See [publishing checks](docs/GITHUB_HANDOFF.md) before pushing. The root `.env`
is tracked; ignoring it does not remove it from the index/history. No new model
runs, staging, commits or pushes are authorized by these context files.

## Archived October 2 Snapshot

The remainder is preserved historical context, not current status. Its run
counts, pending jobs, timing estimates, strict smoke policy and immediate-next-
step instructions are superseded by the dated pages linked above.

**Updated: 2026-10-02.** This is the live entry point. If you are an assistant or
a collaborator picking this up cold, read this file, then
`docs/EXPERIMENT_PLAN.md`. Keep this file current: see "Maintaining this file".

**Numbers come from run artifacts, never from prose.** Read `metrics.json` /
`*.score.md`, and confirm from `manifest.json` that model, scenario hash, token
limit and backend match across the arms you compare. A stale sentence in a
markdown file has already produced a wrong comparator once.

## What the project is

Prospective memory in language-model agents: holding a deferred intention and
acting when its future cue arrives, while occupied with unrelated work. The
benchmark is PM-Bench (7 simulated days, 80 steps, 81 scored task occurrences).

Our method is **SBPM** (Source-Bound Prospective Memory), in
`prospective_memory/method/`. It is a helper model running beside an unmodified
action agent: lifecycle logic in code, scoped language work in the model.

## Four experiments

| # | What | State |
|---|---|---|
| 1 | PM-Bench baselines across models | **mostly done** — results in `PMBench/runs/`; 3 models missing |
| 2 | PIS + memory baselines | **done** — 9 models x 4 methods, **sibling repo** (see below) |
| 3 | SBPM / RGPM (ours) | **4 complete runs + 1 scored ablation pending**; best 52.69% |
| 4 | Learnability (distil a small helper) | not started |

Experiment 2 lives in a **separate repository**, `../prospective-memory-reaearch/`
(note the spelling), with runs under `data/PMBench/runs/`. Searching only this
repo makes it look unrun. Experiment 1's live results moved to `PMBench/runs/`;
`harness/results/` was archived to
`experiments/rgpm/legacy_outputs_archived_20261001/`.

Experiment 3 runs, comparators and per-run analysis: `docs/results_ledger.md`
section "Experiment 3 on SGLang", plus `experiments/rgpm/IMPROVEMENT_LOG.md`.

Experiment 1's analysis is written up: `docs/experiments/exp1_task_taxonomy.md`
(what the categories are) and `docs/experiments/exp1_category_analysis.md`
(how 10 models score on each).

## Immediate next steps, in order

1. **Beat 52.69% with a complete Experiment 3 run.** Standing target and
   procedure in `experiments/rgpm/IMPROVEMENT_LOG.md`. A full run is 13-25 min
   on one H100 on partition `gpu`, so 3 repeats cost about an hour — the
   three-repeat rule is cheap here and there is no excuse for single traces.
2. **Decide whether Set-F1 can remain the headline.** Author PIS retains 4/7
   cross-day and 5/11 updates; no Experiment 3 run has exceeded 2/7 and 2/11
   except the one that selected 425 tasks. See the ledger's "Selection volume
   predicts retention" section. This is a framing decision, not a tuning one.
3. **Finish Experiment 1.** Missing runs: **Gemma-4-E2B**, **GPT-5.4**,
   **Claude Opus 4.6**, plus **Llama-3.3-70B rerun at bf16** (the existing one is
   4-bit, the only unmatched precision in the set). Then 3 repeats per cell.
   Llama-3.3-70B and Qwen2.5-72B are queued as Slurm `1502687` / `1502688` on
   `gpu-res-01`, blocked behind a 9-day job; do not expect them before ~Oct 6.
4. **Decide setup scope.** We hold 4 of PM-Bench's 8 setups (`single_baseline`
   plus three heartbeats). Missing: `todo_ledger`, `multi_baseline`,
   `multi_union_query`, `multi_majority_vote`. This multiplies the run count.

## Non-negotiable serving settings

Both are the difference between reproducing published numbers and being ~18
points off. Full commands in `experiments/README.md`.

- **Actor needs `--generation-config vllm`.** With `auto`, vLLM loads the
  checkpoint's own `generation_config.json` — for Qwen3 that is `do_sample true,
  temperature 0.6, top_k 20, top_p 0.95` — and the actor selects ~7 tasks per
  step instead of ~1. Qwen3-8B's baseline collapses 42.0% -> 24.3%.
- **Helper needs a whitespace-free JSON grammar**, via
  `python -m prospective_memory.serve`. Otherwise greedy decoding can emit
  separator runs until the token cap and discard finished answers.
- The actor cannot share the helper server: PM-Bench's action schema uses
  `maxItems`, which xgrammar cannot compile.

## Rules that protect the results

- **Fallback policy is always `empty`.** PM-Bench's shipped `ground_truth`
  policy substitutes the evaluator's due set when structured output stays
  invalid, so unparseable responses score as correct. 17 of 52 audited runs
  change under correction; `heartbeat_proactive` is where it concentrates.
- **Three repeats minimum.** Measured single-trace spread on *unchanged code* is
  **3.95 Set-F1 points**. Any gap under ~4 points is not interpretable.
- **Report four numbers, not one:** Set-F1, cross-day hits, update hits, false
  alarms per step. Set-F1 alone has ranked a task-spamming strategy above a
  memory one.
- **Never tune against PM-Bench.** It is the held-out test. Iterate on the frozen
  case fixtures in `prospective_memory/examples/`, then return here once.
- **One change per run.** Bundled edits have hidden regressions here before.
- **Never overwrite a run directory.** Preserve aborted attempts too.

## What must not be claimed yet

- Helper suites do not predict benchmark score. A variant that won every suite
  (trigger-roles 8/8 vs 3/8) scored *lower* on PM-Bench.
- Two different PIS numbers exist and are easy to confuse. The **42.9%** in the
  ledger's vLLM rows is our *paper-inspired reimplementation*. The authors' code
  has since been run in Experiment 2 and scores **33.2%** on Qwen3-8B. Quote the
  33.2% run for any comparison; neither supports a claim against their
  published 57.2%.
- Cross-day retention is unsolved, and worse than it looks: our only run that
  retained it selected 425 tasks. Retention currently tracks selection volume,
  not memory. Author PIS beats every Experiment 3 run on it.

## Where things are

```
benchmark/              PM-Bench, vendored upstream (own repo)
PMBench/                Experiment 1 — runner + runs/ (own repo)
harness/                shared runner and corrected scorer
prospective_memory/     baselines/ = PIS;  method/ = SBPM, ours
experiments/rgpm/       Experiment 3: runner, sbatch, reviews, runs/
docs/                   EXPERIMENT_PLAN.md, results_ledger.md (numbers live
                        here), current_work.md = ARCHIVE, not current
third_party/author_pis  the PIS authors' code (run in Experiment 2)
../prospective-memory-reaearch/   Experiment 2 — separate repo
```

Run outputs are git-ignored: an Experiment 3 run is ~535 MB and each run dir
carries its own `manifest.json` and `source/` copy. **Not in git — back them up.**

## Machine state

Slurm cluster, submit from `crest-l001`. Two GPU partitions:

- `gpu` — `crest-g002`, 2x H100, 1-day limit. **Experiment 3 runs here**:
  `sbatch experiments/rgpm/run_one_model.sbatch` (preflight, server, smoke,
  smoke gate, full run), 13-25 min end to end on one GPU.
- `gpu-res-01` — `crest-g001`, 4x H100, 10-day limit, heavily contended; a
  foreign job holds 2 GPUs until ~Oct 11. The 70B jobs are queued here.

Use `PMBench/.venv-sglang/bin/python` for Experiment 3; the system Python is 3.9
and cannot import this code's 3.10 union types.

Tests as of 2026-10-02, discovered from the repo root: `tests/` **443 pass**,
`experiments/rgpm/` **10 pass**, `harness/test_portable*.py` **33 pass**.
The older "525 pass" claim no longer holds: `harness/` as a whole is 84 tests
with **15 errors**, all from one cause.

**Known broken tooling.** `harness/summarize_author_pis.py` scrapes
`pm_bench.score_day` for the literal `if chosen_set == due_now:` and traces that
line. The scorer now reads `... and not invalid:` — our own strict-invalid fix —
so the scrape raises `StopIteration`, taking `report_source_bound_pair.py` with
it. Do **not** fix by just dropping the colon: the extra condition changes when
that line is reached, so invalid steps would stop triggering the tracer and audit
semantics would shift silently. No recorded result depends on it; the
Experiment 3 comparators were recomputed through `score_log`.

## Maintaining this file

Update it whenever any of the following changes, and keep it under ~120 lines by
moving detail into `docs/experiments/`:

- an experiment's state in the table above
- the immediate next steps
- a new non-negotiable setting or a new rule that protects results
- something that must not be claimed
- machine state, if servers are left running

Per-experiment detail belongs in `docs/experiments/<exp>.md`, written when that
experiment's code is written. Numbers belong in `docs/results_ledger.md`.
Historical narrative stays in `docs/current_work.md` and
`docs/project_context.md` — do not rewrite those to match the present, because
they record what was true when runs were executed.
