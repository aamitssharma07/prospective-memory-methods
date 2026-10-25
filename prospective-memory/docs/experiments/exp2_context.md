# Experiment 2: Existing Memory Methods

Snapshot date: **2026-10-25**. [Team entry point](../../TEAM_CONTEXT.md) |
[Results table](results/RESULTS.md#experiment-2-four-memory-methods) |
[Downloadable CSV](results/experiment2.csv).

## Purpose and Scope

Reproduce the research release's existing memory methods. This supplies our
**base + PIS** comparator and the additional Mem0/A-Mem/PIS-RAG controls. It is
not our independently implemented historical `pis` arm, and it is not RGPM.

The original execution workspace is the **sibling repository**
`../prospective-memory-reaearch/` (spelling intentional). The GitHub publication
vendors both workspaces' source as siblings; complete raw results are supplied
through its verified Release rather than normal Git files. The committed table
and CSV above are sufficient to inspect all 44 completed scores without raw
downloads. The original `third_party/author_pis` gitlink is vendored as reference
source in the publication; it must not be confused with the sibling's patched
execution code and retained results.

Eleven models x four methods completed **44 full-week runs**, including the
two large-model extensions. The roster matches Experiment 1.

| Method | Release Runner Setting |
| --- | --- |
| Mem0 | `--setup mem0` |
| A-Mem | `--setup amem` |
| PIS-RAG | `--setup intention --intention-retrieval similarity` |
| PIS | `--setup intention` |

## Protocol and Comparability

- Same parsed PMBench v9 week as Experiment 1: 80 steps, 81 due occurrences.
- The sibling scenario's raw hash differs because of JSON formatting. The exporter checks parsed equality before writing comparisons.
- Local models: SGLang 0.5.20, BF16; two H100s for the large-model extensions.
- GPT-5.4: OpenRouter.
- Actor response limit: 768 tokens; temperature 0. Internal memory maintenance/extraction has method-specific limits, so do not claim every call is capped at 768.
- Invalid model output remains empty/incorrect. It must never be replaced with the hidden due set.
- Reported results are retained completed attempts, not repeated-run means.

See [snapshot.json](results/snapshot.json) for exact raw and parsed scenario
hashes and the hashing definition. Do not confuse that raw-JSON canonical hash
with a simulator-normalized-scenario hash from an RGPM manifest.

## Results and Interpretation

All values are in [the four-method matrix](results/RESULTS.md#experiment-2-four-memory-methods).
Examples for author-release PIS: Qwen3-8B **33.22%**, GPT-5.4 **80.77%**,
Llama-3.3-70B **63.08%**. The older Qwen3-8B `pis` score of roughly 42.9% in
the development ledger belongs to our reimplementation, not this experiment.

Mem0/A-Mem/PIS do not improve every model over its base score. Preserve that
variation rather than assuming that adding memory always helps.

## Files and Evidence

These paths are relative to the sibling execution repository:

| Responsibility | Path |
| --- | --- |
| Detailed context and execution history | `EXPERIMENT_CONTEXT.md` |
| Model roster | `models.json` |
| Release memory runner | `code/run_pm_memory.py` |
| Four-method smoke | `scripts/smoke_four_baselines.sbatch` |
| Anchor validation | `scripts/validate_anchor_run.py` |
| Two-experiment large-model launcher | `scripts/run_large_model_both_experiments.sbatch` |
| Qwen3-8B retained runs | `data/PMBench/runs/exp2_anchor_qwen3_8b/` |
| Other initial retained runs | `data/PMBench/runs/full_matrix/` |
| Large-model retained runs | `data/PMBench/runs/large_models/<model>/experiment2/` |

Completion markers plus full 80-step trajectories identify retained attempts.
Invalid startup/provider attempts are preserved separately and are not scored.
The Llama Mem0 retained result is the successful rerun after an embedding-credit
failure, not the earlier broken attempt.

Bundles include trajectory, score Markdown, cost JSON/JSONL, prompt log,
memory logs and, for PIS variants, intention-state records. The team exporter
recomputes exact F1 from the score report's integer TP/FP/FN, checks the rounded
displayed score, validates completion and hashes the source report and cost file.
This is an export validation, not a new exhaustive audit of the author scorer.

The exported `tokens` field is method chat total, not a clean actor/helper split;
embedding cost is separate. `duration_seconds` comes from saved method wall time.
Do not treat the release's hypothetical USD cost estimate as actual OpenAI billing.

## Reproduce the Table, Not the Inference

From this repository, with the sibling and existing artifacts mounted:

```bash
python harness/export_team_context.py --as-of YYYY-MM-DD \
  --exp2-root ../prospective-memory-reaearch
```

This reads existing files only. It never sources `.env`, starts servers, or calls APIs.
