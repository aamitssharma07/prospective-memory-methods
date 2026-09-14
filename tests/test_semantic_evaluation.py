"""Deterministic checks of semantic-stream evaluation, not model accuracy."""

import copy
import json
import unittest

from prospective_memory.evaluate import evaluate_case


def registration(instruction, *, action="Notify the team", condition="Build completes",
                 sources=("events",), **changes):
    return {
        "op": "register", "action": action, "condition": condition,
        "sources": list(sources), "scope": instruction.get("scope", ""),
        "repeat": False, "target_id": "", "evidence_quote": instruction["text"],
        **changes,
    }


def decision(kind, intention, *, evidence=(), source=""):
    return {
        "kind": kind, "intention_id": intention["id"], "reason": "Scripted test",
        "evidence_ids": list(evidence), "source": source,
    }


class ScriptedRequest:
    def __init__(self, assess, compile=None):
        self.assess = assess
        self.compile = compile or (lambda payload: [registration(payload["instruction"])])
        self.calls = []

    def __call__(self, system, payload, schema):
        self.calls.append(copy.deepcopy({"system": system, "payload": payload, "schema": schema}))
        if "changes" in schema["properties"]:
            return {"changes": self.compile(payload)}
        return {"decisions": self.assess(payload)}

    @property
    def assessments(self):
        return [call["payload"] for call in self.calls if "observations" in call["payload"]]


def observation(identifier, text, source="events", current=True):
    return {"id": identifier, "text": text, "source": source, "current": current}


def case_with_ticks(*ticks):
    return {
        "id": "scripted-case", "sources": ["events", "build_status"],
        "queryable_sources": ["build_status"],
        "instructions": [{"id": "request", "text": "When the build completes, notify the team."}],
        "ticks": list(ticks),
    }


def tick(identifier, observations=(), expected=(), **extra):
    return {
        "id": identifier, "observations": list(observations),
        "expected_act_instruction_ids": list(expected), **extra,
    }


class SemanticEvaluationTests(unittest.TestCase):
    def assert_score(self, result, tp, fp, fn):
        self.assertEqual((result["tp"], result["fp"], result["fn"]), (tp, fp, fn))

    def test_supported_act_is_scored_without_claiming_execution(self):
        request = ScriptedRequest(lambda payload: [
            decision("ACT", payload["intentions"][0], evidence=("complete",))
        ])
        result = evaluate_case(case_with_ticks(tick(
            "ready", [observation("complete", "The build is complete.")], ["request"]
        )), request)
        self.assert_score(result, 1, 0, 0)
        self.assertEqual(result["ticks"][0]["predictions"], ["request"])
        self.assertEqual(result["ticks"][0]["expected"], ["request"])
        self.assertEqual(result["final_state"]["intentions"][0]["status"], "pending")
        self.assertEqual(result["engine_errors"], [])

    def test_expected_labels_and_unqueried_pull_results_are_not_model_inputs(self):
        request = ScriptedRequest(lambda payload: [])
        case = case_with_ticks(tick(
            "PRIVATE_TICK_ID", [observation("visible", "An unrelated meeting begins.")],
            ["request"], pull_responses={"build_status": [
                observation("PRIVATE_RESULT_ID", "PRIVATE_UNOBSERVED_RESULT", "build_status")
            ]},
        ))
        case["private_gold_annotation"] = "PRIVATE_GOLD_VALUE"
        result = evaluate_case(case, request)
        self.assert_score(result, 0, 0, 1)
        serialized = json.dumps(request.calls)
        for forbidden in ("expected_act_instruction_ids", "pull_responses",
                          "PRIVATE_TICK_ID", "PRIVATE_RESULT_ID",
                          "PRIVATE_UNOBSERVED_RESULT", "PRIVATE_GOLD_VALUE"):
            self.assertNotIn(forbidden, serialized)

    def test_check_reveals_only_requested_response_then_allows_act(self):
        def assess(payload):
            item = payload["intentions"][0]
            ids = {row["id"] for row in payload["observations"]}
            if "complete" in ids:
                return [decision("ACT", item, evidence=("complete",))]
            return [decision("CHECK", item, source="build_status")]

        request = ScriptedRequest(assess, lambda payload: [
            registration(payload["instruction"], sources=("build_status",))
        ])
        case = case_with_ticks(tick("ready", expected=["request"], pull_responses={
            "build_status": [observation("complete", "The build is complete.", "build_status")],
        }))
        result = evaluate_case(case, request)
        self.assert_score(result, 1, 0, 0)
        self.assertEqual(result["executed_queries"], 1)
        self.assertEqual(result["ticks"][0]["queried_sources"], ["build_status"])
        self.assertEqual(len(request.assessments), 2)
        self.assertEqual(request.assessments[0]["observations"], [])
        self.assertEqual(request.assessments[1]["observations"][0]["id"], "complete")

    def test_fabricated_reference_to_unqueried_result_is_rejected(self):
        request = ScriptedRequest(lambda payload: [
            decision("ACT", payload["intentions"][0], evidence=("not_requested",))
        ], lambda payload: [registration(payload["instruction"], sources=("build_status",))])
        result = evaluate_case(case_with_ticks(tick(
            "ready", expected=["request"], pull_responses={"build_status": [
                observation("not_requested", "Build complete.", "build_status")
            ]},
        )), request)
        self.assert_score(result, 0, 0, 1)
        self.assertTrue(result["engine_errors"])
        self.assertEqual(request.assessments[0]["observations"], [])

    def test_early_false_positive_does_not_erase_later_false_negative(self):
        def assess(payload):
            if any(row["id"] == "too_early" for row in payload["observations"]):
                return [decision("ACT", payload["intentions"][0], evidence=("too_early",))]
            return []

        result = evaluate_case(case_with_ticks(
            tick("early", [observation("too_early", "The build is still running.")]),
            tick("due", [observation("complete", "The build is complete.")], ["request"]),
        ), ScriptedRequest(assess))
        self.assert_score(result, 0, 1, 1)
        self.assertEqual(result["ticks"][0]["fp"], 1)
        self.assertEqual(result["ticks"][1]["fn"], 1)

    def test_semantically_duplicate_intentions_count_as_extra_false_positive(self):
        def compile(payload):
            instruction = payload["instruction"]
            return [registration(instruction, action="Notify the team"),
                    registration(instruction, action="Send the team a notification")]

        request = ScriptedRequest(lambda payload: [
            decision("ACT", item, evidence=("complete",)) for item in payload["intentions"]
        ], compile)
        result = evaluate_case(case_with_ticks(tick(
            "ready", [observation("complete", "The build is complete.")], ["request"]
        )), request)
        self.assert_score(result, 1, 1, 0)
        self.assertEqual(result["ticks"][0]["predictions"].count("request"), 2)

    def test_revision_is_scored_against_original_instruction_provenance(self):
        def compile(payload):
            instruction = payload["instruction"]
            if instruction["id"] == "revision":
                return [registration(instruction, op="revise", condition="Review approved",
                                     target_id=payload["intentions"][0]["id"])]
            return [registration(instruction)]

        request = ScriptedRequest(lambda payload: [
            decision("ACT", payload["intentions"][0], evidence=("approved",))
        ], compile)
        result = evaluate_case(case_with_ticks(tick(
            "revised", [observation("approved", "The review is approved.")], ["request"],
            instructions=[{"id": "revision", "text": "Notify the team when the review is approved instead."}],
        )), request)
        self.assert_score(result, 1, 0, 0)
        self.assertEqual(result["ticks"][0]["predictions"], ["request"])
        self.assertEqual(tuple(result["final_state"]["intentions"][0]["instruction_ids"]),
                         ("request", "revision"))

    def test_zero_query_rounds_does_not_reveal_pull_results(self):
        request = ScriptedRequest(lambda payload: [
            decision("CHECK", payload["intentions"][0], source="build_status")
        ], lambda payload: [registration(payload["instruction"], sources=("build_status",))])
        result = evaluate_case(case_with_ticks(tick(
            "ready", expected=["request"], pull_responses={"build_status": [
                observation("complete", "Build complete.", "build_status")
            ]},
        )), request, max_query_rounds=0)
        self.assert_score(result, 0, 0, 1)
        self.assertEqual(result["executed_queries"], 0)
        self.assertEqual(len(request.assessments), 1)
        self.assertEqual(request.assessments[0]["observations"], [])

    def test_repeated_checks_stop_at_host_round_budget(self):
        request = ScriptedRequest(lambda payload: [
            decision("CHECK", payload["intentions"][0], source="build_status")
        ], lambda payload: [registration(payload["instruction"], sources=("build_status",))])
        result = evaluate_case(case_with_ticks(tick(
            "not_ready", pull_responses={"build_status": [
                observation("running", "Build still running.", "build_status")
            ]},
        )), request, max_query_rounds=1)
        self.assert_score(result, 0, 0, 0)
        self.assertEqual(result["executed_queries"], 1)
        self.assertEqual(len(request.assessments), 2)

    def test_host_preserves_push_evidence_while_adding_pulled_evidence(self):
        def assess(payload):
            item = payload["intentions"][0]
            ids = {row["id"] for row in payload["observations"]}
            if {"approved", "complete"} <= ids:
                return [decision("ACT", item, evidence=("approved", "complete"))]
            return [decision("CHECK", item, source="build_status")]

        request = ScriptedRequest(assess, lambda payload: [
            registration(payload["instruction"], sources=("events", "build_status"),
                         condition="Build completes and review is approved")
        ])
        result = evaluate_case(case_with_ticks(tick(
            "conjunction", [observation("approved", "Review approved.")], ["request"],
            pull_responses={"build_status": [
                observation("complete", "Build complete.", "build_status")
            ]},
        )), request)
        self.assert_score(result, 1, 0, 0)
        self.assertEqual({row["id"] for row in request.assessments[1]["observations"]},
                         {"approved", "complete"})

    def test_mismatched_pull_response_source_is_rejected(self):
        request = ScriptedRequest(lambda payload: [
            decision("CHECK", payload["intentions"][0], source="build_status")
        ], lambda payload: [registration(payload["instruction"], sources=("build_status",))])
        malformed = case_with_ticks(tick("invalid", pull_responses={
            "build_status": [observation("complete", "Build complete.", "events")]
        }))
        with self.assertRaisesRegex(ValueError, "source"):
            evaluate_case(malformed, request)

    def test_one_query_budget_limits_two_independent_query_proposals(self):
        case = case_with_ticks(tick("both_due", expected=["request", "second"],
                                   pull_responses={
            "build_status": [observation("build_complete", "Build complete.", "build_status")],
            "review_status": [observation("review_complete", "Review complete.", "review_status")],
        }))
        case["sources"].append("review_status")
        case["queryable_sources"].append("review_status")
        case["instructions"].append({"id": "second", "text": "When the review completes, notify the team."})

        def compile(payload):
            source = "build_status" if payload["instruction"]["id"] == "request" else "review_status"
            return [registration(payload["instruction"], sources=(source,))]

        def assess(payload):
            rows = []
            for item in payload["intentions"]:
                source = item["sources"][0]
                evidence = [row["id"] for row in payload["observations"] if row["source"] == source]
                rows.append(decision("ACT", item, evidence=evidence) if evidence
                            else decision("CHECK", item, source=source))
            return rows

        request = ScriptedRequest(assess, compile)
        result = evaluate_case(case, request, max_query_rounds=1)
        self.assert_score(result, 1, 0, 1)
        self.assertEqual(result["executed_queries"], 1)
        self.assertNotIn("review_complete", json.dumps(request.assessments))

    def test_same_intention_is_counted_once_across_query_rounds(self):
        case = case_with_ticks(tick(
            "ready", [observation("first_event", "A delivery arrived.")], ["request"],
            pull_responses={"build_status": [observation("second_event", "Build complete.", "build_status")]},
        ))
        case["instructions"].append({"id": "second", "text": "When the review completes, notify the reviewer."})

        def compile(payload):
            is_first = payload["instruction"]["id"] == "request"
            return [registration(payload["instruction"],
                                 action="First action" if is_first else "Second action",
                                 sources=("events", "build_status") if is_first else ("build_status",))]

        def assess(payload):
            first, second = payload["intentions"]
            ids = {row["id"] for row in payload["observations"]}
            evidence = "second_event" if "second_event" in ids else "first_event"
            return [decision("ACT", first, evidence=(evidence,)),
                    decision("CHECK", second, source="build_status")]

        result = evaluate_case(case, ScriptedRequest(assess, compile))
        self.assert_score(result, 1, 0, 0)
        self.assertEqual(len(result["ticks"][0]["acts"]), 1)

    def test_push_only_source_cannot_be_queried(self):
        request = ScriptedRequest(lambda payload: [
            decision("CHECK", payload["intentions"][0], source="events")
        ])
        result = evaluate_case(case_with_ticks(tick("idle")), request)
        self.assert_score(result, 0, 0, 0)
        self.assertTrue(result["engine_errors"])
        self.assertEqual(len(request.assessments), 1)

    def test_unknown_observation_source_cannot_support_an_act(self):
        request = ScriptedRequest(lambda payload: [
            decision("ACT", payload["intentions"][0], evidence=("fabricated",))
        ])
        result = evaluate_case(case_with_ticks(tick(
            "bad_source", [observation("fabricated", "Build complete.", "hidden_sensor")],
            ["request"],
        )), request)
        self.assert_score(result, 0, 0, 1)
        self.assertTrue(result["engine_errors"])
        self.assertEqual(request.assessments[0]["observations"], [])

    def test_malformed_model_response_is_a_miss_not_gold_substitution(self):
        def malformed(system, payload, schema):
            if "changes" in schema["properties"]:
                return {"changes": [registration(payload["instruction"])]}
            return {"decisions": [{"kind": "ACT"}]}

        result = evaluate_case(case_with_ticks(tick(
            "ready", [observation("complete", "Build complete.")], ["request"]
        )), malformed)
        self.assert_score(result, 0, 0, 1)
        self.assertTrue(result["engine_errors"])
        self.assertEqual(result["ticks"][0]["predictions"], [])


if __name__ == "__main__":
    unittest.main()
