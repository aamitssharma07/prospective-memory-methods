"""Source routing must preserve provenance, uncertainty, and unrelated fields."""

import copy
import unittest

from source_routing import route_specifications


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "operations": [{"operation_id": "request_1", "source_unit_id": "u1", "operation": "new_request",
                            "complete_request_quote": "A calendar change is possible. Send the note when the lamp lights."}],
            "available_sources": ["events", "calendar", "clock"],
        }
        self.reply = {"specifications": [{"operation_id": "request_1", "target_id": "",
            "requested_action": "Send the note", "trigger_condition": "when the lamp lights",
            "watched_sources": ["calendar"], "clock_relation": "none", "recurring": False}]}
        self.events = []

    def route(self, verdict, request=None):
        return route_specifications(self.reply, self.payload, request or (lambda *args: verdict),
                                    lambda kind, **data: self.events.append((kind, data)))

    def test_only_sources_change_and_inputs_are_preserved(self):
        original = copy.deepcopy(self.reply)
        captured = []
        def request(system, payload, schema):
            captured.append(payload)
            return {"status": "routed", "watched_sources": ["events"], "reason": "Visible trigger."}
        result = self.route(None, request)
        expected = copy.deepcopy(original)
        expected["specifications"][0]["watched_sources"] = ["events"]
        self.assertEqual(result, expected)
        self.assertEqual(self.reply, original)
        self.assertEqual(set(captured[0]), {"requested_action", "trigger_condition", "complete_request_quote", "available_sources"})
        self.assertEqual(self.events[0][0], "source_routing_applied")

    def test_invalid_or_unsupported_routing_retains_record(self):
        for verdict in ({"status": "routed", "watched_sources": ["invented"], "reason": ""},
                        {"status": "routed", "watched_sources": [], "reason": ""},
                        {"status": "unsupported", "watched_sources": [], "reason": "unclear"},
                        {"status": "unsupported", "watched_sources": ["events"], "reason": "unclear"}):
            with self.subTest(verdict=verdict):
                self.assertEqual(self.route(verdict), self.reply)
                self.assertIn(self.events[-1][0], ("source_routing_error", "source_routing_unsupported"))

    def test_transport_failure_is_logged_without_losing_registration(self):
        def request(*args):
            raise ConnectionError("offline")
        self.assertEqual(self.route(None, request), self.reply)
        self.assertEqual(self.events[-1][1]["error"]["type"], "ConnectionError")

    def test_invalid_spans_and_revisions_never_get_rerouted(self):
        def unexpected(*args):
            self.fail("Routing should not be called")
        self.reply["specifications"][0]["trigger_condition"] = "invented trigger"
        self.assertEqual(self.route(None, unexpected), self.reply)
        self.reply["specifications"][0]["trigger_condition"] = "when the lamp lights"
        for operation in ("modify_request", "cancel_request"):
            self.payload["operations"][0]["operation"] = operation
            self.assertEqual(self.route(None, unexpected), self.reply)

    def test_clock_gate_retains_clock_and_multiple_sources_are_kept(self):
        self.reply["specifications"][0]["clock_relation"] = "at"
        result = self.route({"status": "routed", "watched_sources": ["events", "calendar", "events"], "reason": "Both."})
        self.assertEqual(result["specifications"][0]["watched_sources"], ["events", "calendar", "clock"])

    def test_channel_origin_is_available_without_changing_source_text(self):
        self.payload["instruction_origin"] = {"source": "calendar", "public_message_id": "message_12"}
        captured = []
        def request(system, payload, schema):
            captured.append(payload)
            return {"status": "routed", "watched_sources": ["calendar"], "reason": "Originating channel."}
        original = copy.deepcopy(self.reply)
        self.route(None, request)
        self.assertEqual(captured[0]["instruction_origin"], self.payload["instruction_origin"])
        self.assertEqual(self.reply, original)
