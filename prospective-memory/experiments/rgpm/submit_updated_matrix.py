"""Plan or submit the updated Experiment 3 sweep; no hosted API calls."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
ACTORS = [
    "Qwen/Qwen3-0.6B", "Qwen/Qwen3-1.7B", "Qwen/Qwen3-4B",
    "Qwen/Qwen3-8B", "Qwen/Qwen3-32B", "google/gemma-4-E2B-it",
    "mistralai/Ministral-3-3B-Instruct-2512",
    "mistralai/Ministral-3-8B-Instruct-2512",
]
HELPERS = [f"Qwen/Qwen3-{size}B" for size in ("0.6", "1.7", "4", "8", "14", "32")]


def plan(helpers, run_root, admission_policy="strict"):
    if admission_policy not in {"strict", "report_only"}:
        raise ValueError("Unknown smoke admission policy")
    if len(helpers) != 4 or len(set(helpers)) != 4 or any(h not in HELPERS for h in helpers):
        raise ValueError("Select four distinct supported Qwen3 helpers")
    rows = []
    for actor in ACTORS:
        for helper in helpers:
            gpus = 1 if actor == helper else 2
            env = {
                "MODEL": actor, "HELPER_MODEL": helper, "TP_SIZE": "1",
                "RUNS_ROOT": run_root, "ACTOR_GUIDANCE": "query_first",
                "QUERY_HANDOFF": "legacy", "QUERY_BUDGET": "1",
                "SOURCE_ROUTING": "1", "SCOPE_GROUNDING": "1",
                "BOUNDED_PRIORITY": "1", "REGISTRATION_GROUNDING": "1",
                "REPORT_GATES": "0", "VERIFY_ACTIONS": "0",
                "RUN_HELPER_PROBES": "0",
                "SMOKE_ADMISSION_POLICY": admission_policy,
            }
            rows.append({"actor": actor, "helper": helper, "gpus": gpus,
                         "environment": env, "status": "planned", "job_id": None})
    return {"schema_version": 1, "methodology": "focused_resolved_partition_v15",
            "scenario": "benchmark/data/synthetic_week_v9.json", "steps": 80,
            "max_tokens": 768, "run_root": run_root, "pairs": rows,
            "excluded_main_models": ["GPT-5.4", "meta-llama/Llama-3.3-70B-Instruct", "Qwen/Qwen2.5-72B-Instruct"],
            "admission_policy": admission_policy,
            "gate_policy": "Smoke failures remain recorded. In report_only mode, complete analyzed smoke runs proceed despite quality errors. Crashes and broken artifact contracts still block. No ground-truth repairs.",
            "resources": "Dedicated GPU per role for asymmetric pairs; homogeneous pairs share one server. Sequential afterany dependencies prevent resource contention.",
            "note": "No inference changes during this sweep. Each run records source and checkpoint provenance. Older runs retained."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helpers", nargs=4, choices=HELPERS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--admission-policy", choices=("strict", "report_only"), default="strict")
    parser.add_argument("--indices", nargs="+", type=int, help="Zero-based original pair indices to submit")
    parser.add_argument("--after", help="Existing job that must terminate before the sweep begins")
    parser.add_argument("--replaces", help="Prior launch record retained for provenance")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Launch record exists; refusing duplicate submission")
    result = plan(args.helpers, args.run_root, args.admission_policy)
    if args.indices is not None:
        if len(set(args.indices)) != len(args.indices) or any(i < 0 or i >= len(result["pairs"]) for i in args.indices):
            raise SystemExit("Pair indices must be unique and in range")
        result["pairs"] = [dict(result["pairs"][i], original_pair_index=i) for i in args.indices]
    result["replaces_launch_record"] = args.replaces
    result["scenario_sha256"] = hashlib.sha256((ROOT / result["scenario"]).read_bytes()).hexdigest()
    result["launcher_sha256"] = hashlib.sha256((ROOT / "experiments/rgpm/run_one_model.sbatch").read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.output.write_text(json.dumps(result, indent=2) + "\n")

    save()
    previous = args.after
    if args.submit:
        for index, row in enumerate(result["pairs"]):
            command = ["sbatch", "--parsable", f"--job-name=exp3-v15-matrix-{index:02d}",
                       f"--gres=gpu:h100:{row['gpus']}",
                       "--partition=" + ("gpu-res-01" if row["gpus"] == 2 else "gpu"),
                       "--qos=" + ("gpu-res-01" if row["gpus"] == 2 else "gpu"),
                       "--export=ALL," + ",".join(f"{k}={v}" for k, v in row["environment"].items())]
            if previous:
                command.append(f"--dependency=afterany:{previous}")
            command.append("experiments/rgpm/run_one_model.sbatch")
            row["submission_argv"] = command
            save()
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            if completed.returncode:
                row.update(status="submission_failed", error=completed.stderr)
                save()
                raise SystemExit("Submission failed; prior submitted jobs are retained in the launch record")
            previous = completed.stdout.strip().split(";")[0]
            if not previous.isdigit():
                row.update(status="submission_response_unrecognized", response=completed.stdout)
                save()
                raise SystemExit("Check scheduler before retrying; submission response unrecognized")
            row.update(status="submitted", job_id=previous)
            save()
            print(f"{previous}: {row['actor']} / {row['helper']}", flush=True)
    print(json.dumps({"pairs": len(result["pairs"]), "submitted": args.submit, "record": str(args.output)}))


if __name__ == "__main__":
    main()
