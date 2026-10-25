"""PIS-inspired, not an author-code reproduction (arXiv:2609.01272).

Form/Revise slot filling, a structural eligibility board, bounded channel checks,
and scoped decisions. Optional original-source verification is our ablation.
No simulator imports, task handles, hidden clocks, or execution-success guesses.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
from dataclasses import asdict
import re

from ..core import Change, Decision, Engine
from ..llm import _object, _rows, SHORT_TEXT, TEXT


DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
FORM = """Maintain a prospective intention store using Form and Revise.
Read the current message, which may contain requests, updates, or merely facts.
Extract ALL genuinely requested future actions as separate rows. Ordinary facts,
observations, speculative possibilities and instructions to somebody else are
not new commitments. Cue appearance is NOT cancellation or a new registration.
Existing records identify revision targets only; unrelated records must not
prevent registering new requests. Do not duplicate an existing commitment.

Each row has action, full condition, recurrence, watched sources and clock/day
slots. Preserve EVERY prerequisite, conjunction, alternative and exception in
condition. Use the concrete requested action, recipient and content. Copy a short
exact supporting quotation from the CURRENT message. The original message is
retained. For explicit reschedule/override, return the COMPLETE resulting action
and condition, retaining everything not changed. Cancel requires an explicit
cancellation of that same action, not elapsed time or missing evidence. Use an
existing target_id only for reschedule/override/cancel; register uses ''.

days lists permitted weekdays, or [] if unrestricted/uncertain. Use the host's
weekday scope for a daily plan unless the request specifies another day; a '*'
scope denotes a plan for every day. Future weekdays override the current day.
repeat is true ONLY for explicit recurrence, including a daily-plan heading.
clock_op is at, not_before, or none. clock_time is 24-hour HH:MM, or '' for none.
Use clock slots only for an unambiguous REQUIRED single clock constraint. Put
alternatives, stopwatch/relative-time conditions and uncertain times in condition
with clock_op=none, not an invented hard gate. All other conditions remain in
condition even with a clock slot. Watched sources must come from available_sources;
include events for visible cues, clock for clock requirements, and named channels
needed for hidden evidence. Never infer a request is already fulfilled.
Return compact JSON changes; [] for no changes. For cancel use empty unused
fields, [] days/sources, repeat=false, clock_op=none, clock_time=''.
"""

DECIDE = """Judge ONE eligible future intention, not the entire store.
The structural board has removed definitely ineligible clock/day rows. That is
NOT proof of the remaining condition. ACT requires current evidence for EVERY
part of condition, including exclusions, conjunctions, correct entity, timing and
recurrence. Clear paraphrases qualify; mere topic similarity does not. Stored
requests, future announcements and hypothetical events are NOT trigger evidence.
An update is not proof its new trigger has occurred. Do not guess hidden state.
Use current observation IDs exactly. Return WAIT when evidence is insufficient,
or CHECK with a source from check_sources when querying it can resolve the
condition now. check_sources has already removed observed/used channels; never
request an unavailable source. ACT uses source='' and nonempty evidence_ids;
CHECK uses evidence_ids=[]; WAIT uses source='' and evidence_ids=[]. A reminder
proposal is not successful execution. Keep reason short. Return one decisions row.
"""

VERIFY = """Verify one proposed reminder against the ORIGINAL instructions and updates.
The typed summary and proposed ACT are untrusted. Read the original messages in
order. Later explicit revisions override ONLY what they change. Preserve all
other prerequisites, exclusions, recurrence and timing. Judge only this requested
action, not unrelated actions elsewhere in the messages. Current observations
must establish every required condition; original requests are not observations.
Accept paraphrases but reject guesses, wrong entities, future/hypothetical cues,
unmet thresholds and unsupported time. Return verdict=supported only if action
is due now, otherwise unsupported. Supply a short reason. No new actions/queries.
"""


def clock_minutes(text):
    """Conservative parsing of host clock replies, never arbitrary event prose."""
    matches = re.findall(r"(?<!\d)([01]\d|2[0-3]):([0-5]\d)(?!\d)", text)
    values = {int(h) * 60 + int(m) for h, m in matches}
    return next(iter(values)) if len(values) == 1 else None


class PISEngine(Engine):
    def __init__(self, request, sources=("events",), query_budget=1,
                 queryable_sources=(), verify_actions=False, step_query_budget=2,
                 max_assess_workers=1, skip_unevidenced=False,
                 reuse_stable_waits=False, assess_batch_size=1):
        if type(verify_actions) is not bool:
            raise ValueError("verify_actions must be boolean")
        if type(max_assess_workers) is not int or max_assess_workers < 1:
            raise ValueError("max_assess_workers must be a positive integer")
        if type(skip_unevidenced) is not bool:
            raise ValueError("skip_unevidenced must be boolean")
        if type(reuse_stable_waits) is not bool:
            raise ValueError("reuse_stable_waits must be boolean")
        if type(assess_batch_size) is not int or assess_batch_size < 1:
            raise ValueError("assess_batch_size must be a positive integer")
        self.max_assess_workers = max_assess_workers
        self.skip_unevidenced = skip_unevidenced
        self.reuse_stable_waits = reuse_stable_waits
        self.assess_batch_size = assess_batch_size
        self.skipped_assessments = 0
        self.batched_assessments = 0
        self.reused_assessments = 0
        # Per-step only: cleared whenever the host declares a new decision
        # boundary, so a stale WAIT can never outlive the evidence window.
        self._stable_waits = {}
        if type(step_query_budget) is not int or step_query_budget < 0:
            raise ValueError("step_query_budget must be nonnegative")
        self.request = request
        self.verify_actions = verify_actions
        self.triggers = {}
        self.board_log = []
        self.verification_log = []
        self._scope = ""
        self._compiled = []
        self.step_query_budget = step_query_budget
        self.step_id = ""
        self.step_queries = []
        super().__init__(self._compile, self._assess, sources, query_budget, queryable_sources)

    def fresh(self):
        return PISEngine(self.request, self.sources, self.query_budget,
                         self.queryable_sources, self.verify_actions, self.step_query_budget,
                         self.max_assess_workers, self.skip_unevidenced,
                         self.reuse_stable_waits, self.assess_batch_size)

    def begin_step(self, step_id):
        """Host decision boundary, not a model-inferred deadline or hidden clock."""
        if not isinstance(step_id, str) or not step_id:
            raise ValueError("Invalid step ID")
        if step_id != self.step_id:
            self.step_id, self.step_queries = step_id, []
            self._stable_waits = {}

    def record_query(self, source):
        """Count actual host query attempts, including wrong/repeated sources."""
        if not isinstance(source, str):
            raise ValueError("Invalid query source")
        self.step_queries.append(source)
        if len(self.step_queries) > 12:
            raise RuntimeError("Actor exceeded 12 queries without advancing; aborting, not scoring a forced action")

    def exhausted_query_guidance(self):
        if self.step_id and len(self.step_queries) >= self.step_query_budget:
            return ("Memory query budget exhausted for this decision. Do not issue more state queries "
                    "for these memory proposals now. Use already available evidence to choose; "
                    "leave unsupported prospective tasks unselected. Multiple supported tasks are allowed.")
        return ""

    def _compile(self, instruction, intentions, sources):
        pending = [i for i in intentions if i.status in {"pending", "attempted"}]
        fields = {
            "op": {"type": "string", "enum": ["register", "reschedule", "override", "cancel"]},
            # Stable grammar: per-message ID enums force expensive recompilation.
            # Identity membership is validated below, before any state mutation.
            "target_id": {"type": "string", "maxLength": 160},
            "action": TEXT, "condition": TEXT, "evidence_quote": TEXT,
            "sources": {"type": "array", "items": {"type": "string", "enum": list(sources)}},
            "days": {"type": "array", "items": {"type": "string", "enum": list(DAYS)}},
            "repeat": {"type": "boolean"},
            "clock_op": {"type": "string", "enum": ["none", "at", "not_before"]},
            "clock_time": {"type": "string", "maxLength": 5},
        }
        schema = _object({"changes": {"type": "array", "items": _object(fields)}})
        existing = [{"id": i.id, "action": i.action,
                     "condition": i.condition.removesuffix(self._slot_suffix(self.triggers[i.id])),
                     "repeat": i.repeat, **self.triggers[i.id]} for i in pending]
        value = self.request(FORM, {"instruction": asdict(instruction),
                                  "intentions": existing, "available_sources": list(sources)}, schema)
        rows = value.get("changes") if isinstance(value, dict) else None
        if not isinstance(rows, list) or len(rows) > 32:
            raise ValueError("Expected at most 32 changes")
        changes = []
        for raw in rows:
            try:
                row = _rows({"changes": [raw]}, "changes", schema)[0]
                row = self._review_change(row, instruction, pending)
                if row is None:
                    continue
                trigger = {k: row[k] for k in ("days", "clock_op", "clock_time")}
                self._validate_trigger(trigger)
                if set(row["sources"]) - set(sources):
                    raise ValueError("Unknown source")
                if row["op"] != "register" and row["target_id"] not in {i.id for i in pending}:
                    raise ValueError("Update needs a known target")
                op = "revise" if row["op"] in {"reschedule", "override"} else row["op"]
                watched = tuple(dict.fromkeys(row["sources"] +
                                (["clock"] if trigger["clock_op"] != "none" and "clock" in sources else [])))
                scope = "*" if instruction.scope in (*DAYS, "*") else instruction.scope
                # Core deduplication compares condition, not our sidecar slots.
                # Keep the effective typed constraints inside that key as well.
                condition = row["condition"]
                if op != "cancel":
                    condition += self._slot_suffix(trigger)
                change = Change(op, row["action"], condition, watched, scope,
                                row["repeat"], row["target_id"], row["evidence_quote"])
                changes.append(change)
                self._compiled.append((change, trigger))
            except (ValueError, KeyError, TypeError) as exc:
                # A malformed row must not discard the other requests in a plan.
                self._error("typed_change", exc)
        return changes

    def _review_change(self, row, instruction, pending):
        """Extension point; the historical policy applies no additional review."""
        return row

    @staticmethod
    def _slot_suffix(trigger):
        parts = []
        if trigger["days"]:
            parts.append("weekdays=" + ",".join(d for d in DAYS if d in trigger["days"]))
        if trigger["clock_op"] != "none":
            parts.append(trigger["clock_op"] + "=" + trigger["clock_time"])
        return " [Typed gates: " + "; ".join(parts) + "]" if parts else ""

    @staticmethod
    def _validate_trigger(trigger):
        if (not isinstance(trigger, dict) or set(trigger) != {"days", "clock_op", "clock_time"}
                or not isinstance(trigger["days"], list)
                or any(day not in DAYS for day in trigger["days"])
                or trigger["clock_op"] not in {"none", "at", "not_before"}
                or not isinstance(trigger["clock_time"], str)):
            raise ValueError("Invalid typed trigger")
        value = trigger["clock_time"]
        if ((trigger["clock_op"] == "none" and value != "")
                or (trigger["clock_op"] != "none" and
                    not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value))):
            raise ValueError("Invalid clock slot")

    def ingest(self, instruction):
        self._compiled = []
        changed = super().ingest(instruction)
        # Core persists after row validation but not after a provider exception.
        # Preserve the raw input on that failure as well; never silently lose it.
        self.instructions.setdefault(instruction.id, instruction)
        for key in changed:
            intention = self.intentions[key]
            for change, trigger in reversed(self._compiled):
                # A later compiled edit may have been rejected by the core.
                # Only attach gates belonging to the record actually applied,
                # not merely the last proposal sharing a target/source quote.
                if (change.op != "cancel" and
                        (change.target_id == key or change.op == "register") and
                        (change.action, change.condition, change.sources, change.scope, change.repeat,
                         change.evidence_quote) ==
                        (intention.action, intention.condition, intention.sources, intention.scope,
                         intention.repeat, intention.evidence_quote)):
                    self.triggers[key] = copy.deepcopy(trigger)
                    break
        return changed

    def _assess(self, intentions, observations, sources, queryable_sources=()):
        current = [o for o in observations if o.current]
        clock_values = {clock_minutes(o.text) for o in current if o.source == "clock"}
        clock_values.discard(None)
        now = next(iter(clock_values)) if len(clock_values) == 1 else None
        observed = {o.source for o in current}
        budget = min(self.query_budget, max(0, self.step_query_budget - len(self.step_queries)))
        results, checked, board = {}, set(), []
        # Code gates first: they make no model calls but can consume the query
        # budget, so they must settle before any assessment is dispatched.
        eligible = []
        for intention in intentions:
            trigger = self.triggers[intention.id]
            if trigger["days"] and self._scope in DAYS and self._scope not in trigger["days"]:
                results[intention.id] = Decision("WAIT", intention.id, "Outside explicit weekday gate")
                continue
            if trigger["clock_op"] != "none":
                due = clock_minutes(trigger["clock_time"])
                if now is None:
                    if ("clock" in queryable_sources and "clock" not in observed
                            and "clock" not in checked and len(checked) < budget):
                        results[intention.id] = Decision("CHECK", intention.id, "Need current clock", source="clock")
                        checked.add("clock")
                    else:
                        results[intention.id] = Decision("WAIT", intention.id, "Current clock unavailable")
                    continue
                if (trigger["clock_op"] == "at" and now != due) or (
                        trigger["clock_op"] == "not_before" and now < due):
                    results[intention.id] = Decision("WAIT", intention.id, "Outside explicit clock gate")
                    continue
            board.append(intention.id)
            eligible.append(intention)

        def _available(intention):
            if len(checked) >= budget:
                return []
            return [s for s in queryable_sources if s in intention.sources
                    and s not in checked and s not in observed]

        def _settle(intention, d, available):
            """Validate one decision and apply its effects, exactly as the serial loop."""
            if d.intention_id != intention.id:
                raise ValueError("Decision references a different intention")
            if d.kind == "CHECK":
                if d.source not in available:
                    raise ValueError("Invalid or exhausted check source")
                checked.add(d.source)
            if d.kind == "ACT" and self.verify_actions:
                verdict_schema = _object({"verdict": {"type": "string", "enum": ["supported", "unsupported"]},
                                          "reason": SHORT_TEXT})
                verdict = self.request(VERIFY, {
                    "intention": asdict(intention), "proposal": asdict(d),
                    "original_instructions": [asdict(self.instructions[k]) for k in intention.instruction_ids],
                    "observations": [asdict(o) for o in current], "current_scope": self._scope,
                }, verdict_schema)
                if (not isinstance(verdict, dict) or set(verdict) != {"verdict", "reason"}
                        or verdict["verdict"] not in {"supported", "unsupported"}
                        or not isinstance(verdict["reason"], str)):
                    raise ValueError("Invalid verification")
                self.verification_log.append({"intention_id": intention.id, **verdict})
                if verdict["verdict"] != "supported":
                    return Decision("WAIT", intention.id, "Source verifier: " + verdict["reason"])
            return d

        # An intention with no queryable source left cannot reach a CHECK: any
        # source it named would be rejected by _decide, so it can never grow
        # `checked`. Its remaining-budget value is therefore already final when
        # the sequential walk reaches it, and only `checked` -- which it cannot
        # touch -- separates it from its neighbours. Such assessments are
        # deferred and dispatched together; every intention that could still
        # spend the budget is resolved in strict order first, so the sequence of
        # budget values handed to the model is identical to the serial loop.
        # An intention with no current observation on any watched source and no
        # queryable source left cannot produce anything but WAIT: ACT requires
        # cited evidence from a watched source, and the schema offers no source
        # to CHECK. Asking the model costs a call to learn nothing. The reason
        # must differ from NO_INTERVENTION_REASON, which the adapter treats as
        # "re-deliver the cached ACT"; an ordinary WAIT clears that cache, which
        # is what a model-produced WAIT does here today.
        independent = {i.id for i in eligible if not _available(i)}

        def _signature(intention):
            return (intention.revision,
                    tuple(sorted(o.id for o in current if o.source in intention.sources)))

        deferred = []
        for intention in eligible:
            signature = _signature(intention)
            # Nothing this intention watches has changed since its last WAIT in
            # this step, and the set of sources it could still query only ever
            # shrinks within a step. Re-asking cannot surface new evidence, and
            # the stored WAIT keeps its original reason so the adapter's
            # act-cache behaviour is unchanged.
            cached = self._stable_waits.get(intention.id)
            if self.reuse_stable_waits and cached is not None and cached[0] == signature:
                self.reused_assessments += 1
                results[intention.id] = cached[1]
                continue
            if intention.id in independent:
                if self.skip_unevidenced and not signature[1]:
                    self.skipped_assessments += 1
                    results[intention.id] = Decision(
                        "WAIT", intention.id, "No current evidence on a watched source")
                    continue
                deferred.append((intention, max(0, budget - len(checked))))
                continue
            available = _available(intention)
            try:
                d = self._decide(intention, current, available, queryable_sources,
                                 budget - len(checked))
                results[intention.id] = _settle(intention, d, available)
                self._remember_wait(intention, signature, results[intention.id])
            except Exception as exc:
                self._error("pis_decide", exc)
                results[intention.id] = Decision("WAIT", intention.id, "Unresolved decision error")

        # Every deferred intention has an empty source list, so one shared
        # prompt can carry several of them without per-intention CHECK options.
        groups = [deferred[i:i + self.assess_batch_size]
                  for i in range(0, len(deferred), self.assess_batch_size)]
        proposals = {}

        def _run(group):
            if len(group) == 1:
                intention, remaining = group[0]
                return [self._decide(intention, current, [], queryable_sources, remaining)]
            self.batched_assessments += 1
            return self._decide_batch(group, current, queryable_sources)

        if len(groups) > 1 and self.max_assess_workers > 1:
            with ThreadPoolExecutor(max_workers=min(self.max_assess_workers, len(groups))) as pool:
                futures = {pool.submit(_run, group): index for index, group in enumerate(groups)}
                for future in as_completed(futures):
                    proposals[futures[future]] = future
        for index, group in enumerate(groups):
            try:
                future = proposals.get(index)
                decided = future.result() if future is not None else _run(group)
                if len(decided) != len(group):
                    raise ValueError("Batched assessment returned the wrong number of rows")
            except Exception as exc:
                # One malformed batch must not lose every intention in it.
                self._error("pis_decide", exc)
                decided = None
            for position, (intention, remaining) in enumerate(group):
                try:
                    if decided is None:
                        d = self._decide(intention, current, [], queryable_sources, remaining)
                    else:
                        d = decided[position]
                    results[intention.id] = _settle(intention, d, [])
                    self._remember_wait(intention, _signature(intention), results[intention.id])
                except Exception as exc:
                    self._error("pis_decide", exc)
                    results[intention.id] = Decision("WAIT", intention.id, "Unresolved decision error")
        self.board_log.append({"scope": self._scope, "active": len(intentions), "eligible": board,
                               "checked_sources": sorted(checked)})
        return [results[i.id] for i in intentions if i.id in results]

    def _decide_batch(self, items, current, queryable_sources):
        """Judge several order-independent intentions together.

        The base engine has no batched prompt, so it falls back to one call
        each. A policy that can share one prompt overrides this.
        """
        return [self._decide(intention, current, [], queryable_sources, budget)
                for intention, budget in items]

    def _remember_wait(self, intention, signature, decision):
        """Only a plain WAIT is reusable; anything else must be re-judged."""
        if decision.kind == "WAIT":
            self._stable_waits[intention.id] = (signature, decision)
        else:
            self._stable_waits.pop(intention.id, None)

    def _decide(self, intention, current, available, queryable_sources, budget):
        fields = {
            "kind": {"type": "string", "enum": ["ACT", "CHECK", "WAIT"]},
            "intention_id": {"type": "string", "maxLength": 160},
            "reason": SHORT_TEXT,
            "evidence_ids": {"type": "array", "items": {"type": "string", "maxLength": 160}},
            "source": {"type": "string", "enum": ["", *queryable_sources]},
        }
        schema = _object({"decisions": {"type": "array", "items": _object(fields)}})
        value = self.request(DECIDE, {
            "intention": {**asdict(intention), **self.triggers[intention.id]},
            "observations": [asdict(o) for o in current],
            "current_scope": self._scope, "check_sources": available,
            "remaining_check_budget": budget,
        }, schema)
        rows = _rows(value, "decisions", schema)
        if len(rows) != 1:
            raise ValueError("Exactly one decision required")
        return Decision(**{**rows[0], "evidence_ids": tuple(rows[0]["evidence_ids"])})

    def tick(self, observations, scope=""):
        self._scope = scope
        return super().tick(observations, scope)

    def snapshot(self):
        return {**super().snapshot(), "engine_kind": "pis_inspired",
                "verify_actions": self.verify_actions, "triggers": copy.deepcopy(self.triggers),
                "board_log": copy.deepcopy(self.board_log),
                "verification_log": copy.deepcopy(self.verification_log), "monitor_scope": self._scope,
                "step_query_budget": self.step_query_budget, "step_id": self.step_id,
                "step_queries": list(self.step_queries)}

    def restore(self, state):
        if not isinstance(state, dict) or state.get("engine_kind") != "pis_inspired":
            raise ValueError("Expected PIS-inspired snapshot")
        if state.get("policy_variant") != getattr(self, "POLICY", None):
            raise ValueError("Snapshot belongs to a different PIS policy variant")
        base = Engine(None, None, ("events",))
        base.restore(state)
        # Concurrency is a runtime setting of this process, not snapshot state:
        # carry it across a restore rather than silently reverting to serial.
        fresh = PISEngine(self.request, base.sources, base.query_budget, base.queryable_sources,
                          state["verify_actions"], state["step_query_budget"],
                          self.max_assess_workers, self.skip_unevidenced,
                          self.reuse_stable_waits, self.assess_batch_size)
        if (not isinstance(state["step_id"], str) or not isinstance(state["step_queries"], list)
                or any(not isinstance(s, str) for s in state["step_queries"])):
            raise ValueError("Invalid step query state")
        fresh.step_id, fresh.step_queries = state["step_id"], list(state["step_queries"])
        if set(state["triggers"]) != set(base.intentions):
            raise ValueError("Trigger/intention mismatch")
        for key, trigger in state["triggers"].items():
            self._validate_trigger(trigger)
            suffix = self._slot_suffix(trigger)
            if suffix and not base.intentions[key].condition.endswith(suffix):
                raise ValueError("Trigger disagrees with effective condition")
        if (not isinstance(state["board_log"], list) or not isinstance(state["verification_log"], list)
                or not isinstance(state["monitor_scope"], str)):
            raise ValueError("Invalid PIS snapshot metadata")
        fresh.__dict__.update({k: v for k, v in base.__dict__.items() if k not in {"compiler", "matcher"}})
        for field in ("triggers", "board_log", "verification_log"):
            setattr(fresh, field, copy.deepcopy(state[field]))
        fresh._scope = state["monitor_scope"]
        self.__dict__.update(fresh.__dict__)
        self.compiler, self.matcher = self._compile, self._assess
