"""Model routing: turn a model id into something the OpenAI Agents SDK can run.

Every provider here speaks the OpenAI Chat Completions wire format, so one
``AsyncOpenAI`` client per provider — differing only in ``base_url`` and key — is
enough to reach all of them. The SDK's native path is used for OpenAI's own
models; everything else is wrapped in ``OpenAIChatCompletionsModel``.

Routing is by the shape of the model id, so adding a provider is one clause:

    "anthropic/claude-x"  ->  contains "/"        -> OpenRouter
    "deepseek-v4-flash"   ->  contains "deepseek" -> DeepSeek direct
    "gpt-5.4-mini"        ->  no match            -> OpenAI native
"""

from __future__ import annotations

from functools import cache

from agents import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from trading_floor import config


@cache
def _client(base_url: str, api_key: str | None) -> AsyncOpenAI:
    """One client per provider, reused across traders and runs."""
    return AsyncOpenAI(base_url=base_url, api_key=api_key)


def get_model(model_name: str):
    """The model object (or plain id) to hand an ``Agent``."""
    if "/" in model_name:  # provider-qualified ids belong to OpenRouter
        client = _client(config.OPENROUTER_BASE_URL, config.OPENROUTER_API_KEY)
    elif "deepseek" in model_name:
        client = _client(config.DEEPSEEK_BASE_URL, config.DEEPSEEK_API_KEY)
    elif "grok" in model_name:
        client = _client(config.GROK_BASE_URL, config.GROK_API_KEY)
    elif "gemini" in model_name:
        client = _client(config.GEMINI_BASE_URL, config.GOOGLE_API_KEY)
    else:
        return model_name  # the SDK's own OpenAI path, with tracing built in
    return OpenAIChatCompletionsModel(model=model_name, openai_client=client)
