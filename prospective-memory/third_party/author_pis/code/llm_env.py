"""Load local LLM settings without putting secrets in git.

Resolution order for api_key / base_url / model:
  CLI flag  >  <PROVIDER>_… env  >  built-in non-secret default

Put keys in a repo-root `.env` (gitignored). The file is loaded automatically.
Add a new vendor by defining NAME_API_KEY / NAME_BASE_URL / NAME_MODEL.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# Public defaults only — never put API keys here.
BUILTIN: dict[str, dict[str, str]] = {
    "qwen": {
        "label": "千问 (Qwen)",
        "base_url": "https://token.pjlab.org.cn/v1",
        "model": "qwen3.5-397b",
        "response_format": "json_schema",
        "out_dir": "local_qwen35",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "response_format": "json_object",
        "out_dir": "local_deepseek",
    },
}

_SKIP_ENV_PREFIXES = {"MEM0_EMBED", "INTENTION_CALIBRATE"}

_CHAT_EXTRAS_PATCHED = False
_EMBED_PATCHED = False
_CHAT_EXTRAS: dict[str, Any] = {}


def _patch_embeddings() -> None:
    global _EMBED_PATCHED
    if _EMBED_PATCHED:
        return
    try:
        from openai.resources.embeddings import Embeddings
    except Exception:
        return
    orig = Embeddings.create

    def create(self, *args, **kwargs):
        from llm_cost import record_embed

        t0 = time.perf_counter()
        resp = orig(self, *args, **kwargs)
        record_embed(resp, kwargs, (time.perf_counter() - t0) * 1000.0)
        return resp

    Embeddings.create = create  # type: ignore[method-assign]
    _EMBED_PATCHED = True


def chat_extra_body(model: str | None) -> dict[str, Any]:
    """Vendor extras that are not in the OpenAI SDK's typed kwargs."""
    name = (model or "").strip().lower()
    if "deepseek" in name:
        # V4 thinks by default; thinking shares max_tokens with content.
        return {"thinking": {"type": "disabled"}}
    return {}


def _promote_reasoning_content(resp: Any) -> Any:
    """PM-Bench reads message.content; thinking models may park JSON in reasoning."""
    try:
        msg = resp.choices[0].message
    except Exception:
        return resp
    content = getattr(msg, "content", None)
    if content and str(content).strip():
        return resp
    for attr in ("reasoning_content", "reasoning"):
        val = getattr(msg, attr, None)
        text = str(val).strip() if val else ""
        if text:
            msg.content = text
            break
    return resp


def _is_retryable_chat_error(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    if status in {429, 500, 502, 503, 504}:
        return True
    text = str(exc)
    # Do not substring-match "504" etc.: aihubmix tids can contain those digits.
    if any(
        phrase in text
        for phrase in (
            "Error code: 429",
            "Error code: 500",
            "Error code: 502",
            "Error code: 503",
            "Error code: 504",
            "Gateway Time-out",
            "Bad Gateway",
            "empty stream",
            "Service is temporarily",
        )
    ):
        return True
    name = type(exc).__name__
    return name in {
        "InternalServerError",
        "APITimeoutError",
        "APIConnectionError",
        "RateLimitError",
    }


def _stream_unsupported(exc: BaseException) -> bool:
    text = str(exc).lower()
    name = type(exc).__name__
    if name in {"BadRequestError", "UnprocessableEntityError"}:
        return True
    return "stream" in text and any(x in text for x in ("not support", "invalid", "400"))


def _delta_field(delta: Any, name: str) -> str:
    if delta is None:
        return ""
    val = getattr(delta, name, None)
    if val is None and isinstance(delta, dict):
        val = delta.get(name)
    return str(val) if val else ""


def _assemble_stream(stream: Any, *, model: str | None) -> Any:
    """Read a streaming completion into one object PM-Bench can parse."""
    import time
    from types import SimpleNamespace

    content: list[str] = []
    reasoning: list[str] = []
    finish_reason = None
    usage = None
    model_name = model
    resp_id = None
    for chunk in stream:
        model_name = getattr(chunk, "model", None) or model_name
        resp_id = getattr(chunk, "id", None) or resp_id
        chunk_usage = getattr(chunk, "usage", None)
        if chunk_usage is not None:
            usage = chunk_usage
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        ch0 = choices[0]
        finish_reason = getattr(ch0, "finish_reason", None) or finish_reason
        delta = getattr(ch0, "delta", None)
        piece = _delta_field(delta, "content")
        if piece:
            content.append(piece)
        thought = _delta_field(delta, "reasoning_content") or _delta_field(
            delta, "reasoning"
        )
        if thought:
            reasoning.append(thought)
    body = "".join(content).strip()
    thought_text = "".join(reasoning).strip()
    if not body and not thought_text:
        raise RuntimeError("empty stream")
    msg = SimpleNamespace(
        role="assistant",
        content=body or None,
        reasoning_content=thought_text or None,
    )
    choice = SimpleNamespace(
        index=0,
        finish_reason=finish_reason or "stop",
        message=msg,
        text=None,
        logprobs=None,
    )

    class _Completion(SimpleNamespace):
        def model_dump(self) -> dict[str, Any]:
            return {
                "id": self.id,
                "model": self.model,
                "choices": [
                    {
                        "finish_reason": self.choices[0].finish_reason,
                        "message": {
                            "role": "assistant",
                            "content": self.choices[0].message.content,
                            "reasoning_content": getattr(
                                self.choices[0].message, "reasoning_content", None
                            ),
                        },
                    }
                ],
            }

    return _Completion(
        id=resp_id or "chatcmpl-stream",
        object="chat.completion",
        created=int(time.time()),
        model=model_name or "",
        choices=[choice],
        usage=usage,
    )


def _create_waiting(orig: Any, self: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """Wait out thinking: stream so nginx sees bytes; retry 502/503/504 forever."""
    import time

    if kwargs.get("stream"):
        return orig(self, *args, **kwargs)
    n = 0
    while True:
        try:
            streamed = dict(kwargs)
            streamed["stream"] = True
            extras = dict(streamed.get("extra_body") or {})
            extras.setdefault("stream_options", {"include_usage": True})
            streamed["extra_body"] = extras
            streamed.setdefault("stream_options", {"include_usage": True})
            try:
                resp = _assemble_stream(
                    orig(self, *args, **streamed),
                    model=kwargs.get("model"),
                )
            except Exception as exc:
                if _stream_unsupported(exc):
                    resp = orig(self, *args, **kwargs)
                else:
                    raise
            return _promote_reasoning_content(resp)
        except Exception as exc:
            if not _is_retryable_chat_error(exc):
                raise
            n += 1
            wait = min(30.0, 1.5 * n)
            print(
                f"[llm] gateway {type(exc).__name__}: {exc}; "
                f"waiting {wait:.0f}s then retry #{n}",
                flush=True,
            )
            time.sleep(wait)


def _keep_sglang_chat_template(model: str | None) -> bool:
    """PM-Bench always sends sglang `chat_template_kwargs`; only Qwen-family gateways want it."""
    name = (model or "").strip().lower()
    return any(tok in name for tok in ("qwen", "kimi", "glm"))


def _merge_chat_extra_body(kwargs: dict[str, Any]) -> None:
    body = dict(kwargs.get("extra_body") or {})
    if not _keep_sglang_chat_template(kwargs.get("model")):
        body.pop("chat_template_kwargs", None)
    body.update(_CHAT_EXTRAS)
    if body:
        kwargs["extra_body"] = body
    else:
        kwargs.pop("extra_body", None)


def install_model_chat_extras(model: str | None) -> dict[str, Any]:
    """Merge vendor extras into every OpenAI chat.completions.create in-process."""
    global _CHAT_EXTRAS_PATCHED, _CHAT_EXTRAS
    extra = chat_extra_body(model)
    _CHAT_EXTRAS = extra
    if _CHAT_EXTRAS_PATCHED:
        return extra
    from openai.resources.chat.completions import Completions

    orig = Completions.create

    def create(self, *args, **kwargs):
        from llm_cost import record_chat

        _merge_chat_extra_body(kwargs)
        name = str(kwargs.get("model") or "").strip().lower()
        # aihubmix gpt-5.6-luna rejects sampling knobs Mem0 still sends.
        if "luna" in name:
            kwargs.pop("top_p", None)
        t0 = time.perf_counter()
        resp = _create_waiting(orig, self, args, kwargs)
        record_chat(resp, kwargs, (time.perf_counter() - t0) * 1000.0)
        return resp

    Completions.create = create  # type: ignore[method-assign]
    _patch_embeddings()
    _CHAT_EXTRAS_PATCHED = True
    return extra


def load_dotenv_files(*paths: Path) -> list[Path]:
    """Load KEY=VAL lines into os.environ. Existing env vars win."""
    loaded: list[Path] = []
    candidates = paths or (ROOT / ".env", ROOT / "code" / ".env")
    for path in candidates:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            if key:
                os.environ.setdefault(key, val)
        loaded.append(path)
    return loaded


def _prefix(name: str) -> str:
    return name.strip().upper().replace("-", "_")


def _env(prefix: str, suffix: str) -> str | None:
    val = os.environ.get(f"{prefix}_{suffix}")
    if val is None:
        return None
    val = val.strip()
    return val or None


def discover_providers() -> list[str]:
    names = set(BUILTIN)
    for key, val in os.environ.items():
        if not key.endswith("_API_KEY") or not (val or "").strip():
            continue
        prefix = key[: -len("_API_KEY")]
        if prefix in _SKIP_ENV_PREFIXES:
            continue
        names.add(prefix.lower().replace("_", "-"))
    default = (os.environ.get("DEFAULT_PROVIDER") or "").strip().lower()
    if default:
        names.add(default)
    return sorted(names)


def resolve_llm(
    provider: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    response_format: str | None = None,
    out_dir: str | None = None,
    runs_dir: Path | None = None,
) -> dict:
    name = (provider or "").strip().lower()
    if not name:
        raise SystemExit(
            "Missing provider. Pass --provider, or set DEFAULT_PROVIDER in .env."
        )
    prefix = _prefix(name)
    builtin = BUILTIN.get(name, {})

    key = (
        api_key
        or _env(prefix, "API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("API_KEY")
    )
    url = base_url or _env(prefix, "BASE_URL") or builtin.get("base_url")
    mdl = model or _env(prefix, "MODEL") or builtin.get("model")
    fmt = (
        response_format
        or _env(prefix, "RESPONSE_FORMAT")
        or builtin.get("response_format")
        or "json_object"
    )
    if not key:
        raise SystemExit(
            f"Missing API key for '{name}'. Set {prefix}_API_KEY in .env "
            f"(or OPENAI_API_KEY), or pass --api-key."
        )
    if not url:
        raise SystemExit(
            f"Missing base URL for '{name}'. Set {prefix}_BASE_URL in .env "
            f"or pass --base-url."
        )
    if not mdl:
        raise SystemExit(
            f"Missing model for '{name}'. Set {prefix}_MODEL in .env "
            f"or pass --model."
        )

    safe = name.replace("/", "-").replace(":", "-").replace(" ", "-")
    folder = builtin.get("out_dir") or f"local_{safe}"
    default_out = str((runs_dir or (ROOT / "data" / "PMBench" / "runs")) / folder)
    return {
        "name": name,
        "label": builtin.get("label") or name,
        "api_key": key,
        "base_url": url,
        "model": mdl,
        "response_format": fmt,
        "out_dir": out_dir or default_out,
    }


def resolve_optional_prefix(prefix: str) -> dict[str, str] | None:
    """Optional second endpoint (e.g. a hosted / local calibrator).

    Needs ``<PREFIX>_MODEL`` and ``<PREFIX>_BASE_URL``. If the URL matches
    the Qwen gateway, a missing key reuses ``QWEN_API_KEY``. Otherwise a
    missing key is ``local`` so vLLM / SGLang can start without a secret.
    """
    p = _prefix(prefix)
    model = _env(p, "MODEL")
    url = _env(p, "BASE_URL")
    if not model or not url:
        return None
    qwen_url = (_env("QWEN", "BASE_URL") or "").rstrip("/")
    same_qwen = bool(qwen_url) and url.rstrip("/") == qwen_url
    key = _env(p, "API_KEY")
    if not key and same_qwen:
        key = _env("QWEN", "API_KEY")
    key = key or os.environ.get("OPENAI_API_KEY") or "local"
    fmt = _env(p, "RESPONSE_FORMAT") or "json_object"
    return {
        "api_key": key,
        "base_url": url,
        "model": model,
        "response_format": fmt,
    }


def format_provider_list() -> str:
    lines = ["Configured LLM providers (.env + built-in defaults):"]
    for name in discover_providers():
        prefix = _prefix(name)
        builtin = BUILTIN.get(name, {})
        has_key = bool(
            _env(prefix, "API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("API_KEY")
        )
        model = _env(prefix, "MODEL") or builtin.get("model") or "(set --model)"
        url = _env(prefix, "BASE_URL") or builtin.get("base_url") or "(set --base-url)"
        flag = "key=set" if has_key else "key=MISSING"
        lines.append(f"  {name:12}  {flag:11}  model={model}  base_url={url}")
    lines.append(
        "Add another vendor: NAME_API_KEY / NAME_BASE_URL / NAME_MODEL in .env, "
        "then --provider NAME."
    )
    return "\n".join(lines)
