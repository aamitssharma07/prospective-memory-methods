#!/usr/bin/env python3
"""Build a deterministic two-step fixture from the released PMBench week."""

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/PMBench/data/synthetic_week_v9.json"
DESTINATION = ROOT / "data/slices/smoke_two_step_v9.json"


def main() -> None:
    scenario = json.loads(SOURCE.read_text(encoding="utf-8"))
    smoke = copy.deepcopy(scenario)
    smoke["scenario_name"] = scenario["scenario_name"] + " (two-step smoke)"
    smoke["days"] = [copy.deepcopy(scenario["days"][0])]
    smoke["days"][0]["steps"] = smoke["days"][0]["steps"][:2]
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_text(json.dumps(smoke, indent=2) + "\n", encoding="utf-8")
    print(DESTINATION)


if __name__ == "__main__":
    main()
