"""Pair saved Qwen3-8B regressions with public handoffs; no inference or edits to runs."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "experiments/rgpm"))
from artifacts import save


def inspect(path):
    steps = list(csv.DictReader((path / "steps.csv").open()))
    by_key = {(s["day"], s["step_id"]): s for s in steps}
    scenario = json.loads((path / "scenario.json").read_text())
    tasks = {d["name"]: {t["id"] for t in d["tasks"]} for d in scenario["days"]}
    categories, cardinality, handoff, schemas = Counter(), Counter(), Counter(), Counter()
    examples = []
    for pos, step in enumerate(steps):
        selected, expected = set(json.loads(step["selected"])), set(json.loads(step["expected"]))
        cardinality[len(selected)] += 1
        for task in selected - expected:
            if task not in tasks[step["day"]]:
                category = "distractor_not_in_day_task_population"
            elif any(task in json.loads(s["expected"]) for s in steps[pos + 1:] if s["day"] == step["day"]):
                category = "before_later_due_occurrence"
            elif any(task in json.loads(s["expected"]) for s in steps[:pos] if s["day"] == step["day"]):
                category = "after_prior_due_occurrence"
            else:
                category = "no_due_occurrence_in_day"
            categories[category] += 1
    for line in (path / "calls.jsonl").open():
        call = json.loads(line)
        value = call.get("parsed")
        if call["role"] != "actor" or not call.get("valid") or not isinstance(value, dict) or value.get("action") != "choose":
            continue
        key = tuple(call["step_key"])
        step = by_key[key]
        context = call["request"]["messages"][-1].get("content", "")
        marker = "Prospective-memory observations and proposals:\n"
        proposals = json.JSONDecoder().raw_decode(context[len(marker):])[0] if context.startswith(marker) else []
        acts = [p for p in proposals if p.get("decision") == "ACT"]
        checks = [p for p in proposals if p.get("decision") == "CHECK"]
        handoff["choose_calls"] += 1
        handoff["ACT_proposals"] += len(acts)
        # Cardinality is descriptive only: one intention can map to several
        # valid public handles, and lack of a proposal does not forbid acting.
        if len(value["task_ids"]) > len(acts):
            handoff["selected_more_handles_than_ACT_proposals"] += 1
        if not acts:
            handoff["steps_without_current_ACT_proposal"] += 1
            handoff["false_positives_without_current_ACT_proposal"] += int(step["fp"])
        schema = call["request"]["response_format"]["json_schema"]["schema"]
        schemas[schema["properties"]["task_ids"].get("maxItems")] += 1
        if key[0] == "Monday" and key[1] in {"d1_s1", "d1_s2", "d1_s3"}:
            examples.append({"step": key, "call_id": call["call_id"], "cycle": call["cycle"],
                             "expected": json.loads(step["expected"]),
                             "selected": json.loads(step["selected"]),
                             "ACT": acts, "CHECK": checks, "current_handoff": context,
                             "recent_public_state_replies": [m["content"] for m in call["request"]["messages"]
                                 if m.get("role") == "user" and str(m.get("content", "")).startswith("State [")][-2:]})
    return {"path": str(path.relative_to(ROOT)),
            "metrics": json.loads((path / "metrics.json").read_text())["metrics"],
            "selected_count_distribution": dict(cardinality),
            "total_selected": sum(k * v for k, v in cardinality.items()),
            "steps_selecting_eight_handles": cardinality[8],
            "false_positive_categories": dict(categories),
            "actor_handoff_counts": dict(handoff),
            "actor_task_ids_max_items_distribution": dict(schemas),
            "examples": examples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    comparison = json.loads((ROOT / "experiments/rgpm/analysis/v15_vs_previous_20261022/comparison.json").read_text())
    pairs = []
    for row in comparison["rows"]:
        if row["actor"] != "Qwen/Qwen3-8B" or row["delta_percentage_points"] is None or row["delta_percentage_points"] >= 0:
            continue
        before = ROOT / row["best_historical"]["metrics_path"]
        after = ROOT / row["new_metrics_path"]
        old_manifest = json.loads((before.parent / "manifest.json").read_text())
        new_manifest = json.loads((after.parent / "manifest.json").read_text())
        for field in ("actor_model", "helper_model", "scenario_sha256", "max_tokens", "helper_max_tokens"):
            if old_manifest[field] != new_manifest[field]:
                raise ValueError(f"Unmatched comparison: {field}")
        pairs.append({"actor": row["actor"], "helper": row["helper"],
                      "before": inspect(before.parent), "after": inspect(after.parent)})
    result = {"schema_version": 1, "pairs": pairs,
              "interpretation": "Observed associations and public trace examples, not a causal ablation. ACT counts are not an authoritative task whitelist. Scoring labels are used only offline, never as model input."}
    save(args.output, result)
    print(json.dumps({"pairs_analyzed": len(pairs), "output": str(args.output)}))


if __name__ == "__main__":
    main()
