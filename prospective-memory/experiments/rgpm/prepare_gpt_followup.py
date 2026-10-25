"""Prepare the deferred GPT follow-up; never submit jobs or issue API requests."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HELPERS = ("Qwen/Qwen3-1.7B", "Qwen/Qwen3-4B", "Qwen/Qwen3-8B")


def plan():
    jobs = []
    runs_root = "experiments/rgpm/runs/registration_v15_gpt_remaining_helpers"
    for helper in HELPERS:
        size = helper.split("Qwen3-")[1].replace(".", "-").lower()
        env = {
            "LOCAL_ONLY": "0", "RUN_FULL": "1", "ACTOR_BACKEND": "openai_chat",
            "ACTOR_MODEL": "gpt-5.4", "HELPER_MODEL": helper,
            "ACTOR_GUIDANCE": "query_first", "QUERY_HANDOFF": "legacy",
            "QUERY_BUDGET": "1", "SOURCE_ROUTING": "1", "SCOPE_GROUNDING": "1",
            "BOUNDED_PRIORITY": "1", "REGISTRATION_GROUNDING": "1",
            "REPORT_GATES": "0", "VERIFY_ACTIONS": "0",
            "RUN_HELPER_PROBES": "0", "SMOKE_ADMISSION_POLICY": "report_only",
            "SMOKE_MAX_ACTOR_CALLS": "24", "SMOKE_MAX_ACTOR_TOKENS": "500000",
            "MAX_ACTOR_CALLS": "300", "MAX_ACTOR_TOKENS": "4000000",
            "RUNS_ROOT": runs_root,
        }
        command = ["sbatch", "--parsable", f"--job-name=exp3-gpt-v15-h{size}",
                   "--partition=gpu", "--qos=gpu", "--gres=gpu:h100:1",
                   "--export=ALL," + ",".join(f"{k}={v}" for k, v in env.items()),
                   "experiments/rgpm/run_gpt_actor.sbatch"]
        jobs.append({"actor": "gpt-5.4", "helper": helper, "status": "prepared_not_submitted",
                     "environment": env, "submission_argv_without_dependency": command,
                     "dependency_rule": "First job: after current local sweep terminates; subsequent jobs: afterany previous GPT job ID. Resolve actual IDs at submission time.",
                     "full_result_directory_template": f"{runs_root}/gpt-5-4-helper-qwen3-{size}/sbpm/gpt-5-4-actor-helper-qwen3-{size}-{{job_id}}"})
    return {
        "schema_version": 1, "task_id": "EXP3-GPT-V15-REMAINING-HELPERS",
        "status": "prepared_awaiting_paid_run_approval", "experiment": 3,
        "methodology": "focused_resolved_partition_v15", "jobs": jobs,
        "scenario": "benchmark/data/synthetic_week_v9.json", "steps": 80,
        "max_output_tokens_per_role": 768, "temperature": 0,
        "actor_reasoning_effort": "none", "actor_endpoint": "https://api.openai.com/v1",
        "helper_backend": "local_sglang_bf16",
        "credential": "OPENAI_API_KEY from repository .env; never include in plan or submission argv",
        "budget_status": "Proposed limits copied from GPT+32B run; approval and actual availability required before spending",
        "combined_proposed_caps": {"actor_calls": 972, "actor_tokens": 13500000},
        "admission": "Offline preflight and complete analyzed smoke required. Quality checks are report-only; semantic guards remain unchanged. Synthetic helper probe batteries skipped, matching the local matrix.",
        "existing_result_to_reuse": {"actor": "gpt-5.4", "helper": "Qwen/Qwen3-32B", "job_id": "1537307", "f1": 0.8571428571428572},
        "launch_checklist": [
            "Wait for the local 32-pair sweep and review its completion/failures; do not require improved F1 as an inclusion criterion.",
            "Recheck that no completed matching v15 result or active GPT job already exists for these three helpers.",
            "Confirm approval for the paid three-pair run and proposed budgets; revalidate source/scenario hashes after any edits.",
            "Read-only authentication/model access check without displaying credentials; this does not prove account credits.",
            "Resolve and verify sequential dependencies, submit once, and record actual IDs and immutable run directories.",
            "Preserve raw/parsed responses, retries, failures, checkpoints, costs, TOK/DUR, and full 80-step F1 for every pair.",
            "Report incomplete/budget-blocked runs explicitly; do not fabricate scores or silently restart paid work.",
        ],
        "inference_changes": "None. No context-compaction, over-selection, or efficiency changes in this task.",
        "execution": "Plan generation only; no jobs submitted and no network/inference requests made.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Plan already exists; use a new output path")
    result = plan()
    result["prepared_at"] = datetime.now(timezone.utc).isoformat()
    sources = (result["scenario"], "experiments/rgpm/run_gpt_actor.sbatch",
               "experiments/rgpm/run.py", "experiments/rgpm/smoke_gate.py",
               "experiments/rgpm/improved_engine.py", "experiments/rgpm/registration_guard.py")
    result["preparation_sha256"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"task": result["task_id"], "prepared_pairs": len(result["jobs"]),
                      "submitted": False, "plan": str(args.output)}))


if __name__ == "__main__":
    main()
