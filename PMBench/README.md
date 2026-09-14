# PM-Bench

PM-Bench is a text-based benchmark for prospective memory in LLM agents. It
places an agent in a seven-day simulated week where the agent must continue an
ongoing activity while remembering delayed intentions, reacting to updates,
and deciding when to query hidden state channels.

This release contains the benchmark and scoring runtime, the deterministic v9
scenario used in the paper, all eight evaluated agent configurations, the 64
reported runs, and the frontend-only human evaluation interface.

## Repository layout

- `sim/pm_bench.py`: scenario validation, interactive/model execution, and
  replay-based scoring.
- `sim/run_eval.py`: unified runner for the evaluated agent configurations.
- `sim/run_todo_ledger.py`: single-agent TODO-ledger scaffold.
- `sim/run_hierarchical_agent.py`: hierarchical baseline.
- `sim/run_hierarchical_agent_union_query.py`: hierarchical union-query
  scaffold.
- `sim/replay_union_votes.py`: majority/unanimous replay ablations.
- `sim/week_builder_v9.py` and `sim/generate_week_v9.py`: deterministic v9
  scenario generation.
- `data/synthetic_week_v9.json`: released benchmark week.
- `runs/March_ALL_results_v9/`: 64 scored runs across eight models and eight
  configurations, plus the aggregate report.
- `webapp/frontend/`: browser-based human evaluation UI.

## Installation

Python 3.10 or newer is recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Model-backed evaluation uses an OpenAI-compatible API. Set credentials only in
your shell environment; do not add them to the repository.

```bash
export OPENROUTER_API_KEY="your-key"
# Or, for the OpenAI backend:
export OPENAI_API_KEY="your-key"
```

Locally served models can be used through the `sglang` backend without a real
API key.

## Validate and inspect the benchmark

Validate the released scenario:

```bash
python3 sim/pm_bench.py validate --scenario data/synthetic_week_v9.json
```

Run an interactive session:

```bash
python3 sim/pm_bench.py run \
  --scenario data/synthetic_week_v9.json \
  --log runs/local/interactive.jsonl
```

Score a completed trajectory:

```bash
python3 sim/pm_bench.py score \
  --scenario data/synthetic_week_v9.json \
  --log runs/local/interactive.jsonl
```

## Run model evaluations

The reported live configurations use `single_baseline`, `todo_ledger`,
`single_heartbeat`, and `multi_union_query`. The optional, fixed 30-minute, and
fixed 60-minute heartbeat variants are selected through `--heartbeat-mode`.
The runner also exposes experimental `multi_baseline` and live
`multi_majority_vote` modes; these are distinct from the paper's replay-based
majority and unanimous ablations.

Example OpenRouter run:

```bash
python3 sim/run_eval.py \
  --setup single_baseline \
  --scenario data/synthetic_week_v9.json \
  --backend openrouter \
  --model meta-llama/llama-3.3-70b-instruct \
  --out-dir runs/local \
  --score
```

Example with a local OpenAI-compatible server:

```bash
python3 sim/run_eval.py \
  --setup todo_ledger \
  --scenario data/synthetic_week_v9.json \
  --backend sglang \
  --base-url http://127.0.0.1:30002/v1 \
  --model Qwen/Qwen3-14B \
  --out-dir runs/local \
  --score
```

To launch a consistent set of configurations for one or more models, use:

```bash
sim/launch_experiments/run_all_setups.sh \
  --backend openrouter \
  --model openai/gpt-5.4 \
  --out-dir runs/local
```

Run `python3 sim/run_eval.py --help` or
`sim/launch_experiments/run_all_setups.sh --help` for all options.

## Released results

The release includes 64 trajectories: eight model backbones evaluated under
eight configurations. Six configurations are live inference runs. The
`hier-majority-vote` and `hier-unanimous-vote` configurations are replay-based
decision-rule ablations derived from the corresponding union-query traces.

The main summary is available at
`runs/March_ALL_results_v9/experiment_output_comparison_report.md`. Rebuild it
from the released logs with:

```bash
python3 runs/March_ALL_results_v9/build_experiment_output_comparison_report.py
```

## Human evaluation UI

The UI runs entirely in the browser and stores unfinished sessions in browser
`localStorage`.

```bash
cd webapp/frontend
npm install
npm run dev
```

The interface uses the same released v9 scenario and can export scorer-compatible
`.jsonl` trajectories and Markdown score reports.

## Data and security notes

- The benchmark scenario is synthetic.
- Released trajectories contain model actions and run metadata, not API keys.
- Credentials are read from `OPENAI_API_KEY` or `OPENROUTER_API_KEY`.
- Local outputs should be written under `runs/local/`, which is ignored by Git.
