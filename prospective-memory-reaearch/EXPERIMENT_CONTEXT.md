# Experiment 2 Context

## Scope

This repository reproduces four memory baselines from the prospective-memory
research release on the released PMBench v9 week. Experiment 1 is the separate
PMBench baseline run under `../prospective-memory/PMBench`; Experiment 3 is RGPM
under `../prospective-memory/experiments/rgpm`. Do not mix their results.

Repository revision: `43e9b426a478bdd6b4e6fb12cb609ca26bd71ff9`.

## Frozen Matrix

The initial matrix is nine enabled models by four baselines, or 36 runs. Models
are frozen in `models.json`. Llama-3.3-70B is present but disabled for a later
two-H100 run.

Baselines:

1. Mem0: `--setup mem0`
2. A-Mem: `--setup amem`
3. PIS-RAG: `--setup intention --intention-retrieval similarity`
4. PIS: `--setup intention`

Do not add baseline, heartbeat, TODO-ledger, PMA, or other ablations to this
matrix without an explicit scope change.

## Shared Run Settings

- Local serving: SGLang 0.5.20, BF16, no quantization.
- Actor maximum output: 768 tokens.
- Actor temperature: 0.0 in the released PMBench runner.
- Local models use OpenAI-compatible localhost endpoints.
- GPT-5.4 uses OpenRouter.
- Invalid model output fails closed with an empty task selection. Never replace
  an invalid response with evaluator ground truth.
- `.env` is local and ignored. Never print or commit secret values.

## Scenario Provenance

Bundled scenario: `data/PMBench/data/synthetic_week_v9.json`.

- Bundled raw SHA-256: `6688e6a10ad7f93d640e60913c68b7cba626f3b8b0a799584885a6cfb17b72fe`
- Experiment 1 raw SHA-256: `94a45937da1363be19ccfdc2c188d132f23093041e30abd3ec22d64d70da8f24`
- Canonical parsed-JSON SHA-256 for both: `439ac4ba8aeb158e8281a5491939ac21a693ad8da13664772821a3f8ef28306a`

The files are parsed-JSON identical; formatting causes the raw hash difference.
The bundled copy remains authoritative for this reproduction.

## Smoke Testing

`scripts/smoke_four_baselines.sbatch` serves Qwen3-0.6B and runs all four
baselines on a deterministic two-step slice. Smoke outputs are isolated under
`smoke_artifacts/` and are not experiment results. The script does not submit
itself and must pass before any full-week matrix is built or launched.

The final smoke test was Slurm job `1502578`. It completed successfully in
1 minute 14 seconds on one H100 using SGLang, BF16, TP=1, and the configured
768-token response limit. Mem0, A-Mem, PIS-RAG, and PIS each produced two step
records plus score, cost/token, prompt, and memory artifacts. PIS and PIS-RAG
also produced intention-store snapshots and step-level intention logs. These
two-step smoke scores are plumbing checks only and must not be reported as
benchmark results.

The top-level model response limit is fixed at `--max-tokens 768` for every
model and baseline, matching Experiment 1. The runner default and launch scripts
must both retain this value. Internal memory extraction and maintenance calls
have their own method-specific limits and are not part of this setting.

## Current Status

- Bundled PMBench data extracted; no full run executed.
- Python 3.10 virtual environment created at `.venv`.
- Client/memory dependencies pinned in `requirements-experiment.txt`.
- Existing eight offline tests pass.
- Provider discovery sees local, GPT-5.4, OpenRouter, and embedding credentials.
- A-Mem's unused LiteLLM/Ollama import is optional so OpenAI 2.6.1 remains
  compatible with the Experiment 1 client environment.
- Mem0 optional BM25 and NLP paths are installed with FastEmbed 0.7.3, spaCy
  3.8.7, and `en_core_web_sm` 3.8.0. Transformers is pinned to 4.57.3 so these
  packages and SentenceTransformers share a compatible Hugging Face client.
- Smoke attempt `1502574` was stopped after exposing an unbounded repeated
  calendar-query loop. The released `max_time_requests=5` limit is now enforced
  across state queries; exhaustion records an empty selection and
  `query_budget_exhausted: true` instead of fabricating an action.
- Final live four-baseline smoke job `1502578` completed with exit code 0.
- No traceback, import failure, or missing-dependency error occurred in the
  final smoke log.
- Explicit output roots are preserved for PIS variants, so future smoke output
  remains under `smoke_artifacts/`; the completed PIS-RAG smoke from job
  `1502578` predates this path-only fix and is under
  `data/PMBench/runs/intention_rag/results/`.
- The full experiment has not been submitted or run.

## Anchor Full Run

`scripts/run_anchor_qwen3_8b.sbatch` is the first full-week launch gate. It runs
only the Qwen3-8B anchor across Mem0, A-Mem, PIS-RAG, and PIS, sequentially on
one BF16 H100 SGLang server with TP=1 and `--max-tokens 768`. Outputs, per-method
logs, server logs, and baseline completion markers are retained under
`data/PMBench/runs/exp2_anchor_qwen3_8b/`. Rerunning the script skips methods
with completion markers; an interrupted method restarts from its beginning.

Anchor job `1502582` was submitted on 2026-09-30 and canceled during Mem0 after
startup validation exposed a provider-routing defect. Mem0ai 2.1.0 prioritizes
the global `OPENROUTER_API_KEY` over its explicitly configured local endpoint,
so internal Mem0 extraction calls went to OpenRouter instead of SGLang. The
adapter now hides that unrelated variable only while constructing Mem0 and
restores it immediately afterward. Artifacts from job `1502582` are invalid and
must not be scored. Treat a replacement run as complete only when all four files
exist under `data/PMBench/runs/exp2_anchor_qwen3_8b/status/`.

Replacement job `1502583` verified that Mem0 no longer contacted OpenRouter,
but SGLang exited when FlashInfer attempted its first sampling-kernel JIT because
the already-installed `ninja` executable was not on `PATH`. Launch scripts now
prepend the SGLang environment's `bin` directory. Artifacts from job `1502583`
are also invalid and retained only for diagnosis.

Job `1502584` reached Ninja but exposed a CUDA 12.2/FlashInfer 0.6.18 JIT
incompatibility: that FlashInfer release passes the unsupported nvcc option
`--compress-mode=size`. SGLang is now launched with its supported
`--sampling-backend pytorch`; this changes only the sampling-kernel
implementation, not generation parameters. Job `1502584` artifacts are invalid.

Valid replacement job `1502585` was submitted on 2026-09-30. Startup validation
confirmed `sampling_backend=pytorch`, local Mem0 inference, successful memory
writes and recalls, and progress beyond Monday step 9 with no routing, JIT,
CUDA, or connection errors. This is the active Qwen3-8B anchor run.

The remaining matrix is guarded by `scripts/validate_anchor_run.py`. It requires
all four completion markers, exactly 80 unique step records per method, complete
score/cost/prompt/memory artifacts, fail-closed model-error rows, and clean
active-job infrastructure/provider logs. `scripts/validate_then_submit_full.sbatch`
submits the remaining seven local models and GPT-5.4 only after those checks
pass. Qwen3-8B is not duplicated, and Llama-3.3-70B remains disabled.

Gate job `1502593` was scheduled with `afterok:1502585`. Its fail-closed design
would have prevented remaining submissions if the anchor or validation failed.
It passed and submitted seven one-H100 local jobs plus one CPU-only GPT-5.4 job
on the `normal` partition.

## Completed Matrix

The Qwen3-8B anchor (`1502585`) and gate (`1502593`) completed successfully.
The gate passed all checks and submitted jobs `1502600` through `1502607`; all
eight completed with exit code 0. Across nine enabled models and four methods,
all 36 runs contain exactly 80 unique steps and complete trajectory, score,
cost/token, prompt, and memory artifacts. There were no local-to-OpenRouter
leaks, rate-limit failures, connection failures, scheduler crashes, or CUDA OOMs.
TorchCodec's startup-only FFmpeg probe tracebacks in Gemma/Ministral server logs
are benign for this text-only workload.

Set-F1 results (%):

| Model | Mem0 | A-Mem | PIS-RAG | PIS |
| --- | ---: | ---: | ---: | ---: |
| Qwen3-0.6B | 2.4 | 2.3 | 11.5 | 0.0 |
| Qwen3-1.7B | 37.0 | 31.0 | 33.3 | 29.9 |
| Qwen3-4B | 34.1 | 35.1 | 29.2 | 36.9 |
| Qwen3-8B | 27.5 | 25.1 | 31.7 | 33.2 |
| Gemma-4-E2B | 24.8 | 24.7 | 19.9 | 34.8 |
| Ministral-3-3B | 37.1 | 23.4 | 7.5 | 49.4 |
| Ministral-3-8B | 49.7 | 40.5 | 36.9 | 51.4 |
| Qwen3-32B | 50.0 | 50.0 | 40.8 | 47.2 |
| GPT-5.4 | 70.6 | 65.3 | 60.6 | 80.8 |
| Llama-3.3-70B | 58.4 | 62.3 | 55.6 | 63.1 |
| Qwen2.5-72B | 54.4 | 56.8 | 53.2 | 62.9 |

All 11 models complete, all four methods each (44 runs). Llama-3.3-70B and
Qwen2.5-72B are the TP=2 extension models (two H100s, BF16, PyTorch sampling,
`--max-tokens 768`), run via `scripts/run_large_model_both_experiments.sbatch`
with `MEM_FRACTION_STATIC` set explicitly: sglang's auto-computed fraction left
no room for the KV cache on either model, and the exact margin needed differs
by model size, so this is not left at the tool's default. Llama-3.3-70B's Mem0
had to be rerun once after an embedding-API credit lapse (confirmed by zero
`embed` calls and 235 `credit_balance_exhausted` errors in the first attempt's
log, versus a clean run with real embed calls in the kept result). Qwen2.5-72B
additionally needed `--disable-prefill-cuda-graph --disable-decode-cuda-graph`:
CUDA graph capture failed two different ways near the needed fraction (a hard
OOM and a PyTorch internal assertion), both specific to graph capture rather
than ordinary inference, and disabling it resolved both without changing the
scored result's correctness.

Update this file after each setup fix, smoke test, submission, or result change.
