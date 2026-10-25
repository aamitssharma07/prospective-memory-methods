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
import io
import json
from pathlib import Path
import platform
import re
import time
from urllib.request import Request, urlopen

from ..core import Engine, Instruction, Observation
from ..decoding import WHITESPACE_REMEDY, probe_compact_decoding, unbounded_whitespace
from ..grounded import make_policy


def counts(predictions, expected):
    predicted, gold = Counter(predictions), Counter(expected)
    tp = sum((predicted & gold).values())
    return {"tp": tp, "fp": sum(predicted.values()) - tp, "fn": sum(gold.values()) - tp}


def metrics(tp, fp, fn):
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}


ACTION_PREFIX = re.compile(
    r"\b(?:remind|notify|alert|tell)\s+me\s+to\s+(.+?)(?:[.!?]|$)", re.IGNORECASE)
STOPWORDS = {
    "a", "about", "an", "and", "are", "as", "at", "be", "can", "for", "has",
    "have", "i", "if", "in", "is", "it", "me", "my", "of", "on", "or", "the",
    "that", "to", "when", "with",
}
GENERIC_ACTIONS = {
    "alert", "alert me", "notify", "notify me", "remind", "remind me",
    "send a reminder", "send reminder", "tell me",
}


def normalized_words(text):
    return [word for word in re.findall(r"[a-z0-9]+", text.lower())
            if word not in STOPWORDS and len(word) > 2]


def expected_action_from_instruction(text):
    match = ACTION_PREFIX.search(text)
    return match.group(1).strip() if match else ""


def action_diagnostics(case, registration_state):
    """Heuristic, scorer-only check for action collapse such as action='remind'."""
    instruction_text = {raw["id"]: raw["text"] for raw in case["instructions"]}
    rows = []
    for intention in registration_state["intentions"]:
        original_id = intention["instruction_ids"][0]
        expected = expected_action_from_instruction(instruction_text.get(original_id, ""))
        action = intention["action"]
        action_words, expected_words = set(normalized_words(action)), set(normalized_words(expected))
        keyword_recall = (len(action_words & expected_words) / len(expected_words)
                          if expected_words else None)
        generic = action.strip().lower() in GENERIC_ACTIONS
        preserved = bool(expected_words) and not generic and keyword_recall >= 0.5
        rows.append({"intention_id": intention["id"], "instruction_id": original_id,
                     "stored_action": action, "expected_action_hint": expected,
                     "generic_action": generic, "keyword_recall": keyword_recall,
                     "action_preserved": preserved})
    return rows


def evaluate_case(case, request, log=None, max_query_rounds=1, policy_variant='legacy'):
    """Run one isolated memory bank; expected labels are read only for scoring."""
    if type(max_query_rounds) is not int or max_query_rounds < 0:
        raise ValueError("max_query_rounds must be a nonnegative integer")
    policy = make_policy(request, policy_variant)
    engine = Engine(policy.compile, policy.assess, sources=case["sources"],
                    queryable_sources=case["queryable_sources"], query_budget=1)
    silent_drops = []

    def ingest(raw):
        """An instruction yielding no change, no error and no deliberate
        suppression was lost with no signal anywhere: record it."""
        before = len(engine.errors), len(engine.suppressed)
        changed = engine.ingest(Instruction(**raw))
        if not changed and (len(engine.errors), len(engine.suppressed)) == before:
            silent_drops.append(raw["id"])

    for raw in case["instructions"]:
        ingest(raw)
    registration_state = engine.snapshot()
    action_rows = action_diagnostics(case, registration_state)
    rows, executed_queries = [], 0
    for tick in case["ticks"]:
        for raw in tick.get("instructions", []):
            ingest(raw)
        observations = [Observation(**raw) for raw in tick["observations"]]
        acts, checks, rounds, queried = {}, [], [], set()
        errors_before = len(engine.errors)
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
        tick_errors = engine.errors[errors_before:]
        row = {"case_id": case["id"], "tick_id": tick["id"],
               "predictions": predictions, "expected": expected,
               "assessment_failed": any(row["phase"] == "assess" for row in tick_errors),
               "tick_errors": tick_errors,
               "acts": [asdict(d) for d in acts.values()], "checks": checks,
               "queried_sources": sorted(queried), "rounds": rounds,
               **counts(predictions, expected), "state": engine.snapshot()}
        rows.append(row)
        if log is not None:
            log(row)
    totals = {key: sum(row[key] for row in rows) for key in ("tp", "fp", "fn")}
    # Scorer-only: an instruction the gold labels expect to fire must have been
    # registered. Instructions that never fire are not counted, so this is a
    # lower bound on missed registrations, never an overstatement.
    must_register = {key for tick in case["ticks"]
                     for key in tick["expected_act_instruction_ids"]}
    registered = {key for intention in engine.snapshot()["intentions"]
                  for key in intention["instruction_ids"]}
    missed_registrations = sorted(must_register - registered)
    preserved = sum(item["action_preserved"] for item in action_rows)
    generic = sum(item["generic_action"] for item in action_rows)
    scored = [item["keyword_recall"] for item in action_rows if item["keyword_recall"] is not None]
    return {"case_id": case["id"], **metrics(**totals), "ticks": rows,
            "exact_ticks": sum(row["fp"] == row["fn"] == 0 for row in rows),
            "failed_assessment_ticks": sum(row["assessment_failed"] for row in rows),
            "unscored_quiet_ticks": sum(row["assessment_failed"] and not row["expected"]
                                        for row in rows),
            "executed_queries": executed_queries, "engine_errors": engine.errors,
            "action_diagnostics": action_rows,
            "silent_drop_instruction_ids": silent_drops,
            "suppressed_duplicates": list(engine.suppressed),
            "required_registration_count": len(must_register),
            "missed_registration_ids": missed_registrations,
            "registered_action_count": len(action_rows),
            "preserved_action_count": preserved,
            "generic_action_count": generic,
            "mean_action_keyword_recall": sum(scored) / len(scored) if scored else None,
            "registration_state": registration_state, "final_state": engine.snapshot()}


class LocalModelRequest:
    """Minimal local inference transport; provider/package independent policy."""

    def __init__(self, base_url, model, compile_max_tokens, assess_max_tokens, calls,
                 guided_decoding_backend=""):
        self.base_url, self.model = base_url, model
        self.compile_max_tokens, self.assess_max_tokens = compile_max_tokens, assess_max_tokens
        self.guided_decoding_backend = guided_decoding_backend
        self.last_raw = None
        self.calls = calls
        self.context = {}
        self.usage = Counter()
        self.call_count = 0
        self.transport_or_decode_errors = 0

    def __call__(self, system, payload, schema):
        phase = ("compile" if "changes" in schema["properties"]
                 else "verify" if "verdict" in schema["properties"]
                 else "probe" if "label" in schema["properties"] else "assess")
        max_tokens = (self.compile_max_tokens if phase in {"compile", "probe"}
                      else self.assess_max_tokens)
        body = {"model": self.model, "temperature": 0.0, "max_tokens": max_tokens,
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": "portable_memory_output", "strict": True, "schema": schema}},
                "chat_template_kwargs": {"enable_thinking": False},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": json.dumps(payload)}]}
        if self.guided_decoding_backend:
            body["guided_decoding_backend"] = self.guided_decoding_backend
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
            record.update(raw=raw, finish_reason=choice.get("finish_reason"), usage=usage,
                          max_tokens=max_tokens)
            self.last_raw = raw
            return json.loads(raw)
        except Exception as exc:
            self.transport_or_decode_errors += 1
            record["error"] = str(exc)
            raise
        finally:
            record["elapsed_seconds"] = time.monotonic() - started
            self.calls.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.calls.flush()


def preflight_compact_decoding(request):
    """Probe the live transport, which exposes the raw text as ``last_raw``.

    A probe that fails to decode is itself the symptom: the separator run that
    breaks parsing is exactly what this checks for, so inspect the raw text
    rather than letting the decode error escape as an unrelated failure.
    """
    def generate_raw(system, payload, schema):
        request.last_raw = None
        try:
            request(system, payload, schema)
        except Exception:
            if request.last_raw is None:
                raise
        return request.last_raw
    return probe_compact_decoding(generate_raw)


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
    parser.add_argument("--cases", type=Path, default=Path(__file__).parent.parent / "examples/semantic_cases_v1.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="Qwen/Qwen3-8B")
    parser.add_argument("--base-url", default="http://127.0.0.1:30002/v1")
    parser.add_argument("--max-tokens", type=int,
                        help="Legacy single output-token cap; overrides phase-specific caps.")
    parser.add_argument("--compile-max-tokens", type=int, default=1024)
    parser.add_argument("--assess-max-tokens", type=int, default=768)
    parser.add_argument("--max-query-rounds", type=int, default=1)
    parser.add_argument("--policy", choices=['legacy', 'grounded', 'verified'], default='legacy',
                        help="Registration repair alone (grounded), plus ACT verification (verified), or legacy.")
    parser.add_argument("--guided-decoding-backend", default="",
                        help="Optional per-request vLLM guided-decoding backend. Honoured only "
                             "by the V0 engine; the V1 engine builds one backend from server "
                             "config and ignores per-request options. Prefer starting the "
                             "server with --guided-decoding-backend "
                             "'xgrammar:disable-any-whitespace'.")
    parser.add_argument("--allow-grammar-whitespace", action="store_true",
                        help="Skip the preflight that refuses a server whose JSON grammar "
                             "permits whitespace. Greedy decoding can settle on a newline "
                             "fixed point after a complete field and emit separators until the "
                             "token cap, turning a correct answer into a decode failure.")
    args = parser.parse_args()
    if args.max_tokens is not None:
        args.compile_max_tokens = args.max_tokens
        args.assess_max_tokens = args.max_tokens
    if args.compile_max_tokens < 1 or args.assess_max_tokens < 1 or args.max_query_rounds < 0:
        parser.error("Positive token allowance and nonnegative query rounds required")
    raw_cases = args.cases.read_bytes()
    dataset = json.loads(raw_cases)
    validate_cases(dataset)
    with io.StringIO() as probe_log:
        compact = preflight_compact_decoding(LocalModelRequest(
            args.base_url, args.model, args.compile_max_tokens, args.assess_max_tokens,
            probe_log, guided_decoding_backend=args.guided_decoding_backend))
    if not compact and not args.allow_grammar_whitespace:
        raise SystemExit(WHITESPACE_REMEDY + " Pass --allow-grammar-whitespace "
                         "to record a run without that guarantee.")
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    manifest = {**{key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
                "started_at": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
                "temperature": 0.0, "enable_thinking": False, "query_budget_per_assessment": 1,
                "semantic_action_accuracy_evaluated": False, "execution_success_evaluated": False,
                "action_preservation_diagnostic": "heuristic scorer-only keyword check; not model input",
                "cases_sha256": hashlib.sha256(raw_cases).hexdigest(),
                "policy_hashes": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                                  for name in ("prospective_memory/core.py", "prospective_memory/llm.py",
                                               "prospective_memory/grounded.py")},
                "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "whitespace_free_grammar_verified": compact,
                "protocol": "ACT proposals aligned by original instruction provenance; no execution/acknowledgement; no labels in model input"}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    for name in (*manifest['policy_hashes'], 'prospective_memory/method/evaluate_cases.py'):
        snapshot = args.output / 'source' / name
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes((root / name).read_bytes())
    # Snapshot the fixed fixture rather than relying on a mutable source path.
    (args.output / "cases.json").write_text(json.dumps(dataset, indent=2))
    started, results = time.monotonic(), []
    with (args.output / "calls.jsonl").open("w") as calls, (args.output / "trace.jsonl").open("w") as trace:
        request = LocalModelRequest(args.base_url, args.model, args.compile_max_tokens,
                                    args.assess_max_tokens, calls,
                                    guided_decoding_backend=args.guided_decoding_backend)
        for case in dataset["cases"]:
            request.context = {"case_id": case["id"]}
            print(f"Starting {case['id']}", flush=True)
            def log(row):
                trace.write(json.dumps(row, ensure_ascii=False) + "\n")
                trace.flush()
            result = evaluate_case(case, request, log=log, max_query_rounds=args.max_query_rounds,
                                   policy_variant=args.policy)
            results.append(result)
            (args.output / "case_results.json").write_text(json.dumps(results, indent=2))
            print(f"Completed {case['id']}: TP={result['tp']} FP={result['fp']} FN={result['fn']}", flush=True)
        totals = {key: sum(case[key] for case in results) for key in ("tp", "fp", "fn")}
        action_count = sum(case["registered_action_count"] for case in results)
        required_registrations = sum(case["required_registration_count"] for case in results)
        missed_registrations = sum(len(case["missed_registration_ids"]) for case in results)
        preserved_action_count = sum(case["preserved_action_count"] for case in results)
        generic_action_count = sum(case["generic_action_count"] for case in results)
        action_recalls = [case["mean_action_keyword_recall"] for case in results
                          if case["mean_action_keyword_recall"] is not None]
        summary = {"status": "completed", "evaluation": "live-model trigger-proposal diagnostic, not execution benchmark",
                   **metrics(**totals), "case_count": len(results),
                   "tick_count": sum(len(case["ticks"]) for case in results),
                   "exact_ticks": sum(case["exact_ticks"] for case in results),
                   "executed_queries": sum(case["executed_queries"] for case in results),
                   "failed_assessment_ticks": sum(case["failed_assessment_ticks"]
                                                  for case in results),
                   "unscored_quiet_ticks": sum(case["unscored_quiet_ticks"] for case in results),
                   "silent_drop_count": sum(len(case["silent_drop_instruction_ids"])
                                            for case in results),
                   "required_registration_count": required_registrations,
                   "missed_registration_count": missed_registrations,
                   "registration_recall": ((required_registrations - missed_registrations)
                                           / required_registrations
                                           if required_registrations else None),
                   "registered_action_count": action_count,
                   "preserved_action_count": preserved_action_count,
                   "generic_action_count": generic_action_count,
                   "action_preservation_rate": preserved_action_count / action_count if action_count else None,
                   "mean_case_action_keyword_recall": (sum(action_recalls) / len(action_recalls)
                                                       if action_recalls else None),
                   "engine_errors": sum(len(case["engine_errors"]) for case in results),
                   "model_calls": request.call_count, "usage": dict(request.usage),
                   "transport_or_decode_errors": request.transport_or_decode_errors,
                   "elapsed_seconds": time.monotonic() - started,
                   "completed_at": datetime.now(timezone.utc).isoformat()}
        (args.output / "metrics.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
