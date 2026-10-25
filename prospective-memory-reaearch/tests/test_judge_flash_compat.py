"""Flash/DeepSeek Judge: skip json_schema and read reasoning_content fallback."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from pm_memory.intention_store import IntentionStoreBackend


class _FakeCompletions:
    def __init__(self, owner: "_FakeClient") -> None:
        self.owner = owner

    def create(self, **kwargs):
        self.owner.calls.append(kwargs)
        return self.owner.response


class _FakeClient:
    def __init__(self, response) -> None:
        self.calls: list[dict] = []
        self.response = response
        self.chat = SimpleNamespace(completions=_FakeCompletions(self))


def _msg(*, content=None, reasoning_content=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content, reasoning_content=reasoning_content
                )
            )
        ]
    )


def _schema() -> dict:
    return {
        "type": "object",
        "properties": {"updates": {"type": "array"}, "due": {"type": "array"}},
        "required": ["updates", "due"],
        "additionalProperties": False,
    }


def test_flash_judge_skips_json_schema_and_disables_thinking() -> None:
    client = _FakeClient(_msg(content='{"updates":[],"due":[]}'))
    store = IntentionStoreBackend(
        llm_client=client,
        llm_model="deepseek-v4-flash",
        use_llm_update=True,
        llm_response_format="json_object",
    )
    data = store._complete_judge_json(
        messages=[{"role": "user", "content": "{}"}],
        max_tokens=128,
        schema_name="intention_scene",
        schema=_schema(),
        where="scene",
    )
    assert data == {"updates": [], "due": []}
    assert len(client.calls) == 1
    assert client.calls[0]["response_format"] == {"type": "json_object"}
    assert client.calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_flash_judge_reads_reasoning_content_when_content_empty() -> None:
    client = _FakeClient(
        _msg(content="", reasoning_content='{"updates":[],"due":[1]}')
    )
    store = IntentionStoreBackend(
        llm_client=client,
        llm_model="deepseek-v4-flash",
        use_llm_update=True,
        llm_response_format="json_object",
    )
    data = store._complete_judge_json(
        messages=[{"role": "user", "content": "{}"}],
        max_tokens=128,
        schema_name="intention_scene",
        schema=_schema(),
        where="scene",
    )
    assert data["due"] == [1]
