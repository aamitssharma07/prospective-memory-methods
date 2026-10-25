"""Check the SGLang compatibility path against MistralCommon's direct IDs."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from huggingface_hub import snapshot_download
from sglang.srt.entrypoints.openai.serving_chat import OpenAIServingChat
from sglang.srt.utils.hf_transformers.tokenizer import get_tokenizer


root = Path(__file__).resolve().parents[1]
for model in (
    "mistralai/Ministral-3-3B-Instruct-2512-BF16",
    "mistralai/Ministral-3-8B-Instruct-2512-BF16",
):
    path = snapshot_download(
        model, cache_dir=root / ".cache/huggingface/hub", local_files_only=True
    )
    tokenizer = get_tokenizer(path)
    assert type(tokenizer).__name__ == "MistralCommonBackend"
    messages = [{"role": "user", "content": "Reply with exactly: PMBENCH_SMOKE_OK"}]
    reference = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, return_dict=False
    )
    if isinstance(reference, dict):
        reference = reference["input_ids"]
    server = SimpleNamespace(
        tokenizer_manager=SimpleNamespace(tokenizer=tokenizer),
        template_manager=SimpleNamespace(chat_template_name="mistral"),
        _get_reasoning_from_request=lambda request: False,
    )
    request = Mock()
    request.messages = [SimpleNamespace(role="user", content=messages[0]["content"])]
    request.continue_final_message = False
    request.ignore_eos = False
    request.stop = None
    request.tools = None
    actual = OpenAIServingChat._apply_conversation_template(server, request, False).prompt_ids
    assert actual == list(reference), model
    jinja_server = SimpleNamespace(tokenizer_manager=SimpleNamespace(tokenizer=tokenizer))
    _, jinja_ids, _ = OpenAIServingChat._render_and_encode_chat_template(
        jinja_server, messages, tools=None, template_kwargs={},
        encode_kwargs={"add_special_tokens": False}, use_cache=False,
    )
    assert jinja_ids == list(reference), model
    result = SimpleNamespace(
        prompt_ids=actual, image_data=None, video_data=None, audio_data=None,
    )
    assert OpenAIServingChat._engine_prompt(server, result, True) == (
        "input_ids", list(reference)
    )
    print(f"PASS {model}: conversation, Jinja, and text-only engine IDs match direct encoding")
