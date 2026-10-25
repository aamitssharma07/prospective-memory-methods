# ProMem

Inference-time scaffold for deferred intentions in LLM agents. The core object is a Prospective Intention Store (PIS). This repository is the code release for reproducing the PM-Bench experiments.

Main method: `--setup intention`. Comparators: `baseline`, `mem0`, `amem`, `todo_ledger`, `heartbeat`.

## Requirements

- Python 3.10+
- An API key in `.env` (see `.env.example`)
- A full-week run calls the LLM many times

## Setup

```bash
# 1. Unpack the released-week benchmark (zip top level is PMBench/ and TriggerBench-Official/)
mkdir -p data
unzip data.zip -d data

# 2. Intention / baseline only need openai
pip install -r requirements.txt

# 3. Fill keys (never commit .env)
cp .env.example .env

# 4. Check providers
python code/run_pm_memory.py --list-providers
```

After unzip, the runner expects:

- `data/PMBench/data/synthetic_week_v9.json`
- `data/PMBench/sim/pm_bench.py`

`--setup mem0` / `--setup amem` also need `third_party/mem0-main` and `third_party/A-mem-main` (not bundled) plus their extra dependencies.

## Reproduce

Released week (default scenario):

```bash
python code/run_pm_memory.py --provider deepseek --setup intention
python code/run_pm_memory.py --provider deepseek --setup baseline
python code/run_pm_memory.py --provider deepseek --setup todo_ledger
python code/run_pm_memory.py --provider deepseek --setup heartbeat
```

30-day extension (do not compare scores with the released week):

```bash
python code/run_pm_memory.py --provider deepseek --setup intention \
  --scenario data/pmbench_month_v10/synthetic_month_v10.json
```

Logs and scores go to `data/PMBench/runs/`.

Connectivity check (no full week):

```bash
python scripts/smoke_llm.py --provider deepseek
```
