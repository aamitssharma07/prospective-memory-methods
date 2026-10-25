#!/usr/bin/env python3
import argparse
import json

from pm_bench import (
    attach_groundtruth_labels,
    compute_scenario_groundtruth,
    normalize_state_visibility,
    requires_state_monitoring,
)


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def format_task(task_ref, state_visibility, id_to_handle):
    task = task_ref["task"]
    current = task_ref["current"]
    task_id = task["id"]
    task_handle = id_to_handle.get(task_id, task_id)
    label = f"{task_handle} => {task_id} ({current['type']})"
    if requires_state_monitoring(current, state_visibility):
        label += " (monitoring event)"
    return label


def export_groundtruth(scenario):
    lines = ["# Synthetic Week Groundtruth", ""]
    report = compute_scenario_groundtruth(scenario)
    state_visibility = normalize_state_visibility(scenario)
    attach_groundtruth_labels(scenario)
    for day in scenario.get("days", []):
        lines.append(f"## {day['name']}")
        lines.append("")
        day_report = report["days"].get(day["name"], {})
        id_to_handle = day_report.get("id_to_handle", {})
        task_map = {task["id"]: task for task in day.get("tasks", [])}
        for step in day.get("steps", []):
            groundtruth = step.get("groundtruth", {"status": "none", "actions": []})
            cue_list = step.get("cues", [])
            lines.append(f"- Step {step['id']} ({step['time']}): cues={cue_list}")
            if groundtruth.get("status") == "due":
                due_refs = []
                for action in groundtruth.get("actions", []):
                    task_id = action.get("id")
                    if task_id not in task_map:
                        continue
                    due_refs.append(
                        {
                            "task": task_map[task_id],
                            "current": {
                                "type": task_map[task_id].get("type"),
                                "cue_channel": task_map[task_id].get("cue_channel", "narrative"),
                            },
                        }
                    )
                due_list = ", ".join(
                    format_task(task_ref, state_visibility, id_to_handle) for task_ref in due_refs
                )
                lines.append(f"  - due: {due_list}")
            else:
                lines.append("  - due: none")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description="Export groundtruth due tasks for a scenario.")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    scenario = load_json(args.scenario)
    output = export_groundtruth(scenario)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
