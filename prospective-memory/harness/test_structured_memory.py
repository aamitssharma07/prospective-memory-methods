import unittest
from structured_memory import StructuredMemory

class StructuredTests(unittest.TestCase):
    def setUp(self):
        self.helper = StructuredMemory(None)
        self.helper.observed = "Collect book when ready. Cancel book collection."
        self.record = dict(id="monday_book", action="Collect book", trigger="hold ready",
                           day="Monday", channel="library_hold", status="pending",
                           evidence="Collect book when ready.")

    def test_preserves_trigger_on_unsupported_revision(self):
        self.helper._edits({"records": [self.record]})
        with self.assertRaises(ValueError):
            self.helper._edits({"records": [{**self.record, "trigger": "now"}]})
        self.assertEqual(self.helper.bank["knowledge"]["monday_book"]["trigger"], "hold ready")

    def test_handles_and_invented_evidence_rejected(self):
        for changes in ({"id": "task_7"}, {"evidence": "book ready now"}, {"trigger": ""}):
            with self.assertRaises(ValueError):
                self.helper._edits({"records": [{**self.record, **changes}]})
        self.assertEqual(self.helper.bank["knowledge"], {})

    def test_cancellation_retained_and_empty_edits_preserve_bank(self):
        self.helper._edits({"records": [self.record]})
        self.helper._edits({"records": [{**self.record, "status": "cancelled", "evidence": "Cancel book collection."}]})
        self.helper._edits({"records": []})
        self.assertEqual(self.helper.bank["knowledge"]["monday_book"]["status"], "cancelled")
