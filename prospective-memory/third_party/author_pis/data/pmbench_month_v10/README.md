# PM-Bench 30-day extension (`synthetic_month_v10`)

Independent 30-day / 333-step stress scenario used in the paper. Do not compare scores with the released week.

```bash
python code/run_pm_memory.py --provider deepseek-chat --setup intention \
  --scenario data/pmbench_month_v10/synthetic_month_v10.json
```

`month_builder_v10.py` / `generate_month_v10.py` regenerate the JSON; they still import helpers from `data/PMBench/sim/`.
