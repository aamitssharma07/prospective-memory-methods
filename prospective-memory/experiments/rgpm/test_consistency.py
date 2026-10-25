"""Offline regression checks for selective serving-consistency reruns."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from consistency_check import longest_requests, probe, validate_served
from submit_consistency_reruns import build_plan, environment


class ConsistencyTests(unittest.TestCase):
    def test_plan_targets_only_eight_checkpoint_and_three_capacity_pairs(self):
        p = build_plan()
        self.assertEqual(len(p["pairs"]), 11)
        self.assertEqual(sum(r["actor"]["model"].startswith("mistralai/") for r in p["pairs"]), 8)
        self.assertEqual(sum(r["actor"]["model"] == "Qwen/Qwen3-32B" for r in p["pairs"]), 3)
        self.assertEqual(len({(r["logical_actor"], r["logical_helper"]) for r in p["pairs"]}), 11)
        for i, r in enumerate(p["pairs"]):
            e = environment("spec.json", i, r, "fresh")
            self.assertEqual(e["ACTOR_GUIDANCE"], "query_first")
            self.assertEqual(e["REGISTRATION_GROUNDING"], "1")
            self.assertEqual(e["SMOKE_ADMISSION_POLICY"], "report_only")
            if r["actor"]["model"].startswith("mistralai/"):
                self.assertTrue(r["actor"]["model"].endswith("-BF16"))
            if r["actor"]["model"] == "Qwen/Qwen3-32B":
                self.assertEqual(r["actor"]["minimum_cache_tokens"], 33738)

    def test_serving_capacity_and_quantization_are_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "config.json").write_text(json.dumps({"max_position_embeddings": 40960}))
            log = root / "server.log"
            log.write_text("max_total_num_tokens=33738, context_len=40960")
            expected = {"model": "Qwen/Qwen3-32B", "revision": "pinned", "dtype": "bfloat16",
                        "mem_fraction_static": 0.75, "disable_cuda_graph": True,
                        "model_context_tokens": 40960, "minimum_cache_tokens": 33738}
            provenance = {**expected, "checkpoint": str(root), "server_log": str(log),
                          "command": ["serve", "--tp-size", "1", "--disable-prefill-cuda-graph", "--disable-decode-cuda-graph"]}
            self.assertEqual(validate_served(expected, provenance)["effective_cache_tokens"], 33738)
            log.write_text("max_total_num_tokens=16753, context_len=40960")
            with self.assertRaises(ValueError):
                validate_served(expected, provenance)
            log.write_text("max_total_num_tokens=33738, context_len=40960")
            (root / "config.json").write_text(json.dumps({"max_position_embeddings": 40960,
                                                         "quantization_config": {"quant_method": "fp8"}}))
            with self.assertRaises(ValueError):
                validate_served(expected, provenance)

    def test_probe_keeps_context_failure_distinct_from_transport_failure(self):
        def fail_context(**kwargs):
            raise ValueError("Input length (50000 tokens) exceeds the maximum allowed length (33732 tokens)")
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fail_context)))
        record, fatal = probe(client, {"max_tokens": 768}, "actor", "original")
        self.assertTrue(record["context_limit_rejected"])
        self.assertIsNone(fatal)
        self.assertIsNone(record["usage"])
        self.assertIn("duration_seconds", record)
        def fail_transport(**kwargs):
            raise ConnectionError("server disconnected")
        client.chat.completions.create = fail_transport
        record, fatal = probe(client, {"max_tokens": 768}, "actor", "original")
        self.assertIsInstance(fatal, ConnectionError)

    def test_longest_probe_preserves_public_messages_and_original_call_id(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records = [{"role": "actor", "call_id": str(i), "request": {
                "messages": [{"role": "user", "content": "public " * i}], "max_tokens": 768}}
                for i in (1, 3)]
            (root / "calls.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
            result = longest_requests(root)
            self.assertEqual(result["actor"][1], "3")
            self.assertEqual(result["actor"][2], records[1]["request"])
