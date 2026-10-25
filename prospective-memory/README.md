# Prospective memory for language-model agents

**Start with [TEAM_CONTEXT.md](TEAM_CONTEXT.md)** for the three experiments,
current results, code locations and remaining work. The
[results snapshot](docs/experiments/results/RESULTS.md) includes base vs PIS vs
RGPM and all three matrices without requiring the raw cluster data.

Before publishing, read [the GitHub handoff checks](docs/GITHUB_HANDOFF.md).
The root `.env` is currently tracked, and nested-repository packaging needs
review. Nothing has been committed or pushed as part of this documentation work.

Research code for a source-bound prospective-memory module: an agent that holds a
deferred intention and acts when its future cue arrives, while occupied with
unrelated work.

## Historical Developer Notes

The notes below describe the older library/vLLM workflow, not the current
SGLang Experiment 1 matrix or RGPM v15 sweep. Use the per-experiment pages linked
from Team Context for current settings, results and entry points.

## Layout

```
benchmark/          PM-Bench, vendored upstream (scenario, simulator, released runs)
harness/            our runner, fallback-corrected scorer, and Experiment 1 results
prospective_memory/ the memory library
├── core.py           engine: identity, provenance, lifecycle, evidence boundaries
├── llm.py            provider-independent schema and prompt helpers
├── decoding.py       whitespace-grammar guard (see "Serving" below)
├── serve.py          server launcher with the required decoding settings
├── adapters/         host adapters (PM-Bench)
├── baselines/        PIS, paper-inspired reimplementation (NOT author code)
└── method/           our source-bound chain, built on the PIS baseline
experiments/        per-experiment configuration and notes
docs/               experiment plan, results ledger, proposed methodology
paper_tables/       generated result tables for the write-up
papers/            source papers and design notes
tests/             library tests (441); harness tests live in harness/
third_party/       author_pis reference material
```

The class chain makes the baseline/method boundary exact:

```
Engine                          core.py
└── PISEngine                   baselines/pis.py        ← PIS baseline
    └── SourceBoundPISEngine    method/source_bound.py  ← ours begins
        └── SourceBoundV3Engine
            └── SourceBoundTriggerEngine
                └── SourceBoundFairTriggerEngine        ← adopted policy
```

## Serving

Model servers **must** forbid repeatable grammar whitespace, and the actor must
use vLLM's own generation defaults rather than the checkpoint's:

```bash
python -m prospective_memory.serve --model <model> --dtype bfloat16 \
  --gpu-memory-utilization 0.9 --port 30002          # helper (whitespace-free)

python -m vllm.entrypoints.openai.api_server --model <model> --dtype bfloat16 \
  --generation-config vllm --port 30003              # actor
```

`--generation-config vllm` is not optional. With `auto`, vLLM loads the
checkpoint's `generation_config.json` (for Qwen3: `do_sample true,
temperature 0.6, top_k 20, top_p 0.95`) and the actor selects ~7 tasks per step
instead of ~1, collapsing the Qwen3-8B baseline from 42.0% to 24.3%.

PM-Bench's actor schema uses `maxItems`, which xgrammar cannot compile, so the
actor cannot share the whitespace-free helper server.

## Running

```bash
python -m unittest discover -s tests -p 'test*.py'
python -m unittest discover -s harness -p 'test*.py'

python harness/run_memory.py --mode selective --memory-version portable \
  --memory-policy sbpm \
  --base-url http://127.0.0.1:30003/v1 --memory-base-url http://127.0.0.1:30002/v1 \
  --output <run dir>
```

Start with `docs/EXPERIMENT_PLAN.md`, then `docs/results_ledger.md` for every
recorded run and `docs/PROPOSED_METHODOLOGY.md` for the adopted configuration.

## Status

Fallback policy is always `empty`; PM-Bench's shipped `ground_truth` policy
substitutes the evaluator's due set when structured output stays invalid, which
rewards unparseable responses. See `paper_tables/` for corrected results.

Measured single-trace spread on unchanged code is **3.95 Set-F1 points**, so any
gap under ~4 points is not interpretable without repeats.
