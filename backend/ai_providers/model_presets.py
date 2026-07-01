"""
Preset registry — maps user-facing model_key strings to a provider instance and an optional
model-name override. Editing this file is the single place to swap a label, point a key at a
different underlying model, or add a new selectable option.

When model_key is given by the caller, the orchestrator looks it up here and calls ONLY that
provider (no chain fallback). Unknown or unconfigured keys surface a clear error to the user
instead of silently substituting a different model.
"""
import os
import sys

# backend/ is the package root; ensure it's on sys.path so sibling modules resolve cleanly
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from ai_providers.groq_provider import GroqProvider
from ai_providers.phi3_provider import Phi3Provider
from ai_providers.cerebras_provider import CerebrasProvider
from ai_providers.demo_provider import DemoProvider
from openrouter_client import OpenRouterProvider
import gemini_client as _gemini_client
import openai_client as _openai_client


class GeminiProvider:
    """Phase 5b frontier tier — wraps gemini_client.py (custom API route)."""
    name = 'GEMINI'

    @property
    def is_configured(self) -> bool:
        return bool(os.getenv('GEMINI_API_KEY'))

    def complete(self, messages, max_tokens: int = 1500, model_name: str = None) -> str:
        resp = _gemini_client.create_chat_completion(messages, max_tokens)
        text = resp.choices[0].message.content
        if '[DEMO MODE]' in text or '[API Error' in text:
            raise RuntimeError(text)
        return text


class OpenAIProvider:
    """Phase 5b frontier tier — wraps openai_client.py (custom API route)."""
    name = 'OPENAI'

    @property
    def is_configured(self) -> bool:
        return bool(os.getenv('OPENAI_API_KEY'))

    def complete(self, messages, max_tokens: int = 1500, model_name: str = None) -> str:
        resp = _openai_client.create_chat_completion(messages, max_tokens)
        text = resp.choices[0].message.content
        if '[DEMO MODE]' in text or '[API Error' in text:
            raise RuntimeError(text)
        return text


# One instance per provider — shared with the orchestrator's fallback chain so there's
# no duplicate state (connection pools, lazy is_configured checks, etc.).
groq_provider = GroqProvider()
phi3_provider = Phi3Provider()
cerebras_provider = CerebrasProvider()
openrouter_provider = OpenRouterProvider()
demo_provider = DemoProvider()
gemini_provider = GeminiProvider()
openai_provider = OpenAIProvider()

# model_key -> {'provider': <instance>, 'model': <optional model-name override or None>}
# 'model': None means use each provider's own default model (from its env var).
PRESET_REGISTRY = {
    'phi3':       {'provider': phi3_provider,       'model': None},
    'groq':       {'provider': groq_provider,       'model': None},
    'cerebras':   {'provider': cerebras_provider,   'model': None},
    'openrouter': {'provider': openrouter_provider, 'model': None},
    'gemini':     {'provider': gemini_provider,     'model': None},
    'openai':     {'provider': openai_provider,     'model': None},
}
