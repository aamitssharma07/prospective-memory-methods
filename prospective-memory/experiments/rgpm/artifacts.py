"""Durable Experiment 3 call records, memory traces and step checkpoints."""

import copy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import uuid

import jsonschema


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save(path, value):
    atomic(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def rows(path):
    path = Path(path)
    if not path.exists():
        return []
    result = []
    lines = path.read_bytes().splitlines(keepends=True)
    for index, line in enumerate(lines):
        try:
            result.append(json.loads(line))
        except (ValueError, UnicodeDecodeError):
            if index != len(lines) - 1 or line.endswith(b"\n"):
                raise
            # An interrupted append is retained in place; never interpreted as a call.
    return result


class ActorBudgetExceeded(BaseException):
    """Stop the run; the benchmark must not retry this as a bad prediction."""


class Session:
    def __init__(self, output, fingerprint, resume=False, stop_after=None, *,
                 max_actor_calls=None, max_actor_tokens=None):
        for value in (max_actor_calls, max_actor_tokens):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError("Actor budgets must be positive integers")
        self.output = Path(output)
        self.fingerprint = fingerprint
        self.session_id = uuid.uuid4().hex
        self.step_key = None
        self.operation_id = None
        self.phase = "startup"
        self.adapter = None
        self.resume_state = None
        self.stop_after = stop_after
        self.committed = 0
        self.started = time.monotonic()
        self.prior_wall = 0
        self.max_actor_calls, self.max_actor_tokens = max_actor_calls, max_actor_tokens
        self._actor_attempts = 0
        self._actor_tokens = 0
        self._actor_usage_unknown = False
        recovered = []
        if resume:
            for path in [*self.output.glob("*.jsonl"), self.output / "prompts.log"]:
                data = path.read_bytes()
                if data and not data.endswith(b"\n"):
                    archive = self.output / "recovery" / self.session_id / path.name
                    archive.parent.mkdir(parents=True, exist_ok=True)
                    archive.write_bytes(data)
                    prefix = data[:data.rfind(b"\n") + 1]
                    atomic(path, prefix.decode())
                    recovered.append(str(archive.relative_to(self.output)))
            paths = sorted((self.output / "checkpoints").glob("*.json"))
            if paths:
                checkpoint = json.loads(paths[-1].read_text())
                if checkpoint["fingerprint"] != fingerprint:
                    raise ValueError("Resume fingerprint mismatch")
                self.checkpoint = checkpoint
                self.resume_state = checkpoint["runtime"]
                self.committed = len(self.resume_state["log_entries"])
                self.prior_wall = checkpoint["inference_wall_seconds"]
                self.rebuild_trajectory()
        calls = [c for c in rows(self.output / "calls.jsonl") if c["role"] == "actor"]
        starts = [e for e in rows(self.output / "events.jsonl")
                  if e.get("event") == "call_start" and e.get("role") == "actor"]
        self._actor_attempts = len({c["call_id"] for c in calls} | {e["call_id"] for e in starts})
        complete_ids = {c["call_id"] for c in calls}
        self._actor_usage_unknown = any(e["call_id"] not in complete_ids for e in starts)
        for call in calls:
            self._account_actor_usage(call.get("usage"))
        self.event("resume" if resume else "startup")
        if recovered:
            self.event("torn_append_recovered", preserved_artifacts=recovered)
        self.status("running")

    def append(self, name, record):
        path = self.output / name
        payload = {"schema_version": 1, "run_id": self.output.name,
                   "session_id": self.session_id, "step_key": self.step_key,
                   "operation_id": self.operation_id, "timestamp": now(), **record}
        with path.open("ab+") as stream:
            # Preserve a torn append but separate the next valid record from it.
            stream.seek(0, os.SEEK_END)
            if stream.tell():
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b"\n":
                    raise ValueError(f"Torn append in {name}; preserve and repair before resume")
            stream.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        return payload

    def event(self, kind, **fields):
        return self.append("events.jsonl", {"event": kind,
                           "session_elapsed_seconds": time.monotonic() - self.started, **fields})

    def status(self, state, **fields):
        save(self.output / "status.json", {"schema_version": 1, "status": state,
             "committed_steps": self.committed, "updated_at": now(), **fields})

    def begin_step(self, day, step):
        self.step_key = [day, step]
        self.event("step_start")

    def operation(self, phase):
        self.phase = phase
        self.operation_id = uuid.uuid4().hex
        return self.operation_id

    def actor_operation(self, messages):
        self.operation("actor")
        self.append("prompts.log", {"messages": messages})

    def wrap_client(self, client):
        if hasattr(client, "with_options"):
            client = client.with_options(max_retries=0, timeout=180)
        def create(**kwargs):
            return self.call(client, "actor", **kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    def call(self, client, role, **kwargs):
        token_field = "max_completion_tokens" if role == "actor" and "max_completion_tokens" in kwargs else "max_tokens"
        if kwargs.get(token_field) != 768 or (token_field == "max_completion_tokens" and "max_tokens" in kwargs):
            raise ValueError("Both agents must use max_tokens=768")
        if role == "actor":
            self._admit_actor(kwargs)
            self._actor_attempts += 1
        call_id = uuid.uuid4().hex
        started = time.monotonic()
        record = {"call_id": call_id, "attempt_id": call_id, "role": role,
                  "phase": self.phase, "request": copy.deepcopy(kwargs),
                  "cycle": getattr(self.adapter, "cycles", 0), "started_at": now(),
                  "parsed": None, "valid": False, "usage": None}
        record["validation_scope"] = "JSON schema and finish reason; semantic validation is in memory traces"
        self.event("call_start", call_id=call_id, role=role, phase=self.phase,
                   request=kwargs)
        try:
            response = client.chat.completions.create(**kwargs)
            record["response"] = response.model_dump()
            record["usage"] = response.usage.model_dump() if response.usage else None
            record["provider_request_id"] = getattr(response, "id", None)
            choice = response.choices[0]
            record["finish_reason"] = choice.finish_reason
            raw = choice.message.content or ""
            record["raw"] = raw
            record["parsed"] = json.loads(raw)
            schema = kwargs.get("response_format", {}).get("json_schema", {}).get("schema")
            if schema:
                jsonschema.validate(record["parsed"], schema)
            if choice.finish_reason == "length":
                raise ValueError("Truncated response")
            record["valid"] = True
            return response
        except Exception as exc:
            record["error"] = {"type": type(exc).__name__, "message": str(exc)}
            raise
        finally:
            record["duration_seconds"] = time.monotonic() - started
            record["finished_at"] = now()
            saved = self.append("calls.jsonl", record)
            if role == "actor":
                self._account_actor_usage(record["usage"])
            if role == "helper":
                self.append("memory_calls.jsonl", record)
            self.event("call_end", call_id=call_id, valid=saved["valid"])

    def _account_actor_usage(self, usage):
        total = usage.get("total_tokens") if isinstance(usage, dict) else None
        if type(total) is not int or total < 0:
            self._actor_usage_unknown = True
        else:
            self._actor_tokens += total

    def _admit_actor(self, kwargs):
        reason = None
        # A byte-based reservation is intentionally conservative for text BPE
        # inputs; it is not provider billing or a universal tokenizer guarantee.
        reserve = (len(json.dumps(kwargs.get("messages", []), ensure_ascii=False).encode())
                   + len(json.dumps(kwargs.get("response_format", {})).encode())
                   + 64 * (len(kwargs.get("messages", [])) + 1)
                   + kwargs.get("max_completion_tokens", kwargs.get("max_tokens", 0)))
        if self.max_actor_calls is not None and self._actor_attempts >= self.max_actor_calls:
            reason = "actor_call_budget_exhausted"
        elif self.max_actor_tokens is not None:
            if self._actor_usage_unknown:
                reason = "actor_usage_unknown"
            elif self._actor_tokens + reserve > self.max_actor_tokens:
                reason = "actor_token_budget_reservation_exceeded"
        if reason:
            self.event("actor_budget_stop", reason=reason, actor_attempts=self._actor_attempts,
                       known_actor_tokens=self._actor_tokens, next_call_token_reservation=reserve,
                       usage_unknown=self._actor_usage_unknown)
            raise ActorBudgetExceeded(reason)

    def bind(self, adapter):
        self.adapter = adapter
        if self.resume_state:
            adapter.restore(self.checkpoint["memory"])

    def rebuild_trajectory(self):
        entries = self.resume_state["log_entries"]
        atomic(self.output / "trajectory.jsonl", "".join(json.dumps(e) + "\n" for e in entries))

    def commit(self, runtime):
        index = len(runtime["log_entries"])
        memory = self.adapter.snapshot()
        save(self.output / "snapshots" / f"{index:06d}.json", memory)
        offsets = {p.name: p.stat().st_size for p in self.output.glob("*.jsonl")}
        checkpoint = {"schema_version": 1, "fingerprint": self.fingerprint,
                      "runtime": runtime, "memory": memory, "log_offsets": offsets,
                      "session_id": self.session_id,
                      "inference_wall_seconds": self.prior_wall + time.monotonic() - self.started}
        save(self.output / "checkpoints" / f"{index:06d}.json", checkpoint)
        self.resume_state = copy.deepcopy(runtime)
        self.committed = index
        self.rebuild_trajectory()
        self.event("checkpoint_commit", checkpoint=f"checkpoints/{index:06d}.json")
        self.status("running")
        if self.stop_after and index >= self.stop_after:
            raise InterruptedError("Requested interruption after committed step")


def traced_adapter_class(base):
    class TracedAdapter(base):
        def __init__(self, engine, session):
            super().__init__(engine)
            self.session = session

        def _ingest(self, message_id, text, scope):
            self.session.operation("instruction_intake")
            before = self.engine.snapshot()
            try:
                return super()._ingest(message_id, text, scope)
            finally:
                after = self.engine.snapshot()
                old = {i["id"]: i for i in before["intentions"]}
                new = {i["id"]: i for i in after["intentions"]}
                self.session.append("memory.jsonl", {
                    "event": "instruction_intake", "cycle": self.cycles,
                    "instruction": {"id": message_id, "text": text, "scope": scope,
                                    "source": getattr(self.engine, "instruction_sources", {}).get(message_id, "events")},
                    "before": before, "after": after,
                    "accepted_changes": [{"intention_id": key, "before": old.get(key), "after": value}
                                         for key, value in new.items() if old.get(key) != value],
                    "new_errors": after["errors"][len(before["errors"]):],
                    "disposition": "changed" if before != after else "no_change",
                })

        def context_for(self, messages):
            self.session.operation("memory_cycle")
            before = self.snapshot()
            try:
                reminder = super().context_for(messages)
                self.session.append("memory.jsonl", {
                    "event": "memory_cycle", "cycle": self.cycles, "before": before,
                    "after": self.snapshot(), "reminder": reminder,
                    "decisions": [asdict(d) for d in self.last_decisions],
                    "query_plan": copy.deepcopy(getattr(self, "last_query_plan", None)),
                })
                return reminder
            except Exception as exc:
                self.session.append("memory.jsonl", {
                    "event": "memory_cycle_error", "cycle": self.cycles,
                    "before": before, "after": self.snapshot(),
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                })
                raise
    return TracedAdapter
