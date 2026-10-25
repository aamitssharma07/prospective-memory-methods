"""Local-only development gate for real compiler registration and update failures."""

import argparse
import copy
from dataclasses import asdict
import json
from pathlib import Path

from run import ROOT, local_url, pm_bench, source_files
from artifacts import Session, digest, save
from analyze import index_artifacts
from improved_engine import ImprovedTriggerEngine
from prospective_memory.baselines.pis_registration import set_extract_spans
from prospective_memory.core import Instruction, Intention
from source_routing import route_specifications
from registration_replay import load_cases, seed_public_state


CASES = [
    {"name": "crowded_plan", "old": ["Move the dentist appointment when a slot opens.",
        "Collect the parcel when the depot opens."],
     "text": "Today's plan:\n- Adjust the seating plan when the room change appears.\n"
             "- Check in with the coordinator at 14:10.\n- Forward the receipt when the email arrives.\n"
             "- Give the briefing when the supervisor arrives.\n- Move the training session when the calendar update arrives.\n"
             "- Collect the visitor badge when reception opens.\n- Send the expense note at 16:45.",
     "new_count": 7, "changed": {}},
    {"name": "return_not_pickup", "old": ["Collect the borrowed projector when the desk opens.",
        "Return the borrowed projector when the return counter opens."],
     "text": "A correction for returning the borrowed projector: instead of the earlier cue, wait for the pickup notice before returning the borrowed projector.",
     "new_count": 0, "changed": {"pm_000002": "revise"}},
    {"name": "reschedule_correct_obligation", "old": ["Move the dentist appointment when a slot opens.",
        "Send the expense note at 16:45."],
     "text": "The timing for sending the expense note has changed. Move sending the expense note to 15:35.",
     "new_count": 0, "changed": {"pm_000002": "revise"}},
    {"name": "missing_update_target", "old": ["Move the dentist appointment when a slot opens."],
     "text": "Change the time for sending the expense note: move it to 15:35.",
     "new_count": 0, "changed": {}, "allow_unresolved": True},
    {"name": "mixed_paragraph", "old": ["Pay the club fee when the invoice arrives."],
     "text": "Cancel paying the club fee. On Friday, buy batteries when you see the supply cart.",
     "new_count": 1, "changed": {"pm_000001": "cancel"},
     "new_quote": "On Friday, buy batteries when you see the supply cart."},
    {"name": "multiple_occasions_one_action", "old": [],
     "text": "Every day, place the water bottle on the table at breakfast and dinner.",
     "new_count": 1, "changed": {}},
    {"name": "provider_cue_is_not_new_request", "old": ["Send the signed form when approval arrives by email."],
     "text": "Approval for the signed form has arrived. Please do it now.", "origin": "email",
     "new_count": 0, "changed": {}},
    {"name": "new_request_in_provider_reply", "old": ["Send the signed form when approval arrives by email."],
     "text": "Please collect the visitor badge tomorrow when reception opens.", "origin": "email",
     "new_count": 1, "changed": {}},
    {"name": "provider_recipient_revision", "old": ["Send the signed form to Morgan when approval arrives by email."],
     "text": "Send the signed form to Lee instead of Morgan, still only after approval arrives by email.",
     "origin": "email", "new_count": 0, "changed": {"pm_000001": "revise"}},
    {"name": "provider_additional_occasion", "old": ["Send a status report on Monday at 10:00."],
     "text": "Keep the Monday status report. Also send a separate status report on Friday at 14:00.",
     "origin": "email", "new_count": 1, "changed": {}},
    {"name": "provider_reference_paraphrase", "old": ["Start the inspection when the permit is granted."],
     "text": "The inspection permit has been granted. Go ahead with it.", "origin": "email",
     "new_count": 0, "changed": {}},
    {"name": "provider_explicit_activation", "old": ["Unlock the cabinet when authorization arrives."],
     "text": "Authorization has arrived. Unlock the cabinet now.", "origin": "email",
     "new_count": 0, "changed": {}},
    {"name": "provider_same_cue_different_action", "old": ["Notify Alex when the room becomes available."],
     "text": "The room has become available. Please book it for tomorrow's workshop.", "origin": "email",
     "new_count": 1, "changed": {}},
]


def evaluate(case, before, engine):
    changed = {key: ("cancel" if engine.intentions[key].status == "cancelled" else "revise")
               for key, old in before.items() if engine.intentions[key] != old}
    additions = [i for key, i in engine.intentions.items() if key not in before]
    quote_ok = not case.get("new_quote") or any(i.evidence_quote == case["new_quote"] for i in additions)
    terms_ok = all(any(all(term.lower() in (i.action + " " + i.condition).lower() for term in terms)
                      for i in additions) for terms in case.get("required_new_terms", []))
    unresolved = [e for e in engine.errors if e["phase"] != "registration_classification_invalid"
                  and not (case.get("allow_unresolved", False) and e["phase"] == "v3_unit_classification"
                           and e["error"] == "Update has no unique supported pending target")]
    passed = (len(additions) == case["new_count"] and changed == case["changed"] and quote_ok and terms_ok
              and not unresolved)
    return {"case": case["name"], "passed": bool(passed), "observed_new_count": len(additions),
            "observed_changes": changed, "expected_new_count": case["new_count"],
            "expected_changes": case["changed"], "errors": engine.errors,
            "source_terms_preserved": terms_ok,
            "new_intentions": [asdict(i) for i in additions]}


def probe(args, client=None):
    local_url(args.base_url)
    replay = getattr(args, "replay_run", None)
    cases = load_cases(replay) if replay else CASES
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    sources = source_files()
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    provenance = json.loads(Path(args.provenance).read_text()) if getattr(args, "provenance", None) else None
    save(output / "manifest.json", {"kind": "local_registration_diagnostic", "model": args.model,
        "max_tokens": 768, "temperature": 0, "source_sha256": hashes,
        "helper_provenance": provenance,
        "replay_trace_sha256": digest(Path(replay) / "memory.jsonl") if replay else None,
        "note": "Development cases motivated by inspected failures; not held-out F1."
                " Pending public requests are seeded; each new input uses the real compiler."})
    save(output / "cases.json", cases)
    for path in sources:
        destination = output / "source" / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())
    session = Session(output, digest(output / "manifest.json"))
    client = client or pm_bench.build_llm_client("sglang", base_url=args.base_url)
    if hasattr(client, "with_options"):
        client = client.with_options(max_retries=0, timeout=180)

    def request(system, payload, schema):
        schema = copy.deepcopy(schema)
        for key, count in {"unit_classifications": 1, "identity_reviews": 1,
                           "specifications": len(payload.get("operations", [])),
                           "trigger_projections": len(payload.get("records", []))}.items():
            if key in schema["properties"] and count:
                schema["properties"][key].update(minItems=count, maxItems=count)
        phase = ("source_routing" if set(schema["properties"]) == {"status", "watched_sources", "reason"}
                 else next(iter(schema["properties"])))
        if payload.get("classification_repair"):
            phase = "registration_repair"
        elif payload.get("classification_review"):
            phase = "registration_review"
        session.operation(phase)
        response = session.call(client, "helper", model=args.model, temperature=0, max_tokens=768,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload)}],
            response_format={"type": "json_schema", "json_schema": {
                "name": "registration_probe", "strict": True, "schema": schema}},
            extra_body={"chat_template_kwargs": {"enable_thinking": False}})
        value = json.loads(response.choices[0].message.content)
        if "specifications" in schema["properties"]:
            value = route_specifications(value, payload, request, session.event)
        return value

    results = []
    try:
        set_extract_spans(True)
        for case in cases:
            session.begin_step("registration_diagnostic", case["name"])
            state = case.get("initial_state", {})
            engine = ImprovedTriggerEngine(request, sources=tuple(state.get("sources", ("events", "email", "calendar", "clock"))),
                queryable_sources=tuple(state.get("queryable_sources", ("email", "calendar", "clock"))),
                projector_id=provenance["projector_id"] if provenance else args.model + ";max_tokens=768",
                registration_grounding=True, scope_grounding=True, bounded_priority=True)
            engine.begin_step(case["name"])
            for number, text in enumerate(case.get("old", []), 1):
                key, source = f"pm_{number:06d}", f"old_{number}"
                engine.instructions[source] = Instruction(source, text, "Monday")
                engine.intentions[key] = Intention(key, text, text, ("events", "email", "clock"),
                    scope="*", instruction_ids=(source,), evidence_quote=text)
                engine.triggers[key] = {"days": [], "clock_op": "none", "clock_time": ""}
            engine._next_id = len(case.get("old", [])) + 1
            if state:
                seed_public_state(engine, state)
            before = dict(engine.intentions)
            message_id = case.get("instruction_id", "new_message")
            engine.instruction_sources[message_id] = case.get("origin", "events")
            engine.ingest(Instruction(message_id, case["text"], case.get("scope", "Monday")))
            result = evaluate(case, before, engine)
            results.append(result)
            save(output / "snapshots" / (case["name"] + ".json"), engine.snapshot())
            session.append("results.jsonl", result)
            save(output / "results.json", {"passed": False, "status": "running", "cases": results})
        passed = all(r["passed"] for r in results)
        save(output / "results.json", {"passed": passed, "status": "complete", "cases": results})
        session.status("complete" if passed else "failed")
        return passed
    except BaseException as exc:
        session.event("probe_error", error={"type": type(exc).__name__, "message": str(exc)})
        session.status("failed")
        raise
    finally:
        index_artifacts(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--replay-run", type=Path)
    args = parser.parse_args()
    passed = probe(args)
    print(json.dumps({"passed": passed, "output": str(args.output)}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
