"""Atomic, identity-bound checkpoints for PM-Bench runners."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


VERSION = 1


def digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def identity(*, runner: str, scenario: dict, model: str, backend: str,
             options: dict, source_paths: list[Path]) -> dict:
    return {
        "runner": runner,
        "scenario_sha256": digest(scenario),
        "model": model,
        "backend": backend,
        "options": options,
        "source_sha256": {
            str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source_paths
        },
    }


def save(path: str | Path, expected_identity: dict, state: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    payload = {"version": VERSION, "identity": expected_identity, "state": state}
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def load(path: str | Path, expected_identity: dict) -> dict:
    target = Path(path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("version") != VERSION:
        raise ValueError("Unsupported checkpoint version")
    if payload.get("identity") != expected_identity:
        raise ValueError("Checkpoint identity does not match this experiment")
    state = payload.get("state")
    if not isinstance(state, dict):
        raise ValueError("Malformed checkpoint state")
    return state
