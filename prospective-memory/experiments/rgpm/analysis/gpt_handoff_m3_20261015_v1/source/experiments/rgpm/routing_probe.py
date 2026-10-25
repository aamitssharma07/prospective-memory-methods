"""Live helper-only source-routing diagnostics, separate from benchmark scoring."""

import argparse
import json
from pathlib import Path

from run import local_url, pm_bench
from artifacts import Session, digest, save
from source_routing import route_specifications


CASES = [
    ("background_email", "An email may arrive. Move the crate when the loading light turns green.",
     "Move the crate", "when the loading light turns green", ["events"]),
    ("action_destination", "Send a calendar invitation when a visitor reaches the desk.",
     "Send a calendar invitation", "when a visitor reaches the desk", ["events"]),
    ("provider_evidence", "Phone reception when the inspection board posts clearance.",
     "Phone reception", "when the inspection board posts clearance", ["inspection_board"]),
    ("combined_prerequisites", "Sign the form when the clock reads 14:40 and approval arrives by email.",
     "Sign the form", "when the clock reads 14:40 and approval arrives by email", ["clock", "email"]),
    ("calendar_evidence", "Collect the permit when the calendar lists the appointment.",
     "Collect the permit", "when the calendar lists the appointment", ["calendar"]),
    ("provider_no_action_monitoring", "When the inspection board reports a passed test, open the valve.",
     "open the valve", "When the inspection board reports a passed test", ["inspection_board"]),
    ("scene_and_provider", "Send an email when the badge is handed over and the calendar lists the visitor.",
     "Send an email", "when the badge is handed over and the calendar lists the visitor", ["events", "calendar"]),
    ("quoted_channel_fact", "The inspection is cleared. File the memo now.",
     "File the memo now", "The inspection is cleared", ["inspection_board"],
     {"source": "inspection_board", "public_message_id": "public_provider_reply"}),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    local_url(args.base_url)
    args.output.mkdir(parents=True, exist_ok=False)
    routing_source = Path(__file__).with_name("source_routing.py")
    manifest = {"kind": "helper_source_routing_diagnostic", "model": args.model,
                "max_tokens": 768, "temperature": 0, "enable_thinking": False,
                "probe_sha256": digest(__file__), "routing_sha256": digest(routing_source),
                "note": "Generic development diagnostics; passing does not establish benchmark improvement."}
    save(args.output / "manifest.json", manifest)
    save(args.output / "cases.json", CASES)
    for source in (Path(__file__), routing_source):
        (args.output / source.name).write_bytes(source.read_bytes())
    session = Session(args.output, manifest["routing_sha256"])
    client = pm_bench.build_llm_client("sglang", base_url=args.base_url).with_options(max_retries=0, timeout=180)

    def request(system, payload, schema):
        session.operation("source_routing")
        response = session.call(client, "helper", model=args.model, temperature=0, max_tokens=768,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload)}],
            response_format={"type": "json_schema", "json_schema": {
                "name": "rgpm_helper", "strict": True, "schema": schema}},
            extra_body={"chat_template_kwargs": {"enable_thinking": False}})
        return json.loads(response.choices[0].message.content)

    results = []
    for case in CASES:
        name, quote, action, condition, expected = case[:5]
        session.begin_step("routing_diagnostic", name)
        payload = {"operations": [{"operation_id": "request_1", "source_unit_id": "u1",
                    "operation": "new_request", "complete_request_quote": quote}],
                   "available_sources": ["events", "clock", "email", "calendar", "inspection_board"]}
        if len(case) == 6:
            payload["instruction_origin"] = case[5]
        # Empty input sources ensure a retained/failed routing cannot pass a case.
        reply = {"specifications": [{"operation_id": "request_1", "target_id": "",
                  "requested_action": action, "trigger_condition": condition,
                  "clock_relation": "none", "watched_sources": []}]}
        result = route_specifications(reply, payload, request, session.event)
        selected = result["specifications"][0]["watched_sources"]
        results.append({"case": name, "expected_sources": expected, "selected_sources": selected,
                        "passed": set(expected) == set(selected)})
    passed = all(r["passed"] for r in results)
    save(args.output / "results.json", {"passed": passed, "cases": results})
    session.status("complete" if passed else "failed")
    print(json.dumps({"passed": passed, "cases": results}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
