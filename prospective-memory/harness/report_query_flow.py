#!/usr/bin/env python3
"""Read-only CHECK-to-query audit of completed portable PM-Bench runs.

No model calls, scorer, trigger labels, task-handle matching or runtime mutation.
The adapter saves the prefix BEFORE the last action: N cycles must therefore
align with N-1 saved actions plus the final executed trajectory choice. Ambiguous
or rejected action streams fail closed rather than being counted as queries.
"""

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospective_memory.core import Decision
from prospective_memory.method.fair_checks import FairCheckArbiter


RAW_FILES = ("manifest.json", "scenario.json", "metrics.json", "trajectory.jsonl",
             "memory.jsonl", "memory_snapshot.json")
FAIR_SOURCE = "prospective_memory/method/fair_checks.py"
GUIDANCE = "Prospective-memory observations and proposals:\n"
HANDOFF = "Optional exact-source query handoff (advisory, not executed):\n"
LIMITS = [
    "Descriptive immediate-next-action uptake, not task performance, useful retrieval, semantic correctness or causal improvement.",
    "A CHECK is a proposal. Actual queries require a saved actor action, matching public State reply and reconciliation with executed trajectory counters.",
    "The last action is an executed trajectory choice; its missing raw actor JSON and task handles are not reconstructed.",
    "Steps flagged as fallback are retained and marked; their executed choice need not represent a model-generated choice.",
    "CHECK counts use a proposal denominator; actual-query counts use an action denominator. Multiple CHECKs may precede one action.",
    "Clock queries are included in query totals. Repeated means the same source was already queried in the same step, not that the query was necessarily useless.",
    "Fairness replay checks bookkeeping and the frozen scheduler rule, not the semantic eligibility or information value of candidates, optimal scheduling, or absence of starvation.",
    "Source/scenario hashes are checked against the saved manifest. Raw hashes are fingerprints and stability checks, not independent authentication unless expected raw hashes are supplied.",
    "Unsupported/ambiguous prefixes (including rejected actions or heartbeat actions) fail loudly. This audit does not repair or silently skip them.",
]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def counts(value, label):
    require(isinstance(value, dict) and all(isinstance(k, str) and k and type(v) is int and v > 0
                                          for k, v in value.items()), "Invalid " + label)
    return Counter(value)


def verify_inputs(path, expected_hashes=None):
    """Validate frozen sources; do not execute them or read benchmark truth."""
    raw = {name: digest(path / name) for name in RAW_FILES}
    if (path / "memory_calls.jsonl").is_file():
        raw["memory_calls.jsonl"] = digest(path / "memory_calls.jsonl")
    if expected_hashes is not None:
        require(isinstance(expected_hashes, dict) and bool(expected_hashes), "Empty expected raw hashes")
        for name, expected in expected_hashes.items():
            require(name in raw and raw[name] == expected, "Expected raw hash mismatch: " + str(name))
    manifest = read_json(path / "manifest.json")
    require(manifest.get("memory_version") == "portable", "Expected a portable memory run")
    hashes = manifest.get("source_sha256")
    require(isinstance(hashes, dict) and bool(hashes), "Missing frozen source hashes")
    for name, expected in hashes.items():
        relative = Path(name)
        require(not relative.is_absolute() and ".." not in relative.parts,
                "Unsafe source snapshot path")
        saved = path / "source" / relative
        require(saved.resolve().is_relative_to((path / "source").resolve()), "Source snapshot escapes run")
        require(digest(saved) == expected, "Source snapshot hash mismatch: " + name)
    require(raw["scenario.json"] == manifest.get("scenario_sha256"), "Scenario snapshot hash mismatch")
    return manifest, raw


def decode_guidance(row, explicit):
    """Count only CHECKs actually included in the logged injected reminder."""
    bank = row["bank"]
    intentions = {item["id"]: item for item in bank["intentions"]}
    checks = [d for d in row["decisions"] if d["kind"] == "CHECK"]
    expected = []
    for d in checks:
        require(d["intention_id"] in intentions, "CHECK has unknown intention")
        item = intentions[d["intention_id"]]
        require(d["source"] in bank["queryable_sources"] and d["source"] in item["sources"],
                "CHECK has unadvertised/unbound source")
        expected.append({"decision": "CHECK", "source": d["source"], "action": item["action"],
                         "condition": item["condition"], "reason": d["reason"]})
    reminder = row["reminder"]
    require(isinstance(reminder, str), "Invalid logged reminder")
    guidance = []
    if reminder.startswith(GUIDANCE):
        guidance, _ = json.JSONDecoder().raw_decode(reminder[len(GUIDANCE):])
        require(isinstance(guidance, list), "Invalid delivered guidance")
    require([d for d in guidance if d.get("decision") == "CHECK"] == expected,
            "Logged CHECKs differ from delivered reminder")
    if explicit and checks:
        require(HANDOFF in reminder, "Missing explicit query appendix")
        appendix, _ = json.JSONDecoder().raw_decode(reminder.split(HANDOFF, 1)[1])
        require(appendix == {
            "optional_query_actions": [{"action": "query_state", "choice": "NONE", "task_ids": [],
                                        "channel": d["source"]} for d in checks],
            "current_observed_sources": list(dict.fromkeys(o["source"] for o in row["observations"]
                                                          if o["current"] and o["source"] in bank["sources"])),
            "actual_query_attempts_this_step": bank.get("step_queries"),
        }, "Explicit handoff differs from host ledger/decisions")
    return checks


def saved_actions(messages):
    actions = []
    for index, message in enumerate(messages):
        require(isinstance(message, dict) and isinstance(message.get("content"), str), "Invalid message")
        if message.get("role") != "assistant":
            continue
        action = json.loads(message["content"])
        require(isinstance(action, dict) and action.get("action") in {"choose", "check_time", "query_state"},
                "Unsupported actor action; cannot align reliably")
        source = ""
        reply = ""
        if action["action"] != "choose":
            source = "clock" if action["action"] == "check_time" else action.get("channel")
            require(isinstance(source, str) and bool(source) and action.get("choice") == "NONE"
                    and action.get("task_ids") == [], "Rejected/malformed query action")
            require(index + 1 < len(messages) and messages[index + 1]["role"] == "user",
                    "Query lacks a public reply")
            reply = messages[index + 1]["content"]
            match = re.fullmatch(r"State \[([^\]]+)\]:\s*(.*)", reply, re.DOTALL)
            require(match is not None and match.group(1) == source,
                    "Query reply does not confirm requested source (possibly rejected action)")
        else:
            require(action.get("choice") in {"A", "B", "C"}, "Invalid saved choice")
        actions.append({"message_index": index, "kind": action["action"], "choice": action.get("choice"),
                        "source": source, "reply": reply, "origin": "saved_actor_json"})
    return actions


class FairReplay:
    """Reconcile every offer/reset with actual prior actions, never proposals."""

    def __init__(self):
        self.arbiter = None
        self.log = []
        self.epoch = 0
        self.rows = []
        self.history = []

    def cycle(self, row, previous_action, checks):
        bank, cycle = row["bank"], row["cycle"]
        log = bank["arbitration_log"]
        require(isinstance(log, list) and log[:len(self.log)] == self.log, "Arbitration log is not append-only")
        added = log[len(self.log):]
        resets = [e for e in added if e.get("event") == "capability_reset"]
        selections = [e for e in added if e.get("event") == "selection"]
        require(len(resets) <= 1 and len(selections) <= 1 and added == resets + selections,
                "Unsupported arbitration event order/count")
        if self.arbiter is None:
            initial = resets[0]["previous_history"]["queryable_sources"] if resets else bank["queryable_sources"]
            self.arbiter = FairCheckArbiter(initial)
        for event in resets:
            require(self.arbiter.snapshot() == event["previous_history"], "Reset lost/changed fair query history")
            require(event["queryable_sources"] != list(self.arbiter.queryable_sources), "Spurious capability reset")
            self.arbiter = FairCheckArbiter(event["queryable_sources"])
            self.epoch += 1
        require(list(self.arbiter.queryable_sources) == sorted(bank["queryable_sources"]),
                "Fair arbiter capabilities differ from bank")
        if previous_action and previous_action["source"] in self.arbiter.queryable_sources:
            self.arbiter.record_query(previous_action["source"])
            self.history.append({"epoch": self.epoch, "cycle_recorded": cycle, "action_cycle": cycle - 1,
                                 "event": "queried", **self.arbiter.snapshot()["queried"][-1]})
        selected_pairs = []
        for event in selections:
            require(event["step_id"] == bank["step_id"] and event["scope"] == row["scope"]
                    and event["queryable_sources"] == list(self.arbiter.queryable_sources),
                    "Arbitration event is not aligned to current cycle")
            available = min(bank["query_budget"], max(0, bank["step_query_budget"] - len(bank["step_queries"])))
            require(event["budget"] == available, "Arbitration remaining budget mismatch")
            candidates = [Decision(**{**d, "evidence_ids": tuple(d["evidence_ids"])}) for d in event["candidates"]]
            intentions = {item["id"]: item for item in bank["intentions"]}
            observed = {o["source"] for o in row["observations"] if o["current"]}
            require(all(d.intention_id in intentions and d.source in intentions[d.intention_id]["sources"]
                        and d.source not in observed for d in candidates),
                    "Arbitration candidate has unknown intention, unbound source or current source already observed")
            selection = self.arbiter.arbitrate(candidates, budget=available, priority_sources=event["priority_sources"])
            require(list(selection.selected_sources) == event["selected_sources"]
                    and list(selection.deferred_sources) == event["deferred_sources"], "Fair selection replay mismatch")
            representatives = {g.source: g.decisions[0].intention_id for g in selection.selected}
            require(representatives == event["representatives"], "Wrong fair representatives")
            selected_pairs = list(representatives.items())
            for group in (*selection.selected, *selection.deferred):
                selected = group.source in representatives
                self.rows.append({"cycle": cycle, "scope": row["scope"], "host_step_id": bank["step_id"],
                                  "source": group.source, "candidate_intentions": len(group.decisions),
                                  "candidate_intention_ids": [d.intention_id for d in group.decisions],
                                  "representative_id": representatives.get(group.source, ""),
                                  "selected_source": int(selected), "shared_source": int(selected and len(group.decisions) > 1),
                                  "shared_intentions": len(group.decisions) - 1 if selected else 0,
                                  "deferred_source": int(not selected),
                                  "deferred_intentions": 0 if selected else len(group.decisions),
                                  "priority_source": int(group.source in event["priority_sources"])})
            if selection.selected:
                self.history.extend({"epoch": self.epoch, "cycle_recorded": cycle, "action_cycle": "",
                                     "event": "offered", **e}
                                    for e in self.arbiter.snapshot()["offered"][-len(selection.selected):])
        require(selected_pairs == [(d["source"], d["intention_id"]) for d in checks],
                "Selected fair sources differ from delivered CHECKs")
        require(self.arbiter.snapshot() == bank["fair_check_state"], "Actual fair offer/query history mismatch")
        self.log = log


def audit_run(run_dir, *, expected_hashes=None):
    path = Path(run_dir).resolve()
    manifest, raw = verify_inputs(path, expected_hashes)
    snapshot, metrics = read_json(path / "memory_snapshot.json"), read_json(path / "metrics.json")
    memory, trajectory = jsonl(path / "memory.jsonl"), jsonl(path / "trajectory.jsonl")
    require(bool(memory) and trajectory and trajectory[0].get("record_type") == "run_metadata", "Missing completed logs")
    metadata, entries = trajectory[0], trajectory[1:]
    require(metadata.get("finished_at_utc") and metadata.get("entry_count") == len(entries)
            and metrics.get("steps") == len(entries), "Missing/inconsistent completion metadata")
    # Only public day/step identities are read; never due tasks, triggers or gold.
    scenario = read_json(path / "scenario.json")
    require([(d["name"], s["id"]) for d in scenario["days"] for s in d["steps"]]
            == [(e["day"], e["step_id"]) for e in entries], "Run is not a complete scenario in order")
    require(snapshot.get("adapter") == "pmbench" and snapshot.get("version") == 1,
            "Expected portable PMBench adapter snapshot")
    messages = snapshot["messages"]
    require(snapshot["seen"] == len(messages) and snapshot["cycles"] == len(memory)
            and [r["cycle"] for r in memory] == list(range(1, len(memory) + 1)), "Memory cycle/cursor mismatch")
    require(snapshot["engine"] == memory[-1]["bank"] and snapshot["last_decisions"] == memory[-1]["decisions"]
            and snapshot["current_observations"] == memory[-1]["observations"], "Final snapshot disagrees with last cycle")
    variant = snapshot["engine"].get("policy_variant")
    require(manifest.get("policy_variant") == variant, "Manifest/snapshot policy mismatch")
    explicit = manifest.get("memory_query_handoff", "legacy") == "explicit"
    require(manifest.get("memory_query_handoff", "legacy") in {"legacy", "explicit"}
            and snapshot.get("query_handoff", "legacy") == ("explicit" if explicit else "legacy"), "Query handoff mode mismatch")
    for field, snapshot_field in (("memory_check_budget", "query_budget"), ("pis_step_query_budget", "step_query_budget")):
        if field in manifest:
            require(manifest[field] == snapshot["engine"].get(snapshot_field), "Manifest/snapshot budget mismatch")
    actions = saved_actions(messages)
    require(len(actions) + 1 == len(memory), "Expected N-1 saved actions for N memory cycles")
    require(entries and entries[-1].get("choice") in {"A", "B", "C"}, "Final executed choice missing")
    actions.append({"message_index": len(messages), "kind": "choose", "choice": entries[-1]["choice"],
                    "source": "", "reply": "", "origin": "final_executed_trajectory_choice"})
    fair = None
    if variant == "sbpm":
        require(manifest["source_sha256"].get(FAIR_SOURCE) == digest(ROOT / FAIR_SOURCE),
                "Current pure fair arbiter differs from frozen source; cannot replay silently")
        fair = FairReplay()
    cycle_rows, check_rows, actual = [], [], Counter()
    step_index, queries, replies, step_histogram = 0, [], {}, Counter()
    previous_action = None
    menus = [i for i, m in enumerate(messages) if m.get("role") == "user"
             and re.search(r"^Step action menu\s*:", m["content"], re.MULTILINE)]
    require(len(menus) == len(entries), "Public step-menu count differs from completed trajectory")
    for row, action in zip(memory, actions):
        require(step_index < len(entries), "Extra actor action after final step")
        entry, bank, cycle = entries[step_index], row["bank"], row["cycle"]
        require(row.get("mode") == "portable" and row["scope"] == entry["day"], "Memory day/step alignment mismatch")
        prior_menus = [i for i in menus if i < action["message_index"]]
        require(prior_menus and prior_menus[-1] == menus[step_index]
                and bank.get("step_id") == f"message_{menus[step_index]}", "Memory step does not match action prefix")
        require(bank.get("step_queries") == queries, "Actual step-query ledger differs from prefix")
        require(bank.get("policy_variant") == variant, "Policy changed within run")
        advertised = {name.strip() for m in messages[:action["message_index"]] if m.get("role") == "system"
                      for match in re.finditer(r"Available state channels:\s*([^\n.]+)", m["content"])
                      for name in match[1].split(",") if name.strip()}
        require(set(bank["queryable_sources"]) == advertised and set(bank["sources"]) == advertised | {"events"},
                "Bank capabilities differ from public interface")
        for obs in row["observations"]:
            match = re.fullmatch(r"message_(\d+)(?:_clock_\d+)?", obs["id"])
            require(match is not None and menus[step_index] <= int(match[1]) < action["message_index"]
                    and messages[int(match[1])]["role"] == "user" and obs.get("current") is True,
                    "Current observation does not belong to this action prefix")
        checks = decode_guidance(row, explicit)
        if fair:
            fair.cycle(row, previous_action, checks)
        source = action["source"]
        observed = list(dict.fromkeys(o["source"] for o in row["observations"] if o["current"]))
        repeated = bool(source and source in queries)
        same_reply = bool(repeated and replies.get(source) == action["reply"])
        common = {"cycle": cycle, "day": entry["day"], "step_id": entry["step_id"],
                  "host_step_id": bank["step_id"], "next_action": action["kind"], "actual_source": source,
                  "action_origin": action["origin"], "actor_message_index": action["message_index"],
                  "step_fallback": bool(entry.get("fallback_triggered", False)),
                  "queries_before": list(queries), "current_observed_sources": observed,
                  "repeat_query_this_step": repeated, "identical_repeat_reply": same_reply}
        cycle_rows.append({**common, "delivered_check_sources": [d["source"] for d in checks]})
        for decision in checks:
            check_rows.append({**common, "intention_id": decision["intention_id"], "check_source": decision["source"],
                               "outcome": ("choose_without_query" if not source else
                                           "exact_source" if source == decision["source"] else "different_source")})
        if source:
            require(source in bank["queryable_sources"], "Executed query has an unadvertised source")
            actual[source] += 1
            queries.append(source)
            replies[source] = action["reply"]
        else:
            require(action["choice"] == entry["choice"], "Actor/trajectory choice mismatch")
            require(Counter(queries) == counts(entry.get("state_queries"), "trajectory query counts"),
                    "Executed trajectory queries differ from saved action sequence")
            require(entry.get("check_time", 0) == queries.count("clock"), "Trajectory clock counter mismatch")
            step_histogram[len(queries)] += 1
            step_index += 1
            queries, replies = [], {}
        previous_action = action
    require(step_index == len(entries) and not queries, "Incomplete final action alignment")
    for container in (metrics.get("metrics", {}), metrics.get("summary", {})):
        require(container.get("state_query_calls") == sum(actual.values())
                and container.get("check_time_calls") == actual["clock"], "Saved metric query totals mismatch")
    by_source = {}
    for source in sorted({r["check_source"] for r in check_rows}):
        outcomes = Counter(r["outcome"] for r in check_rows if r["check_source"] == source)
        by_source[source] = {"checks": sum(outcomes.values()), **{k: outcomes[k] for k in
                            ("exact_source", "different_source", "choose_without_query")}}
    outcomes = Counter(r["outcome"] for r in check_rows)
    summary = {"completed_steps": len(entries), "memory_cycles": len(memory), "delivered_checks": len(check_rows),
               **{k: outcomes[k] for k in ("exact_source", "different_source", "choose_without_query")},
               "checks_by_source": by_source, "actual_queries_including_clock": sum(actual.values()),
               "different_source_routes": [{"requested_source": requested, "actual_source": queried, "count": n}
                                           for (requested, queried), n in sorted(Counter(
                                               (r["check_source"], r["actual_source"]) for r in check_rows
                                               if r["outcome"] == "different_source").items())],
               "actual_queries_by_source": dict(sorted(actual.items())), "actual_source_diversity": len(actual),
               "actual_queries_without_check": sum(bool(r["actual_source"]) and not r["delivered_check_sources"] for r in cycle_rows),
               "repeated_queries_same_step": sum(r["repeat_query_this_step"] for r in cycle_rows),
               "identical_repeat_replies": sum(r["identical_repeat_reply"] for r in cycle_rows),
               "step_query_count_histogram": dict(sorted(step_histogram.items())),
               "fallback_steps": sum(bool(e.get("fallback_triggered")) for e in entries)}
    arbitration, history, fair_summary = [], [], None
    if fair:
        arbitration, history = fair.rows, fair.history
        require(Counter(h["source"] for h in history if h["event"] == "queried") == actual,
                "Fair actual-query history does not reconcile to trajectory")
        columns = ("candidate_intentions", "selected_source", "shared_source", "shared_intentions", "deferred_source", "deferred_intentions", "priority_source")
        fair_summary = {"selection_events": sum(e["event"] == "selection" for e in fair.log),
                        "capability_resets": fair.epoch, "candidate_source_groups": len(arbitration),
                        **{k: sum(r[k] for r in arbitration) for k in columns},
                        "by_source": {s: {"candidate_source_groups": sum(r["source"] == s for r in arbitration),
                                          **{k: sum(r[k] for r in arbitration if r["source"] == s) for k in columns}}
                                      for s in sorted({r["source"] for r in arbitration})},
                        "actual_queried_by_source": dict(sorted(actual.items()))}
    require(all(digest(path / name) == value for name, value in raw.items()), "Raw input changed during audit")
    # Recheck frozen sources too: a read-only report must not bless a moving run.
    verify_inputs(path, raw)
    return {"format_version": 1, "artifact_consistency": "PASS", "run_dir": str(path),
            "policy_variant": variant, "query_handoff": "explicit" if explicit else "legacy",
            "created_at_utc": datetime.now(timezone.utc).isoformat(), "raw_sha256": raw,
            "expected_raw_hashes_verified": dict(expected_hashes or {}),
            "source_sha256": manifest["source_sha256"], "auditor_sha256": digest(Path(__file__)),
            "summary": summary, "fair_arbitration": fair_summary, "cycles": cycle_rows,
            "checks": check_rows, "arbitration": arbitration, "fair_history": history, "limitations": LIMITS}


def write_report(result, output_dir):
    output = Path(output_dir).resolve()
    run = Path(result["run_dir"])
    require(output != run and not output.is_relative_to(run), "Report output must be outside the input run")
    output.mkdir(parents=True, exist_ok=False)
    (output / "ANALYSIS.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    for name in ("cycles", "checks", "arbitration", "fair_history"):
        rows = result[name]
        if rows:
            with (output / (name + ".csv")).open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                                 for k, v in row.items()} for row in rows)
    s = result["summary"]
    lines = ["# Completed-run query-flow audit", "", f"Input: `{result['run_dir']}`.", "",
             "Artifact alignment: **PASS**. This is not a performance or causal-improvement result.", "",
             f"{s['memory_cycles']} cycles across {s['completed_steps']} steps; {s['delivered_checks']} delivered CHECKs.", "",
             "| Requested source | CHECKs | Exact source next | Different source next | Choose without query |",
             "|---|---:|---:|---:|---:|"]
    for source, row in s["checks_by_source"].items():
        lines.append(f"| {source.replace('|', '&#124;')} | {row['checks']} | {row['exact_source']} | {row['different_source']} | {row['choose_without_query']} |")
    lines += [f"| Total | {s['delivered_checks']} | {s['exact_source']} | {s['different_source']} | {s['choose_without_query']} |", "",
              f"Actual queries: **{s['actual_queries_including_clock']}**, including **{s['actual_queries_by_source'].get('clock', 0)} clock**; "
              f"{s['actual_source_diversity']} distinct sources; {s['repeated_queries_same_step']} same-step repeats "
              f"({s['identical_repeat_replies']} identical replies).", "",
              "Actual source counts: `" + json.dumps(s["actual_queries_by_source"]) + "`.", "",
              "The final cycle is matched to the executed trajectory choice, not invented raw actor JSON."]
    if result["fair_arbitration"]:
        f = result["fair_arbitration"]
        lines += ["", f"V5 arbitration: {f['candidate_intentions']} candidate intention rows in {f['candidate_source_groups']} "
                  f"cycle/source groups; {f['selected_source']} selected groups ({f['shared_source']} shared by multiple intentions); "
                  f"{f['shared_intentions']} additional intentions shared selected sources; "
                  f"{f['deferred_source']} deferred groups ({f['deferred_intentions']} intentions).",
                  "Actual query history was replayed separately from offers, including repeats and substitutions."]
    lines += ["", "CSV rows and verified fingerprints are in this directory; full details are in [ANALYSIS.json](ANALYSIS.json).", "",
              "## Limits", "", *["- " + item for item in LIMITS]]
    (output / "README.md").write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path, help="fresh directory outside the input run")
    parser.add_argument("--expected-hashes", type=Path, help="optional JSON mapping of raw filenames to previously recorded SHA256")
    args = parser.parse_args(argv)
    try:
        result = audit_run(args.run, expected_hashes=read_json(args.expected_hashes) if args.expected_hashes else None)
        write_report(result, args.output)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f"Query-flow audit FAILED: {exc}\n")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
