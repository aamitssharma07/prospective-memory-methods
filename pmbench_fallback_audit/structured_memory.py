"""Intention records with stable identities and observation-backed revisions."""
import json
import re
from memory_intervention import MemoryAssistant

FIELDS = ("action", "trigger", "day", "channel", "status", "evidence")
INSTRUCTIONS = '''STRUCTURED_INTENTIONS_V2
Maintain intentions from user instructions, never from menu availability alone.
Use stable descriptive IDs such as monday_library_hold, never task_N handles.
Keep action, full trigger condition, applicable day (or daily), channel (or
narrative), status (pending/attempted/cancelled/expired), and an exact evidence
quote from the supplied messages. Preserve cross-day intentions and daily tasks.
Do not copy menu lures into intentions. Do not delete records. Use the existing
ID for revisions and quote the observed revision/cancellation supporting changes.
An attempted action does not prove completion. Output only new or changed records.
Return JSON {"records":[{"id":"...","action":"...","trigger":"...",
"day":"...","channel":"...","status":"pending","evidence":"exact quote"}]}.
'''


class StructuredMemory(MemoryAssistant):
    def _edits(self, value):
        if not isinstance(value, dict) or not isinstance(value.get("records"), list):
            raise ValueError("Expected records")
        # Validate each edit independently so one bad record cannot discard others.
        self.rejected = []
        for item in value["records"]:
            try:
                key = self._text(item["id"], 100)
                if not key or re.search(r"task_\d+", key):
                    raise ValueError("Unstable task handle ID")
                record = {f: self._text(item[f], 800) for f in FIELDS}
                if any(not v.strip() for v in record.values()):
                    raise ValueError("Missing intention condition or evidence")
                if record["status"] not in {"pending", "attempted", "cancelled", "expired"}:
                    raise ValueError("Invalid status")
                if record["evidence"] not in self.observed:
                    raise ValueError("Evidence is not an observed quote")
                old = self.bank["knowledge"].get(key)
                if old and any(old[f] != record[f] for f in ("action", "trigger", "day", "status")):
                    if record["evidence"] == old["evidence"]:
                        raise ValueError("Revision needs new supporting evidence")
                if len(self.bank["knowledge"]) >= 128 and key not in self.bank["knowledge"]:
                    raise ValueError("Bank full")
                self.bank["knowledge"][key] = record
            except (ValueError, TypeError, KeyError) as exc:
                self.rejected.append(str(exc))
        if self.rejected:
            raise ValueError("Rejected records: " + "; ".join(self.rejected))

    def context_for(self, messages):
        self.observed = "\n".join(m.get("content", "") for m in messages)
        original = self.generate
        def generate(system, payload):
            if '"edits"' in system:
                return original(INSTRUCTIONS, payload)
            system += '''
Use the structured intentions. Compare their day and complete trigger against
observed evidence. For hidden channels recommend a query if evidence is missing;
do not say the task is due. Never recommend repeating an action merely because
it was previously selected. Do not repeat yesterday's intentions today. Prefer
silence when the current observation already makes the appropriate action clear.
Retain trigger conditions in the reminder. Never treat a pending task as due.
'''
            return original(system, payload)
        self.generate = generate
        try:
            return super().context_for(messages)
        finally:
            self.generate = original
