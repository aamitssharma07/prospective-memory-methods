# Author-code PIS comparison

This is separate from our independent `prospective_memory/pis.py` implementation.
Run the authors' `code/run_pm_memory.py --setup intention` without editing its
memory logic, and compare its baseline and errors with our completed pilot.

## Source and data

- Repository: https://github.com/ChengcanWu/prospective-memory-reaearch
- Revision: `43e9b426a478bdd6b4e6fb12cb609ca26bd71ff9`
- Local checkout: `third_party/author_pis/` (ignored; MIT license).
- Extract only `PMBench/data/` and `PMBench/sim/` from its `data.zip` into its
  `data/` directory, excluding hidden paths and caches. Do not extract the bundled
  `.git` or other benchmarks. Validate archive paths before extraction.
- The bundled synthetic week is JSON-identical to ours; raw hashes differ due
  to formatting. Both fresh arms use our exact `synthetic_week_v9.json`.
- The authors' `score_log` and `score_day` are AST-identical to ours. Their runner
  already logs empty selections for invalid output, rather than ground-truth
  fallback. Do not describe this GitHub version as retaining the original leak.

## Local reproduction settings

Qwen3-8B snapshot `b968826d9c46dd6066d109eabc6255188de91218`, BF16, no
quantization, vLLM 0.8.5.post1, 32768 context, server seed 0, temperature 0,
nonthinking. Actor: GPU1 / port30003 / max_tokens768. Helper: GPU0 / port30002
using `prospective_memory.serve` (compact-whitespace grammar). Both servers use
the same weights. Preserve author helper token limits and schemas.

`run_author_pis.py` wraps the author's existing SDK patch only to route helpers
locally, disable Qwen thinking, and record inputs/outputs/usage. It leaves compact
history, forced clock checks, event matching, channel hints, rewriting, extraction,
update handling and done-on-selection unchanged. No embeddings or paid API calls.
Author `--force-query-channels`, `--gate-time-due` and other ablations remain off.

```
.venv/bin/python -u pmbench_fallback_audit/run_author_pis.py \
  pmbench_fallback_audit/memory_results/NEW_UNIQUE_DIRECTORY
.venv/bin/python pmbench_fallback_audit/summarize_author_pis.py \
  pmbench_fallback_audit/memory_results/NEW_UNIQUE_DIRECTORY
```

The wrapper requires running local servers. It snapshots source, scenario,
commit, command arguments and raw calls. It does not stop those servers itself;
the supervising operator should stop only servers it owns after completion.
Runtime guards are intended to abort, never manufacture valid actions or scores.

## Offline comparison

`summarize_author_pis.py` independently re-scores complete traces, captures the
scorer's actual state-aware due set before each choice, and reconciles every
TP/FP/FN with aggregate metrics. Ground truth is used only here, not at inference.
It saves `RESULTS.md`, `FAILURE_ANALYSIS.json`, and every FP/FN in `failures.csv`.

Compare against `qwen3-8b-pis-triplet-20260922-03`. Inspect public inputs, raw helper
outputs, recall text, status snapshots and actor selections for specific causes:
lost/miscompiled intention, wrong revision, premature completion, incorrect cue
matching, ignored correct reminder, or formatting failure. Do not infer causality
from a miss alone. Separate observed evidence from hypotheses.

This is a current-GitHub-code reproduction under local inference settings, not a
claim to reproduce the paper's exact numbers. Architectures, prompt lengths,
query budgets and costs differ. Report precision and recall alongside F1; fewer
selected actions alone can improve F1 while losing true positives. Earlier
`pis_verified` generated no ACT and made no verifier calls, so it is not evidence
of a verification effect. Single runs do not establish statistical significance.
