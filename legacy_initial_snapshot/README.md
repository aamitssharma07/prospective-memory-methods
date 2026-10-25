# prospective-memory-methods

Research code for developing and evaluating general prospective-memory methods
for language-model agents.

The project focuses on agents that must remember an intention and act when a
future condition becomes true, even when the condition may arrive much later,
through another channel, or during unrelated work.

## What is here

- `prospective_memory/`: portable prospective-memory core, model policy, event
  stream evaluator, PM-Bench adapter, examples, and documentation.
- `pmbench_fallback_audit/`: corrected PM-Bench fallback analysis, runners,
  memory-intervention experiments, and compact result summaries.
- `PMBench/`: local copy of the benchmark code and synthetic scenario used by the
  experiments.
- `tests/`: benchmark-independent tests for the portable memory module and live
  diagnostic harness.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r PMBench/requirements.txt
pip install -r pmbench_fallback_audit/requirements.txt
```

Run the lightweight test suite:

```bash
python3 -m unittest discover -s tests -p 'test*.py' -v
python3 -m unittest discover -s pmbench_fallback_audit -p 'test*.py' -v
```

Read `prospective_memory/README.md` and `pmbench_fallback_audit/MEMORY_EXPERIMENT.md`
before starting a new experiment. They record the current method, runnable
commands, and limitations.

## Current caution

The portable memory method has passed scripted software tests and one small
independent Qwen3-8B diagnostic, but it has not yet shown an improvement on
PM-Bench. The next experiment should run one fixed model, preferably Qwen3-8B, on
PM-Bench with `--memory-version portable` and compare against the clean baseline.
