#!/usr/bin/env python3
"""Exercise serving and PM-Bench parsers without running an experiment."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sim"))
import pm_bench
import run_todo_ledger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--backend", choices=["sglang", "openrouter"], default="sglang")
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    key = os.environ.get("OPENROUTER_API_KEY") if args.backend == "openrouter" else "None"
    if not key:
        parser.error("OPENROUTER_API_KEY is missing; source .env first")
    client = OpenAI(base_url=args.base_url, api_key=key, timeout=120.0, max_retries=0)
    extra = {"chat_template_kwargs": {"enable_thinking": False}} if args.backend == "sglang" else {}
    listed = [row.id for row in client.models.list().data]
    if args.model not in listed:
        raise RuntimeError(f"Expected {args.model!r} in served models: {listed}")

    plain = client.chat.completions.create(
        model=args.model,
        messages=[{"role": "user", "content": "Reply with exactly: PMBENCH_SMOKE_OK"}],
        temperature=0,
        max_tokens=256,
        extra_body=extra,
    )
    plain_text = plain.choices[0].message.content or ""
    if not plain_text.strip() or plain.choices[0].finish_reason == "length":
        raise RuntimeError("Empty or truncated plain response")

    schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["choose A"]},
            "task_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["action", "task_ids"],
        "additionalProperties": False,
    }
    structured = client.chat.completions.create(
        model=args.model,
        messages=[{
            "role": "user",
            "content": "Return action choose A with one task ID: smoke-task.",
        }],
        temperature=0,
        max_tokens=256,
        extra_body=extra,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "pm_action_smoke", "schema": schema},
        },
    )
    structured_text = structured.choices[0].message.content or ""
    parsed = json.loads(structured_text)
    if parsed != {"action": "choose A", "task_ids": ["smoke-task"]}:
        raise RuntimeError(f"Unexpected structured response: {parsed!r}")

    actual_checks = {}
    for heartbeat in (False, True):
        for handles in (["task_1"], []):
            messages = [{"role": "user", "content":
                'Return a JSON action: action="choose", choice="A", task_ids=[], '
                'channel="NONE". If heartbeat fields are required, set '
                'heartbeat_enabled=false and heartbeat_minutes=30.'}]
            action = pm_bench.request_model_action(
                client, args.model, messages, handles, ["clock"], args.backend,
                allow_heartbeat=heartbeat, max_tokens=768,
            )
            if any(action.get(k) != v for k, v in {
                "action": "choose", "choice": "A", "task_ids": [], "channel": "NONE"
            }.items()):
                raise RuntimeError(f"Unexpected actual PM-Bench action: {action}")
            actual_checks[f"heartbeat={heartbeat},empty_menu={not handles}"] = action
    raw, ledger_usage = run_todo_ledger._call_model(
        client, args.model,
        [{"role": "user", "content":
          'Return JSON: action="choose", choice="A", task_ids=[], channel="NONE", ledger=[]'}],
        args.backend, 0, 768,
        response_schema=run_todo_ledger._build_response_schema(["task_1"], ["clock"]),
    )
    ledger_action, ledger, error = run_todo_ledger._validate_payload(
        pm_bench.parse_json_payload(raw), ["clock"]
    )
    if error or ledger_action["action"] != "choose" or ledger != []:
        raise RuntimeError(f"TODO-ledger validation failed: {error}: {raw}")

    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "model": args.model,
        "backend": args.backend,
        "served_models": listed,
        "plain_response": plain_text,
        "structured_response": parsed,
        "actual_pmbench_responses": actual_checks,
        "todo_ledger_response": raw,
        "todo_ledger_token_usage": ledger_usage,
        "checks": {
            "model_discovery": True,
            "plain_chat_nonempty": bool(plain_text.strip()),
            "json_schema_exact": True,
            "actual_pmbench_parser": True,
            "todo_ledger_parser": True,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"model": args.model, "checks": payload["checks"],
                      "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
