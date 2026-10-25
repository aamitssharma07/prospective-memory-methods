"""Local helper diagnostics for readiness and fair monitoring; never a GPT actor."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from run import local_url, pm_bench
from artifacts import Session, digest, save
from improved_engine import ImprovedTriggerEngine, BoundedPriorityArbiter
from prospective_memory.baselines.pis import DAYS
from prospective_memory.core import Decision, Instruction, Intention, Observation


CASES = [
    {"name": "current_day_scene", "action": "Carry the toolkit", "condition": "when the service cart reaches the door on Friday",
     "scope": "Friday", "days": ["Friday"], "sources": ["events"],
     "observations": [("events", "The service cart has reached the door.")], "expected": "ACT"},
    {"name": "wrong_day", "action": "Carry the toolkit", "condition": "when the service cart reaches the door on Friday",
     "scope": "Thursday", "days": ["Friday"], "sources": ["events"],
     "observations": [("events", "The service cart has reached the door.")], "expected": "WAIT"},
    {"name": "absent_cue", "action": "Carry the toolkit", "condition": "when the service cart reaches the door on Friday",
     "scope": "Friday", "days": ["Friday"], "sources": ["events"],
     "observations": [("events", "The door is shut. No service cart is here.")], "expected": "WAIT"},
    {"name": "prediction", "action": "Bring the pass", "condition": "when the ferry arrives",
     "sources": ["events"], "observations": [("events", "The ferry is expected to arrive later.")], "expected": "WAIT"},
    {"name": "weekend_recurrence", "action": "Place the bottle on the counter", "condition": "every day when breakfast begins",
     "scope": "Sunday", "days": list(DAYS), "repeat": True, "sources": ["events"],
     "observations": [("events", "You begin eating breakfast.")], "expected": "ACT"},
    {"name": "strict_threshold_positive", "action": "Transfer emergency funds", "condition": "when the current account balance is below 95 dollars",
     "sources": ["bank_balance"], "observations": [("bank_balance", "Current account balance: 94 dollars.")], "expected": "ACT"},
    {"name": "threshold_equality", "action": "Transfer emergency funds", "condition": "when the current account balance is below 95 dollars",
     "sources": ["bank_balance"], "observations": [("bank_balance", "Current account balance: 95 dollars.")], "expected": "WAIT"},
    {"name": "missing_approval", "action": "Sign the form", "condition": "when the light is green and approval has arrived by email",
     "sources": ["events", "email"], "observations": [("events", "The light is green."), ("email", "Approval is still pending.")],
     "expected": "WAIT"},
    {"name": "conjunction_positive", "action": "Sign the form", "condition": "when the light is green and approval has arrived by email",
     "sources": ["events", "email"], "observations": [("events", "The light is green."), ("email", "Approval has just arrived.")],
     "expected": "ACT"},
    {"name": "historical_occurrence", "action": "Call the coordinator", "condition": "when an approval email arrives today",
     "scope": "Friday", "sources": ["email"],
     "observations": [("email", "Historical entry: approval email arrived Thursday at 10:00. No new approval today.")], "expected": "WAIT"},
    {"name": "clock_before_gate", "action": "Call the coordinator", "condition": "at 10:00",
     "clock_op": "at", "clock_time": "10:00", "sources": ["clock"],
     "observations": [("clock", "09:30")], "expected": "WAIT"},
    {"name": "explicit_deadline", "action": "Submit the form", "condition": "when approval arrives before 10:00",
     "sources": ["email", "clock"], "observations": [("email", "Approval arrived today at 10:15."), ("clock", "10:15")],
     "expected": "WAIT"},
    {"name": "useful_missing_source", "action": "File the invoice", "condition": "when approval arrives by email",
     "sources": ["email"], "observations": [("events", "The room is quiet.")], "expected": "CHECK"},
    {"name": "activity_not_clock", "action": "Put the cup on the table", "condition": "when breakfast begins",
     "sources": ["events"], "observations": [("events", "You are reviewing notes. No meal has started."), ("clock", "08:50")],
     "expected": "WAIT"},
]


def fixture_engine(case, request, projector_id, *, projected=True):
    sources = ("events", "clock", "email", "bank_balance")
    engine = ImprovedTriggerEngine(request, sources=sources, queryable_sources=sources[1:],
                                   projector_id=projector_id, projection_batch_size=1,
                                   scope_grounding=True, bounded_priority=True)
    condition, action = case["condition"], case["action"]
    text = action + " " + condition + "."
    trigger = {"days": case.get("days", []), "clock_op": case.get("clock_op", "none"),
               "clock_time": case.get("clock_time", "")}
    engine.instructions["public_request"] = Instruction("public_request", text)
    engine.intentions["pm_000001"] = Intention(
        "pm_000001", action, condition + engine._slot_suffix(trigger), tuple(case["sources"]),
        scope="*", repeat=case.get("repeat", False), instruction_ids=("public_request",), evidence_quote=text)
    engine.triggers["pm_000001"] = trigger
    engine._next_id = 2
    if projected:
        engine.projections.refresh(list(engine.intentions.values()), engine.instructions)
    engine.begin_step("public_step")
    return engine


def probe(args, client=None):
    local_url(args.base_url)
    args.output = Path(args.output)
    args.output.mkdir(parents=True, exist_ok=False)
    sources = [Path(__file__), Path(__file__).with_name("improved_engine.py")]
    hashes = {p.name: digest(p) for p in sources}
    save(args.output / "manifest.json", {
        "kind": "local_helper_diagnostic", "model": args.model, "base_url": args.base_url,
        "max_tokens": 768, "temperature": 0, "enable_thinking": False, "source_sha256": hashes,
        "note": "Development diagnostics with direct fixture registration; actor and live compiler are exercised separately in smoke."})
    save(args.output / "cases.json", CASES)
    for source in sources:
        (args.output / source.name).write_bytes(source.read_bytes())
    session = Session(args.output, hashes[Path(__file__).name])
    client = client or pm_bench.build_llm_client("sglang", base_url=args.base_url)
    if hasattr(client, "with_options"):
        client = client.with_options(max_retries=0, timeout=180)

    def request(system, payload, schema):
        session.operation("trigger_projection" if "trigger_projections" in schema["properties"] else "assess")
        response = session.call(client, "helper", model=args.model, temperature=0, max_tokens=768,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload)}],
            response_format={"type": "json_schema", "json_schema": {
                "name": "rgpm_helper", "strict": True, "schema": schema}},
            extra_body={"chat_template_kwargs": {"enable_thinking": False}})
        return json.loads(response.choices[0].message.content)

    results = []
    try:
        for case in CASES:
            session.begin_step("helper_diagnostic", case["name"])
            engine = fixture_engine(case, request, args.model + ";diagnostic;max_tokens=768")
            observations = [Observation(f"public_observation_{i}", text, source)
                            for i, (source, text) in enumerate(case["observations"])]
            decisions = engine.tick(observations, scope=case.get("scope", "Monday"))
            decision = decisions[0]
            results.append({"case": case["name"], "expected": case["expected"], "observed": decision.kind,
                            "passed": decision.kind == case["expected"] and not engine.errors,
                            "decision": asdict(decision), "errors": engine.errors})
            save(args.output / "snapshots" / (case["name"] + ".json"), engine.snapshot())
            save(args.output / "results.json", {"passed": False, "cases": results, "status": "in_progress"})
        arbiter = BoundedPriorityArbiter(("clock", "mail", "balance"))
        candidates = [Decision("CHECK", source, "Unknown public prerequisite", source=source)
                      for source in arbiter.queryable_sources]
        offered = [arbiter.arbitrate(candidates, budget=1, priority_sources=("clock",)).selected_sources[0]
                   for _ in range(8)]
        save(args.output / "monitoring.json", {"offered_sources": offered, "history": arbiter.snapshot(),
             "passed": set(offered) == set(arbiter.queryable_sources), "actor_queries": 0})
        passed = all(r["passed"] for r in results) and set(offered) == set(arbiter.queryable_sources)
        save(args.output / "results.json", {"passed": passed, "cases": results, "status": "complete"})
        session.status("complete" if passed else "failed")
        return passed
    except BaseException as exc:
        session.event("probe_error", error={"type": type(exc).__name__, "message": str(exc)})
        session.status("failed")
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    passed = probe(args)
    print(json.dumps({"passed": passed, "output": str(args.output)}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
