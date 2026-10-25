"""Exercise full scenario execution and resume with deterministic fake responses."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from verify_model_precision import validate_config

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim"))
import pm_bench as pm
import run_todo_ledger as todo


def main():
    validate_config({"dtype": "bfloat16"})
    for config in (
        {"quantization_config": {"quant_method": "fp8"}},
        {"text_config": {"quantization_config": {"quant_method": "fp8"}}},
        {"torch_dtype": "float16"},
    ):
        try:
            validate_config(config)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Precision guard accepted {config}")
    print("PASS precision guard: BF16 accepted; FP8, nested FP8, FP16 rejected")
    scenario = json.loads((ROOT / "data/synthetic_week_v9.json").read_text())
    expected = sum(len(day["steps"]) for day in scenario["days"])
    action = {"action": "choose", "choice": "A", "task_ids": [], "channel": "NONE"}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for mode in ("single", "optional", "auto30", "todo"):
            module = todo.PM_BENCH if mode == "todo" else pm
            def run(path, resume=False):
                common = dict(scenario=scenario, log_path=str(path), model="offline-fixture",
                              backend="sglang", base_url=None, api_key="None",
                              max_time_requests=0, checkpoint_path=str(path)+".checkpoint",
                              resume=resume)
                if mode == "todo":
                    return todo.run_todo_ledger(**common, prompt_log_path=None,
                        ledger_log_path=None, show_task_legend=False, max_invalid_retries=2,
                        temperature=0, max_tokens=768, max_context_tokens=12000, out_dir=None)[0]
                return pm.run_llm(**common, env_path=None,
                    enable_heartbeat=mode == "optional",
                    auto_heartbeat_minutes=30 if mode == "auto30" else None)
            calls = 0
            interrupt = False
            def response(*args, **kwargs):
                nonlocal calls
                calls += 1
                if interrupt and calls == 15:
                    raise InterruptedError("simulated interruption")
                return json.dumps(dict(action, ledger=[])) if mode == "todo" else copy.deepcopy(action)
            target = patch.object(todo, "_call_model", side_effect=response) if mode == "todo" else patch.object(pm, "request_model_action", side_effect=response)
            with patch.object(module, "build_llm_client", return_value=None), target, contextlib.redirect_stdout(io.StringIO()):
                baseline = run(root / (mode+"-full.jsonl"))
                calls = 0
                interrupt = True
                path = root / (mode+"-resume.jsonl")
                try:
                    run(path)
                except InterruptedError:
                    pass
                else:
                    raise AssertionError("Interruption was not exercised")
                interrupt = False
                resumed = run(path, True)
                assert resumed == baseline and len(resumed) == expected, mode
            print(f"PASS {mode}: {expected} steps; resumed trajectory equals uninterrupted trajectory")
        with patch.object(pm, "build_llm_client", return_value=None), patch.object(
            pm, "request_model_action", side_effect=pm.InvalidModelResponseError("invalid fixture", raw_text="bad", finish_reason=None)
        ), contextlib.redirect_stdout(io.StringIO()):
            entries = pm.run_llm(scenario, str(root / "invalid.jsonl"), "fixture", None, 0, "sglang", None, "None")
            summary, _, _ = pm.score_log(scenario, entries)
            assert len(entries) == expected
            assert all(e["invalid_response"] and e["task_ids"] == [] for e in entries)
            assert summary["exact_set_match_steps"] == 0
            assert summary["set_tp"] == 0
        print(f"PASS invalid fallback: {expected} invalid steps, no task credit or exact-set matches")
        for kind, model_response in (
            ("malformed", "not JSON"),
            ("empty-error", ValueError("empty backend response")),
        ):
            with patch.object(todo.PM_BENCH, "build_llm_client", return_value=None), patch.object(
                todo, "_call_model", side_effect=model_response
                if isinstance(model_response, Exception) else None,
                return_value=model_response if isinstance(model_response, str) else None,
            ), contextlib.redirect_stdout(io.StringIO()):
                entries = todo.run_todo_ledger(
                    scenario, str(root / f"todo-{kind}.jsonl"), "fixture", "sglang",
                    None, "None", max_time_requests=0, prompt_log_path=None,
                    ledger_log_path=None, show_task_legend=False,
                    max_invalid_retries=2, temperature=0, max_tokens=768,
                    max_context_tokens=12000, out_dir=None,
                )[0]
                summary, _, _ = pm.score_log(scenario, entries)
                assert len(entries) == expected
                assert all(e["invalid_response"] and e["task_ids"] == [] for e in entries)
                assert summary["exact_set_match_steps"] == 0
                assert summary["set_tp"] == 0
            print(f"PASS TODO {kind} fallback: {expected} invalid steps, no task credit")


if __name__ == "__main__":
    main()
