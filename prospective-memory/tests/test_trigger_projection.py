"""Isolated static-projection contracts. Scripted callbacks make no model calls."""

import copy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from prospective_memory.core import Instruction, Intention
from prospective_memory.method.projection_cache import PROJECT, SCHEMA, TriggerProjectionCache, projection_definition


PROJECTOR_ID = "scripted-model:v1;temperature=0;token-budget=4096"


def source_state(number=1):
    key, message_id = f"pm_{number:06d}", f"request_{number}"
    text = "Deliver the sealed packet to Dana when the authorization arrives."
    intention = Intention(key, text, text, ("inbox",), instruction_ids=(message_id,), evidence_quote=text)
    return intention, {message_id: Instruction(message_id, text)}


def response_row(binding, **updates):
    i = binding["intention"]
    return {"intention_id": i["id"], "revision": i["revision"],
            "source_instruction_ids": list(i["instruction_ids"]), "status": "projected",
            "action_to_perform_next": "Deliver the sealed packet to Dana",
            "readiness_question": "Has the authorization arrived?",
            "reason": "Scripted static decomposition", **updates}


class Provider:
    def __init__(self):
        self.calls = []
        self.rows = None
        self.fail = False

    def __call__(self, system, payload, schema):
        self.calls.append((system, copy.deepcopy(payload), copy.deepcopy(schema)))
        if self.fail:
            raise RuntimeError("Scripted provider outage")
        rows = self.rows(payload) if callable(self.rows) else self.rows
        return {"trigger_projections": copy.deepcopy(rows) if rows is not None
                else [response_row(b) for b in payload["records"]]}


class TriggerProjectionTests(unittest.TestCase):
    def test_public_definition_fingerprint_matches_cache_and_cannot_mutate_schema(self):
        cache = TriggerProjectionCache(None, projector_id=PROJECTOR_ID)
        definition = projection_definition()
        self.assertEqual(set(definition), {"prompt", "schema", "sha256"})
        self.assertEqual(definition["sha256"], cache.snapshot()["projector"]["prompt_schema_sha256"])
        before = copy.deepcopy(SCHEMA)
        definition["schema"].clear()
        self.assertEqual(SCHEMA, before)

    def test_prompt_contrasts_independent_repeated_occasions_with_joint_prerequisites(self):
        # A contract assertion, not evidence that a live model follows it.
        self.assertIn("AND AGAIN", PROJECT)
        self.assertIn("Has the process just started OR just exited?", PROJECT)
        self.assertIn("BOTH prerequisites as a conjunction", PROJECT)

    def cache(self):
        p = Provider()
        return TriggerProjectionCache(p, projector_id=PROJECTOR_ID), p

    def test_static_projection_keeps_original_source_unchanged_and_is_not_an_action(self):
        i, sources = source_state()
        original = copy.deepcopy((i, sources))
        cache, p = self.cache()
        self.assertEqual(cache.refresh([i], sources), [i.id])
        view = cache.get(i, sources)
        self.assertEqual(view.status, "projected")
        self.assertEqual(view.action_to_perform_next, "Deliver the sealed packet to Dana")
        self.assertEqual(view.readiness_question, "Has the authorization arrived?")
        self.assertEqual(view.source_instruction_ids, i.instruction_ids)
        self.assertEqual((i, sources), original)
        self.assertEqual(i.status, "pending")
        self.assertFalse(hasattr(view, "all_conditions_met"))
        self.assertFalse(hasattr(cache, "tick"))
        self.assertFalse(hasattr(cache, "acknowledge"))
        self.assertEqual(len(p.calls), 1)

    def test_unchanged_bank_uses_cache_without_repeat_callback(self):
        i, sources = source_state()
        cache, p = self.cache()
        cache.refresh([i], sources)
        self.assertEqual(cache.refresh([i], sources), [])
        self.assertEqual(len(p.calls), 1)
        self.assertIsNotNone(cache.get(i, sources))
        self.assertEqual(len(p.calls), 1)

    def test_revision_invalidates_old_view_and_preserves_chronological_sources(self):
        i, sources = source_state()
        cache, p = self.cache()
        cache.refresh([i], sources)
        sources["update"] = Instruction("update", "Use written authorization from Lee instead.")
        revised = replace(i, revision=2, instruction_ids=i.instruction_ids + ("update",),
                          condition=i.condition + "\n" + sources["update"].text)
        self.assertIsNone(cache.get(revised, sources))
        self.assertEqual(cache.refresh([revised], sources), [i.id])
        view = cache.get(revised, sources)
        self.assertEqual(view.revision, 2)
        self.assertEqual(view.source_instruction_ids, ("request_1", "update"))
        self.assertEqual([m["id"] for m in p.calls[-1][1]["records"][0]["original_instructions"]],
                         ["request_1", "update"])

    def test_source_text_change_with_same_revision_still_invalidates(self):
        i, sources = source_state()
        cache, p = self.cache()
        cache.refresh([i], sources)
        changed = {"request_1": Instruction("request_1", sources["request_1"].text + " Keep it sealed.")}
        self.assertIsNone(cache.get(i, changed))
        cache.refresh([i], changed)
        self.assertEqual(len(p.calls), 2)

    def test_scope_source_set_condition_and_recurrence_changes_also_invalidate(self):
        i, sources = source_state()
        for update in [{"scope": "project-blue"}, {"sources": ("sensor",)},
                       {"repeat": True}, {"condition": "Only after explicit written approval."}]:
            with self.subTest(update=update):
                cache, _ = self.cache()
                cache.refresh([i], sources)
                self.assertIsNone(cache.get(replace(i, **update), sources))

    def test_closed_and_removed_intentions_retire_derived_views_without_calls(self):
        i, sources = source_state()
        for status in ("completed", "cancelled"):
            with self.subTest(status=status):
                cache, p = self.cache()
                cache.refresh([i], sources)
                closed = replace(i, status=status)
                self.assertIsNone(cache.get(closed, sources))
                self.assertEqual(cache.refresh([closed], sources), [])
                self.assertEqual(cache.snapshot()["entries"], [])
                self.assertEqual(len(p.calls), 1)
        cache, p = self.cache()
        cache.refresh([i], sources)
        cache.refresh([], sources)
        self.assertIsNone(cache.get(i, sources))
        self.assertEqual(len(p.calls), 1)

    def test_explicit_status_rebind_preserves_static_view_without_callback(self):
        i, sources = source_state()
        cache, p = self.cache()
        cache.refresh([i], sources)
        view = cache.get(i, sources)
        attempted = replace(i, status="attempted")
        self.assertTrue(cache.rebind_status(attempted, sources))
        self.assertIs(cache.get(attempted, sources), view)
        self.assertTrue(cache.rebind_status(i, sources))
        self.assertIs(cache.get(i, sources), view)
        self.assertEqual(cache.refresh([i], sources), [])
        self.assertEqual(len(p.calls), 1)

    def test_general_get_does_not_implicitly_rebind_status(self):
        i, sources = source_state()
        cache, p = self.cache()
        cache.refresh([i], sources)
        attempted = replace(i, status="attempted")
        self.assertIsNone(cache.get(attempted, sources))
        self.assertFalse(cache.rebind_status(attempted, sources))
        self.assertEqual(len(p.calls), 1)

    def test_status_rebind_rejects_closure_or_any_other_binding_change(self):
        i, sources = source_state()
        changes = [{"status": "completed"}, {"status": "cancelled"},
                   {"status": "attempted", "revision": 2},
                   {"status": "attempted", "action": "Another requested action"},
                   {"status": "attempted", "condition": "Another condition"},
                   {"status": "attempted", "sources": ("sensor",)},
                   {"status": "attempted", "scope": "another-scope"},
                   {"status": "attempted", "repeat": True}]
        for update in changes:
            with self.subTest(update=update):
                cache, p = self.cache()
                cache.refresh([i], sources)
                self.assertFalse(cache.rebind_status(replace(i, **update), sources))
                self.assertEqual(cache.snapshot()["entries"], [])
                self.assertEqual(len(p.calls), 1)

    def test_status_rebind_rejects_changed_full_source_missing_source_and_config(self):
        i, sources = source_state()
        attempted = replace(i, status="attempted")
        cache, p = self.cache()
        cache.refresh([i], sources)
        changed = {"request_1": replace(sources["request_1"], text="Deliver only after written authorization.")}
        self.assertFalse(cache.rebind_status(attempted, changed))
        self.assertEqual(cache.snapshot()["entries"], [])
        self.assertEqual(len(p.calls), 1)
        cache, p = self.cache()
        cache.refresh([i], sources)
        with self.assertRaises(ValueError):
            cache.rebind_status(attempted, {})
        self.assertEqual(cache.snapshot()["entries"], [])
        self.assertEqual(len(p.calls), 1)
        cache, p = self.cache()
        cache.refresh([i], sources)
        # Simulate a changed configuration binding, never an inference call.
        cache._projector["identity"] = "changed-model-config"
        self.assertFalse(cache.rebind_status(attempted, sources))
        self.assertEqual(cache.snapshot()["entries"], [])
        self.assertEqual(len(p.calls), 1)

    def test_status_rebind_snapshot_is_stable_and_restores_without_callback(self):
        i, sources = source_state()
        cache, p = self.cache()
        cache.refresh([i], sources)
        before = cache.snapshot()
        attempted = replace(i, status="attempted")
        cache.rebind_status(attempted, sources)
        rebound = cache.snapshot()
        self.assertNotEqual(rebound["entries"][0]["binding_sha256"], before["entries"][0]["binding_sha256"])
        self.assertEqual(rebound["entries"][0]["projection"], before["entries"][0]["projection"])
        restored = TriggerProjectionCache(p, projector_id=PROJECTOR_ID)
        restored.restore(json.loads(json.dumps(rebound)))
        self.assertEqual(restored.snapshot(), rebound)
        self.assertIsNotNone(restored.get(attempted, sources))
        self.assertTrue(restored.rebind_status(i, sources))
        self.assertEqual(restored.snapshot(), before)
        self.assertEqual(len(p.calls), 1)

    def test_batched_requests_only_include_new_or_changed_records(self):
        bank, sources = [], {}
        for n in range(1, 6):
            i, original = source_state(n)
            bank.append(i)
            sources.update(original)
        p = Provider()
        cache = TriggerProjectionCache(p, projector_id=PROJECTOR_ID, batch_size=2)
        cache.refresh(bank, sources)
        self.assertEqual([len(payload["records"]) for _, payload, _ in p.calls], [2, 2, 1])
        bank[2] = replace(bank[2], revision=2)
        cache.refresh(bank, sources)
        self.assertEqual(len(p.calls), 4)
        self.assertEqual(p.calls[-1][1]["records"][0]["intention"]["id"], bank[2].id)

    def test_unsupported_view_is_cached_empty_and_retry_is_explicit(self):
        i, sources = source_state()
        cache, p = self.cache()
        p.rows = lambda payload: [response_row(payload["records"][0], status="unsupported",
            action_to_perform_next="", readiness_question="", reason="Cannot separate safely")]
        cache.refresh([i], sources)
        view = cache.get(i, sources)
        self.assertEqual((view.status, view.action_to_perform_next, view.readiness_question), ("unsupported", "", ""))
        cache.refresh([i], sources)
        self.assertEqual(len(p.calls), 1)
        self.assertTrue(cache.invalidate(i.id))
        self.assertFalse(cache.invalidate(i.id))
        p.rows = None
        cache.refresh([i], sources)
        self.assertEqual(len(p.calls), 2)
        self.assertEqual(cache.get(i, sources).status, "projected")

    def test_provider_failure_does_not_expose_stale_projection_after_revision(self):
        i, sources = source_state()
        cache, p = self.cache()
        cache.refresh([i], sources)
        p.fail = True
        revised = replace(i, revision=2)
        cache.refresh([revised], sources)
        view = cache.get(revised, sources)
        self.assertEqual((view.status, view.revision, view.action_to_perform_next), ("error", 2, ""))
        self.assertEqual(cache.errors[-1]["phase"], "projection_request")
        cache.refresh([revised], sources)
        self.assertEqual(len(p.calls), 2)

    def test_unknown_model_identity_never_creates_an_unrequested_view(self):
        i, sources = source_state()
        cache, p = self.cache()
        p.rows = lambda payload: [response_row(payload["records"][0], intention_id="unknown")]
        cache.refresh([i], sources)
        self.assertEqual(cache.get(i, sources).status, "error")
        self.assertEqual([e["projection"]["intention_id"] for e in cache.snapshot()["entries"]], [i.id])

    def test_stale_revisions_foreign_missing_or_reordered_sources_fail_closed(self):
        i, sources = source_state()
        sources["update"] = Instruction("update", "Retain the seal.")
        i = replace(i, revision=2, instruction_ids=i.instruction_ids + ("update",))
        for update in [{"revision": 1}, {"revision": True},
                       {"source_instruction_ids": ["foreign"]},
                       {"source_instruction_ids": ["request_1"]},
                       {"source_instruction_ids": ["update", "request_1"]}]:
            with self.subTest(update=update):
                cache, p = self.cache()
                p.rows = lambda payload: [response_row(payload["records"][0], **update)]
                cache.refresh([i], sources)
                self.assertEqual(cache.get(i, sources).status, "error")

    def test_duplicate_or_missing_rows_cannot_choose_arbitrary_interpretation(self):
        i, sources = source_state()
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):
                cache, p = self.cache()
                p.rows = (lambda payload: [response_row(payload["records"][0])] * 2) if duplicate else []
                cache.refresh([i], sources)
                self.assertEqual(cache.get(i, sources).status, "error")

    def test_invalid_row_does_not_discard_independent_valid_projection(self):
        first, sources = source_state()
        second, others = source_state(2)
        sources.update(others)
        cache, p = self.cache()
        p.rows = lambda payload: [response_row(payload["records"][0], readiness_question=""),
                                  response_row(payload["records"][1])]
        cache.refresh([first, second], sources)
        self.assertEqual(cache.get(first, sources).status, "error")
        self.assertEqual(cache.get(second, sources).status, "projected")

    def test_output_cannot_smuggle_readiness_evidence_or_completion_fields(self):
        i, sources = source_state()
        for update in [{"all_conditions_met": True}, {"evidence_ids": ["e1"]},
                       {"status": "completed"}, {"status": "ACT"}, {"observed_time": "12:00"}]:
            with self.subTest(update=update):
                cache, p = self.cache()
                p.rows = lambda payload: [response_row(payload["records"][0], **update)]
                cache.refresh([i], sources)
                self.assertEqual(cache.get(i, sources).status, "error")

    def test_unsupported_with_nonempty_derived_text_rejected(self):
        i, sources = source_state()
        cache, p = self.cache()
        p.rows = lambda payload: [response_row(payload["records"][0], status="unsupported")]
        cache.refresh([i], sources)
        self.assertEqual(cache.get(i, sources).status, "error")

    def test_bad_identity_types_and_long_text_fail_safely(self):
        i, sources = source_state()
        for update in [{"intention_id": []}, {"readiness_question": "x" * 801},
                       {"action_to_perform_next": 123}, {"reason": None}]:
            with self.subTest(update=update):
                cache, p = self.cache()
                p.rows = lambda payload: [response_row(payload["records"][0], **update)]
                cache.refresh([i], sources)
                self.assertEqual(cache.get(i, sources).status, "error")

    def test_missing_current_source_cannot_return_previously_cached_view(self):
        i, sources = source_state()
        cache, _ = self.cache()
        cache.refresh([i], sources)
        with self.assertRaises(ValueError):
            cache.get(i, {})
        self.assertEqual(cache.snapshot()["entries"], [])

    def test_invalid_input_bank_is_rejected_before_mutating_cache(self):
        i, sources = source_state()
        cache, p = self.cache()
        cache.refresh([i], sources)
        before = cache.snapshot()
        for bank, originals in [([i, i], sources), ([i], {}),
                                ([replace(i, instruction_ids=())], sources),
                                ([replace(i, revision=True)], sources)]:
            with self.subTest(bank=bank):
                with self.assertRaises(ValueError):
                    cache.refresh(bank, originals)
                self.assertEqual(cache.snapshot(), before)
        self.assertEqual(len(p.calls), 1)

    def test_request_sees_exact_originals_but_no_observations_or_expected_outcomes(self):
        i, sources = source_state()
        cache, p = self.cache()
        cache.refresh([i], sources)
        _, payload, _ = p.calls[0]
        self.assertEqual(set(payload), {"records"})
        self.assertEqual(set(payload["records"][0]), {"intention", "original_instructions"})
        self.assertEqual(payload["records"][0]["original_instructions"][0]["text"], sources["request_1"].text)
        self.assertNotIn("observations", json.dumps(payload))
        self.assertNotIn("expected_", json.dumps(payload))

    def test_callback_cannot_mutate_authoritative_sources_or_global_schema(self):
        i, sources = source_state()
        before = copy.deepcopy((i, sources, SCHEMA))

        def hostile(system, payload, schema):
            row = response_row(payload["records"][0])
            payload["records"][0]["original_instructions"][0]["text"] = "Changed"
            schema.clear()
            return {"trigger_projections": [row]}

        cache = TriggerProjectionCache(hostile, projector_id=PROJECTOR_ID)
        cache.refresh([i], sources)
        self.assertEqual((i, sources, SCHEMA), before)
        self.assertEqual(cache.snapshot()["entries"][0]["binding"]["original_instructions"][0]["text"], sources["request_1"].text)

    def test_more_than_32_historical_sources_remain_preserved(self):
        i, sources = source_state()
        for n in range(1, 35):
            sources[f"u{n}"] = Instruction(f"u{n}", f"Accepted context update {n}.")
        i = replace(i, revision=35, instruction_ids=tuple(sources))
        cache, _ = self.cache()
        cache.refresh([i], sources)
        self.assertEqual(cache.get(i, sources).source_instruction_ids, i.instruction_ids)

    def test_snapshot_roundtrip_has_no_callbacks_and_revalidates_current_binding(self):
        i, sources = source_state()
        cache, p = self.cache()
        cache.refresh([i], sources)
        state = json.loads(json.dumps(cache.snapshot()))
        restored = TriggerProjectionCache(p, projector_id=PROJECTOR_ID, batch_size=1)
        restored.restore(state)
        self.assertEqual(restored.snapshot(), cache.snapshot())
        self.assertEqual(restored.get(i, sources), cache.get(i, sources))
        self.assertEqual(restored.batch_size, 4)
        self.assertEqual(len(p.calls), 1)
        self.assertIsNone(restored.get(replace(i, revision=2), sources))

    def test_snapshot_error_and_unsupported_states_roundtrip(self):
        i, sources = source_state()
        for fail in (False, True):
            with self.subTest(fail=fail):
                cache, p = self.cache()
                p.fail = fail
                if not fail:
                    p.rows = lambda payload: [response_row(payload["records"][0], status="unsupported",
                                                           action_to_perform_next="", readiness_question="")]
                cache.refresh([i], sources)
                restored = TriggerProjectionCache(None, projector_id=PROJECTOR_ID)
                restored.restore(json.loads(json.dumps(cache.snapshot())))
                self.assertEqual(restored.snapshot(), cache.snapshot())

    def test_snapshot_tampering_rejected_atomically(self):
        i, sources = source_state()
        cache, p = self.cache()
        cache.refresh([i], sources)
        original = cache.snapshot()
        mutations = [lambda s: s.update(kind="another_cache"),
                     lambda s: s.update(version=True),
                     lambda s: s["projector"].update(identity="another-model"),
                     lambda s: s["projector"].update(prompt_schema_sha256="wrong"),
                     lambda s: s["entries"][0]["binding"]["projector"].update(identity="another-model"),
                     lambda s: s["entries"][0].update(binding_sha256="wrong"),
                     lambda s: s["entries"][0]["projection"].update(revision=99),
                     lambda s: s["entries"][0]["projection"].update(source_instruction_ids=["foreign"]),
                     lambda s: s["entries"][0]["binding"]["original_instructions"][0].update(text="Changed"),
                     lambda s: s["entries"].append(copy.deepcopy(s["entries"][0])),
                     lambda s: s["errors"].append({"bad": "error"})]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                bad = copy.deepcopy(original)
                mutate(bad)
                with self.assertRaises(ValueError):
                    cache.restore(bad)
                self.assertEqual(cache.snapshot(), original)
        self.assertEqual(len(p.calls), 1)

    def test_snapshot_return_value_cannot_mutate_internal_bindings(self):
        i, sources = source_state()
        cache, _ = self.cache()
        cache.refresh([i], sources)
        state = cache.snapshot()
        state["entries"][0]["binding"]["original_instructions"][0]["text"] = "Changed"
        self.assertEqual(cache.get(i, sources).status, "projected")
        self.assertNotEqual(cache.snapshot()["entries"][0]["binding"]["original_instructions"][0]["text"], "Changed")

    def test_invalid_batch_sizes_rejected(self):
        for size in (0, 33, -1, True, 1.5):
            with self.subTest(size=size), self.assertRaises(ValueError):
                TriggerProjectionCache(None, projector_id=PROJECTOR_ID, batch_size=size)

    def test_model_configuration_identity_is_required(self):
        with self.assertRaises(TypeError):
            TriggerProjectionCache(None)
        for identity in (None, "", " ", 123, {}):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                TriggerProjectionCache(None, projector_id=identity)

    def test_snapshot_model_configuration_mismatch_rejected_without_inference(self):
        i, sources = source_state()
        cache, p = self.cache()
        cache.refresh([i], sources)
        state = cache.snapshot()
        self.assertEqual(state["projector"]["identity"], PROJECTOR_ID)
        self.assertEqual(state["entries"][0]["binding"]["projector"], state["projector"])
        other = TriggerProjectionCache(p, projector_id="scripted-model:v2;temperature=0")
        before = other.snapshot()
        with self.assertRaises(ValueError):
            other.restore(state)
        self.assertEqual(other.snapshot(), before)
        self.assertEqual(len(p.calls), 1)

    def test_prompt_and_schema_changes_reject_prior_snapshot(self):
        i, sources = source_state()
        cache, p = self.cache()
        cache.refresh([i], sources)
        state = cache.snapshot()
        changed_schema = copy.deepcopy(SCHEMA)
        changed_schema["description"] = "Different projection contract"
        for name, value in (("PROJECT", PROJECT + "\nAdditional instruction."), ("SCHEMA", changed_schema)):
            with self.subTest(name=name), patch("prospective_memory.method.projection_cache." + name, value):
                other = TriggerProjectionCache(p, projector_id=PROJECTOR_ID)
                before = other.snapshot()
                with self.assertRaises(ValueError):
                    other.restore(state)
                self.assertEqual(other.snapshot(), before)
        self.assertEqual(len(p.calls), 1)

    def test_default_batch_is_four_not_a_transport_token_guarantee(self):
        bank, sources = [], {}
        for n in range(1, 6):
            intention, originals = source_state(n)
            bank.append(intention)
            sources.update(originals)
        cache, p = self.cache()
        cache.refresh(bank, sources)
        self.assertEqual([len(payload["records"]) for _, payload, _ in p.calls], [4, 1])

    def test_cached_definition_is_frozen_against_global_prompt_schema_mutation(self):
        i, sources = source_state()
        cache, p = self.cache()
        original_profile = cache.snapshot()["projector"]
        with patch("prospective_memory.method.projection_cache.PROJECT", "Changed prompt"), \
                patch("prospective_memory.method.projection_cache.SCHEMA", {}):
            cache.refresh([i], sources)
            self.assertEqual(p.calls[0][0], PROJECT)
            self.assertEqual(p.calls[0][2], SCHEMA)
            cache.restore(cache.snapshot())
        self.assertEqual(cache.snapshot()["projector"], original_profile)


if __name__ == "__main__":
    unittest.main()
