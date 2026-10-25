"""Read-only runtime audit; write a separate report without changing results."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "experiments/rgpm"))
from analyze import pm_bench
from artifacts import save


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def audit(target, reference, expected_hash):
    root = ROOT / target["result_directory"]
    report = {"job_id": target["selected_job_id"], "actor": target["actor"],
              "helper": target["helper"], "result_directory": str(root.relative_to(ROOT)),
              "issues": [], "warnings": []}
    if not (root / "manifest.json").exists():
        report["status"] = "not_started"
        return report
    manifest = json.loads((root / "manifest.json").read_text())
    status = json.loads((root / "status.json").read_text())
    report.update(status=status["status"], committed_steps=status["committed_steps"])
    checks = {"actor_model": target["actor"], "helper_model": target["helper"],
              "scenario_sha256": expected_hash, "max_tokens": 768, "helper_max_tokens": 768,
              "temperature": 0, "actor_guidance": "query_first", "query_handoff": "legacy",
              "scope_grounding": True, "bounded_priority": True, "registration_grounding": True,
              "source_routing": True, "report_gates": False, "verify_actions": False,
              "query_budget": 1, "step_query_budget": 2}
    for key, expected in checks.items():
        if manifest.get(key) != expected:
            report["issues"].append(f"Manifest mismatch: {key}")
    method_prefixes = ("prospective_memory/", "benchmark/sim/", "harness/")
    method_files = {"experiments/rgpm/run.py", "experiments/rgpm/adapter.py",
                    "experiments/rgpm/improved_engine.py", "experiments/rgpm/registration_guard.py",
                    "experiments/rgpm/source_routing.py"}
    drift = [name for name, sha in manifest["source_sha256"].items()
             if (name.startswith(method_prefixes) or name in method_files)
             and name in reference["source_sha256"] and sha != reference["source_sha256"][name]]
    report["method_source_drift_vs_gpt"] = drift
    if drift:
        report["issues"].append("Method source differs from successful GPT run")
    for name, sha in manifest["source_sha256"].items():
        snapshot = root / "source" / name
        if not snapshot.exists() or digest(snapshot) != sha:
            report["issues"].append(f"Source snapshot hash mismatch: {name}")
    if status["status"] != "complete":
        return report
    scenario = json.loads((root / "scenario.json").read_text())
    if digest(root / "scenario.json") != expected_hash:
        report["issues"].append("Saved scenario hash mismatch")
    entries = [json.loads(line) for line in (root / "trajectory.jsonl").open()]
    expected_steps = [(d["name"], s["id"]) for d in scenario["days"] for s in d["steps"]]
    if [(e["day"], e["step_id"]) for e in entries] != expected_steps or len(entries) != 80:
        report["issues"].append("Missing, duplicate or reordered trajectory steps")
    for entry in entries:
        if entry.get("fallback_triggered") and (entry.get("task_ids") or entry.get("fallback_policy") != "empty"):
            report["issues"].append("Invalid actor fallback is not empty/incorrect")
    for index in range(1, 81):
        for folder in ("checkpoints", "snapshots"):
            if not (root / folder / f"{index:06d}.json").exists():
                report["issues"].append(f"Missing {folder}/{index:06d}.json")
    summary, _, count = pm_bench.score_log(scenario, entries, strict_invalid=True)
    stored = json.loads((root / "metrics.json").read_text())
    for key in ("set_tp", "set_fp", "set_fn"):
        if summary[key] != stored["metrics"][key]:
            report["issues"].append(f"Recomputed metric mismatch: {key}")
    tp, fp, fn = (summary[k] for k in ("set_tp", "set_fp", "set_fn"))
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0
    if abs(f1 - stored["metrics"]["set_f1"]) > 1e-12 or count != 80:
        report["issues"].append("Recomputed F1/step-count mismatch")
    report["f1"] = f1
    counts, failures, phases, errors = Counter(), Counter(), Counter(), Counter()
    finishes, call_ids = Counter(), set()
    context_rejections, context_steps = 0, set()
    calls_hash = hashlib.sha256()
    for line in (root / "calls.jsonl").open("rb"):
        calls_hash.update(line)
        call = json.loads(line)
        role, request = call["role"], call["request"]
        counts[role] += 1
        phases[call["phase"]] += 1
        finishes[call.get("finish_reason")] += 1
        if call["call_id"] in call_ids:
            report["issues"].append("Duplicate call ID")
        call_ids.add(call["call_id"])
        if request.get("max_tokens") != 768 or request.get("temperature") != 0:
            report["issues"].append("Call token/temperature mismatch")
        if request.get("model") != target["actor" if role == "actor" else "helper"]:
            report["issues"].append("Actual call model mismatch")
        if not call.get("valid"):
            failures[role] += 1
            error = call.get("error") or {}
            errors[str(error.get("type", error) if isinstance(error, dict) else error)[:180]] += 1
            message = str(error.get("message", "") if isinstance(error, dict) else error).lower()
            if role == "actor" and ("maximum context length" in message or
                                    ("input length" in message and "maximum allowed length" in message)):
                context_rejections += 1
                context_steps.add(tuple(call.get("step_key") or []))
        if "response" not in call and not call.get("error"):
            report["issues"].append("Call has neither raw response nor error")
    report.update(call_counts=dict(counts), failed_calls=dict(failures), error_types=dict(errors),
                  finish_reasons=dict(finishes), assessment_calls=phases["assess"],
                  invalid_actor_steps=stored["invalid_responses"])
    report.update(actor_context_rejections=context_rejections,
                  actor_steps_with_context_rejections=len(context_steps))
    if context_rejections:
        report["issues"].append("Actor context-capacity rejections affect benchmark interpretation")
    index = json.loads((root / "artifact_index.json").read_text())["artifacts"]
    for name in ("manifest.json", "scenario.json", "trajectory.jsonl", "metrics.json",
                 "cost.json", "memory_snapshot.json", "calls.jsonl", "status.json"):
        if name not in index:
            report["issues"].append(f"Artifact not indexed: {name}")
        elif (calls_hash.hexdigest() if name == "calls.jsonl" else digest(root / name)) != index[name]["sha256"]:
            report["issues"].append(f"Artifact hash mismatch: {name}")
    cost = json.loads((root / "cost.json").read_text())
    if cost["incomplete_attempts"]:
        report["issues"].append("Completed run has unfinished call attempts")
    for role, n in counts.items():
        if cost["all_attempts"][role]["calls"] != n:
            report["issues"].append(f"Cost call-count mismatch: {role}")
    errors = json.loads((root / "memory_snapshot.json").read_text())["engine"]["errors"]
    report["semantic_error_count"] = len(errors)
    if failures or errors:
        report["warnings"].append("Model output/semantic failures present; retain as measured quality outcomes")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    targets = json.loads((ROOT / "experiments/rgpm/launches/v15_finalized_targets.json").read_text())
    reference = json.loads((ROOT / targets["existing_gpt_result"]["result_directory"] / "manifest.json").read_text())
    result = {"created_at": datetime.now(timezone.utc).isoformat(), "runs": [],
              "scope": "Read-only metadata/source checks; completed-run rescore and streamed call audit; hashes of key artifacts. Full memory/event streams are not rehashed."}
    for target in targets["local_targets"]:
        try:
            report = audit(target, reference, targets["scenario_sha256"])
        except Exception as exc:
            report = {"job_id": target["selected_job_id"], "issues": [f"Audit error: {type(exc).__name__}: {exc}"]}
        result["runs"].append(report)
        save(args.output, result)
        print(json.dumps({k: report.get(k) for k in ("job_id", "status", "f1", "issues", "failed_calls", "semantic_error_count")}), flush=True)


if __name__ == "__main__":
    main()
