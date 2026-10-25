"""Two-call GPT comparison of a saved CHECK handoff; never a benchmark run."""

import argparse
import copy
import hashlib
import json
from pathlib import Path

from run import pm_bench, source_files
from adapter import RGPMAdapter
from artifacts import Session, digest, rows, save
from analyze import cost_summary, index_artifacts
from query_uptake_probe import cases_from_run


MODEL = "openai/gpt-5.4"
BASE_URL = "https://openrouter.ai/api/v1"


def probe(args, client=None):
    input_run = Path(args.input_run)
    cases = [case for case in cases_from_run(input_run, max_cases=1000000)
             if case["original_call_id"] == args.source_call_id]
    if len(cases) != 1:
        raise ValueError("Select exactly one saved skipped-CHECK call with remaining budget")
    case = cases[0]
    original = case["request"]
    if original.get("model") != MODEL or original.get("max_tokens") != 768 or original.get("temperature") != 0:
        raise ValueError("Replay requires a saved GPT-5.4 request at temperature=0 and max_tokens=768")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    inputs = {name: digest(input_run / name) for name in ("memory.jsonl", "calls.jsonl", "manifest.json")}
    files = source_files()
    root = Path(__file__).resolve().parents[2]
    config = {"kind": "gpt_paired_handoff_diagnostic", "model": MODEL, "base_url": BASE_URL,
              "max_tokens": 768, "temperature": 0, "max_actor_calls": 2, "max_actor_tokens": 20000,
              "source_call_id": args.source_call_id, "input_run": str(input_run.resolve()),
              "input_sha256": inputs, "source_sha256": {str(p.relative_to(root)): digest(p) for p in files},
              "note": "One saved next-action context, two independent requests, no retries, rollout or full-run F1."}
    fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    save(output / "manifest.json", {"schema_version": 1, "fingerprint": fingerprint, **config})
    save(output / "case.json", {key: value for key, value in case.items() if key != "request"})
    for path in files:
        target = output / "source" / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    session = Session(output, fingerprint, max_actor_calls=2, max_actor_tokens=20000)
    results = {"schema_version": 1, "status": "in_progress", "step_key": case["step_key"],
               "source_call_id": args.source_call_id, "variants": {}}
    save(output / "results.json", results)
    try:
        client = client or pm_bench.build_llm_client("openrouter", base_url=BASE_URL)
        if hasattr(client, "with_options"):
            client = client.with_options(max_retries=0, timeout=180)
        session.begin_step(*case["step_key"])
        for variant in ("original", "query_first"):
            session.operation(variant)
            request = copy.deepcopy(original)
            if variant == "query_first":
                request["messages"][-1]["content"] += "\n" + RGPMAdapter.render_query_plan(case["plan"])
            response = session.call(client, "actor", **request)
            action = json.loads(response.choices[0].message.content)
            source = "clock" if action.get("action") == "check_time" else action.get("channel")
            results["variants"][variant] = {
                "action": action, "followed": action.get("action") in {"query_state", "check_time"}
                and source == case["plan"]["next_action"]["channel"]}
            save(output / "results.json", results)
        results.update(status="complete", note="A single next-action pair cannot establish F1 improvement or reproducibility.")
        save(output / "results.json", results)
        session.event("complete")
        session.status("complete")
        return results
    except BaseException as exc:
        from artifacts import ActorBudgetExceeded
        state = "interrupted" if isinstance(exc, (KeyboardInterrupt, InterruptedError, ActorBudgetExceeded)) else "failed"
        results.update(status=state, error={"type": type(exc).__name__, "message": str(exc)})
        save(output / "results.json", results)
        session.event(state, error=results["error"])
        session.status(state)
        raise
    finally:
        calls = rows(output / "calls.jsonl")
        costs = [call["usage"]["cost"] for call in calls if isinstance(call.get("usage"), dict)
                 and type(call["usage"].get("cost")) in (int, float)]
        save(output / "cost.json", {"schema_version": 1, "all_attempts": cost_summary(calls),
             "provider_reported_cost_usd": sum(costs) if costs else None,
             "calls_with_reported_cost": len(costs), "cost_total_is_partial": len(costs) != len(calls)})
        index_artifacts(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-run", type=Path, required=True)
    parser.add_argument("--source-call-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(probe(parser.parse_args()), indent=2))
