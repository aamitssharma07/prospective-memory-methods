# Experiment Context

## Purpose

This repository is the clean workspace for reproducing a focused subset of
PM-Bench and evaluating future prospective-memory methods against it. The
experiment uses the authors' released v9 scenario and four selected baselines.
Eleven models have completed all four baselines (44 completed runs), including
the two TP=2 extension models, Llama-3.3-70B and Qwen2.5-72B. Mistral Small 3.2
24B and Claude Opus 4.6 are disabled and must not be run without an explicit
decision.

## Repository Provenance

- Upstream repository: `https://github.com/genglinliu/PMBench.git`
- Upstream commit at clone time: `e1093c470c8981daf522d4ef047a7c3a71e077d7`
- Upstream branch: `main`
- Local model registry: `models.json`
- Experiment specification: `experiment.json`
- Matrix launcher: `sim/run_experiment_matrix.py`
- Environment file: `.env` copied from the previous research repository
- `.env` is ignored by Git and has local permissions `600`
- Official local-serving runtime: SGLang `0.5.20` in `.venv-sglang`

The upstream repository identifies its local backend as SGLang but does not
pin the SGLang package version or preserve a server launch command. We pin
`0.5.20`, the stable release selected during setup, so every new run uses the
same runtime. The previously installed vLLM environment is not part of the
official baseline and must not be used to produce the primary results.
SGLang `0.5.20` requires OpenAI Python `2.6.1`; that version remains within
upstream PM-Bench's declared `openai>=1.0.0` compatibility range.
The canonical experiment server template is `scripts/run_local_model.sbatch`. It requests
the cluster's required `gpu` partition and `gpu` QoS, defaults to one H100,
serves in BF16 without a runtime quantization flag, and redirects SGLang,
FlashInfer, Transformers, and Hugging Face caches into the repository.
The cluster exposes CUDA 12.2 compiler headers, while SGLang `0.5.20` ships a
CUDA 13 runtime and otherwise probes its optional JIT DeepGEMM path on H100.
The server template disables JIT DeepGEMM for these dense BF16 models; this
avoids an unsupported local kernel compilation and does not quantize weights.
`ninja` is pinned explicitly because SGLang compiles fused kernels such as RoPE
at model startup but does not install the build executable as a dependency.

## Frozen Scenario

- Scenario: `data/synthetic_week_v9.json`
- Steps: 80
- SHA-256: `94a45937da1363be19ccfdc2c188d132f23093041e30abd3ec22d64d70da8f24`

The scenario hash is checked by the matrix launcher. A mismatch stops command
generation or execution. We use the released scenario rather than generating
new seeds so the resulting scores remain directly comparable with the paper.

## Models

| # | Model | Model ID | Backend | Notes |
|---:|---|---|---|---|
| 1 | Qwen3-0.6B | `Qwen/Qwen3-0.6B` | SGLang | BF16 |
| 2 | Qwen3-1.7B | `Qwen/Qwen3-1.7B` | SGLang | BF16 |
| 3 | Qwen3-4B | `Qwen/Qwen3-4B` | SGLang | BF16 |
| 4 | Qwen3-8B | `Qwen/Qwen3-8B` | SGLang | BF16; experiment anchor |
| 5 | Gemma-4-E2B | `google/gemma-4-E2B-it` | SGLang | BF16 |
| 6 | Ministral-3-3B | `mistralai/Ministral-3-3B-Instruct-2512-BF16` | SGLang | BF16 |
| 7 | Ministral-3-8B | `mistralai/Ministral-3-8B-Instruct-2512-BF16` | SGLang | BF16 |
| 8 | Qwen3-32B | `Qwen/Qwen3-32B` | SGLang | BF16; tensor parallel 1, smoke-tested |
| 9 | Mistral-Small-3.2-24B | `mistralai/mistral-small-3.2-24b-instruct` | OpenRouter | Disabled; local SGLang attempts failed and user declined hosted execution |
| 10 | Llama-3.3-70B | `meta-llama/Llama-3.3-70B-Instruct` | SGLang | Complete; BF16, tensor parallel 2 on reserved partition `gpu-res-01` |
| 11 | Qwen2.5-72B | `Qwen/Qwen2.5-72B-Instruct` | SGLang | Complete; BF16, tensor parallel 2 on reserved partition `gpu-res-01` |
| 12 | GPT-5.4 | `openai/gpt-5.4` | OpenRouter | Hosted API |
| 13 | Claude Opus 4.6 | `anthropic/claude-opus-4.6` | OpenRouter | Disabled; GPT-5.4 is the only hosted API model in this experiment |

Preflight update (2026-09-29): Ministral IDs use the official `-BF16`
repositories; the unsuffixed checkpoints declare FP8. SGLang 0.5.20 needs
the text-only MistralCommon tokenizer correction in `scripts/sglang_site/`;
both selected Ministral models passed live parser checks with it. Qwen3-32B
passed BF16 checks on one H100 and now uses tensor parallel 1. The reserved
`gpu-res-01` partition and QoS permit two GPUs per user, so Llama-3.3-70B uses
tensor parallel 2 there. The server launcher checks cached
precision metadata before serving; this is not a weight-by-weight audit.
See `runs/setup/PREFLIGHT_REPORT.md` for preflight evidence. Eleven models have
completed 44 runs, including both TP=2 extension models. Both Mistral Small
3.2 24B and Claude Opus 4.6 remain in the registry for provenance with
`enabled: false`.

Models not listed here are outside the experiment scope unless this document
and `models.json` are deliberately updated together.

## Baselines

Each included model runs exactly these four configurations:

| Baseline | Runner configuration | Reason for inclusion |
|---|---|---|
| Single baseline | `single_baseline` | Basic no-memory control and pipeline sanity check |
| Optional heartbeat | `single_heartbeat --heartbeat-mode optional` | Strong overall PM-Bench baseline |
| TODO-ledger | `todo_ledger` | Precision-oriented baseline closest to memory-based methods |
| Auto-heartbeat 30m | `single_heartbeat --heartbeat-mode auto30` | Strong update-sensitive baseline |

The completed matrix is 11 models x 4 baselines = 44 runs.

The following configurations are intentionally excluded: auto-heartbeat 60m,
hierarchical multi-agent, majority vote, and unanimous vote. They are not part
of the approved compute budget or comparison table.

## Invalid-Response Fallback Correction

### Upstream behavior

When a model repeatedly returned output that PM-Bench could not parse, the
upstream runner caught `InvalidModelResponseError` and constructed a fallback
action using `due_now`, the simulator's hidden ground-truth set. The fallback
therefore submitted the correct task IDs for the model. This kept long sweeps
from stopping when a provider returned empty or truncated structured output,
but it placed answer-key information inside the scored trajectory.

The effect is not neutral. A model that never emits valid structured output can
receive credit for actions selected by the evaluator. Because output-formatting
reliability tends to correlate with model capability, this behavior can inflate
weaker models most and compress the performance differences under evaluation.

### Corrected behavior

The correction is implemented in `sim/pm_bench.py` and, for the TODO-ledger
baseline, `sim/run_todo_ledger.py`. After the existing request and parse
retries are exhausted:

1. The sweep continues instead of crashing.
2. The fallback action is a neutral `choose A` action with `task_ids: []`.
3. The fallback never reads or copies `due_now`.
4. The trajectory records `invalid_response: true`, the policy name
   `fail_closed_empty`, and the parse failure reason.
5. The scorer increments `invalid_response_steps`.
6. An invalid response is always an exact-set mismatch, even on a step where
   the ground-truth task set is empty. Formatting failure therefore cannot earn
   accidental exact-match credit.
7. Valid model responses retain the original scoring behavior.

TODO-ledger also retains its existing optional ledger-reset retry. If that
still fails, it records the same empty prediction and leaves ledger state
unchanged. Empty backend responses and malformed JSON receive zero task
credit instead of aborting the sweep.

This is technically a fail-closed fallback rather than a state rollback: no
scored simulator action has been applied when parsing fails, so there is no
state mutation to reverse. The purpose is to preserve sweep continuity without
leaking ground truth or awarding evaluator-generated answers to the model.

Offline checks cover the full 80-step scenario for all four baselines,
interrupted/resumed trajectories, and invalid-output scoring for both the
single and TODO-ledger runners. Invalid responses receive zero task true
positives and zero exact-set matches, including on correct-empty steps.

## Execution Guardrails

`sim/run_experiment_matrix.py` is the canonical matrix entry point. Its default
behavior is preview-only: it validates configuration and prints commands but
does not contact a model endpoint. Actual inference requires `--execute`.

Additional safeguards:

- The scenario SHA-256 must match `experiment.json`.
- The registry must contain unique model IDs.
- The experiment must contain exactly the approved four baseline names.
- SGLang execution requires an explicit `--base-url`.
- The model list can be filtered by model name, model ID, or backend.
- All completed runs request score reports through `--score`.

Preview commands:

```bash
python3 sim/run_experiment_matrix.py
python3 sim/run_experiment_matrix.py --model Qwen3-8B
python3 sim/run_experiment_matrix.py --backend openrouter
```

Use `--execute` only for an explicitly selected enabled model. Bulk execution
will skip disabled Mistral Small 3.2 24B and Claude Opus 4.6.

## Results and Intermediate Artifacts

Planned outputs are rooted at `runs/core-four/`. Every completed run should
retain enough information to score, audit, and inspect it without calling the
model again:

- Action trajectory in JSONL format
- Every raw model response for each step, including query/retry responses
- Markdown score report
- Full prompt log
- TODO-ledger trajectory for the TODO-ledger baseline
- Run metadata including model, backend, start/end time, duration, and entries
- Invalid-response flags, policy, and reason on affected steps
- `metrics.json` with the complete nested scorer output and derived rates
- `steps.csv` with expected and selected IDs for every timeline step
- `failures.csv` containing every FP, FN, invalid, or missing step
- `ANALYSIS.md` with headline and per-day interpretation

The live trajectory and exact runtime state are atomically checkpointed after
every completed step. A checkpoint contains the next-step cursor, conversation
history, task lifecycle state, heartbeat/query state, completed trajectory and,
for TODO-ledger, ledger state. Resume rejects changes to the scenario, model,
backend, setup-affecting options, or runner source hashes. The matrix launcher
automatically resumes when a matching checkpoint exists, skips runs with
complete metrics, and removes the checkpoint only after successful completion.

After runs exist, `sim/aggregate_results.py` builds `results.json`,
`results.csv`, and `RESULTS.md` across all available model/setup bundles. These
formats support later questions and new tables without model inference.

The remaining results work is any additional paper-specific visualization.
The saved trajectory, prompts, step table,
failure inventory, nested metrics, and aggregate tables are the durable source
for future offline analysis.

`scripts/estimate_runtime.py` derives a planning estimate from the preserved
80-step run metadata in `runs/all_results_v9`. During actual matrix execution,
`tqdm` reports elapsed time, completion rate, and a live ETA based on observed
run durations. These measurements are reporting-only and do not enter prompts,
scoring, checkpoints, or model configuration.

## Current Status

### Reproducibility snapshot

The completed local runs did not use vLLM. Qwen, Gemma, and Ministral were all
served with the same environment:

- SGLang `0.5.20`
- PyTorch `2.13.0`
- Transformers `5.12.1`
- BF16 weights, no quantization
- One H100 per completed local model and tensor parallel size 1
- Slurm request: `gpu` partition, `gpu` QoS, `gpu:h100:1`, 16 CPUs, 128 GB RAM
- Cluster hardware: NVIDIA H100 NVL, approximately 94 GB per card
- `--max-tokens 768`, temperature `0.0`, two invalid-response retries
- Invalid-response policy `fail_closed_empty`, never `ground_truth`
- Server model length unset (checkpoint/SGLang default)
- No vLLM `--generation-config`; SGLang used model sampling defaults

The canonical local server command was:

```bash
.venv-sglang/bin/sglang serve \
  --model-path "$MODEL_ID" \
  --host 127.0.0.1 \
  --port 30002 \
  --dtype bfloat16 \
  --tp-size 1
```

Gemma `google/gemma-4-E2B-it` successfully loaded with this command. Its
effective SGLang static GPU-memory fraction was `0.85785`; its selected
attention and sampling backends were Triton and FlashInfer. This success does
not identify a compatible vLLM version because vLLM was not installed or used.

### Completed corrected Set-F1

| Model | Single | Optional heartbeat | TODO-ledger | Auto heartbeat 30m |
|---|---:|---:|---:|---:|
| Qwen3-0.6B | 24.8% | 18.6% | 21.1% | 19.9% |
| Qwen3-1.7B | 29.8% | 27.8% | 36.0% | 31.1% |
| Qwen3-4B | 13.7% | 8.6% | 17.0% | 20.8% |
| Qwen3-8B | 42.0% | 40.5% | 52.5% | 38.6% |
| Gemma-4-E2B | 35.4% | 30.5% | 20.1% | 29.3% |
| Ministral-3-3B | 52.3% | 48.8% | 24.3% | 53.1% |
| Ministral-3-8B | 60.3% | 60.3% | 52.5% | 61.8% |
| Qwen3-32B | 50.7% | 50.3% | 54.1% | 51.7% |
| GPT-5.4 | 75.7% | 73.1% | 68.1% | 71.8% |
| Llama-3.3-70B | 69.3% | 65.6% | 69.6% | 62.5% |
| Qwen2.5-72B | 61.9% | 58.5% | 57.9% | 59.5% |

Both TP=2 extension models needed `--mem-fraction-static` set explicitly above
sglang's auto-computed default, which left no room for the KV cache; the exact
margin needed differs by model (Qwen2.5-72B's larger footprint also needed
`--disable-prefill-cuda-graph --disable-decode-cuda-graph` to avoid a CUDA
graph capture failure at that margin). See `../prospective-memory-reaearch/
EXPERIMENT_CONTEXT.md` for the paired Experiment 2 numbers and the same
calibration notes.

These values come from each run's `metrics.json` under `rates.set_f1`. The
durable aggregate and per-step artifacts are under `runs/core-four/`.

### SGLang smoke test

On 2026-09-28, a non-scored smoke test loaded `Qwen/Qwen3-0.6B` on one
H100 through SGLang `0.5.20`. The server reported BF16 model weights, a BF16
KV cache, and `quantization: None`. Model discovery, ordinary chat completion,
and the same OpenAI `json_schema` response mechanism used by PM-Bench all
returned HTTP 200 responses. The exact structured response was
`{"action": "choose A", "task_ids": ["smoke-task"]}`. The machine-readable
record is `runs/setup/sglang-qwen3-0.6b-smoke.json`.

The smoke test identified and corrected two launcher prerequisites before any
experiment run: optional JIT DeepGEMM must be disabled because the cluster
does not provide a CUDA 13 compiler, and the virtual environment must be on
`PATH` so SGLang can invoke `ninja` for fused-kernel compilation. The final
server startup, warm-up generation, and both smoke requests succeeded.

On 2026-09-29, preflight was repeated with `Qwen/Qwen3-0.6B` in BF16 and no
quantization. Model discovery, plain chat, strict JSON-schema output, all four
PM-Bench action-schema variants, and TODO-ledger parsing passed. The smoke
harness was updated to preserve the token-usage tuple returned by the current
TODO runner. Evidence is in
`runs/setup/sglang-qwen3-0.6b-preflight-20260929.json`; temporary Slurm job
`1501112` was stopped after the test.

Completed:

- Fresh upstream repository cloned
- Nine-model, 36-run core matrix completed
- Four-baseline matrix finalized
- Released v9 scenario frozen by hash
- Ground-truth fallback removed from the scored path
- Invalid-response accounting added to console and Markdown reports
- Environment file copied and excluded from Git
- Dependency and runtime setup
- Local model-server orchestration
- Preview and execution of the 36-command matrix
- Atomic per-step trajectory checkpoints implemented
- Exact step-boundary resume implemented for all four selected baselines
- Offline per-run and cross-run analysis outputs implemented
- Clean aggregate JSON, CSV, and Markdown generation implemented
- SGLang BF16 server and JSON-schema endpoint smoke test passed

Outstanding:

- Mistral-Small-3.2-24B local jobs `1501373` and `1501386` failed before
  inference. SGLang 0.5.20 recognizes the checkpoint as multimodal, while its
  standalone text-only mode does not support `Mistral3ForConditionalGeneration`.
  No valid result bundle was produced. Do not run it through OpenRouter unless
  the user explicitly reverses the decision not to do so.
- Claude Opus 4.6 is intentionally excluded.

Non-scored smoke inference was completed before the main benchmark started.

## Main Execution

The 36-run matrix was submitted to Slurm on 2026-09-29. Eight local
models run as self-contained one-GPU jobs; each job starts its own BF16 SGLang
server, waits for health, executes four resumable baselines, and stops the
server. GPT-5.4 runs in a detached normal-partition job. Slurm job `1501122`
aggregated available completed outputs after all nine experiment jobs finished.
The complete model-to-job mapping is preserved in
`runs/jobs/submission-20260929.json`.

On 2026-09-30, Mistral-Small-3.2-24B and Llama-3.3-70B were added to the
comparison candidates. Download job `1501372` completed. Mistral jobs `1501373`
and `1501386` failed during SGLang startup and Mistral was subsequently
disabled. Claude Opus 4.6 remains excluded.

Llama-3.3-70B and Qwen2.5-72B (added later as the second TP=2 extension model)
both completed on 2026-10-07 via `../prospective-memory-reaearch/scripts/
run_large_model_both_experiments.sbatch`, after several earlier attempts failed
for unrelated reasons (a node left draining by an unreaped TP=2 server process;
sglang's auto-computed `--mem-fraction-static` leaving no KV-cache headroom for
either model; Qwen2.5-72B additionally hitting a CUDA graph capture failure at
the higher fraction its larger footprint needed). See
`../prospective-memory-reaearch/EXPERIMENT_CONTEXT.md` for the paired
Experiment 2 results and the full calibration history.
