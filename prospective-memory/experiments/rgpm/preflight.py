"""Record offline launch checks without issuing inference or submitting jobs."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    checks = []
    for name, command in (
        ("method_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"]),
        ("adapter_tests", [sys.executable, "-m", "unittest", "discover", "-s", "harness", "-p", "test_portable*.py", "-q"]),
        ("runner_tests", [sys.executable, "-m", "unittest", "discover", "-s", "experiments/rgpm", "-p", "test_*.py", "-v"]),
        ("launcher_syntax", ["bash", "-n", "experiments/exp3_method.sh"]),
        ("gpt_launcher_syntax", ["bash", "-n", "experiments/rgpm/run_gpt_actor.sbatch"]),
        ("local_launcher_syntax", ["bash", "-n", "experiments/rgpm/run_local_validation.sbatch"]),
        ("consolidated_gpt_launcher_syntax", ["bash", "-n", "experiments/rgpm/run_consolidated_gpt.sbatch"]),
    ):
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        (args.output / (name + ".log")).write_text(completed.stdout + completed.stderr)
        checks.append({"name": name, "passed": completed.returncode == 0,
                       "command": command, "returncode": completed.returncode})

    sys.path.insert(0, str(ROOT / "benchmark" / "sim"))
    import pm_bench

    day = {"name": "Invalid response regression", "tasks": [],
           "steps": [{"id": "s1", "time": "09:00", "text": "Continue.",
                      "options": ["A. Continue", "B. Wait", "C. Skip"], "cues": []}]}
    action = {"day": day["name"], "step_id": "s1", "choice": "A", "task_ids": [],
              "fallback_triggered": True, "fallback_policy": "empty",
              "fallback_reason": "scripted malformed model output"}
    metrics = pm_bench.score_day(day, [action], strict_invalid=True)[0]
    evidence = {"day": day, "action": action, "metrics": metrics,
                "expected_exact_set_match_steps": 0}
    (args.output / "invalid_response_regression.json").write_text(json.dumps(evidence, indent=2))
    checks.append({"name": "invalid_empty_response_is_incorrect",
                   "passed": metrics["exact_set_match_steps"] == 0,
                   "observed_exact_set_match_steps": metrics["exact_set_match_steps"]})

    from types import SimpleNamespace
    from unittest.mock import patch
    from test_runner import Client, scenario
    from run import run
    from artifacts import save
    scripted_scenario = args.output / "scripted_scenario.json"
    save(scripted_scenario, scenario())
    provenance = args.output / "scripted_provenance.json"
    save(provenance, {"execution": "scripted offline fixture; no model inference", "usage": "synthetic test values"})
    client = Client()
    scripted_args = SimpleNamespace(output=str(args.output / "scripted_bundle"),
        scenario=str(scripted_scenario), model="scripted", base_url="http://127.0.0.1:30003/v1",
        projector_id="scripted:v1;max_tokens=768", kind="smoke", resume=False,
        provenance=str(provenance), stop_after=None, source_routing=True,
        scope_grounding=True, bounded_priority=True, registration_grounding=True, local_only=True)
    with patch.object(pm_bench, "build_llm_client", return_value=client):
        run(scripted_args, helper_client=client)
    checks.append({"name": "scripted_artifact_bundle", "passed": True,
                   "artifact": "scripted_bundle/"})
    sources = [ROOT / "benchmark/sim/pm_bench.py", ROOT / "harness/run_memory.py",
               ROOT / "experiments/exp3_method.sh", Path(__file__).resolve()]
    result = {"schema_version": 1, "kind": "offline_preflight",
              "created_at": datetime.now(timezone.utc).isoformat(),
              "status": "passed" if all(c["passed"] for c in checks) else "blocked",
              "actor_model": "Qwen/Qwen3-8B", "helper_model": "Qwen/Qwen3-8B",
              "required_max_tokens": 768, "inference_calls": 0,
              "live_model_smoke_performed": False, "checks": checks,
              "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sources}}
    (args.output / "status.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
