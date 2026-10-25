"""Frozen, generic live-helper smoke test; NOT a PM-Bench or actor benchmark.

Gold expectations are scorer-only. A deterministic test host follows valid CHECK
proposals using prewritten responses; ACT is never executed or acknowledged.
Registration, exact proposal sequences and evidence/control boundaries are
reported separately. Passing does not prove semantic correctness or actor uptake.
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
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .core import Instruction, Observation
from .decoding import WHITESPACE_REMEDY, probe_compact_decoding, unbounded_whitespace
from .pis_grounded import GroundedPISEngine
from .method.source_bound import SourceBoundPISEngine
from .method.source_bound_v3 import SourceBoundV3Engine
from .method.trigger_engine import SourceBoundTriggerEngine
from .method.fair_trigger import SourceBoundFairTriggerEngine
from .method.projection_cache import projection_definition


DEFAULT_CASES = Path(__file__).parent / "examples/pis_grounded_smoke_v1.json"
SOURCE_FILES = (
    "prospective_memory/__init__.py", "prospective_memory/core.py",
    "prospective_memory/llm.py", "prospective_memory/baselines/pis.py",
    "prospective_memory/pis_grounded.py", "prospective_memory/decoding.py",
    "prospective_memory/method/source_bound.py", "prospective_memory/baselines/pis_registration.py",
    "prospective_memory/method/calendar_guard.py",
    "prospective_memory/method/source_bound_v3.py", "prospective_memory/method/registration.py",
    "prospective_memory/method/trigger_engine.py", "prospective_memory/method/projection_cache.py",
    "prospective_memory/method/fair_trigger.py", "prospective_memory/method/fair_checks.py",
    "prospective_memory/evaluate_pis_grounded.py",
    "docs/dev_protocols/PIS_GROUNDED_SMOKE_PROTOCOL.md",
    "docs/dev_protocols/PIS_SOURCE_BOUND_PROTOCOL.md", "docs/dev_protocols/TRANSFER_VALIDATION.md",
    "docs/dev_protocols/PIS_SOURCE_BOUND_V3.md",
    "docs/dev_protocols/TRIGGER_ROLE_PROTOCOL.md",
)
PROTECTION_PHASES = {"clock_guard", "change_review", "v2_clock_guard", "v2_day_guard",
                     "v3_clock_guard", "v3_day_guard"}
ENGINES = {"pis_grounded": GroundedPISEngine, "sbpm_minimal": SourceBoundPISEngine,
           "sbpm_no_projection": SourceBoundV3Engine,
           "sbpm_no_arbiter": SourceBoundTriggerEngine,
           "sbpm": SourceBoundFairTriggerEngine}


def projection_options(policy, projector_id=None, projection_batch_size=4):
    """Projection policies require a caller-owned model/config identity, never inferred."""
    if policy not in {SourceBoundTriggerEngine.POLICY, SourceBoundFairTriggerEngine.POLICY}:
        return {}
    if not isinstance(projector_id, str) or not projector_id.strip():
        raise ValueError("--projector-id is required for " + policy + " and must identify model/config")
    if type(projection_batch_size) is not int or not 1 <= projection_batch_size <= 32:
        raise ValueError("--projection-batch-size must be between 1 and 32 for projection policies")
    return {"projector_id": projector_id, "projection_batch_size": projection_batch_size}


class SmokeAbort(BaseException):
    """Infrastructure/budget abort bypasses engine's model-failure containment."""


def unexpected_errors(rows):
    return [row for row in rows if row["phase"] not in PROTECTION_PHASES]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def phase_name(schema):
    properties = schema.get("properties", {})
    for field, phase in (("changes", "compile"), ("reviews", "change_review"),
                         ("operations", "extract"), ("specifications", "compile_typed"),
                         ("unit_classifications", "classify_unit"), ("identity_reviews", "identity_review"),
                         ("trigger_projections", "trigger_projection"),
                         ("assessments", "assess"), ("label", "probe")):
        if field in properties:
            return phase
    return "unknown"


class AuditedRequest:
    """Log every request, raw HTTP response, output, token usage and failure.

    Monetary cost is null unless both per-million token rates are supplied. Local
    GPU electricity/rental cost is not inferable from an OpenAI-compatible reply.
    """

    def __init__(self, base_url, model, max_tokens, calls, timeout=180,
                 input_usd_per_million=None, output_usd_per_million=None, max_calls=300):
        self.base_url, self.model, self.max_tokens = base_url, model, max_tokens
        self.calls, self.timeout, self.context = calls, timeout, {}
        self.rates = (input_usd_per_million, output_usd_per_million)
        self.max_calls = max_calls
        self.call_count = self.error_count = 0
        self.usage, self.phase_counts = Counter(), Counter()
        self.cost_usd = 0.0 if None not in self.rates else None
        self.last_raw = None

    def __call__(self, system, payload, schema):
        if self.call_count >= self.max_calls:
            self.calls.write(json.dumps({"event": "call_budget_abort", **self.context,
                                        "max_calls": self.max_calls, "time": utc_now()}) + "\n")
            self.calls.flush()
            raise SmokeAbort(f"Maximum helper-call budget ({self.max_calls}) exhausted")
        self.last_raw = None
        phase = phase_name(schema)
        body = {"model": self.model, "temperature": 0.0, "max_tokens": self.max_tokens,
                "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": "grounded_pis_smoke", "strict": True, "schema": schema}},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": json.dumps(payload)}]}
        self.call_count += 1
        self.phase_counts[phase] += 1
        row = {"call_id": self.call_count, **self.context, "phase": phase,
               "started_at": utc_now(), "request": body, "system": system,
               "payload": payload, "schema": schema, "usage": {},
               "estimated_token_cost_usd": None, "error": None}
        started = time.monotonic()
        try:
            req = Request(self.base_url.rstrip("/") + "/chat/completions",
                          data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=self.timeout) as response:
                row["http_status"] = response.status
                row["raw_http_response"] = response.read().decode("utf-8", errors="replace")
            value = json.loads(row["raw_http_response"])
            row["response"] = value
            usage = value.get("usage") or {}
            row["usage"] = usage
            self.usage.update({key: usage.get(key, 0) or 0 for key in
                               ("prompt_tokens", "completion_tokens", "total_tokens")})
            if self.cost_usd is not None:
                cost = ((usage.get("prompt_tokens", 0) or 0) * self.rates[0] +
                        (usage.get("completion_tokens", 0) or 0) * self.rates[1]) / 1e6
                self.cost_usd += cost
                row["estimated_token_cost_usd"] = cost
            choice = value["choices"][0]
            self.last_raw = choice["message"]["content"] or ""
            row.update(raw=self.last_raw, finish_reason=choice.get("finish_reason"),
                       repeatable_grammar_whitespace=unbounded_whitespace(self.last_raw))
            decoded = json.loads(self.last_raw)
            row["decoded"] = decoded
            return decoded
        except Exception as exc:
            self.error_count += 1
            row["error"] = {"type": type(exc).__name__, "message": str(exc)}
            if isinstance(exc, HTTPError):
                row["http_status"] = exc.code
                row["raw_http_response"] = exc.read().decode("utf-8", errors="replace")
            if isinstance(exc, (OSError, TimeoutError)):
                raise SmokeAbort("Inference transport unavailable: " + str(exc)) from exc
            raise
        finally:
            row["elapsed_seconds"] = time.monotonic() - started
            self.calls.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.calls.flush()

    def summary(self):
        return {"model_calls_including_preflight": self.call_count,
                "calls_by_phase": dict(self.phase_counts), "usage": dict(self.usage),
                "transport_or_decode_errors": self.error_count,
                "estimated_token_cost_usd": self.cost_usd,
                "cost_note": "Token-price estimate only; local GPU cost is not measured."}


def validate_cases(dataset):
    if dataset.get("version") != 1 or not dataset.get("cases"):
        raise ValueError("Expected nonempty version-1 frozen suite")
    seen_cases = set()
    for case in dataset["cases"]:
        if case["id"] in seen_cases:
            raise ValueError("Duplicate case ID")
        seen_cases.add(case["id"])
        GroundedPISEngine(None, sources=case["sources"],
                          queryable_sources=case["queryable_sources"])
        instruction_ids, observation_ids, tick_ids = set(), set(), set()

        def instructions(rows):
            for raw in rows:
                item = Instruction(**raw)
                if item.id in instruction_ids:
                    raise ValueError("Duplicate instruction ID")
                instruction_ids.add(item.id)

        def records(rows):
            if len({r["origin_id"] for r in rows}) != len(rows):
                raise ValueError("Duplicate expected record origin")
            for row in rows:
                if row["origin_id"] not in instruction_ids:
                    raise ValueError("Record expectation references unknown instruction")
                if set(row.get("instruction_ids", [])) - instruction_ids:
                    raise ValueError("Unknown provenance expectation")
                if set(row.get("required_sources", [])) - set(case["sources"]):
                    raise ValueError("Unknown expected source")

        instructions(case["instructions"])
        records(case["expected_initial_records"])
        if not case["expected_initial_records"]:
            raise ValueError("Smoke cases require explicit positive registration coverage")
        for tick in case["ticks"]:
            if tick["id"] in tick_ids:
                raise ValueError("Duplicate tick ID")
            tick_ids.add(tick["id"])
            instructions(tick.get("instructions", []))
            records(tick["expected_records"])
            if not tick["expected_rounds"]:
                raise ValueError("Expected at least one decision round")
            for expected in tick["expected_rounds"]:
                for row in expected:
                    if row["origin_id"] not in instruction_ids or row["kind"] not in {"WAIT", "CHECK", "ACT"}:
                        raise ValueError("Invalid expected decision")
                    if (row["kind"] == "CHECK") != bool(row.get("source")):
                        raise ValueError("Only CHECK may have a nonempty source")
                    if row.get("source") and row["source"] not in case["queryable_sources"]:
                        raise ValueError("Expected CHECK to unavailable source")
            all_observations = list(tick["observations"])
            for source, responses in tick.get("pull_responses", {}).items():
                if source not in case["queryable_sources"]:
                    raise ValueError("Pull fixture for unavailable source")
                if any(raw["source"] != source for raw in responses):
                    raise ValueError("Pull fixture source mismatch")
                all_observations.extend(responses)
            for raw in all_observations:
                item = Observation(**raw)
                if item.source not in case["sources"] or item.id in observation_ids:
                    raise ValueError("Unknown observation source or duplicate observation ID")
                observation_ids.add(item.id)


def score_records(engine, expected, initial_state):
    """Exact counts/provenance/slots plus explicitly labeled lexical diagnostics."""
    initial = {r["id"]: r for r in initial_state.get("intentions", [])}
    rows = []
    for requirement in expected:
        matches = [i for i in engine.intentions.values()
                   if i.instruction_ids and i.instruction_ids[0] == requirement["origin_id"]]
        checks = {"exactly_one_record": len(matches) == 1}
        if len(matches) == 1:
            item = matches[0]
            checks["status"] = item.status == requirement.get("status", "pending")
            for field in ("instruction_ids", "required_sources"):
                if field in requirement:
                    checks[field] = (list(item.instruction_ids) == requirement[field]
                                     if field == "instruction_ids" else
                                     set(requirement[field]) <= set(item.sources))
            for field in ("clock_op", "clock_time"):
                if field in requirement:
                    checks[field] = engine.triggers[item.id][field] == requirement[field]
            for field in ("action", "condition"):
                fragments = requirement.get(field + "_contains_any")
                if fragments:
                    checks[field + "_lexical_diagnostic"] = any(
                        fragment.lower() in getattr(item, field).lower() for fragment in fragments)
            if requirement.get("preserve_identity"):
                checks["preserve_identity"] = item.id in initial
            if requirement.get("unchanged_from_initial"):
                checks["unchanged_from_initial"] = asdict(item) == initial.get(item.id)
        rows.append({"origin_id": requirement["origin_id"], "checks": checks,
                     "passed": all(checks.values()), "matched_ids": [i.id for i in matches]})
    count_ok = len(engine.intentions) == len(expected)
    return {"passed": count_ok and all(row["passed"] for row in rows),
            "expected_count": len(expected), "actual_count": len(engine.intentions),
            "exact_record_count": count_ok, "rows": rows}


def normalize_decisions(engine, decisions):
    return [{"origin_id": engine.intentions[d.intention_id].instruction_ids[0],
             "kind": d.kind, "source": d.source} for d in decisions]


def decision_counter(rows):
    return Counter((row["origin_id"], row["kind"], row.get("source", "")) for row in rows)


def boundary_errors(engine, decisions, observations):
    current = {o.id: o for o in observations if o.current}
    observed_sources = {o.source for o in current.values()}
    errors = []
    for d in decisions:
        item = engine.intentions[d.intention_id]
        if d.kind == "ACT":
            if (d.source or not d.evidence_ids or any(key not in current for key in d.evidence_ids)
                    or not any(current[key].source in item.sources
                               for key in d.evidence_ids if key in current)):
                errors.append({"decision": asdict(d), "error": "Invalid ACT evidence boundary"})
        if d.kind == "CHECK":
            if (d.evidence_ids or d.source not in engine.queryable_sources
                    or d.source not in item.sources or d.source in observed_sources):
                errors.append({"decision": asdict(d), "error": "Invalid CHECK source boundary"})
    return errors


def run_case(case, request, log=None, max_query_rounds=2, engine_class=GroundedPISEngine,
             engine_options=None):
    """Use one fresh bank; only public inputs enter engine/model callbacks."""
    if type(max_query_rounds) is not int or max_query_rounds < 0:
        raise ValueError("max_query_rounds must be nonnegative")
    engine = engine_class(request, case["sources"], queryable_sources=case["queryable_sources"],
                              query_budget=1, step_query_budget=2, **(engine_options or {}))
    registrations, coverage, ticks = [], {}, []

    def context(**values):
        if hasattr(request, "context"):
            request.context = {"case_id": case["id"], **values}

    def emit(row):
        if log is not None:
            log({"case_id": case["id"], **row})

    def ingest(raw, tick_id):
        context(tick_id=tick_id, instruction_id=raw["id"])
        before = len(engine.errors)
        changed = engine.ingest(Instruction(**raw))
        row = {"instruction_id": raw["id"], "tick_id": tick_id, "changed_ids": changed,
               "errors": engine.errors[before:], "state": engine.snapshot()}
        registrations.append(row)
        emit({"event": "registration", **row})

    def remember_coverage(requirements):
        for row in requirements:
            origin = row["origin_id"]
            coverage.setdefault(origin, any(i.instruction_ids[0] == origin
                                            for i in engine.intentions.values()))

    for raw in case["instructions"]:
        ingest(raw, "initial")
    initial_state = engine.snapshot()
    initial_checks = score_records(engine, case["expected_initial_records"], initial_state)
    remember_coverage(case["expected_initial_records"])
    for tick in case["ticks"]:
        engine.begin_step(tick["id"])
        for raw in tick.get("instructions", []):
            ingest(raw, tick["id"])
        record_checks = score_records(engine, tick["expected_records"], initial_state)
        remember_coverage(tick["expected_records"])
        observations = [Observation(**raw) for raw in tick["observations"]]
        rounds, queried, fixture_errors = [], set(), []
        for round_index in range(max_query_rounds + 1):
            context(tick_id=tick["id"], round=round_index)
            before = len(engine.errors)
            decisions = engine.tick(observations, scope=tick.get("scope", ""))
            row = {"round": round_index, "observations": [asdict(o) for o in observations],
                   "decisions": [asdict(d) for d in decisions],
                   "normalized": normalize_decisions(engine, decisions),
                   "boundary_errors": boundary_errors(engine, decisions, observations),
                   "engine_errors": engine.errors[before:], "state": engine.snapshot()}
            rounds.append(row)
            emit({"event": "decision", "tick_id": tick["id"], **row})
            if round_index == max_query_rounds:
                break
            replies = []
            for decision in decisions:
                if decision.kind != "CHECK" or decision.source in queried:
                    continue
                engine.record_query(decision.source)
                queried.add(decision.source)
                raw_replies = tick.get("pull_responses", {}).get(decision.source)
                if raw_replies is None:
                    fixture_errors.append("No frozen response for requested source: " + decision.source)
                    continue
                replies.extend(Observation(**raw) for raw in raw_replies)
            if not replies:
                break
            replaced = {o.source for o in replies}
            observations = [o for o in observations if o.source not in replaced] + replies
        expected = tick["expected_rounds"]
        exact = len(rounds) == len(expected) and all(
            decision_counter(actual["normalized"]) == decision_counter(gold)
            for actual, gold in zip(rounds, expected))
        row = {"tick_id": tick["id"], "record_checks": record_checks, "rounds": rounds,
               "expected_rounds": expected, "exact_decisions": exact,
               "queried_sources": sorted(queried), "fixture_errors": fixture_errors,
               "passed": record_checks["passed"] and exact and not fixture_errors and
                         not any(unexpected_errors(r["engine_errors"]) or r["boundary_errors"] for r in rounds)}
        ticks.append(row)
    acts = Counter(d["origin_id"] for tick in ticks for rnd in tick["rounds"]
                   for d in rnd["normalized"] if d["kind"] == "ACT")
    # Occurrence-aligned ACT counts prevent a wrong-time ACT from offsetting a miss.
    tp = fp = fn = 0
    for actual_tick, expected_tick in zip(ticks, case["ticks"]):
        for index in range(max(len(actual_tick["rounds"]), len(expected_tick["expected_rounds"]))):
            actual = actual_tick["rounds"][index]["normalized"] if index < len(actual_tick["rounds"]) else []
            gold = expected_tick["expected_rounds"][index] if index < len(expected_tick["expected_rounds"]) else []
            a = Counter(d["origin_id"] for d in actual if d["kind"] == "ACT")
            b = Counter(d["origin_id"] for d in gold if d["kind"] == "ACT")
            overlap = sum((a & b).values())
            tp += overlap
            fp += sum(a.values()) - overlap
            fn += sum(b.values()) - overlap
    return {"case_id": case["id"], "passed": initial_checks["passed"] and all(coverage.values())
            and all(t["passed"] for t in ticks) and not unexpected_errors(engine.errors),
            "initial_record_checks": initial_checks, "registration_events": registrations,
            "registration_coverage": coverage, "initial_state": initial_state,
            "ticks": ticks, "final_state": engine.snapshot(), "engine_errors": engine.errors,
            "protection_events": [e for e in engine.errors if e["phase"] in PROTECTION_PHASES],
            "unexpected_errors": unexpected_errors(engine.errors),
            "act_tp": tp, "act_fp": fp, "act_fn": fn, "act_count": sum(acts.values())}


def summarize(results):
    tp, fp, fn = (sum(r["act_" + key] for r in results) for key in ("tp", "fp", "fn"))
    required = sum(len(r["registration_coverage"]) for r in results)
    registered = sum(sum(r["registration_coverage"].values()) for r in results)
    return {"case_count": len(results), "passed_cases": sum(r["passed"] for r in results),
            "all_cases_passed": all(r["passed"] for r in results),
            "required_registration_count": required, "registered_requirement_count": registered,
            "registration_coverage": registered / required if required else None,
            "delivered_act_proposals": sum(r["act_count"] for r in results),
            "proposal_counts": dict(Counter(d["kind"] for r in results for t in r["ticks"]
                                             for rnd in t["rounds"] for d in rnd["decisions"])),
            "act_tp": tp, "act_fp": fp, "act_fn": fn,
            "act_precision": tp / (tp + fp) if tp + fp else None,
            "act_recall": tp / (tp + fn) if tp + fn else None,
            "act_f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
            "engine_event_count": sum(len(r["engine_errors"]) for r in results),
            "protection_event_count": sum(len(r["protection_events"]) for r in results),
            "unexpected_error_count": sum(len(r["unexpected_errors"]) for r in results)}


def evaluate(dataset, request, output=None, max_query_rounds=2, engine_class=GroundedPISEngine,
             engine_options=None):
    validate_cases(dataset)
    results = []
    for case in dataset["cases"]:
        print("Starting " + case["id"], flush=True)
        if output is None:
            result = run_case(case, request, max_query_rounds=max_query_rounds, engine_class=engine_class,
                              engine_options=engine_options)
        else:
            with (output / "trace.jsonl").open("a") as trace:
                def log(row):
                    trace.write(json.dumps(row, ensure_ascii=False) + "\n")
                    trace.flush()
                result = run_case(case, request, log, max_query_rounds, engine_class, engine_options)
            write_json(output / (case["id"] + ".json"), result)
        results.append(result)
        if output is not None:
            write_json(output / "case_results.json", results)
            write_json(output / "status.json", {"status": "running", "stage": "cases",
                       "completed_cases": len(results), "total_cases": len(dataset["cases"]),
                       "last_case": case["id"], "updated_at": utc_now()})
        print(f"Completed {case['id']}: passed={result['passed']} ACT={result['act_count']}", flush=True)
    return results, summarize(results)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--policy", choices=tuple(ENGINES), default="pis_grounded")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="Qwen/Qwen3-8B")
    parser.add_argument("--base-url", default="http://127.0.0.1:30002/v1")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--projector-id", help="Required for V4/V5: stable model/version and decoding/config identity")
    parser.add_argument("--projection-batch-size", type=int, default=4)
    parser.add_argument("--max-query-rounds", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--max-calls", type=int, default=300)
    parser.add_argument("--input-usd-per-million", type=float)
    parser.add_argument("--output-usd-per-million", type=float)
    args = parser.parse_args(argv)
    try:
        engine_options = projection_options(args.policy, args.projector_id, args.projection_batch_size)
    except ValueError as exc:
        parser.error(str(exc))
    rates = (args.input_usd_per_million, args.output_usd_per_million)
    if (args.max_tokens < 1 or args.max_query_rounds < 0 or args.timeout <= 0 or args.max_calls < 1
            or (None in rates and any(r is not None for r in rates))
            or any(r is not None and r < 0 for r in rates)):
        parser.error("Invalid token/query/timeout/cost configuration")
    raw = args.cases.read_bytes()
    dataset = json.loads(raw)
    validate_cases(dataset)
    # Refuse overwrite BEFORE any request, including the audited grammar probe.
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "cases.json").write_bytes(raw)
    root = Path(__file__).resolve().parents[1]
    hashes = {}
    for name in SOURCE_FILES:
        content = (root / name).read_bytes()
        hashes[name] = hashlib.sha256(content).hexdigest()
        destination = args.output / "source" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    manifest = {"started_at": utc_now(), "python": platform.python_version(),
                "args": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                "policy": ENGINES[args.policy].POLICY, "temperature": 0.0, "enable_thinking": False,
                "cases_sha256": hashlib.sha256(raw).hexdigest(), "source_hashes": hashes,
                "protocol": "Scorer-only expectations; deterministic host follows CHECK; ACT not executed.",
                "comparison_limit": "Generic helper smoke test, not actor uptake or PM-Bench performance.",
                "record_lexical_checks": "Scorer-only diagnostics, not complete semantic verification.",
                "query_budget_per_assessment": 1, "query_budget_per_step": 2}
    if engine_options:
        manifest["projection_definition"] = projection_definition()
    write_json(args.output / "manifest.json", manifest)
    write_json(args.output / "status.json", {"status": "running", "stage": "preflight", "updated_at": utc_now()})
    started = time.monotonic()
    request = None
    try:
        with (args.output / "calls.jsonl").open("w") as calls:
            request = AuditedRequest(args.base_url, args.model, args.max_tokens, calls,
                                     args.timeout, *rates, max_calls=args.max_calls)
            request.context = {"stage": "preflight"}

            def raw_probe(system, payload, schema):
                try:
                    request(system, payload, schema)
                except Exception:
                    if request.last_raw is None:
                        raise
                return request.last_raw

            compact = probe_compact_decoding(raw_probe)
            manifest["whitespace_free_grammar_verified"] = compact
            write_json(args.output / "manifest.json", manifest)
            if not compact:
                raise RuntimeError(WHITESPACE_REMEDY)
            if request.error_count or json.loads(request.last_raw).get("label") != "ready":
                raise SmokeAbort("Preflight did not return a valid ready response")
            results, summary = evaluate(dataset, request, args.output, args.max_query_rounds,
                                        ENGINES[args.policy], engine_options)
            summary["all_cases_passed"] = summary["all_cases_passed"] and request.error_count == 0
            summary.update(status="completed", **request.summary(),
                           elapsed_seconds=time.monotonic() - started, completed_at=utc_now())
            write_json(args.output / "metrics.json", summary)
            write_json(args.output / "status.json", {"status": "completed",
                       "all_cases_passed": summary["all_cases_passed"],
                       "completed_cases": len(results), "updated_at": utc_now()})
            print(json.dumps(summary, indent=2), flush=True)
    except BaseException as exc:
        failure = {"status": "failed", "error_type": type(exc).__name__, "error": str(exc),
                   "updated_at": utc_now(), "elapsed_seconds": time.monotonic() - started}
        if request is not None:
            failure.update(request.summary())
        write_json(args.output / "status.json", failure)
        raise


if __name__ == "__main__":
    main()
