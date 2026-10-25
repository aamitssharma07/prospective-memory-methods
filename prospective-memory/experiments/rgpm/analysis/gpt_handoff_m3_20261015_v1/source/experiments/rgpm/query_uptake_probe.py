"""Compare old/new CHECK handoffs on saved public prompts using a local actor."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from run import local_url, pm_bench
from adapter import RGPMAdapter
from artifacts import Session, digest, rows, save
from prospective_memory.core import Decision, Intention, Observation


def cases_from_run(input_run, max_cases):
    if type(max_cases) is not int or max_cases <= 0:
        raise ValueError("max_cases must be a positive integer")
    input_run = Path(input_run)
    traces = {(trace["session_id"], trace["cycle"]): trace for trace in rows(input_run / "memory.jsonl")
              if trace["event"] == "memory_cycle"}
    cases = []
    for call in rows(input_run / "calls.jsonl"):
        action = call.get("parsed")
        if (call["role"] != "actor" or not call["valid"] or not isinstance(action, dict)
                or action.get("action") != "choose"):
            continue
        trace = traces.get((call["session_id"], call["cycle"]))
        if trace is None or trace["step_key"] != call["step_key"]:
            continue
        state = trace["after"]
        engine_state = state["engine"]
        engine = SimpleNamespace(
            intentions={i["id"]: Intention(**i) for i in engine_state["intentions"]},
            sources=engine_state["sources"], queryable_sources=engine_state["queryable_sources"],
            step_queries=engine_state["step_queries"], step_query_budget=engine_state["step_query_budget"])
        adapter = RGPMAdapter(engine, guidance="query_first", query_handoff="legacy")
        adapter.scope = state["scope"]
        adapter.current_observations = [Observation(**o) for o in state["current_observations"]]
        adapter.last_decisions = [Decision(**{**d, "evidence_ids": tuple(d["evidence_ids"])})
                                  for d in trace["decisions"]]
        plan = adapter._query_plan()
        if plan is not None:
            messages = call["request"]["messages"]
            if (not messages or messages[-1].get("role") != "user"
                    or messages[-1].get("content") != trace["reminder"]):
                raise ValueError("Saved actor prompt does not end in its recorded memory handoff")
            cases.append({"step_key": call["step_key"], "cycle": call["cycle"],
                          "original_call_id": call["call_id"], "plan": plan,
                          "request": copy.deepcopy(call["request"])})
        if len(cases) >= max_cases:
            break
    return cases


def probe(args, client=None):
    local_url(args.base_url)
    cases = cases_from_run(args.input_run, args.max_cases)
    if not cases:
        raise ValueError("No skipped CHECK with remaining budget found in input run")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    inputs = {name: digest(Path(args.input_run) / name) for name in ("memory.jsonl", "calls.jsonl", "manifest.json")}
    sources = {p.name: digest(p) for p in (Path(__file__), Path(__file__).with_name("adapter.py"))}
    fingerprint = hashlib.sha256(json.dumps({"inputs": inputs, "sources": sources}, sort_keys=True).encode()).hexdigest()
    save(output / "manifest.json", {"kind": "local_actor_handoff_diagnostic", "model": args.model,
         "base_url": args.base_url, "max_tokens": 768, "temperature": 0,
         "input_run": str(Path(args.input_run).resolve()), "input_sha256": inputs,
         "source_sha256": sources,
         "note": "Paired next-action replay on saved public prompts; no simulation, GPT calls or full-run F1."})
    for path in (Path(__file__), Path(__file__).with_name("adapter.py")):
        (output / path.name).write_bytes(path.read_bytes())
    save(output / "cases.json", [{k: v for k, v in case.items() if k != "request"} for case in cases])
    session = Session(output, fingerprint, max_actor_calls=2 * len(cases), max_actor_tokens=500000)
    client = client or pm_bench.build_llm_client("sglang", base_url=args.base_url)
    if hasattr(client, "with_options"):
        client = client.with_options(max_retries=0, timeout=180)
    results = []
    try:
        for case in cases:
            session.begin_step(*case["step_key"])
            result = {k: v for k, v in case.items() if k != "request"}
            for variant in ("original", "query_first"):
                session.operation(variant)
                request = copy.deepcopy(case["request"])
                request.update(model=args.model, temperature=0, max_tokens=768,
                               extra_body={"chat_template_kwargs": {"enable_thinking": False}})
                if variant == "query_first":
                    request["messages"][-1]["content"] += "\n" + RGPMAdapter.render_query_plan(case["plan"])
                response = session.call(client, "actor", **request)
                action = json.loads(response.choices[0].message.content)
                source = "clock" if action.get("action") == "check_time" else action.get("channel")
                result[variant] = {"action": action, "followed": action.get("action") in {"query_state", "check_time"}
                                   and source == case["plan"]["next_action"]["channel"]}
            results.append(result)
            save(output / "results.json", {"passed": False, "status": "in_progress", "cases": results})
        save(output / "results.json", {"passed": True, "status": "complete", "cases": results,
             "followed_counts": {variant: sum(case[variant]["followed"] for case in results)
                                 for variant in ("original", "query_first")},
             "note": "Passed means valid diagnostic responses. Taking every CHECK is not a quality criterion; a fulfilled or irrelevant request may be declined. Inspect each paired action."})
        session.status("complete")
        return True
    except BaseException as exc:
        session.event("probe_error", error={"type": type(exc).__name__, "message": str(exc)})
        session.status("failed")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--max-cases", type=int, default=6)
    args = parser.parse_args()
    passed = probe(args)
    print(json.dumps({"passed": passed, "output": str(args.output)}))
    raise SystemExit(0 if passed else 1)
