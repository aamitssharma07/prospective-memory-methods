#!/usr/bin/env python3
"""Verify completed pilot artifacts and generate a three-arm report; no inference."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmark/sim"))
import pm_bench
from prospective_memory.baselines.pis import PISEngine
from prospective_memory.adapters.pmbench import PMBenchAdapter
from score_paired import metric_payload
from summarize_memory_pair import jsonl, summarize


def audit(path):
    result = summarize(path)
    if not result["source_snapshot_hashes_verified"] or not result["scenario_snapshot_hash_verified"]:
        raise ValueError("Snapshot hash mismatch")
    scenario = pm_bench.load_scenario(str(path / "scenario.json"))
    entries, _ = pm_bench.read_log_with_metadata(str(path / "trajectory.jsonl"))
    summary, _, steps = pm_bench.score_log(scenario, entries)
    if metric_payload(summary) != result["metrics"] or steps != result["steps"]:
        raise ValueError("Independent rescoring disagrees")
    result["independent_rescore_verified"] = True
    if (path / "memory_snapshot.json").exists():
        state = json.loads((path / "memory_snapshot.json").read_text())
        adapter = PMBenchAdapter(PISEngine(None))
        adapter.restore(state)
        if json.loads(json.dumps(adapter.snapshot())) != state:
            raise ValueError("Snapshot restoration mismatch")
        result["snapshot_restore_verified"] = True
        bank = state["engine"]
        result["verifier_verdicts"] = dict(Counter(v["verdict"] for v in bank["verification_log"]))
        result["typed_clock_slots"] = dict(Counter(t["clock_op"] for t in bank["triggers"].values()))
        result["board"] = {
            "active_total": sum(b["active"] for b in bank["board_log"]),
            "eligible_total": sum(len(b["eligible"]) for b in bank["board_log"]),
            "max_eligible": max((len(b["eligible"]) for b in bank["board_log"]), default=0),
        }
        calls = jsonl(path / "memory_calls.jsonl")
        result["registration_calls"] = [
            {"instruction_id": c["payload"]["instruction"]["id"],
             "rows": len(json.loads(c["raw"])["changes"])}
            for c in calls if c["phase"] == "compile" and "error" not in c]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory
    environment = json.loads((root / "environment.json").read_text())
    if hashlib.sha256((root / "PROTOCOL.md").read_bytes()).hexdigest() != environment["protocol_sha256"]:
        raise ValueError("Frozen protocol mismatch")
    result = {arm: audit(root / arm) for arm in ("baseline", "pis", "pis_verified")}
    base = result["baseline"]["manifest"]
    common = ("model", "base_url", "scenario_sha256", "max_tokens", "temperature", "fallback")
    if not all(all(r["manifest"][k] == base[k] for k in common) for r in result.values()):
        raise ValueError("Unmatched actor settings")
    left, right = result["pis"]["manifest"], result["pis_verified"]["manifest"]
    if left["source_sha256"] != right["source_sha256"]:
        raise ValueError("Memory arms used different code")
    for key in ("memory_max_tokens", "memory_check_budget", "memory_model", "memory_base_url"):
        if left[key] != right[key]:
            raise ValueError("Unmatched helper settings")
    (root / "ANALYSIS.json").write_text(json.dumps(result, indent=2) + "\n")
    names = {"baseline": "Agent alone", "pis": "PIS-inspired", "pis_verified": "PIS-inspired + source verifier"}
    lines = ["# Qwen3-8B PIS-inspired pilot — 2026-09-22", "",
             "Completed matched 80-step PM-Bench runs; independent paper-inspired implementation,",
             "not an author-code reproduction. See frozen [protocol](PROTOCOL.md).", "",
             "| Arm | TP | FP | FN | Precision | Recall | Set-F1 | Actor queries | Fallback steps |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for arm, r in result.items():
        m = r["metrics"]
        lines.append(f"| {names[arm]} | {m['set_tp']} | {m['set_fp']} | {m['set_fn']} | "
                     f"{m['set_precision']:.1%} | {m['set_recall']:.1%} | {m['set_f1']:.1%} | "
                     f"{sum(m['state_query_calls'].values()) if isinstance(m['state_query_calls'], dict) else m['state_query_calls']} | {r['fallback_steps']} |")
    lines += ["", "TP = on-time correct selections; FP = wrong/not-due selections; FN = missed on-time",
              "occurrences (includes those performed late). Percentages are micro metrics, not task accuracy.",
              "", "## Cost and reliability", "",
              "| Arm | Runtime | Helper calls | Helper tokens | Truncated replies | Helper API/JSON errors |",
              "|---|---:|---:|---:|---:|---:|"]
    for arm, r in result.items():
        lines.append(f"| {names[arm]} | {r['duration_seconds'] / 60:.1f} min | {r['helper_calls']} | "
                     f"{r['helper_tokens_excluding_probe'].get('total_tokens', 0):,} | "
                     f"{r['helper_length_finishes']} | {r['helper_api_or_json_errors']} |")
    lines += ["", "Helper tokens include Form/Revise, Decide and verification calls, but exclude the",
              "grammar probe. Actor tokens are not logged: these are NOT total system tokens.", "",
              "## Diagnostics", ""]
    for arm, r in result.items():
        lines += [f"### {names[arm]}", "",
                  f"- Selections per step, count → number of steps: `{r['actor_selection_cardinality']}`.",
                  f"- Total selected tasks: {r['chosen_tasks']}; late: {r['metrics']['late']}; never done: {r['metrics']['miss']}.",
                  f"- Helper phases: `{r['helper_calls_by_phase']}`.",
                  f"- Engine errors: `{r['engine_errors_by_phase']}`.",
                  f"- Error messages: `{r['engine_error_messages']}`.",
                  f"- Final bank statuses: `{r['bank_statuses']}`.",
                  f"- Verifier verdicts: `{r.get('verifier_verdicts', {})}`.",
                  f"- Board totals: `{r.get('board', {})}`.", ""]
    lines += ["## Interpretation and limits", "",
              "Compare recall and FP alongside F1. A large output-count shift needs a separate",
              "cardinality control before attributing an F1 gain to better remembering. Single",
              "traces on a reused development benchmark are not statistical/generalization evidence.",
              "The two memory arms differ only in optional same-model original-source verification;",
              "their subsequent interaction histories may diverge. The verifier cannot recover",
              "unregistered intentions or false exclusions from typed filtering.", "",
              "The generic helper never sees task menus or hidden due labels. The unchanged actor",
              "resolves handles and retains action authority. PM-Bench provides no authoritative",
              "execution-success feedback; pending entries are not completed from guesses. This",
              "differs from the paper's direct due-set decoder and done-marking. Clock support is",
              "limited to explicit single HH:MM gates; other conditions remain model judgments.", "",
              "Verified: matching actor/helper settings, frozen policy hashes across memory arms,",
              "source/scenario/protocol hashes, independent rescoring, and exact snapshot restore.",
              "Raw manifests, conversations, trajectories, calls and snapshots remain in each arm folder."]
    (root / "RESULTS.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:12]))


if __name__ == "__main__":
    main()
