# PM-Bench fallback audit

This directory contains the experiment layer for evaluating open-weight models
under PM-Bench's original invalid-response fallback and a corrected empty-action
fallback. The upstream benchmark remains the source of scenarios, prompts, agent
logic, and metrics.

PM-Bench's scenario, system prompt, step prompts, action schema, retry behavior,
and scoring functions are reused unchanged. Only the terminal invalid-response
fallback is selectable and instrumented.

## Install

Use Python 3.10+ in a fresh environment on the GPU machine:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r pmbench_fallback_audit/requirements.txt
```

Some gated checkpoints (notably Llama and Gemma) require accepting their license
on Hugging Face and setting `HF_TOKEN` before download.

## Design

The small hook in `PMBench/sim/pm_bench.py` adds two policies:

- `ground_truth`: original PM-Bench behavior; invalid output is replaced by the
  ground-truth due task set.
- `empty`: corrected behavior; invalid output produces no task selections.

Every single-agent trace now records `fallback_triggered`, `fallback_policy`, and
`fallback_reason`. The default is `ground_truth`, preserving upstream behavior.

The affected setups are `single_baseline` and `single_heartbeat` (including the
proactive, auto-30m, and auto-60m modes). The TODO-ledger and hierarchical runners
have their own recovery behavior and must not be described as using this exact
ground-truth fallback without a separate audit.

## Pilot run

Start a local vLLM/SGLang-compatible server, then run the original policy:

```bash
python PMBench/sim/run_eval.py \
  --setup single_heartbeat \
  --heartbeat-mode optional \
  --model Qwen/Qwen3-0.6B \
  --backend sglang \
  --base-url http://127.0.0.1:30002/v1 \
  --invalid-response-fallback ground_truth \
  --score
```

Use `score_paired.py` on that newly instrumented JSONL trace to obtain the original
score and the empty-fallback same-trace counterfactual:

```bash
python pmbench_fallback_audit/score_paired.py \
  --scenario PMBench/data/synthetic_week_v9.json \
  --log PATH/TO/RUN.jsonl \
  --output PATH/TO/RUN.paired.json
```

Then perform a separate corrected end-to-end run:

```bash
python PMBench/sim/run_eval.py \
  --setup single_heartbeat \
  --heartbeat-mode optional \
  --model Qwen/Qwen3-0.6B \
  --backend sglang \
  --base-url http://127.0.0.1:30002/v1 \
  --invalid-response-fallback empty \
  --score
```

## Reporting rule

Use the paired score to isolate immediate score credit caused by answer
substitution. Use the separate corrected run as the primary end-to-end performance
number whenever the two policies create different future runtime states.

`models.json` freezes the initial model list. Record the exact model revision,
precision/quantization, chat template, thinking mode, decoding parameters, and
inference-engine version with every run.

## Matrix runner

Print the full plan without downloading a model:

```bash
python pmbench_fallback_audit/run_matrix.py --dry-run
```

Run one pilot model while automatically starting and stopping vLLM:

```bash
python pmbench_fallback_audit/run_matrix.py --models Qwen/Qwen3-0.6B
```

If a compatible model server is already running at the URL in `experiment.json`:

```bash
python pmbench_fallback_audit/run_matrix.py \
  --models Qwen/Qwen3-0.6B \
  --external-server
```

Completed model/setup pairs are skipped automatically. Aggregate finished paired
reports with:

```bash
python pmbench_fallback_audit/aggregate_results.py \
  --results pmbench_fallback_audit/results \
  --output pmbench_fallback_audit/results/summary.csv
```

The paired JSON retains PM-Bench's complete summary and per-day metric structures,
in addition to the compact fallback-audit fields used by the CSV aggregator.
