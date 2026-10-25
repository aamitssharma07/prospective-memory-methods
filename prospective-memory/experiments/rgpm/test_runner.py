"""Offline regression tests for the exact Experiment 3 execution path."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from run import ROOT, run, pm_bench, PMBenchAdapter, SourceBoundFairTriggerEngine
from artifacts import ActorBudgetExceeded, Session, digest, rows, save, traced_adapter_class
from analyze import analyze, validate
from smoke_gate import gate
from query_uptake_probe import probe as uptake_probe
from tests.test_pis_fair_trigger import Provider


class Response:
    def __init__(self, raw):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=raw), finish_reason="stop")]
        self.usage = SimpleNamespace(model_dump=lambda: {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18})
        self.id = "scripted"

    def model_dump(self):
        return {"id": self.id, "choices": [{"message": {"content": self.choices[0].message.content},
                                           "finish_reason": "stop"}], "usage": self.usage.model_dump()}


class Client:
    def __init__(self, invalid=False, transport_once=False, query_loop=False):
        self.provider = Provider()
        self.provider.watched = ["events"]
        self.actor_calls = 0
        self.invalid = invalid
        self.transport_once = transport_once
        self.query_loop = query_loop
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        schema = kwargs["response_format"]["json_schema"]["schema"]
        if "action" in schema["properties"]:
            self.actor_calls += 1
            if self.transport_once and self.actor_calls == 1:
                raise ConnectionError("scripted transport failure")
            value = {"action": "choose", "choice": "A", "task_ids": [], "channel": "NONE"}
            if self.query_loop:
                value = {"action": "check_time", "choice": "NONE", "task_ids": [], "channel": "clock"}
            return Response("{broken" if self.invalid else json.dumps(value))
        system = kwargs["messages"][0]["content"]
        payload = json.loads(kwargs["messages"][1]["content"])
        if set(schema["properties"]) == {"status", "watched_sources", "reason"}:
            return Response(json.dumps({"status": "routed", "watched_sources": ["events"], "reason": "Visible approval."}))
        value = self.provider(system, payload, schema)
        if "specifications" in value:
            for record, operation in zip(value["specifications"], payload["operations"]):
                fields = schema["properties"]["specifications"]["items"]["properties"]
                for key in ("requested_action", "trigger_condition"):
                    if key in fields:
                        record[key] = operation["complete_request_quote"]
        return Response(json.dumps(value))


def scenario():
    return {"scenario_name": "scripted_rgpm", "state_visibility": {"clock": False},
            "state_channels": {"clock": {"mode": "snapshot"}}, "days": [
                {"name": day, "start_instructions": ["Send the report when approval arrives."],
                 "tasks": [], "steps": [
                     {"id": f"s{i}", "time": f"09:0{i}", "text": "The desk is quiet.",
                      "options": ["A. Continue", "B. Wait", "C. Skip"], "cues": []}
                     for i in range(2)]} for day in ("Monday", "Tuesday")]}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.scenario = self.root / "scenario.json"
        save(self.scenario, scenario())

    def tearDown(self):
        self.temp.cleanup()

    def args(self, name, **changes):
        values = dict(output=str(self.root / name), scenario=str(self.scenario), model="Qwen/Qwen3-8B",
                      base_url="http://127.0.0.1:30003/v1", projector_id="scripted:v1;max_tokens=768",
                      kind="smoke", resume=False, provenance=None, stop_after=None)
        return SimpleNamespace(**{**values, **changes})

    def execute(self, args, client=None):
        client = client or Client()
        with patch.object(pm_bench, "build_llm_client", return_value=client):
            return run(args, helper_client=client)

    def test_resume_matches_uninterrupted_without_repeating_completed_calls(self):
        full = self.execute(self.args("full"))
        first = Client()
        with self.assertRaises(InterruptedError):
            self.execute(self.args("resumed", stop_after=2), first)
        self.assertEqual(first.actor_calls, 2)
        second = Client()
        resumed = self.execute(self.args("resumed", resume=True), second)
        self.assertEqual(second.actor_calls, 2)
        self.assertEqual(full, resumed)
        for name in ("trajectory.jsonl", "memory_snapshot.json"):
            self.assertEqual((self.root / "full" / name).read_bytes(), (self.root / "resumed" / name).read_bytes())
        self.assertEqual(analyze(self.root / "resumed"), resumed)
        self.assertTrue(rows(self.root / "resumed/memory.jsonl"))
        memory = json.loads((self.root / "resumed/memory_snapshot.json").read_text())
        self.assertTrue(memory["engine"]["intentions"])
        calls = rows(self.root / "resumed/calls.jsonl")
        self.assertTrue(all(c["valid"] for c in calls), [c.get("error") for c in calls if not c["valid"]])

    def test_hosted_actor_provenance_does_not_inherit_local_helper(self):
        provenance = self.root / "helper.json"
        save(provenance, {"model": "local-helper", "gpu": "scripted"})
        with patch.object(pm_bench, "load_openrouter_api_key", return_value="scripted-not-a-key"):
            self.execute(self.args("hosted", actor_backend="openrouter", model="hosted-actor",
                helper_model="local-helper", base_url="https://openrouter.ai/api/v1",
                provenance=str(provenance)))
        manifest = json.loads((self.root / "hosted/manifest.json").read_text())
        self.assertEqual(manifest["provenance"]["model"], "local-helper")
        self.assertEqual(manifest["actor_provenance"]["model"], "hosted-actor")
        self.assertEqual(manifest["actor_provenance"]["backend"], "openrouter")
        self.assertNotIn("gpu", manifest["actor_provenance"])

    def test_direct_openai_uses_audited_chat_with_token_cap(self):
        client = Client()
        original = client.chat.completions.create
        actor_requests = []

        def capture(**kwargs):
            if "max_completion_tokens" in kwargs:
                actor_requests.append(kwargs)
            return original(**kwargs)

        client.chat.completions.create = capture
        self.execute(self.args("direct", actor_backend="openai_chat", model="gpt-5.4",
            helper_model="local-helper", base_url="https://api.openai.com/v1"), client)
        self.assertEqual(len(actor_requests), 4)
        for request in actor_requests:
            self.assertEqual(request["max_completion_tokens"], 768)
            self.assertNotIn("max_tokens", request)
            self.assertEqual(request["reasoning_effort"], "none")
            self.assertTrue(request["response_format"]["json_schema"]["strict"])
        manifest = json.loads((self.root / "direct/manifest.json").read_text())
        self.assertEqual(manifest["actor_provenance"]["backend"], "openai_chat")
        self.assertNotIn("gpu", manifest["actor_provenance"])
        calls = [c for c in rows(self.root / "direct/calls.jsonl") if c["role"] == "actor"]
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(c["valid"] for c in calls))

    def test_invalid_empty_is_incorrect_and_attempts_survive(self):
        metrics = self.execute(self.args("invalid"), Client(invalid=True))
        self.assertEqual(metrics["invalid_responses"], 4)
        self.assertEqual(metrics["exact_match_rate"], 0)
        calls = [c for c in rows(self.root / "invalid/calls.jsonl") if c["role"] == "actor"]
        self.assertEqual(len(calls), 8)
        self.assertTrue(all(c["raw"] == "{broken" and not c["valid"] for c in calls))
        self.assertTrue(all(e["task_ids"] == [] for e in rows(self.root / "invalid/trajectory.jsonl")))

    def test_routing_calls_and_changes_survive_resume(self):
        full = self.execute(self.args("routed_full", source_routing=True))
        with self.assertRaises(InterruptedError):
            self.execute(self.args("routed_resume", source_routing=True, stop_after=2))
        resumed = self.execute(self.args("routed_resume", source_routing=True, resume=True))
        self.assertEqual(full, resumed)
        for name in ("trajectory.jsonl", "memory_snapshot.json"):
            self.assertEqual((self.root / "routed_full" / name).read_bytes(),
                             (self.root / "routed_resume" / name).read_bytes())
        calls = rows(self.root / "routed_resume/calls.jsonl")
        self.assertTrue(any(c["phase"] == "source_routing" and c["valid"] for c in calls))
        events = rows(self.root / "routed_resume/events.jsonl")
        self.assertTrue(any(e["event"] == "source_routing_applied" for e in events))
        self.assertTrue(all(c["request"]["max_tokens"] == 768 for c in calls))

    def test_consolidated_candidate_matches_after_resume(self):
        flags = dict(source_routing=True, scope_grounding=True, bounded_priority=True,
                     registration_grounding=True, local_only=True)
        full = self.execute(self.args("candidate_full", **flags))
        first = Client()
        with self.assertRaises(InterruptedError):
            self.execute(self.args("candidate_resume", stop_after=2, **flags), first)
        second = Client()
        resumed = self.execute(self.args("candidate_resume", resume=True, **flags), second)
        self.assertEqual((first.actor_calls, second.actor_calls), (2, 2))
        self.assertEqual(full, resumed)
        for name in ("trajectory.jsonl", "memory_snapshot.json"):
            self.assertEqual((self.root / "candidate_full" / name).read_bytes(),
                             (self.root / "candidate_resume" / name).read_bytes())
        memory = json.loads((self.root / "candidate_resume/memory_snapshot.json").read_text())
        self.assertTrue(memory["engine"]["monitoring_log"])
        self.assertTrue(memory["engine"]["readiness_log"])
        self.assertTrue(memory["engine"]["candidate_config"]["bounded_priority"])

    def test_gate_refreshes_hashes_after_writing_analysis_and_gate(self):
        self.execute(self.args("indexed_gate"))
        output = self.root / "indexed_gate"
        gate(output)
        index = json.loads((output / "artifact_index.json").read_text())["artifacts"]
        self.assertIn("smoke_gate.json", index)
        for name, metadata in index.items():
            self.assertEqual(metadata["sha256"], digest(output / name), name)

    def test_query_first_plan_survives_resume_without_replaying_completed_calls(self):
        def client():
            result = Client()
            result.provider.watched = ["clock"]
            return result
        flags = dict(actor_guidance="query_first", query_handoff="legacy",
                     source_routing=False, scope_grounding=True,
                     bounded_priority=True, registration_grounding=True, local_only=True)
        full = self.execute(self.args("query_full", **flags), client())
        first, second = client(), client()
        with self.assertRaises(InterruptedError):
            self.execute(self.args("query_resume", stop_after=2, **flags), first)
        resumed = self.execute(self.args("query_resume", resume=True, **flags), second)
        self.assertEqual((first.actor_calls, second.actor_calls), (2, 2))
        self.assertEqual(full, resumed)
        traces = [t for t in rows(self.root / "query_resume/memory.jsonl") if t["event"] == "memory_cycle"]
        self.assertTrue(traces)
        self.assertTrue(all(t["query_plan"]["next_action"]["channel"] == "clock" for t in traces))
        uptake = (self.root / "query_resume/query_uptake.csv").read_text()
        self.assertIn("advanced_without_offered_check", uptake)
        probe_output = self.root / "uptake_probe"
        uptake_client = Client(query_loop=True)
        self.assertTrue(uptake_probe(SimpleNamespace(input_run=self.root / "query_resume",
                       output=probe_output, model="scripted", base_url="http://127.0.0.1:30003/v1",
                       max_cases=2), uptake_client))
        probe_calls = rows(probe_output / "calls.jsonl")
        self.assertEqual(len(probe_calls), 4)
        original = probe_calls[0]["request"]["messages"]
        candidate = probe_calls[1]["request"]["messages"]
        self.assertEqual(candidate[:-1], original[:-1])
        self.assertEqual(len(candidate), len(original))
        self.assertTrue(candidate[-1]["content"].startswith(original[-1]["content"] + "\n"))
        self.assertIn("Unresolved prospective-memory check", candidate[-1]["content"])
        for name in ("trajectory.jsonl", "memory_snapshot.json"):
            self.assertEqual((self.root / "query_full" / name).read_bytes(),
                             (self.root / "query_resume" / name).read_bytes())

    def test_local_only_rejects_hosted_before_constructing_clients(self):
        with patch.object(pm_bench, "build_llm_client", side_effect=AssertionError("Hosted call forbidden")) as build:
            with self.assertRaisesRegex(ValueError, "forbids"):
                run(self.args("hosted", local_only=True, actor_backend="openrouter",
                              base_url="https://openrouter.ai/api/v1"))
            build.assert_not_called()
        self.assertFalse((self.root / "hosted").exists())

    def test_smoke_quality_limits_reject_extra_actions_and_misses(self):
        self.execute(self.args("quality_gate"))
        output = self.root / "quality_gate"
        metrics = analyze(output)
        for fp, fn in ((0, 0), (1, 0), (0, 1)):
            sample = copy.deepcopy(metrics)
            sample["summary"].update(set_fp=fp, set_fn=fn)
            with patch("smoke_gate.analyze", return_value=sample):
                result = gate(output, max_false_positives=0, max_false_negatives=0)
            self.assertEqual(result["checks"]["false_positives_within_limit"], fp == 0)
            self.assertEqual(result["checks"]["false_negatives_within_limit"], fn == 0)
            if fp or fn:
                self.assertFalse(result["passed"])
        with self.assertRaises(ValueError):
            gate(output, max_false_positives=-1)

    def test_report_only_admits_quality_failure_without_erasing_it(self):
        self.execute(self.args("report_quality"))
        output = self.root / "report_quality"
        sample = analyze(output)
        sample["summary"].update(set_fp=1, set_fn=1)
        manifest = json.loads((output / "manifest.json").read_text())
        manifest["registration_grounding"] = True
        save(output / "manifest.json", manifest)
        snapshot = json.loads((output / "memory_snapshot.json").read_text())
        snapshot["engine"]["errors"].append({"phase": "scripted", "error": "Unsupported update"})
        save(output / "memory_snapshot.json", snapshot)
        with patch("smoke_gate.analyze", return_value=sample):
            result = gate(output, max_false_positives=0, max_false_negatives=0,
                          admission_policy="report_only")
        self.assertFalse(result["passed"])
        self.assertTrue(result["admitted_to_benchmark"])
        self.assertFalse(result["checks"]["no_semantic_errors"])
        self.assertTrue(result["semantic_errors"])
        status = json.loads((output / "status.json").read_text())
        status["status"] = "interrupted"
        save(output / "status.json", status)
        with patch("smoke_gate.analyze", return_value=sample):
            self.assertFalse(gate(output, admission_policy="report_only")["admitted_to_benchmark"])

    def test_actor_call_budget_counts_retries_and_resumes(self):
        client = Client(transport_once=True)
        with self.assertRaises(ActorBudgetExceeded):
            self.execute(self.args("limited", max_actor_calls=2), client)
        self.assertEqual(client.actor_calls, 2)
        self.assertEqual(len([c for c in rows(self.root / "limited/calls.jsonl") if c["role"] == "actor"]), 2)
        next_client = Client()
        with self.assertRaises(ActorBudgetExceeded):
            self.execute(self.args("limited", max_actor_calls=2, resume=True), next_client)
        self.assertEqual(next_client.actor_calls, 0)
        self.assertEqual(json.loads((self.root / "limited/status.json").read_text())["status"], "interrupted")

    def test_actor_token_budget_stops_before_call_and_unknown_usage_is_not_zero(self):
        output = self.root / "tokens"
        output.mkdir()
        session = Session(output, "scripted", max_actor_tokens=5000)
        client = Client()
        kwargs = dict(model="scripted", max_tokens=768,
                      messages=[{"role": "user", "content": "request"}],
                      response_format={"type": "json_schema", "json_schema": {"schema": {
                          "type": "object", "properties": {"action": {"type": "string"}},
                          "additionalProperties": True}}})
        session.call(client, "actor", **kwargs)
        response = client.create(**kwargs)
        response.usage = None
        response.model_dump = lambda: {"id": "scripted_no_usage", "choices": [], "usage": None}
        missing_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: response)))
        session.call(missing_client, "actor", **kwargs)
        with self.assertRaises(ActorBudgetExceeded):
            session.call(client, "actor", **kwargs)
        self.assertEqual(client.actor_calls, 2)
        self.assertEqual(rows(output / "events.jsonl")[-1]["reason"], "actor_usage_unknown")
        session2 = Session(output, "scripted", max_actor_tokens=1)
        with self.assertRaises(ActorBudgetExceeded):
            session2.call(client, "actor", **kwargs)
        self.assertEqual(client.actor_calls, 2)
        self.assertEqual(rows(output / "events.jsonl")[-1]["reason"], "actor_usage_unknown")
        limited_output = self.root / "tiny_token_budget"
        limited_output.mkdir()
        tiny = Session(limited_output, "scripted", max_actor_tokens=1)
        with self.assertRaises(ActorBudgetExceeded):
            tiny.call(client, "actor", **kwargs)
        self.assertEqual(client.actor_calls, 2)
        self.assertEqual(rows(limited_output / "events.jsonl")[-1]["reason"],
                         "actor_token_budget_reservation_exceeded")

    def test_incomplete_actor_attempt_blocks_token_budget_resume(self):
        output = self.root / "incomplete_budget"
        output.mkdir()
        (output / "prompts.log").touch()
        original = Session(output, "scripted")
        original.event("call_start", call_id="interrupted_attempt", role="actor", phase="actor")
        resumed = Session(output, "scripted", resume=True, max_actor_tokens=5000)
        with self.assertRaises(ActorBudgetExceeded):
            resumed.call(Client(), "actor", max_tokens=768, messages=[])
        self.assertEqual(rows(output / "events.jsonl")[-1]["reason"], "actor_usage_unknown")

    def test_transport_retry_and_completion_validation(self):
        self.execute(self.args("retry"), Client(transport_once=True))
        calls = [c for c in rows(self.root / "retry/calls.jsonl") if c["role"] == "actor"]
        self.assertEqual(len(calls), 5)
        self.assertEqual(calls[0]["error"]["type"], "ConnectionError")
        self.assertEqual(calls[0]["operation_id"], calls[1]["operation_id"])
        entries = rows(self.root / "retry/trajectory.jsonl")
        for bad in (entries[:-1], entries + entries[:1], list(reversed(entries))):
            with self.assertRaises(ValueError):
                validate(self.root / "retry", scenario(), bad)
        (self.root / "retry/snapshots/000002.json").unlink()
        with self.assertRaises(ValueError):
            analyze(self.root / "retry")

    def test_query_loop_is_incorrect_and_resumes_on_next_step(self):
        client = Client(query_loop=True)
        with self.assertRaises(InterruptedError):
            self.execute(self.args("loop", stop_after=1), client)
        self.assertEqual(client.actor_calls, 12)
        metrics = self.execute(self.args("loop", resume=True), Client(query_loop=True))
        self.assertEqual(metrics["invalid_responses"], 4)
        self.assertEqual(metrics["exact_match_rate"], 0)
        entries = rows(self.root / "loop/trajectory.jsonl")
        self.assertEqual(len(entries), 4)
        self.assertTrue(all(e["task_ids"] == [] and e["fallback_triggered"] for e in entries))
        self.assertTrue(all(e["state_queries"] == {"clock": 12} for e in entries))
        events = [e for e in rows(self.root / "loop/events.jsonl") if e["event"] == "actor_query_limit"]
        self.assertEqual(len(events), 4)
        self.assertTrue(all(e["query_attempts"] == ["clock"] * 12 for e in events))
        calls = [c for c in rows(self.root / "loop/calls.jsonl") if c["role"] == "actor"]
        self.assertEqual(len(calls), 48)
        self.assertTrue(all(c["raw"] and c["valid"] for c in calls))

    def test_fingerprint_change_rejected(self):
        with self.assertRaises(InterruptedError):
            self.execute(self.args("changed", stop_after=1))
        with self.assertRaisesRegex(ValueError, "changed"):
            self.execute(self.args("changed", resume=True, model="different"))

    def test_registration_omission_and_rejected_update_preserve_evidence(self):
        output = self.root / "stages"
        output.mkdir()
        session = Session(output, "scripted")
        client = Client()

        def request(system, payload, schema):
            response = session.call(client, "helper", model="scripted", max_tokens=768,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload)}],
                response_format={"type": "json_schema", "json_schema": {"schema": schema}})
            return json.loads(response.choices[0].message.content)

        engine = SourceBoundFairTriggerEngine(request, projector_id="scripted")
        adapter = traced_adapter_class(PMBenchAdapter)(engine, session)
        session.bind(adapter)
        client.provider.kind = "fact"
        adapter._ingest("omitted", "Send the report after approval.", "Monday")
        self.assertFalse(engine.intentions)
        client.provider.kind = "new_request"
        adapter._ingest("registered", "Send the report after approval.", "Monday")
        self.assertTrue(engine.intentions)
        client.provider.kind, client.provider.target = "modify_request", "pm_000001"
        client.provider.same_target = False
        adapter._ingest("rejected", "Send the report to Lee instead after approval.", "Monday")
        self.assertEqual(engine.intentions["pm_000001"].revision, 1)
        trace = rows(output / "memory.jsonl")
        self.assertEqual(trace[0]["accepted_changes"], [])
        self.assertTrue(trace[1]["accepted_changes"])
        self.assertTrue(trace[2]["new_errors"])
        self.assertEqual(trace[2]["accepted_changes"], [])
        self.assertTrue(rows(output / "memory_calls.jsonl"))

    def test_torn_append_is_archived_and_resume_continues(self):
        with self.assertRaises(InterruptedError):
            self.execute(self.args("torn", stop_after=1))
        path = self.root / "torn/calls.jsonl"
        with path.open("ab") as stream:
            stream.write(b'{"incomplete":')
        self.execute(self.args("torn", resume=True))
        archives = list((self.root / "torn/recovery").glob("*/calls.jsonl"))
        self.assertEqual(len(archives), 1)
        self.assertTrue(archives[0].read_bytes().endswith(b'{"incomplete":'))

    def test_legacy_scoring_unchanged_and_strict_scoring_fixed(self):
        day = scenario()["days"][0]
        actions = [{"task_ids": [], "fallback_triggered": True} for _ in day["steps"]]
        self.assertEqual(pm_bench.score_day(day, actions)[0]["exact_set_match_steps"], 2)
        self.assertEqual(pm_bench.score_day(day, actions, strict_invalid=True)[0]["exact_set_match_steps"], 0)


if __name__ == "__main__":
    unittest.main()
