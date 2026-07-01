import os
from typing import Any, Dict, List

GROQ_API_KEY = os.getenv('GROQ_API_KEY')
GROQ_MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')


class GroqProvider:
    """Primary provider — Groq's LPU inference API. Free tier, ~0.5-1s responses."""

    name = 'GROQ'

    def __init__(self):
        self._client = None
        if GROQ_API_KEY:
            from groq import Groq
            self._client = Groq(api_key=GROQ_API_KEY, timeout=30.0)

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    def complete(self, messages: List[Dict[str, Any]], max_tokens: int = 1500, model_name: str = None) -> str:
        response = self._client.chat.completions.create(
            model=model_name or GROQ_MODEL,
            messages=messages,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content
