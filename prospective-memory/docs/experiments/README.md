# Experiment Context Index

Updated: **2026-10-25**. Start with [Team Context](../../TEAM_CONTEXT.md).

| Current Page | Contents |
| --- | --- |
| [Experiment 1](exp1_context.md) | PMBench controls: protocol, 44 completed runs, evidence locations |
| [Experiment 2](exp2_context.md) | Mem0, A-Mem, PIS-RAG, author PIS: 44 completed runs and sibling-repository boundary |
| [Experiment 3: RGPM](exp3_rgpm_context.md) | Proposed method, v15 sweep, consistency corrections, GPT status and limitations |
| [Results](results/RESULTS.md) | Base/PIS/RGPM comparison plus all three matrices |
| [Snapshot JSON](results/snapshot.json) | Row-level numbers, statuses, source paths and hashes |
| [GitHub handoff](../GITHUB_HANDOFF.md) | Secret handling, nested repos, raw-archive requirements |

CSV exports are [Experiment 1](results/experiment1.csv),
[Experiment 2](results/experiment2.csv), and [RGPM attempts](results/experiment3.csv).
They are readable in a plain clone without raw data or API access.

## Historical Analysis

One file per experiment, written when that experiment's code is written. Each is
self-contained: what was run, the exact command, the results, the findings, and
the caveats that limit what may be claimed.

| File | Experiment |
|---|---|
| `exp1_task_taxonomy.md` | PM-Bench task categories, one worked example each — read this first |
| `exp1_category_analysis.md` | Experiment 1 — per-category results for all 10 models |

The taxonomy/category files below describe the earlier analysis cohort, not
the finalized SGLang 44-run matrix. Do not lift their old baseline numbers into
current comparisons. Later work has the current pages above.

Historical planning notes:

- Experiment 2 — PIS baseline (authors' released code in `third_party/author_pis`,
  plus our paper-inspired `pis` arm)
- Experiment 3 — RGPM/SBPM, our method. Start at
  `experiments/rgpm/EXPERIMENT_CONTEXT.md`.
- Experiment 4 — learnability (distillation / fine-tuning of a small helper)

## Conventions

- **State the command.** Every file ends with a reproduce block that runs.
- **Validate against the benchmark's own scorer** where a metric is derived, and
  say so. Numbers that cannot be cross-checked are labelled as such.
- **Caveats are part of the result**, not an appendix: repeat count, precision,
  which setups were covered, and what the metric cannot distinguish.
- **Raw data lives outside these files.** Point at the CSV or run directory
  rather than pasting rows, so the analysis stays re-runnable.
