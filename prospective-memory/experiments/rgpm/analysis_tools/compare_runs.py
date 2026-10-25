"""Compare complete RGPM bundles without modifying either source run."""

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def load(root):
    if read(root / "status.json")["status"] != "complete":
        raise ValueError(f"Run is incomplete: {root}")
    manifest = read(root / "manifest.json")
    scenario = read(root / "scenario.json")
    expected = [(d["name"], s["id"]) for d in scenario["days"] for s in d["steps"]]
    with (root / "steps.csv").open(newline="") as stream:
        steps = list(csv.DictReader(stream))
    with (root / "per_task.csv").open(newline="") as stream:
        tasks = list(csv.DictReader(stream))
    if [(s["day"], s["step_id"]) for s in steps] != expected:
        raise ValueError(f"Incomplete or reordered step table: {root}")
    trajectory = [json.loads(line) for line in (root / "trajectory.jsonl").read_text().splitlines()]
    if [(s["day"], s["step_id"]) for s in trajectory] != expected:
        raise ValueError(f"Incomplete or reordered trajectory: {root}")
    provenance = read(root / "analysis_provenance.json")
    for name, digest in provenance["inputs"].items():
        actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
        if actual != digest:
            raise ValueError(f"Stale analysis input: {root / name}")
    return dict(root=str(root.resolve()), manifest=manifest, scenario=scenario,
                metrics=read(root / "metrics.json"), cost=read(root / "cost.json"),
                steps=steps, tasks=tasks)


def compare(before, after):
    if before["scenario"] != after["scenario"]:
        raise ValueError("Cannot pair different scenarios")
    for key in ("actor_model", "helper_model", "max_tokens", "helper_max_tokens"):
        if before["manifest"][key] != after["manifest"][key]:
            raise ValueError(f"Unmatched configuration: {key}")
    changes = []
    for old, new in zip(before["steps"], after["steps"]):
        if old["expected"] != new["expected"]:
            raise ValueError("Step expectations differ")
        delta = {f"delta_{key}": int(new[key]) - int(old[key]) for key in ("tp", "fp", "fn")}
        changes.append(dict(day=new["day"], step_id=new["step_id"], **delta,
                            before_selected=json.loads(old["selected"]),
                            after_selected=json.loads(new["selected"]),
                            expected=json.loads(new["expected"]),
                            before_invalid=old["invalid"], after_invalid=new["invalid"],
                            after_invalid_reason=new["invalid_reason"],
                            after_call_ids=json.loads(new["call_ids"]),
                            after_memory_rows=json.loads(new["memory_rows"]),
                            after_snapshot=new["snapshot"]))
    old_tasks = {(t["day"], t["task_id"]): t for t in before["tasks"]}
    new_tasks = {(t["day"], t["task_id"]): t for t in after["tasks"]}
    if old_tasks.keys() != new_tasks.keys():
        raise ValueError("Task populations differ")
    task_changes = [dict(day=k[0], task_id=k[1], before=old_tasks[k]["result"],
                         after=t["result"], type=t["type"], regular=t["regular"],
                         updated=t["updated"], cross_day=t["cross_day"])
                    for k, t in new_tasks.items() if old_tasks[k]["result"] != t["result"]]
    slices = {}
    for label, run in (("before", before), ("after", after)):
        slices[label] = {}
        for field in ("type", "regular", "updated", "cross_day"):
            slices[label][field] = {
                value: dict(Counter(t["result"] for t in run["tasks"] if t[field] == value))
                for value in sorted({t[field] for t in run["tasks"]})}
    return dict(before=before["root"], after=after["root"],
                metrics={"before": before["metrics"]["metrics"], "after": after["metrics"]["metrics"]},
                cost={"before": before["cost"]["all_attempts"], "after": after["cost"]["all_attempts"]},
                slices=slices, task_changes=task_changes, step_changes=changes,
                note="Paired development results on an inspected scenario; no held-out or causal claim.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(load(args.before), load(args.after))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "comparison.json").write_text(json.dumps(result, indent=2) + "\n")
    for key in ("task_changes", "step_changes"):
        records = result[key]
        if records:
            with (args.output / f"{key}.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(records[0]))
                writer.writeheader()
                writer.writerows({k: json.dumps(v) if isinstance(v, list) else v
                                 for k, v in row.items()} for row in records)
    print(json.dumps(result["metrics"], indent=2))


if __name__ == "__main__":
    main()
