"""Rerun only checkpoint/context-capacity mismatches with v15 inference unchanged."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

from artifacts import save

ROOT = Path(__file__).resolve().parents[2]


def role_spec(provenance):
    config = json.loads((Path(provenance["checkpoint"]) / "config.json").read_text())
    text_config = config.get("text_config", config)
    if config.get("quantization_config") or text_config.get("quantization_config"):
        raise ValueError("Historical consistency template must be unquantized BF16")
    command = provenance["command"]
    log = Path(provenance["server_log"])
    capacity = re.findall(r"max_total_num_tokens=(\d+)", log.read_text()) if log.exists() else []
    return {"model": provenance["model"], "revision": provenance["revision"],
            "dtype": provenance["dtype"], "mem_fraction_static": provenance["mem_fraction_static"],
            "disable_cuda_graph": "--disable-prefill-cuda-graph" in command,
            "model_context_tokens": text_config["max_position_embeddings"],
            "minimum_cache_tokens": int(capacity[-1]) if capacity else None}


def build_plan():
    original = json.loads((ROOT / "experiments/rgpm/analysis/v15_vs_previous_complete32_20261023/comparison.json").read_text())
    rows = original["rows"]
    pairs = []
    for row in rows:
        is_ministral = row["actor"].startswith("mistralai/Ministral-3-")
        is_capacity = row["actor"] == "Qwen/Qwen3-32B" and row["helper"] != "Qwen/Qwen3-32B"
        if not (is_ministral or is_capacity):
            continue
        reference = row
        inferred = row["older"] is None
        if inferred:
            reference = next(r for r in rows if r["actor"] == row["actor"] and r["helper"] == "Qwen/Qwen3-4B")
        old_path = ROOT / reference["older"]["metrics_path"]
        old = json.loads((old_path.parent / "manifest.json").read_text())
        actor = role_spec(old["actor_provenance"])
        helper = role_spec(old["provenance"])
        if inferred:
            updated = json.loads((ROOT / row["updated_metrics_path"]).with_name("manifest.json").read_text())
            helper["model"] = row["helper"]
            helper["revision"] = updated["provenance"]["revision"]
            helper["minimum_cache_tokens"] = None
        if "H100 NVL" not in old["actor_provenance"]["gpu"]:
            raise ValueError("Reference does not use the historical NVL allocation")
        if actor["mem_fraction_static"] is None or helper["mem_fraction_static"] is None:
            raise ValueError("Reference must record both co-located memory fractions")
        if actor["disable_cuda_graph"] != helper["disable_cuda_graph"]:
            raise ValueError("Existing launcher expects matching graph modes")
        pairs.append({"logical_actor": row["actor"], "logical_helper": row["helper"],
                      "actor": actor, "helper": helper,
                      "original_updated_job": row["job_id"],
                      "original_updated_result_directory": str(Path(row["updated_metrics_path"]).parent),
                      "reference_manifest": str(old_path.with_name("manifest.json").relative_to(ROOT)),
                      "reference_kind": "same-family 4B-helper serving template; no historical 1.7B pair" if inferred else "same historical pair",
                      "reason": "FP8 checkpoint differs from earlier BF16" if is_ministral else "32B actor KV capacity below earlier NVL allocation",
                      "status": "planned", "job_id": None})
    return {"schema_version": 1, "experiment": 3,
            "authorization": "User selected only pairs with mismatched settings, keeping updated methodology",
            "methodology": "focused_resolved_partition_v15", "pairs": pairs,
            "runs_root": "experiments/rgpm/runs/registration_v15_consistency_20261023",
            "scenario": "benchmark/data/synthetic_week_v9.json", "max_tokens": 768,
            "hardware": "One 96GB-class H100 NVL on crest-g002; historical actor/helper co-location",
            "limitations": [
                "Other hardware-layout differences are not claimed eliminated across the original full cohort; this targets the eight checkpoint and three demonstrated serving-capacity mismatches.",
                "Three 1.7B-helper pairs lack historical full runs; use the corresponding same-actor 4B-helper serving template, with the actual 1.7B revision pinned.",
                "Qwen3-0.6B native-window overflows are not a changed serving setting and are not rerun or silently repaired here.",
                "Matching old capacity does not guarantee longer updated-method inputs fit; preserve any such failures and score empty/incorrect.",
                "Historical references are individually recorded; they span earlier development runs, not one uniform old version.",
            ]}


def environment(spec_path, index, pair, runs_root):
    return {"MODEL": pair["actor"]["model"], "HELPER_MODEL": pair["helper"]["model"],
            "TP_SIZE": "1", "MEM_FRACTION_ACTOR": str(pair["actor"]["mem_fraction_static"]),
            "MEM_FRACTION_HELPER": str(pair["helper"]["mem_fraction_static"]),
            "DISABLE_CUDA_GRAPH": "1" if pair["actor"]["disable_cuda_graph"] else "0",
            "ACTOR_GUIDANCE": "query_first", "QUERY_HANDOFF": "legacy", "QUERY_BUDGET": "1",
            "SOURCE_ROUTING": "1", "SCOPE_GROUNDING": "1", "BOUNDED_PRIORITY": "1",
            "REGISTRATION_GROUNDING": "1", "REPORT_GATES": "0", "VERIFY_ACTIONS": "0",
            "RUN_HELPER_PROBES": "0", "SMOKE_ADMISSION_POLICY": "report_only",
            "RUNS_ROOT": runs_root, "CONSISTENCY_SPEC": str(spec_path), "CONSISTENCY_INDEX": str(index)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Plan already exists; refusing duplicate submission")
    result = build_plan()
    result.update(created_at=datetime.now(timezone.utc).isoformat(), after_job=args.after,
                  status="submitting" if args.submit else "prepared")
    paths = ("experiments/rgpm/run_one_model.sbatch", "experiments/rgpm/consistency_check.py",
             "experiments/rgpm/improved_engine.py", "experiments/rgpm/registration_guard.py",
             "benchmark/data/synthetic_week_v9.json")
    result["source_sha256"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
    save(args.output, result)
    previous = args.after
    for index, pair in enumerate(result["pairs"]):
        env = environment(args.output, index, pair, result["runs_root"])
        command = ["sbatch", "--parsable", f"--job-name=exp3-v15-consistency-{index:02d}",
                   "--partition=gpu", "--qos=gpu", "--gres=gpu:h100:1", "--nodelist=crest-g002",
                   "--export=ALL," + ",".join(f"{k}={v}" for k, v in env.items()),
                   "--dependency=afterany:" + previous, "experiments/rgpm/run_one_model.sbatch"]
        pair.update(environment=env, submission_argv=command)
        save(args.output, result)
        if not args.submit:
            continue
        reply = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if reply.returncode or not reply.stdout.strip().split(";")[0].isdigit():
            pair.update(status="submission_failed_or_unknown", error=reply.stderr, response=reply.stdout)
            result["status"] = "partial_submission"
            save(args.output, result)
            raise SystemExit("Submission did not complete; inspect recorded jobs before retrying")
        previous = reply.stdout.strip().split(";")[0]
        pair.update(status="submitted", job_id=previous)
        save(args.output, result)
        print(json.dumps({"job": previous, "actor": pair["actor"]["model"], "helper": pair["helper"]["model"]}), flush=True)
    result["status"] = "submitted" if args.submit else "prepared"
    save(args.output, result)
    print(json.dumps({"pairs": len(result["pairs"]), "status": result["status"]}))


if __name__ == "__main__":
    main()
