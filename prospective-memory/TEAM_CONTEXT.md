# Team Context

Updated: **2026-10-25**, America/Chicago. Start here when joining the project.
This page and the linked experiment summaries supersede older status prose.
They do not authorize new inference or change any experiment configuration.

GitHub publication: [repository](https://github.com/aamitssharma07/prospective-memory-methods).
Read [Publication Status](docs/PUBLICATION_STATUS.md) for the source upload,
full raw-result archive, restore workflow and the distinction between the
original research checkout and the credential-free publication copy.

## The Research Question

Can a plug-and-play prospective-memory helper improve an existing agent's
ability to remember an instruction and act when its future condition arrives?
Our proposed method is **RGPM: Relevance-Grounded Prospective Memory**. Earlier
implementation documents also use **SBPM**, Source-Bound Prospective Memory.

```text
Experiment 1                 Experiment 2                   Experiment 3
Base agent / PMBench        Existing memory approaches     Our RGPM helper
controls                    Mem0, A-Mem, PIS-RAG, PIS       + the main agent
          \________________________|________________________/
                                   |
                      Compare the same main model:
                      F1, precision, recall, failures,
                      cross-day/updates, tokens and time
```

## Read in This Order

1. [Results: base vs PIS vs RGPM, plus all three matrices](docs/experiments/results/RESULTS.md).
2. [Experiment 1 context](docs/experiments/exp1_context.md): what our base controls mean.
3. [Experiment 2 context](docs/experiments/exp2_context.md): author-release memory methods.
4. [Experiment 3 context](docs/experiments/exp3_rgpm_context.md): RGPM steps, versions, current results and gaps.
5. [GitHub handoff and publishing checks](docs/GITHUB_HANDOFF.md): secrets, nested repos and raw data.

No cluster access or API key is needed to read these pages or the committed
[CSV/JSON snapshot](docs/experiments/results/). Regenerating it requires access
to the original run artifacts, but never model calls.

## Verified State

| Experiment | Coverage | Current Interpretation |
| --- | --- | --- |
| 1 | 11 models x 4 controls = 44 complete runs | Current SGLang/hosted baseline reproduction, not the historical vLLM table |
| 2 | 11 models x 4 memory methods = 44 complete runs | Author-release reproduction; its workspace is a sibling repository |
| 3 | Original 8 main models x 4 Qwen helpers = 32 complete runs | Updated v15 method; some serving/checkpoint mismatches require separate results |
| 3 consistency | 9/11 reruns complete; 2 failed before PMBench | Prefer these prespecified serving/checkpoint corrections, not whichever F1 is higher |
| 3 GPT | 2/4 helper combinations complete | 1.7B: 77.33% F1; 32B: 85.71%; 4B/8B unfinished after credit exhaustion |

The October 25 midnight credit-gated retry stopped without experiment calls
because credits were still unavailable. The 4B-helper benchmark remains
resumable at 73/80 steps. No automatic credit retry is currently scheduled by
that one-shot job. The two BF16 Ministral + 32B-helper consistency attempts
failed with helper connection errors during their saved serving probes; they
are not full-dataset results or zero-F1 observations.

## Where the Evidence Lives

| Item | Location |
| --- | --- |
| Git-friendly result tables | [docs/experiments/results/RESULTS.md](docs/experiments/results/RESULTS.md) |
| Row-level numbers, status, source locations and hashes | [docs/experiments/results/snapshot.json](docs/experiments/results/snapshot.json) |
| Experiment 1 source and raw bundles | `PMBench/`, especially `PMBench/runs/core-four/` |
| Experiment 2 source and raw bundles | Sibling `../prospective-memory-reaearch/`, especially `data/PMBench/runs/` |
| Experiment 3 runtime and analyses | [experiments/rgpm/](experiments/rgpm/) |
| Shared memory implementation | [prospective_memory/](prospective_memory/) |
| Historical development narrative | [docs/project_context.md](docs/project_context.md), [docs/results_ledger.md](docs/results_ledger.md) |

Raw bundles are not embedded in the small team snapshot or ordinary Git tree.
All 84,259 retained raw files are available in the
[full-results Release](https://github.com/aamitssharma07/prospective-memory-methods/releases/tag/research-snapshot-2026-10-25).
The published repository's `results/README.md` and `results/restore_results.py`
provide checksum-verified group downloads and restoration to the original
sibling-workspace layout. No model calls are needed for failure-level analysis.
The publication vendors both workspaces' source; the original research setup
used separate repositories. See [Publication Status](docs/PUBLICATION_STATUS.md).

## Reading Results Correctly

- **Base** means Experiment 1 `single_baseline`, not its best-performing control.
- **PIS** means Experiment 2 author-release PIS, not our historical `pis` reimplementation.
- **F1** is set micro-F1: `2*TP / (2*TP + FP + FN)`. Tables show percentages.
- **N/A** means unrun, interrupted, excluded or failed before completion. Read the status; it does not mean zero.
- A completed run can contain model/context errors. Those empty/incorrect predictions remain scored.
- BF16 and FP8 checkpoints, different serving capacities and different providers are not matched conditions.
- GPT baselines use OpenRouter; current RGPM GPT runs use direct OpenAI. Preserve that distinction in reports.
- These are retained development traces on one repeatedly inspected scenario, not a held-out benchmark or statistical significance claim.
- Earlier repeat spread is specific to its tested setup, not a universal four-point significance threshold.
- RGPM does not beat every comparator/pair. Report regressions, missing cells, cost and latency as well as wins.

## Updating This Handoff

On the research machine, after new bundles finish:

```bash
python harness/export_team_context.py --as-of YYYY-MM-DD
python -m unittest discover -s harness -p 'test_team_context.py'
```

The exporter reads saved results only. It validates the 44-cell matrices,
integer score counts and completion status, preserves the original and rerun
cohorts separately, and refuses ambiguous Experiment 2 candidate selection.
Update the three context pages when scope or status changes. Do not rewrite
historical findings to make them match the latest results.
