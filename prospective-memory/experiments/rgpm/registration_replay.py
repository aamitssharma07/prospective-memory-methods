"""Development annotations and public-state loading for canceled-run replay.

These expectations are evaluator-only annotations of public instructions, not
benchmark task labels. Each case starts from its own historical memory state.
This is a compiler diagnostic, not a resumed benchmark or a counterfactual F1.
"""

import copy
import json
from pathlib import Path

from prospective_memory.core import Instruction, Intention


ANNOTATIONS = {
    "message_21": {"name": "replay_pending_reminder", "new_count": 0, "changed": {}},
    "message_45": {"name": "replay_return_update", "new_count": 0,
                   "changed": {"pm_000009": "revise"}},
    "message_81": {"name": "replay_seven_new_requests", "new_count": 7, "changed": {},
                   "required_new_terms": [[term] for term in (
                       "prep plan", "check in with your manager", "vendor reply", "quick update",
                       "move the check-in", "room key", "budget note")]},
    "message_92": {"name": "replay_cross_day_request", "new_count": 1, "changed": {},
                   "required_new_terms": [["room change note", "Wednesday", "lab cubby"]]},
    "message_110": {"name": "replay_missing_manager_target", "new_count": 0, "changed": {},
                    "allow_unresolved": True},
    "message_116": {"name": "replay_missing_budget_target", "new_count": 0, "changed": {},
                    "allow_unresolved": True},
    "message_163": {"name": "replay_mixed_cancellation", "new_count": 1,
                    "changed": {"pm_000019": "cancel"},
                    "required_new_terms": [["laundry soap", "Friday", "laundry room cart"]]},
    "message_169": {"name": "replay_background_and_new_request", "new_count": 1, "changed": {},
                    "required_new_terms": [["spare tote bag", "Thursday", "parcel counter"]]},
}


def load_cases(run):
    run = Path(run)
    if run.name != "gpt-5-4-actor-helper-qwen3-8b-1535138":
        raise ValueError("Replay annotations apply only to canceled run 1535138")
    found = {}
    with (run / "memory.jsonl").open() as stream:
        for line_number, line in enumerate(stream, 1):
            row = json.loads(line)
            if row.get("event") != "instruction_intake":
                continue
            message = row["instruction"]
            key = message["id"]
            if key not in ANNOTATIONS:
                continue
            if key in found:
                raise ValueError("Ambiguous replay instruction: " + key)
            state = row["before"]
            found[key] = {**copy.deepcopy(ANNOTATIONS[key]), "text": message["text"],
                "instruction_id": key, "scope": message["scope"], "origin": message["source"],
                "initial_state": {field: state[field] for field in (
                    "instructions", "intentions", "triggers", "next_id", "sources", "queryable_sources")},
                "evidence": {"input_run": str(run.resolve()), "memory_line": line_number,
                             "step_key": row["step_key"]}}
            if found.keys() == ANNOTATIONS.keys():
                break
    if found.keys() != ANNOTATIONS.keys():
        raise ValueError("Missing replay inputs: " + str(sorted(ANNOTATIONS.keys() - found.keys())))
    return [found[key] for key in ANNOTATIONS]


def seed_public_state(engine, state):
    """Transplant only public requests and records; keep fresh runtime policy/cache."""
    engine.instructions = {r["id"]: Instruction(**r) for r in state["instructions"]}
    engine.intentions = {r["id"]: Intention(**{**r, "sources": tuple(r["sources"]),
        "instruction_ids": tuple(r["instruction_ids"])}) for r in state["intentions"]}
    engine.triggers = copy.deepcopy(state["triggers"])
    engine._next_id = state["next_id"]
