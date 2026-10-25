"""Use direct MistralCommon IDs on pinned SGLang's legacy template route."""

import os
import sys

if os.environ.get("PMBENCH_MISTRAL_TOKENIZER_FIX") == "1":
    from sglang.srt.entrypoints.openai.serving_chat import OpenAIServingChat

    _original_conversation = OpenAIServingChat._apply_conversation_template
    _original_engine_prompt = OpenAIServingChat._engine_prompt

    def _direct_ids(tokenizer, messages):
        token_ids = tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True, return_dict=False
        )
        if isinstance(token_ids, dict):
            token_ids = token_ids["input_ids"]
        return list(token_ids)

    def _conversation_with_direct_ids(self, request, is_multimodal):
        result = _original_conversation(self, request, is_multimodal)
        tokenizer = self.tokenizer_manager.tokenizer
        if request.tools or request.continue_final_message:
            raise ValueError("Ministral direct-ID serving supports plain chat only")
        messages = [
            {"role": message.role, "content": message.content}
            for message in request.messages
        ]
        result.prompt_ids = _direct_ids(tokenizer, messages)
        return result

    def _render_with_direct_ids(
        self, messages, *, tools, template_kwargs, encode_kwargs, use_cache
    ):
        if tools:
            raise ValueError("Ministral direct-ID serving supports plain chat only")
        tokenizer = self.tokenizer_manager.tokenizer
        options = dict(
            add_generation_prompt=True, tools=None, return_dict=False,
            **template_kwargs,
        )
        rendered = tokenizer.apply_chat_template(messages, tokenize=False, **options)
        token_ids = tokenizer.apply_chat_template(messages, tokenize=True, **options)
        if isinstance(token_ids, dict):
            token_ids = token_ids["input_ids"]
        return rendered, list(token_ids), None

    OpenAIServingChat._apply_conversation_template = _conversation_with_direct_ids
    OpenAIServingChat._render_and_encode_chat_template = _render_with_direct_ids

    def _text_only_engine_prompt(self, processed_messages, is_multimodal):
        if not any((
            processed_messages.image_data,
            processed_messages.video_data,
            processed_messages.audio_data,
        )):
            return "input_ids", processed_messages.prompt_ids
        return _original_engine_prompt(self, processed_messages, is_multimodal)

    OpenAIServingChat._engine_prompt = _text_only_engine_prompt
    print(f"PMBench Ministral tokenizer fix installed in PID {os.getpid()}", file=sys.stderr)
