"""Experiment 3 actor guidance for evidence gathering and precise execution."""

import json

from prospective_memory.adapters.pmbench import PMBenchAdapter, _STATE


# Only these two WAIT reasons are produced by code arithmetic in
# SourceBoundFairTriggerEngine._assess ("now != due", scope not in days). Model
# written WAIT explanations stay out of the handoff: one of them previously
# rejected a satisfied breakfast trigger in its own prose.
GATE_REASONS = ("Outside explicit clock gate", "Outside explicit weekday gate")


class RGPMAdapter(PMBenchAdapter):
    # Class default so instances built via object.__new__ in tests carry a variant.
    guidance = "balanced_v2"
    report_gates = False
    gate_style = "terse"

    def __init__(self, engine, log=None, query_handoff="explicit", guidance="balanced_v2",
                 report_gates=False, gate_style="terse"):
        super().__init__(engine, log, query_handoff=query_handoff)
        self.guidance = guidance
        self.report_gates = report_gates
        self.gate_style = gate_style

    def _gate_blocked(self):
        """Obligations whose own typed gate is unsatisfied by the clock/scope now.

        Reports a computed comparison, not a judgement: the engine already
        decided WAIT in code before any model call. The action text is included
        so the actor can match it to a menu handle; no task ID or expected
        answer is involved.
        """
        intentions = getattr(self.engine, "intentions", {}) or {}
        triggers = getattr(self.engine, "triggers", {}) or {}
        rows = []
        for decision in self.last_decisions:
            if decision.kind != "WAIT" or decision.reason not in GATE_REASONS:
                continue
            intention = intentions.get(decision.intention_id)
            if intention is None:
                continue
            trigger = triggers.get(decision.intention_id) or {}
            gate = {}
            if trigger.get("clock_op") and trigger["clock_op"] != "none":
                gate["required_time"] = f"{trigger['clock_op']} {trigger.get('clock_time','')}".strip()
            if trigger.get("days"):
                gate["permitted_days"] = list(trigger["days"])
            rows.append({"action": intention.action, "not_due_reason": decision.reason, **gate})
        return rows

    def _query_plan(self):
        """Describe one offered query using current public evidence and attempts."""
        attempts = getattr(self.engine, "step_queries", None)
        limit = getattr(self.engine, "step_query_budget", None)
        if (not isinstance(attempts, (list, tuple))
                or any(not isinstance(source, str) for source in attempts)
                or type(limit) is not int or limit < 0):
            raise ValueError("Query-first guidance requires a valid step-query ledger and budget")
        remaining = max(0, limit - len(attempts))
        if not remaining:
            return None
        observed = {o.source for o in self.current_observations if o.current}
        # Reuse the shared adapter's capability validation without issuing a query.
        self._explicit_query_handoff()
        for decision in self.last_decisions:
            if decision.kind != "CHECK" or decision.source in observed or decision.source in attempts:
                continue
            intention = self.engine.intentions[decision.intention_id]
            if intention.status != "pending" or intention.scope not in {"", "*", self.scope}:
                continue
            return {
                "status": "unresolved_prerequisite",
                "intention_id": intention.id, "revision": intention.revision,
                "requested_action": intention.action, "condition": intention.condition,
                "reason": decision.reason,
                "current_observed_sources": sorted(observed),
                "actual_query_attempts_this_step": list(attempts),
                "remaining_queries_this_step": remaining,
                "next_action": {"action": "query_state", "choice": "NONE",
                                "task_ids": [], "channel": decision.source},
            }
        return None

    @staticmethod
    def render_query_plan(plan):
        if plan is None:
            return ""
        return ("Unresolved prospective-memory check:\n" + json.dumps(plan, ensure_ascii=False)
                + "\nBefore advancing on an outstanding request, use next_action to inspect this prerequisite while the "
                "query budget remains. A prior-step reply does not establish current state. "
                "After the reply, reassess all requested actions against the current evidence "
                "and latest revisions. CHECK alone never authorizes task selection. "
                "Do not repeat a source already observed or attempted this step. "
                "If the public conversation shows that this one-shot request was already "
                "performed, do not check or execute it again. Recurring requests still require "
                "their next stated occasion. This is advisory: you retain the query and action "
                "choices and may decline an irrelevant, fulfilled or superseded request.")

    def context_for(self, messages):
        self.last_query_plan = None
        if hasattr(self.engine, "instruction_sources"):
            # Derived only from the public conversation, rebuilt on every cycle.
            self.engine.instruction_sources = {
                f"message_{i}": match.group(1) for i, message in enumerate(messages)
                if message.get("role") == "user" and isinstance(message.get("content"), str)
                and (match := _STATE.match(message["content"]))}
        context = super().context_for(messages)
        if self.report_gates:
            blocked = self._gate_blocked()
            if blocked:
                if self.gate_style == "verbose":
                    # Original reasoning-heavy form: measurably hurt a smaller
                    # actor (Ministral-3-8B), which cut its own reasoning short
                    # right after reading it and under-selected unrelated due
                    # actions in the same step. Kept only for the side-by-side
                    # verbose-vs-terse comparison; terse is the default.
                    context += ("\nStored obligations whose own requested time or day does not match now "
                                "(computed from the request, not a prediction); do not select these yet:\n"
                                + json.dumps(blocked, ensure_ascii=False))
                else:
                    # One short line per item instead of the JSON block above:
                    # same underlying fact (a code comparison, not a model
                    # judgement), minimal added prompt length.
                    lines = []
                    for row in blocked:
                        need = row.get("required_time") or (
                            "days: " + ",".join(row["permitted_days"]) if row.get("permitted_days") else "")
                        lines.append(f"- {row['action']} (needs {need})" if need else f"- {row['action']}")
                    context += "\nNot due yet, skip for now:\n" + "\n".join(lines)
        if self.guidance == "query_first":
            self.last_query_plan = self._query_plan()
            return (context + "\n" + self.render_query_plan(self.last_query_plan)).strip()
        if self.guidance == "none":
            return context
        return (context + "\nReview the latest instructions and current observations for due actions. "
                "Helper proposals are fallible and may omit a due action. "
                "For recurring requests at several times or events, evaluate each occurrence "
                "independently; a later occurrence need not happen before an earlier one. "
                "When readiness depends on unobserved state, use an available query before "
                "advancing, within the shared query budget. Prioritize a proposed CHECK or "
                "a source needed by the current instructions and observations. Query the exact "
                "channel; a clock query cannot reveal another channel's state. "
                "After a query, reconsider all due actions using the returned evidence. "
                "Select an action when its requested trigger is satisfied now. "
                "The menu lists available actions, including distractors and future obligations; "
                "availability does not establish readiness. A CHECK requests information, "
                "not execution. Match the exact requested "
                "action, object, recipient and current time to its current menu handle. "
                "For a request with several scheduled occurrences, select only the occurrence "
                "due now. Do not select canceled or superseded actions. Include every action "
                "due now, but stop once those handles are listed; never fill the array to its "
                "maximum length. Use task_ids=[] when no requested action is due.")
