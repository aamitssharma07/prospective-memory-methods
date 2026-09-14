"""Live-model diagnostic on fixed independent natural-language event streams.

Gold labels are scorer-only. The model receives instruction/observation fields
through the same portable policy used by environment adapters. This measures
trigger proposals aligned by instruction provenance, not action execution or
semantic action-description correctness. ACTs are not executed/acknowledged.
"""

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time
from urllib.request import Request, urlopen

from .core import Engine, Instruction, Observation
from .llm import LLMMemoryPolicy


def counts(predictions, expected):
    predicted, gold = Counter(predictions), Counter(expected)
    tp = sum((predicted & gold).values())
    return {"tp": tp, "fp": sum(predicted.values()) - tp, "fn": sum(gold.values()) - tp}


def metrics(tp, fp, fn):
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}


def evaluate_case(case, request, log=None, max_query_rounds=1):
    """Run one isolated memory bank; expected labels are read only for scoring."""
    if type(max_query_rounds) is not int or max_query_rounds < 0:
        raise ValueError("max_query_rounds must be a nonnegative integer")
    policy = LLMMemoryPolicy(request)
    engine = Engine(policy.compile, policy.assess, sources=case["sources"],
                    queryable_sources=case["queryable_sources"], query_budget=1)
    for raw in case["instructions"]:
        engine.ingest(Instruction(**raw))
    registration_state = engine.snapshot()
    rows, executed_queries = [], 0
    for tick in case["ticks"]:
        for raw in tick.get("instructions", []):
            engine.ingest(Instruction(**raw))
        observations = [Observation(**raw) for raw in tick["observations"]]
        acts, checks, rounds, queried = {}, [], [], set()
        for round_index in range(max_query_rounds + 1):
            decisions = engine.tick(observations, scope=tick.get("scope", ""))
            rounds.append({"round": round_index,
                           "observations": [asdict(o) for o in observations],
                           "decisions": [asdict(d) for d in decisions]})
            for decision in decisions:
                if decision.kind == "ACT":
                    acts.setdefault(decision.intention_id, decision)
                elif decision.kind == "CHECK":
                    checks.append(asdict(decision))
            if round_index == max_query_rounds:
                break
            responses = []
            for decision in decisions:
                if decision.kind != "CHECK" or decision.source in queried:
                    continue
                queried.add(decision.source)
                executed_queries += 1
                source_responses = tick.get("pull_responses", {}).get(decision.source)
                if source_responses is None:
                    responses.append(Observation(
                        f"{tick['id']}_query_{round_index}_{decision.source}",
                        "No current update is available from this source.", source=decision.source))
                else:
                    for raw in source_responses:
                        observation = Observation(**raw)
                        if observation.source != decision.source:
                            raise ValueError("Fixture pull response source does not match requested source")
                        responses.append(observation)
            if not responses:
                break
            # Match PM-Bench's current-source snapshot replacement rule, without
            # importing its adapter or any benchmark task data.
            updated_sources = {item.source for item in responses}
            observations = [item for item in observations if item.source not in updated_sources] + responses
        predictions = [engine.intentions[key].instruction_ids[0] for key in acts]
        expected = list(tick["expected_act_instruction_ids"])
        row = {"case_id": case["id"], "tick_id": tick["id"],
               "predictions": predictions, "expected": expected,
               "acts": [asdict(d) for d in acts.values()], "checks": checks,
               "queried_sources": sorted(queried), "rounds": rounds,
               **counts(predictions, expected), "state": engine.snapshot()}
        rows.append(row)
        if log is not None:
            log(row)
    totals = {key: sum(row[key] for row in rows) for key in ("tp", "fp", "fn")}
    return {"case_id": case["id"], **metrics(**totals), "ticks": rows,
            "exact_ticks": sum(row["fp"] == row["fn"] == 0 for row in rows),
            "executed_queries": executed_queries, "engine_errors": engine.errors,
            "registration_state": registration_state, "final_state": engine.snapshot()}


class LocalModelRequest:
    """Minimal local inference transport; provider/package independent policy."""

    def __init__(self, base_url, model, max_tokens, calls):
        self.base_url, self.model, self.max_tokens, self.calls = base_url, model, max_tokens, calls
        self.context = {}
        self.usage = Counter()
        self.call_count = 0
        self.transport_or_decode_errors = 0

    def __call__(self, system, payload, schema):
        phase = "compile" if "changes" in schema["properties"] else "assess"
        body = {"model": self.model, "temperature": 0.0, "max_tokens": self.max_tokens,
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": "portable_memory_output", "strict": True, "schema": schema}},
                "chat_template_kwargs": {"enable_thinking": False},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": json.dumps(payload)}]}
        record = {**self.context, "phase": phase, "payload": payload}
        started = time.monotonic()
        self.call_count += 1
        try:
            http_request = Request(self.base_url.rstrip("/") + "/chat/completions",
                                   data=json.dumps(body).encode(),
                                   headers={"Content-Type": "application/json"})
            with urlopen(http_request, timeout=180) as response:
                value = json.load(response)
            choice = value["choices"][0]
            raw = choice["message"]["content"] or ""
            usage = value.get("usage") or {}
            self.usage.update({key: usage.get(key, 0) or 0 for key in
                               ("prompt_tokens", "completion_tokens", "total_tokens")})
            record.update(raw=raw, finish_reason=choice.get("finish_reason"), usage=usage)
            return json.loads(raw)
        except Exception as exc:
            self.transport_or_decode_errors += 1
            record["error"] = str(exc)
            raise
        finally:
            record["elapsed_seconds"] = time.monotonic() - started
            self.calls.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.calls.flush()


def validate_cases(dataset):
    if dataset.get("version") != 1 or not dataset.get("cases"):
        raise ValueError("Expected nonempty version-1 case collection")
    seen = set()
    for case in dataset["cases"]:
        if case["id"] in seen:
            raise ValueError("Duplicate case ID")
        seen.add(case["id"])
        initial = {raw["id"] for raw in case["instructions"]}
        if len(initial) != len(case["instructions"]):
            raise ValueError("Duplicate initial instruction ID")
        Engine(None, None, case["sources"], queryable_sources=case["queryable_sources"])
        for tick in case["ticks"]:
            if set(tick["expected_act_instruction_ids"]) - initial:
                raise ValueError("Gold labels must identify initial instructions")
            for raw in tick["observations"]:
                if Observation(**raw).source not in case["sources"]:
                    raise ValueError("Unknown fixture observation source")
            for source, responses in tick.get("pull_responses", {}).items():
                if source not in case["queryable_sources"]:
                    raise ValueError("Pull fixture for nonqueryable source")
                if any(Observation(**raw).source != source for raw in responses):
                    raise ValueError("Pull fixture source mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).parent / "examples/semantic_cases_v1.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="Qwen/Qwen3-8B")
    parser.add_argument("--base-url", default="http://127.0.0.1:30002/v1")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--max-query-rounds", type=int, default=1)
    args = parser.parse_args()
    if args.max_tokens < 1 or args.max_query_rounds < 0:
        parser.error("Positive token allowance and nonnegative query rounds required")
    raw_cases = args.cases.read_bytes()
    dataset = json.loads(raw_cases)
    validate_cases(dataset)
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    manifest = {**{key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
                "started_at": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
                "temperature": 0.0, "enable_thinking": False, "query_budget_per_assessment": 1,
                "semantic_action_accuracy_evaluated": False, "execution_success_evaluated": False,
                "cases_sha256": hashlib.sha256(raw_cases).hexdigest(),
                "policy_hashes": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                                  for name in ("prospective_memory/core.py", "prospective_memory/llm.py")},
                "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "protocol": "ACT proposals aligned by original instruction provenance; no execution/acknowledgement; no labels in model input"}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    # Snapshot the fixed fixture rather than relying on a mutable source path.
    (args.output / "cases.json").write_text(json.dumps(dataset, indent=2))
    started, results = time.monotonic(), []
    with (args.output / "calls.jsonl").open("w") as calls, (args.output / "trace.jsonl").open("w") as trace:
        request = LocalModelRequest(args.base_url, args.model, args.max_tokens, calls)
        for case in dataset["cases"]:
            request.context = {"case_id": case["id"]}
            print(f"Starting {case['id']}", flush=True)
            def log(row):
                trace.write(json.dumps(row, ensure_ascii=False) + "\n")
                trace.flush()
            result = evaluate_case(case, request, log=log, max_query_rounds=args.max_query_rounds)
            results.append(result)
            (args.output / "case_results.json").write_text(json.dumps(results, indent=2))
            print(f"Completed {case['id']}: TP={result['tp']} FP={result['fp']} FN={result['fn']}", flush=True)
        totals = {key: sum(case[key] for case in results) for key in ("tp", "fp", "fn")}
        summary = {"status": "completed", "evaluation": "live-model trigger-proposal diagnostic, not execution benchmark",
                   **metrics(**totals), "case_count": len(results),
                   "tick_count": sum(len(case["ticks"]) for case in results),
                   "exact_ticks": sum(case["exact_ticks"] for case in results),
                   "executed_queries": sum(case["executed_queries"] for case in results),
                   "engine_errors": sum(len(case["engine_errors"]) for case in results),
                   "model_calls": request.call_count, "usage": dict(request.usage),
                   "transport_or_decode_errors": request.transport_or_decode_errors,
                   "elapsed_seconds": time.monotonic() - started,
                   "completed_at": datetime.now(timezone.utc).isoformat()}
        (args.output / "metrics.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
