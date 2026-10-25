"""Bounded intention bank and optional transient reminders from public messages."""
import copy
import json
import time

RULES = """You assist a prospective-memory agent using ONLY supplied observations.
Retain user intentions and their conditions, revisions and cancellations. Record
queries and attempted actions, without assuming an attempt succeeded. Hidden
channels and time require an observed query response. Never infer that a cue is
true merely from the action menu. Store descriptions, not persistent task_N handles;
handles must be resolved against the current menu. Do not invent observations.
"""


class MemoryAssistant:
    def __init__(self, generate, mode="selective", log=None):
        if mode not in {"selective", "always", "full_bank"}:
            raise ValueError(mode)
        self.generate, self.mode, self.log = generate, mode, log
        self.bank = {"status": "", "knowledge": {}, "procedural": {}}
        self.seen = 0
        self.cycles = 0

    def _edits(self, value):
        if not isinstance(value, dict) or not isinstance(value.get("edits"), list):
            raise ValueError("Expected edits list")
        if len(value["edits"]) > 16:
            raise ValueError("Too many edits")
        bank = copy.deepcopy(self.bank)
        for edit in value["edits"]:
            op = edit.get("op")
            if op == "status":
                bank["status"] = self._text(edit["text"], 1200)
            elif op in {"save", "delete"}:
                section = edit["section"]
                if section not in {"knowledge", "procedural"}:
                    raise ValueError("Invalid section")
                key = self._text(edit["id"], 80)
                if op == "save":
                    bank[section][key] = self._text(edit["text"], 800)
                else:
                    bank[section].pop(key, None)
            else:
                raise ValueError("Invalid operation")
        if any(len(bank[s]) > 64 for s in ("knowledge", "procedural")):
            raise ValueError("Bank capacity exceeded; delete stale entries")
        self.bank = bank

    @staticmethod
    def _text(value, limit):
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError("Invalid text field")
        return value

    def context_for(self, messages):
        # Include every newly observed message so encoding instructions cannot
        # disappear before the first bank update; retain eight for local context.
        visible = {"new_messages": messages[self.seen:], "recent": messages[-8:]}
        self.seen = len(messages)
        self.cycles += 1
        record = {"cycle": self.cycles, "mode": self.mode, "errors": []}
        started = time.monotonic()
        try:
            prompt = RULES + '\nReturn JSON {"edits": [...]} only. Operations: '
            prompt += ' {"op":"status","text":"..."}, {"op":"save","section":"knowledge" or "procedural","id":"...","text":"..."}, or {"op":"delete","section":"knowledge" or "procedural","id":"..."}.'
            raw = self.generate(prompt, {**visible, "bank": self.bank})
            record["edit_output"] = raw
            self._edits(json.loads(raw))
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            record["errors"].append("bank: " + str(exc))
        reminder = ""
        if self.mode == "full_bank":
            # Private status is never exposed to the actor.
            reminder = json.dumps({s: self.bank[s] for s in ("knowledge", "procedural")})
        else:
            try:
                prompt = RULES + '\nReturn JSON {"reminder":"short evidence-grounded reminder"}.'
                prompt += (" Use an empty string when no reminder is useful." if self.mode == "selective"
                           else " Provide a reminder every time; uncertainty should recommend checking evidence.")
                raw = self.generate(prompt, {**visible, "bank": self.bank})
                record["intervention_output"] = raw
                reminder = self._text(json.loads(raw)["reminder"], 1200)
                if self.mode == "always" and not reminder.strip():
                    raise ValueError("Always mode requires a reminder")
            except (ValueError, TypeError, KeyError) as exc:
                record["errors"].append("intervention: " + str(exc))
                reminder = ""
        record.update(bank=copy.deepcopy(self.bank), reminder=reminder,
                      elapsed_seconds=time.monotonic() - started)
        if self.log:
            self.log.write(json.dumps(record) + "\n")
            self.log.flush()
        return "Memory context (verify against observed evidence):\n" + reminder if reminder else ""
