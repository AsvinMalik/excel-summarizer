import os
from typing import Any, Dict, List

CEREBRAS_API_KEY = os.getenv('CEREBRAS_API_KEY')
CEREBRAS_MODEL = os.getenv('CEREBRAS_MODEL', 'gpt-oss-120b')


class CerebrasProvider:
    """Secondary cloud fallback — Cerebras Cloud API. Free tier, ~1-2s responses, 1M tokens/day."""

    name = 'CEREBRAS'

    def __init__(self):
        self._client = None
        if CEREBRAS_API_KEY:
            from cerebras.cloud.sdk import Cerebras
            self._client = Cerebras(api_key=CEREBRAS_API_KEY, timeout=30.0)

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    def complete(self, messages: List[Dict[str, Any]], max_tokens: int = 1500, model_name: str = None) -> str:
        # gpt-oss-120b is a reasoning model that consumes hidden reasoning tokens before
        # generating visible content. Enforce a minimum so small callers (router, map-reduce)
        # don't exhaust the budget on reasoning alone and get content=None back.
        effective_max = max(max_tokens, 200)
        response = self._client.chat.completions.create(
            model=model_name or CEREBRAS_MODEL,
            messages=messages,
            max_tokens=effective_max,
        )
        return response.choices[0].message.content
