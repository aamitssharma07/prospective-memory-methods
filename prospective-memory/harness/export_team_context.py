"""Export small, credential-free team result snapshots from existing artifacts only."""

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_IDS = ["Qwen/Qwen3-0.6B", "Qwen/Qwen3-1.7B", "Qwen/Qwen3-4B", "Qwen/Qwen3-8B",
             "google/gemma-4-E2B-it", "mistralai/Ministral-3-3B-Instruct-2512-BF16",
             "mistralai/Ministral-3-8B-Instruct-2512-BF16", "Qwen/Qwen3-32B",
             "openai/gpt-5.4", "meta-llama/Llama-3.3-70B-Instruct", "Qwen/Qwen2.5-72B-Instruct"]
HELPERS = ["Qwen/Qwen3-1.7B", "Qwen/Qwen3-4B", "Qwen/Qwen3-8B", "Qwen/Qwen3-32B"]
SETUPS = ["single_baseline", "optional_heartbeat", "todo_ledger", "auto_heartbeat_30m"]
METHODS = ["mem0", "amem", "pis_rag", "pis"]


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(model):
    return "openai/gpt-5.4" if model == "gpt-5.4" else model


def label(model):
    model = canonical(model)
    if "Ministral-3-3B" in model:
        return "Ministral-3-3B"
    if "Ministral-3-8B" in model:
        return "Ministral-3-8B"
    return {"google/gemma-4-E2B-it": "Gemma-4-E2B", "openai/gpt-5.4": "GPT-5.4",
            "meta-llama/Llama-3.3-70B-Instruct": "Llama-3.3-70B",
            "Qwen/Qwen2.5-72B-Instruct": "Qwen2.5-72B"}.get(model, model.split("/")[-1])


def location(path):
    return Path(os.path.relpath(path, ROOT)).as_posix()


def score_metrics(tp, fp, fn):
    if any(type(n) is not int or n < 0 for n in (tp, fp, fn)):
        raise ValueError("Invalid score counts")
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0}


def validate_complete(row):
    if row["status"] != "complete" or row["completed_steps"] != 80:
        raise ValueError("Only complete 80-step results may receive headline metrics")
    if row["tp"] + row["fn"] != 81:
        raise ValueError("Unexpected due-occurrence population")


def experiment1(root):
    result = []
    for path in sorted((root / "runs/core-four").glob("*/*/metrics.json")):
        manifest_path = path.parent / "manifest.json"
        m, data = read(manifest_path), read(path)
        summary = data["summary"]
        row = {"experiment": 1, "cohort": "core_four", "actor": m["model"]["id"],
               "helper": None, "method": m["setup"]["name"], "status": data["status"],
               "completed_steps": data["completed_steps"], "backend": m["model"]["backend"],
               "max_tokens": m["generation"]["max_tokens"], "scenario_sha256": m["scenario_sha256"],
               "invalid_response_policy": m["invalid_response_policy"],
               **score_metrics(*(summary[k] for k in ("set_tp", "set_fp", "set_fn"))),
               "cross_day_hit": summary.get("cross_day_hit"), "update_hit": summary.get("update_hit"),
               "invalid_response_steps": summary.get("invalid_response_steps"),
               "tokens": (data.get("run_metadata", {}).get("token_usage") or {}).get("total_tokens"),
               "duration_seconds": data.get("run_metadata", {}).get("duration_seconds"),
               "source": location(path), "source_sha256": sha(path),
               "manifest": location(manifest_path), "manifest_sha256": sha(manifest_path)}
        validate_complete(row)
        if abs(row["f1"] - data["rates"]["set_f1"]) > 1e-12:
            raise ValueError(f"Score/count mismatch: {path}")
        if row["max_tokens"] != 768 or row["invalid_response_policy"] != "fail_closed_empty":
            raise ValueError(f"Unexpected Experiment 1 protocol: {path}")
        result.append(row)
    actual = Counter((r["actor"], r["method"]) for r in result)
    if actual != Counter((m, s) for m in MODEL_IDS for s in SETUPS):
        raise ValueError("Experiment 1 is not the expected unique 11-by-4 matrix")
    return result


def markdown_metrics(text):
    values = {}
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[0] in {"Set TP", "Set FP", "Set FN", "Set F1"}:
            if cells[0] in values:
                raise ValueError("Ambiguous repeated metric")
            values[cells[0]] = cells[1]
    result = score_metrics(*(int(values[k]) for k in ("Set TP", "Set FP", "Set FN")))
    reported = float(values["Set F1"].rstrip("%")) / 100
    if abs(result["f1"] - reported) > 0.00051:
        raise ValueError("Score table disagrees with integer counts")
    return result


def experiment2(root, scenario_sha):
    runs = root / "data/PMBench/runs"
    roots = [(runs / "exp2_anchor_qwen3_8b", runs / "exp2_anchor_qwen3_8b/status", "")]
    roots += [(p, p / "status", "") for p in sorted((runs / "full_matrix").iterdir())
              if (p / "status").is_dir()]
    roots += [(p / "experiment2", p / "status", "experiment2_")
              for p in sorted((runs / "large_models").iterdir()) if (p / "experiment2").is_dir()]
    result = []
    for directory, markers, prefix in roots:
        selected = {}
        for path in sorted(directory.rglob("*.score.md")):
            if "invalid_attempts" in path.parts:
                continue
            method = next((name for pattern, name in (("intention-rag-", "pis_rag"),
                           ("intention-", "pis"), ("mem0-", "mem0"), ("amem-", "amem"))
                           if path.name.startswith(pattern)), None)
            if method is None:
                continue
            if method in selected:
                raise ValueError(f"Multiple retained candidates for {directory}/{method}; select explicitly")
            selected[method] = path
        if set(selected) != set(METHODS):
            raise ValueError(f"Missing method in {directory}")
        for method, path in selected.items():
            marker = markers / (prefix + method + ".complete")
            if not marker.is_file():
                raise ValueError(f"Missing completion marker: {marker}")
            stem = path.name.removesuffix(".score.md")
            cost_path = path.with_name(stem + ".cost.json")
            trajectory = path.with_name(stem + ".jsonl")
            with trajectory.open() as stream:
                metadata = json.loads(next(stream))
                steps = [json.loads(line) for line in stream if line.strip()]
            if len(steps) != 80 or len({(s["day"], s["step_id"]) for s in steps}) != 80:
                raise ValueError(f"Incomplete trajectory: {trajectory}")
            if any(s.get("model_error") and s.get("task_ids") for s in steps):
                raise ValueError(f"Failed response received selections: {trajectory}")
            cost = read(cost_path)
            row = {"experiment": 2, "cohort": "author_memory_baselines", "actor": metadata["model"],
                   "helper": None, "method": method, "status": "complete", "completed_steps": len(steps),
                   "backend": metadata["backend"], "max_tokens": 768, "scenario_sha256": scenario_sha,
                   **markdown_metrics(path.read_text()),
                   "tokens": cost["chat"].get("total_tokens"),
                   "duration_seconds": cost.get("wall_seconds"),
                   "source": location(path), "source_sha256": sha(path),
                   "cost_source": location(cost_path), "cost_source_sha256": sha(cost_path),
                   "completion_marker": location(marker),
                   "settings_evidence": "Sibling EXPERIMENT_CONTEXT.md; no per-run max-token manifest",
                   "token_scope": "method chat total; not actor/helper-separated, embeddings excluded"}
            validate_complete(row)
            result.append(row)
    # The release records standard Ministral names even when BF16 weights are served.
    normalized = lambda m: m + "-BF16" if m.startswith("mistralai/Ministral-") and not m.endswith("-BF16") else m
    actual = Counter((normalized(r["actor"]), r["method"]) for r in result)
    if actual != Counter((m, s) for m in MODEL_IDS for s in METHODS):
        raise ValueError("Experiment 2 is not the expected unique 11-by-4 matrix")
    return result


def rgpm_row(directory, cohort, actor, helper, job_id, smoke=None, diagnostic=None):
    status_path, metrics_path = directory / "status.json", directory / "metrics.json"
    status = read(status_path) if status_path.exists() else {"status": "not_started", "committed_steps": 0}
    row = {"experiment": 3, "cohort": cohort, "actor": actor, "helper": helper,
           "method": "rgpm_v15", "job_id": str(job_id), "status": status["status"],
           "completed_steps": status.get("committed_steps", 0), "f1": None,
           "max_tokens": 768, "source": location(directory), "note": None}
    if status_path.exists():
        row.update(status_source=location(status_path), status_source_sha256=sha(status_path))
        row["error_type"] = (status.get("error") or {}).get("type")
    if diagnostic and diagnostic.exists():
        with diagnostic.open() as stream:
            errors = [(json.loads(line).get("error") or {}).get("type") for line in stream if line.strip()]
        if any(errors):
            row.update(status="serving_probe_failed", error_type=next(e for e in errors if e),
                       diagnostic_source=location(diagnostic), diagnostic_source_sha256=sha(diagnostic))
    if row["status"] == "not_started" and smoke and (smoke / "status.json").exists():
        state = read(smoke / "status.json")
        row.update(status="smoke_" + state["status"], smoke_completed_steps=state["committed_steps"],
                   error_type=(state.get("error") or {}).get("type"))
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        m = read(manifest_path)
        if (canonical(m["actor_model"]) != canonical(actor) or m["helper_model"] != helper
                or m["max_tokens"] != 768 or m["helper_max_tokens"] != 768):
            raise ValueError(f"Unexpected RGPM model/token configuration: {directory}")
        row.update(backend=m["actor_backend"], scenario_sha256=m["scenario_sha256"],
                   manifest=location(manifest_path), manifest_sha256=sha(manifest_path),
                   actor_output_tokens=m["max_tokens"], helper_output_tokens=m["helper_max_tokens"],
                   actor_checkpoint_revision=(m.get("actor_provenance") or {}).get("revision"),
                   helper_checkpoint_revision=(m.get("provenance") or {}).get("revision"))
    if row["status"] == "complete":
        metrics = read(metrics_path)
        values, summary = metrics["metrics"], metrics["summary"]
        row.update(score_metrics(*(values[k] for k in ("set_tp", "set_fp", "set_fn"))))
        row.update(cross_day_hit=summary.get("cross_day_hit"), update_hit=summary.get("update_hit"),
                   invalid_response_steps=metrics.get("invalid_responses"),
                   metrics_source=location(metrics_path), metrics_source_sha256=sha(metrics_path))
        if abs(row["f1"] - values["set_f1"]) > 1e-12 or metrics["steps"] != 80:
            raise ValueError(f"Inconsistent RGPM metrics: {directory}")
        validate_complete(row)
        cost_path = directory / "cost.json"
        if cost_path.exists():
            cost = read(cost_path)
            row["duration_seconds"] = cost.get("active_session_wall_seconds")
            for role in ("actor", "helper"):
                values = cost["all_attempts"][role]
                row.update({role + "_tokens": values["tokens"]["total_tokens"],
                            role + "_calls": values["calls"],
                            role + "_summed_call_seconds": values["summed_call_seconds"],
                            role + "_usage_unknown_calls": values["usage_unknown_calls"]})
    return row


def experiment3(root):
    home = root / "experiments/rgpm"
    targets = read(home / "launches/v15_finalized_targets.json")
    result = [rgpm_row(root / r["result_directory"], "original_v15_32", r["actor"], r["helper"],
                       r["selected_job_id"]) for r in targets["local_targets"]]
    if len(result) != 32 or any(r["status"] != "complete" for r in result):
        raise ValueError("Original 32-pair sweep is incomplete")
    consistency = read(home / "launches/v15_consistency_reruns_20261023.json")
    slug = lambda m: m.split("/")[-1].replace(".", "-").lower()
    for r in consistency["pairs"]:
        actor, helper, job = r["actor"]["model"], r["helper"]["model"], str(r["job_id"])
        a, h = slug(actor), slug(helper)
        run_id = a + "-actor-helper-" + h + "-" + job
        directory = root / consistency["runs_root"] / (a + "-helper-" + h) / "sbpm" / run_id
        result.append(rgpm_row(directory, "consistency_v15", actor, helper, job,
                              diagnostic=home / "jobs" / run_id / "consistency_admission/calls.jsonl"))
    gpt = read(home / "launches/gpt_v15_remaining_helpers_submitted_20261023.json")
    for r in gpt["jobs"]:
        directory = root / r["result_directory"]
        smoke = home / "smoke_artifacts" / directory.relative_to(home / "runs/registration_v15_gpt_remaining_helpers")
        result.append(rgpm_row(directory, "gpt_v15", r["actor"], r["helper"], r["job_id"], smoke=smoke))
    previous = home / "runs/registration_v15_openai_full/gpt-5-4-helper-qwen3-32b/sbpm/gpt-5-4-actor-helper-qwen3-32b-1537307"
    result.append(rgpm_row(previous, "gpt_v15", "gpt-5.4", "Qwen/Qwen3-32B", "1537307"))
    context_flags = {("Qwen/Qwen3-0.6B", h) for h in (HELPERS[0], HELPERS[1], HELPERS[3])}
    context_flags |= {("Qwen/Qwen3-32B", h) for h in HELPERS[:3]}
    for row in result:
        notes = []
        if row["cohort"] == "original_v15_32":
            if (row["actor"], row["helper"]) in context_flags:
                notes.append("Known context rejection(s); empty/incorrect predictions retained")
            if "Ministral" in row["actor"]:
                notes.append("Standard FP8 checkpoint; not the BF16 comparator")
        if row.get("error_type") == "ActorBudgetExceeded":
            notes.append("Stopped after missing actor usage following credit rejection; not a full result")
        row["note"] = "; ".join(notes) or None
    return result


def preferred_rows(rows):
    selected = {}
    for cohort in ("original_v15_32", "consistency_v15", "gpt_v15"):
        for row in rows:
            if row["cohort"] != cohort:
                continue
            # Choose serving/checkpoint parity, never the higher observed F1.
            selected[(label(row["actor"]), row["helper"])] = row
    return selected


def percent(row):
    return f"{100 * row['f1']:.2f}" if row and row["status"] == "complete" else "N/A"


def table(headers, records):
    return ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(str(v) for v in row) + " |" for row in records)]


def render(snapshot):
    e1, e2, e3 = (snapshot[k] for k in ("experiment1", "experiment2", "experiment3"))
    index1 = {(label(r["actor"]), r["method"]): r for r in e1}
    index2 = {(label(r["actor"]), r["method"]): r for r in e2}
    selected = preferred_rows(e3)
    lines = ["# Results Snapshot", "", "Artifact-derived snapshot: " + snapshot["as_of"] + " (America/Chicago).",
             "Generated offline by `harness/export_team_context.py`; no model or embedding calls.", "",
             "F1 values are percentages. N/A means no completed full result, not zero.",
             "Run paths and source hashes are in [snapshot.json](snapshot.json) and the three CSV files.", "",
             "## Base, PIS, and RGPM", "",
             "RGPM uses the updated v15 method. For the 11 consistency targets, use that attempt",
             "even if it scores lower or fails; never fall back to a higher FP8/original result.",
             "All other local cells retain their original v15 run. These choices do not establish",
             "identical serving hardware across all experiments. GPT providers also differ.", ""]
    lines += table(["Main Model", "Base (Exp 1)", "PIS (Exp 2)", "RGPM h1.7B", "RGPM h4B", "RGPM h8B", "RGPM h32B"],
                   [[label(m), percent(index1.get((label(m), "single_baseline"))),
                     percent(index2.get((label(m), "pis"))),
                     *(percent(selected.get((label(m), h))) for h in HELPERS)] for m in MODEL_IDS])
    lines += ["", "Two BF16 Ministral + 32B-helper reruns failed serving probes before PMBench.",
              "GPT + 4B is interrupted at 73/80; GPT + 8B is interrupted in smoke (0 steps).",
              "Their F1 is not reported. The original FP8 Ministral results remain below.", "",
              "## Experiment 1: Four Baselines", "", "44 complete full-week runs; SGLang local actors, OpenRouter GPT.", ""]
    lines += table(["Model", *SETUPS], [[label(m), *(percent(index1.get((label(m), s))) for s in SETUPS)] for m in MODEL_IDS])
    lines += ["", "## Experiment 2: Four Memory Methods", "", "44 complete full-week runs from the sibling author-release workspace.", ""]
    lines += table(["Model", "Mem0", "A-Mem", "PIS-RAG", "PIS"],
                   [[label(m), *(percent(index2.get((label(m), s))) for s in METHODS)] for m in MODEL_IDS])
    lines += ["", "## RGPM: Original 32-Pair Sweep", "", "All 32 completed. Ministral rows here are FP8, not the BF16 consistency reruns.", ""]
    original = {(label(r["actor"]), r["helper"]): r for r in e3 if r["cohort"] == "original_v15_32"}
    lines += table(["Main Model", "h1.7B", "h4B", "h8B", "h32B"],
                   [[label(m), *(percent(original.get((label(m), h))) for h in HELPERS)] for m in MODEL_IDS if label(m) not in {"GPT-5.4", "Llama-3.3-70B", "Qwen2.5-72B"}])
    lines += ["", "Known original context-failure flags: Qwen0.6B + h1.7/h4/h32 and Qwen32B + h1.7/h4/h8.",
              "These results include the empty/incorrect outcomes, not repaired predictions.", "",
              "## RGPM: Follow-Up Attempts", ""]
    lines += table(["Job", "Main", "Helper", "Cohort", "Status", "Steps", "F1"],
                   [[r["job_id"], label(r["actor"]), label(r["helper"]), r["cohort"], r["status"],
                     r["completed_steps"], percent(r)] for r in e3 if r["cohort"] != "original_v15_32"])
    lines += ["", "## Interpretation", "",
              "- These are single retained development traces, not replicated mean performance.",
              "- PMBench v9 was repeatedly inspected during RGPM development; this is not a held-out validation claim.",
              "- Compare checkpoint precision, serving capacity, backend, token limits and scenario before attributing a delta to methodology.",
              "- Exp 2's 768-token actor limit does not cover its separate method-specific maintenance calls.",
              "- Token and duration scopes differ; read the CSV fields and each experiment context before pooling costs.",
              "- No claim of universal superiority, statistical significance, or production efficiency follows from this snapshot.", ""]
    return "\n".join(lines)


def export(root, exp2_root, output, as_of):
    raw1, raw2 = root / "PMBench/data/synthetic_week_v9.json", exp2_root / "data/PMBench/data/synthetic_week_v9.json"
    if read(raw1) != read(raw2):
        raise ValueError("Experiment scenarios are not parsed-JSON identical")
    parsed_sha = hashlib.sha256(json.dumps(read(raw1), sort_keys=True).encode()).hexdigest()
    snapshot = {"schema_version": 1, "as_of": as_of,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "exporter_sha256": sha(Path(__file__)),
                "scenario": {"steps": 80, "due_occurrences": 81, "experiment1_raw_sha256": sha(raw1),
                             "experiment2_raw_sha256": sha(raw2), "parsed_json_sha256": parsed_sha,
                             "parsed_hash_encoding": "sha256(json.dumps(parsed_json, sort_keys=True).encode())"},
                "experiment1": experiment1(root / "PMBench"), "experiment2": experiment2(exp2_root, sha(raw2)),
                "experiment3": experiment3(root)}
    for row in snapshot["experiment1"] + snapshot["experiment3"]:
        if row["status"] == "complete" and row["scenario_sha256"] != sha(raw1):
            raise ValueError("Completed result uses a different raw scenario")
    output.mkdir(parents=True, exist_ok=True)
    (output / "snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
    for key in ("experiment1", "experiment2", "experiment3"):
        records = snapshot[key]
        columns = sorted({k for r in records for k in r})
        with (output / (key + ".csv")).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(records)
    (output / "RESULTS.md").write_text(render(snapshot))
    print(json.dumps({"output": location(output), "records": {k: len(snapshot[k]) for k in (
        "experiment1", "experiment2", "experiment3")}}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exp2-root", type=Path, default=ROOT.parent / "prospective-memory-reaearch")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/experiments/results")
    parser.add_argument("--as-of", required=True, help="Snapshot date in America/Chicago, YYYY-MM-DD")
    args = parser.parse_args()
    export(ROOT, args.exp2_root.resolve(), args.output.resolve(), args.as_of)


if __name__ == "__main__":
    main()
