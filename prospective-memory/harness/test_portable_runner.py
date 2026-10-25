"""Offline runner wiring tests, not language-model performance measurements."""

import contextlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import run_memory


class PortableRunnerTests(unittest.TestCase):
    def test_portable_phase_logging_is_schema_driven(self):
        for key, expected in (("operations", "extract"),
                              ("unit_classifications", "classify_unit"),
                              ("identity_reviews", "identity_review"),
                              ("specifications", "compile_typed"),
                              ("trigger_projections", "trigger_projection"),
                              ("changes", "compile"),
                              ("reviews", "change_review"),
                              ("resolutions", "resolve"),
                              ("verdict", "verify"),
                              ("assessments", "assess"),
                              ("decisions", "assess")):
            with self.subTest(key=key):
                schema = {"properties": {key: {"type": "array"}}}
                self.assertEqual(run_memory.portable_phase(schema), expected)
                self.assertEqual(schema, {"properties": {key: {"type": "array"}}})

    def test_generate_helper_preserves_explicit_portable_schema(self):
        client = Mock()
        schema = {"type": "object", "properties": {"changes": {"type": "array"}}}
        run_memory.generate_helper(client, "fixture", "compile", {}, 4096, schema=schema)
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["response_format"]["json_schema"]["schema"], schema)
        self.assertEqual(kwargs["max_tokens"], 4096)
        self.assertFalse(kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"])

    def test_new_policy_token_default_does_not_override_explicit_limits(self):
        for policy, explicit_limit, expected in (("sbpm_minimal", None, 4096),
                                                 ("sbpm_minimal", 1024, 1024),
                                                 ("sbpm_no_projection", None, 4096),
                                                 ("sbpm_no_projection", 1024, 1024),
                                                 ("sbpm_no_arbiter", None, 4096),
                                                 ("sbpm_no_arbiter", 1024, 1024),
                                                 ("sbpm", None, 4096),
                                                 ("pis", None, 2048)):
            with self.subTest(policy=policy, limit=explicit_limit), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "run"
                argv = ["run_memory.py", "--mode", "selective", "--memory-version", "portable",
                        "--memory-policy", policy, "--output", str(output)]
                if explicit_limit is not None:
                    argv += ["--memory-max-tokens", str(explicit_limit)]
                if policy in run_memory.PROJECTED_POLICIES:
                    argv += ["--memory-projector-id", "fixture-model-config"]
                # The manifest is written before any model connection. Inspect
                # it without making a request or fabricating a completed run.
                with patch.object(sys, "argv", argv), \
                     patch.object(run_memory.pm_bench, "build_llm_client", side_effect=RuntimeError("offline boundary")), \
                     self.assertRaisesRegex(RuntimeError, "offline boundary"):
                    run_memory.main()
                manifest = json.loads((output / "manifest.json").read_text())
                self.assertEqual(manifest["memory_max_tokens"], expected)
                self.assertFalse((output / "metrics.json").exists())

    def test_runner_refuses_a_server_whose_grammar_permits_whitespace(self):
        """Indented probe output proves completed helper answers can be lost."""
        def helper(client, model, system, payload, max_tokens, schema=None):
            self.assertIn("label", schema["properties"])
            return SimpleNamespace(usage=None, choices=[SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content='{\n  "label": "ready"\n}'))])

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            argv = ["run_memory.py", "--mode", "selective", "--memory-version", "portable",
                    "--model", "fixture", "--output", str(output)]
            with patch.object(sys, "argv", argv), \
                 patch.object(run_memory.pm_bench, "build_llm_client", return_value=None), \
                 patch.object(run_memory, "generate_helper", side_effect=helper), \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    run_memory.main()
            self.assertIn("disable-any-whitespace", str(raised.exception))

    def test_portable_runner_full_80_step_public_interface(self):
        compiled, acted, helper_phases = [], [], []

        def helper(client, model, system, payload, max_tokens, schema=None):
            self.assertIsNotNone(schema)
            if "label" in schema["properties"]:
                # The runner refuses a server whose JSON grammar allows whitespace.
                helper_phases.append("probe")
                return SimpleNamespace(usage=None, choices=[SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content='{"label":"ready"}'))])
            if "changes" in schema["properties"]:
                text = payload["instruction"]["text"]
                self.assertNotIn("Step action menu", text)
                self.assertIsNone(re.search(r"task_\d+\s*:", text))
                self.assertIsNone(re.search(r"^[ABC][).:]\s", text, re.MULTILINE))
                compiled.append(text)
                # Deliberately scripted registration: tests wiring, not semantics.
                result = {"changes": [] if len(compiled) > 1 else [{
                    "op": "register", "action": "Fixture-only action",
                    "condition": "Fixture-only condition", "sources": ["events"],
                    "scope": "*", "repeat": True, "target_id": "",
                    "evidence_quote": text[:200],
                }]}
                helper_phases.append("compile")
            else:
                observations = payload["observations"]
                result = {"decisions": [] if not observations else [{
                    "kind": "ACT", "intention_id": payload["intentions"][0]["id"],
                    "reason": "Scripted fixture", "source": "",
                    "evidence_ids": [observations[0]["id"]],
                }]}
                helper_phases.append("assess")
            self.assertNotIn("due_now", json.dumps(payload))
            return SimpleNamespace(usage=None, choices=[SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(content=json.dumps(result)))])

        def actor(client, model, messages, *args, **kwargs):
            transient = [message for message in messages
                         if message["content"].startswith("Prospective-memory observations and proposals:")]
            self.assertEqual(len(transient), 1)
            acted.append(messages[-1]["content"])
            return {"action": "choose", "choice": "A", "task_ids": [], "channel": "NONE"}

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            argv = ["run_memory.py", "--mode", "selective", "--memory-version", "portable",
                    "--model", "fixture", "--output", str(output)]
            with patch.object(sys, "argv", argv), \
                 patch.object(run_memory.pm_bench, "build_llm_client", return_value=None), \
                 patch.object(run_memory, "generate_helper", side_effect=helper), \
                 patch.object(run_memory.pm_bench, "request_model_action", side_effect=actor), \
                 contextlib.redirect_stdout(io.StringIO()):
                run_memory.main()
            self.assertEqual(len(acted), 80)
            self.assertEqual(helper_phases.count("probe"), 1)
            self.assertIn("compile", helper_phases)
            self.assertEqual(helper_phases.count("assess"), 80)
            metrics = json.loads((output / "metrics.json").read_text())
            self.assertEqual(metrics["fallback_steps"], 0)
            trajectory = [json.loads(line) for line in (output / "trajectory.jsonl").read_text().splitlines()]
            self.assertEqual(sum("step_id" in entry for entry in trajectory), 80)
            self.assertEqual(len((output / "memory.jsonl").read_text().splitlines()), 80)
            self.assertIsInstance(json.loads((output / "memory_snapshot.json").read_text()), dict)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["fallback"], "empty")
            self.assertEqual(manifest["memory_version"], "portable")
            self.assertIn("prospective_memory/core.py", manifest["source_sha256"])
            self.assertEqual(len(manifest["scenario_sha256"]), 64)

    def test_unsupported_mode_fails_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "not-created"
            with patch.object(sys, "argv", ["run_memory.py", "--mode", "always",
                              "--memory-version", "portable", "--output", str(output)]), \
                 contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                run_memory.main()
            self.assertFalse(output.exists())

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sys, "argv", ["run_memory.py", "--mode", "selective",
                              "--memory-version", "portable", "--output", directory]), \
                 self.assertRaises(FileExistsError):
                run_memory.main()

    def test_projection_configuration_is_required_and_cannot_be_silently_ignored(self):
        for policy, extra in (("sbpm_no_arbiter", []),
                              ("sbpm", []),
                              ("sbpm_no_arbiter", ["--memory-projector-id", " "]),
                              ("pis", ["--memory-projector-id", "fixture"]),
                              ("sbpm_no_arbiter", ["--memory-projector-id", "fixture",
                                                             "--memory-projection-batch-size", "0"])):
            with self.subTest(policy=policy, extra=extra), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "not-created"
                argv = ["run_memory.py", "--mode", "selective", "--memory-version", "portable",
                        "--memory-policy", policy, "--output", str(output), *extra]
                with patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()), \
                     self.assertRaises(SystemExit):
                    run_memory.main()
                self.assertFalse(output.exists())

    def test_pis_arms_full_week_restore_and_keep_helper_menu_free(self):
        for policy in ("pis", "pis_verified", "pis_grounded", "sbpm_minimal", "sbpm_no_projection",
                       "sbpm_no_arbiter", "sbpm"):
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "run"
                calls = []
                def helper(client, model, system, payload, max_tokens, schema=None):
                    props = schema["properties"]
                    if "label" not in props:
                        self.assertEqual(max_tokens, 4096 if policy in run_memory.SOURCE_BOUND_VARIANTS else 2048)
                    if "label" in props:
                        result = {"label": "ready"}
                    elif "unit_classifications" in props:
                        first = not calls
                        calls.append("classify_unit")
                        self.assertTrue(payload["source_units"])
                        result = {"unit_classifications": [{
                            "unit_id": payload["focus_unit_id"],
                            "classification": "new_request" if first else "fact",
                            "related_intention_id": "", "reason": "Scripted runner fixture"}]}
                    elif "identity_reviews" in props:
                        calls.append("identity_review")
                        result = {"identity_reviews": [{"same_obligation": True,
                                  "explicit_update": True, "reason": "Scripted runner fixture"}]}
                    elif "operations" in props:
                        first = not calls
                        calls.append("extract")
                        result = {"operations": [] if not first else [{
                            "operation": "new_request",
                            "complete_request_quote": payload["current_message"]["text"][:100]}]}
                        self.assertNotIn("pending_update_targets", payload)
                    elif "specifications" in props:
                        calls.append("compile_typed")
                        self.assertEqual(payload["pending_update_targets"], [])
                        result = {"specifications": [{
                            "operation_id": payload["operations"][0]["operation_id"],
                            "target_id": "", "watched_sources": ["events", "clock"] if policy == "sbpm" else ["events"],
                            "permitted_days": [], "recurring": True,
                            "clock_relation": "none", "required_clock_time": ""}]}
                        if "reason" in props["specifications"]["items"]["properties"]:
                            result["specifications"][0]["reason"] = "Scripted metadata fixture"
                    elif "changes" in props:
                        first = not calls
                        calls.append("form")
                        result = {"changes": [] if not first else [{
                            "op": "register", "target_id": "", "action": "Fixture action",
                            "condition": "Fixture event", "evidence_quote": payload["instruction"]["text"][:100],
                            "sources": ["events"], "days": [], "repeat": True,
                            "clock_op": "none", "clock_time": ""}]}
                    elif "reviews" in props:
                        calls.append("change_review")
                        result = {"reviews": [{"verdict": "supported", "reason": "Fixture"}]}
                    elif "trigger_projections" in props:
                        calls.append("trigger_projection")
                        result = {"trigger_projections": [{
                            "intention_id": r["intention"]["id"], "revision": r["intention"]["revision"],
                            "source_instruction_ids": r["intention"]["instruction_ids"], "status": "projected",
                            "action_to_perform_next": "Fixture action", "readiness_question": "Has the fixture cue occurred?",
                            "reason": "Scripted static interpretation only"} for r in payload["records"]]}
                    elif "assessments" in props:
                        calls.append("decide")
                        obs = payload["observations"][0]
                        assessment = {"reason": "Fixture", "evidence_ids": [obs["id"]]}
                        fields = props["assessments"]["items"]["properties"]
                        if "evidence_quotes" in fields:
                            assessment["evidence_quotes"] = [obs["text"][:100]]
                        if policy in run_memory.PROJECTED_POLICIES:
                            assessment.update(trigger_ready_now=True, missing_observation_source="")
                            if policy == "sbpm" and calls.count("decide") == 1:
                                assessment.update(trigger_ready_now=False, missing_observation_source="clock", evidence_ids=[])
                        elif policy in run_memory.SOURCE_BOUND_VARIANTS:
                            assessment.update(all_conditions_met=True, missing_observation_source="")
                        else:
                            assessment.update(state="satisfied", missing_source="")
                        result = {"assessments": [assessment]}
                        self.assertTrue(payload["original_instructions"])
                    elif "verdict" in props:
                        calls.append("verify")
                        result = {"verdict": "supported", "reason": "Fixture"}
                        self.assertTrue(payload["original_instructions"])
                    else:
                        calls.append("decide")
                        result = {"decisions": [{"kind": "ACT", "intention_id": payload["intention"]["id"],
                            "reason": "Fixture", "source": "", "evidence_ids": [payload["observations"][0]["id"]]}]}
                    self.assertNotIn("due_now", json.dumps(payload))
                    self.assertNotIn("Step action menu", json.dumps(payload))
                    return SimpleNamespace(usage=None, choices=[SimpleNamespace(
                        finish_reason="stop", message=SimpleNamespace(content=json.dumps(result)))])

                def actor(*args, **kwargs):
                    return {"action": "choose", "choice": "A", "task_ids": [], "channel": "NONE"}

                argv = ["run_memory.py", "--mode", "selective", "--memory-version", "portable",
                        "--memory-policy", policy, "--model", "fixture", "--output", str(output)]
                if policy in run_memory.PROJECTED_POLICIES:
                    argv += ["--memory-projector-id", "fixture-model-config", "--memory-projection-batch-size", "2"]
                if policy == "sbpm":
                    argv += ["--memory-query-handoff", "explicit"]
                with patch.object(sys, "argv", argv), \
                     patch.object(run_memory.pm_bench, "build_llm_client", return_value=None), \
                     patch.object(run_memory, "generate_helper", side_effect=helper), \
                     patch.object(run_memory.pm_bench, "request_model_action", side_effect=actor), \
                     contextlib.redirect_stdout(io.StringIO()):
                    run_memory.main()
                state = json.loads((output / "memory_snapshot.json").read_text())
                self.assertEqual(calls.count("decide"), 80, state["engine"]["errors"][:5])
                self.assertEqual(calls.count("verify"), 80 if policy == "pis_verified" else 0)
                restore_options = {}
                if policy in run_memory.PROJECTED_POLICIES:
                    from prospective_memory.method.trigger_engine import SourceBoundTriggerEngine
                    from prospective_memory.method.fair_trigger import SourceBoundFairTriggerEngine
                    engine_class = (SourceBoundFairTriggerEngine if policy == "sbpm"
                                    else SourceBoundTriggerEngine)
                    restore_options = {"projector_id": "fixture-model-config", "projection_batch_size": 2}
                    self.assertEqual(calls.count("trigger_projection"), 1)
                elif policy == "sbpm_no_projection":
                    from prospective_memory.method.source_bound_v3 import SourceBoundV3Engine
                    engine_class = SourceBoundV3Engine
                elif policy == "sbpm_minimal":
                    from prospective_memory.method.source_bound import SourceBoundPISEngine
                    engine_class = SourceBoundPISEngine
                else:
                    engine_class = run_memory.GroundedPISEngine if policy == "pis_grounded" else run_memory.PISEngine
                handoff = "explicit" if policy == "sbpm" else "legacy"
                adapter = run_memory.PMBenchAdapter(engine_class(None, **restore_options), query_handoff=handoff)
                adapter.restore(state)
                self.assertEqual(json.loads(json.dumps(adapter.snapshot())), state)
                self.assertTrue((output / "source/prospective_memory/baselines/pis.py").exists())
                if policy in run_memory.SOURCE_BOUND_VARIANTS:
                    manifest = json.loads((output / "manifest.json").read_text())
                    self.assertEqual(manifest["policy_variant"], run_memory.SOURCE_BOUND_VARIANTS[policy])
                    self.assertEqual(manifest["memory_max_tokens"], 4096)
                    self.assertEqual(manifest["pis_step_query_budget"], 2)
                    self.assertEqual(manifest["pis_query_abort_limit"], 12)
                    files = ["method/source_bound.py", "baselines/pis_registration.py", "method/calendar_guard.py"]
                    if policy in {"sbpm_no_projection", *run_memory.PROJECTED_POLICIES}:
                        files += ["method/source_bound_v3.py", "method/registration.py"]
                    if policy in run_memory.PROJECTED_POLICIES:
                        files += ["method/projection_cache.py", "method/trigger_engine.py"]
                        self.assertEqual(manifest["memory_projector_id"], "fixture-model-config")
                        self.assertEqual(manifest["memory_projection_batch_size"], 2)
                        self.assertTrue(manifest["projection_definition"]["sha256"])
                    if policy == "sbpm":
                        files += ["method/fair_checks.py", "method/fair_trigger.py"]
                        self.assertEqual(sum(e["event"] == "selection" for e in state["engine"]["arbitration_log"]), 80)
                        self.assertEqual(manifest["memory_query_handoff"], "explicit")
                        cycles = [json.loads(line) for line in (output / "memory.jsonl").read_text().splitlines()]
                        self.assertIn("optional_query_actions", cycles[0]["reminder"])
                        self.assertIn('"channel": "clock"', cycles[0]["reminder"])
                    for filename in files:
                        self.assertTrue((output / "source/prospective_memory" / filename).exists())
                        self.assertIn("prospective_memory/" + filename, manifest["source_sha256"])
                    logs = [json.loads(line) for line in (output / "memory_calls.jsonl").read_text().splitlines()]
                    self.assertEqual(sum(row["phase"] == "compile_typed" for row in logs), 1)
                    self.assertEqual(sum(row["phase"] == "assess" for row in logs), 80)
                    self.assertEqual(sum(row["phase"] == "extract" for row in logs), calls.count("extract"))
                    self.assertEqual(sum(row["phase"] == "classify_unit" for row in logs), calls.count("classify_unit"))
                    self.assertEqual(sum(row["phase"] == "identity_review" for row in logs), calls.count("identity_review"))
                    self.assertTrue(all(row["max_tokens"] == 4096 for row in logs))
                    self.assertTrue(all("system" in row and "schema" in row for row in logs))
                    self.assertEqual(sum(row["phase"] == "trigger_projection" for row in logs),
                                     1 if policy in run_memory.PROJECTED_POLICIES else 0)
                if policy == "pis_grounded":
                    self.assertEqual(calls.count("change_review"), 1)
                    self.assertTrue((output / "source/prospective_memory/pis_grounded.py").exists())
                    logs = [json.loads(line) for line in (output / "memory_calls.jsonl").read_text().splitlines()]
                    self.assertEqual(sum(row["phase"] == "change_review" for row in logs), 1)

    def test_pis_adapter_counts_wrong_queries_and_delivers_exhaustion(self):
        engine = run_memory.PISEngine(lambda *args: {"changes": []})
        adapter = run_memory.PMBenchAdapter(engine)
        messages = [
            {"role": "system", "content": "Available state channels: clock, email."},
            {"role": "user", "content": "A new event.\nStep action menu:\n- task_1: Wait."},
            {"role": "assistant", "content": json.dumps({"action": "query_state", "channel": "email"})},
            {"role": "user", "content": "State [email]: Nothing."},
            {"role": "assistant", "content": json.dumps({"action": "query_state", "channel": "email"})},
            {"role": "user", "content": "State [email]: Nothing."},
        ]
        guidance = adapter.context_for(messages)
        self.assertIn("budget exhausted", guidance)
        self.assertEqual(engine.step_queries, ["email", "email"])
        restored = run_memory.PMBenchAdapter(engine.fresh())
        restored.restore(json.loads(json.dumps(adapter.snapshot())))
        self.assertEqual(restored.engine.step_queries, ["email", "email"])
        messages.append({"role": "user", "content": "Next event.\nStep action menu:\n- task_2: Wait."})
        self.assertEqual(adapter.context_for(messages), "")
        self.assertEqual(engine.step_queries, [])


if __name__ == "__main__":
    unittest.main()
