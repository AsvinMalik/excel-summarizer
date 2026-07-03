import logging
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'), override=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import shared provider instances from the preset registry so there's no duplicate state.
from ai_providers.model_presets import (
    PRESET_REGISTRY,
    groq_provider as _groq,
    phi3_provider as _phi3,
    cerebras_provider as _cerebras,
    openrouter_provider as _openrouter,
    demo_provider as _demo,
)

os.makedirs(os.path.join(os.path.dirname(__file__), 'logs'), exist_ok=True)
logger = logging.getLogger('procure_ai')
if not logger.handlers:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler = logging.FileHandler(os.path.join(os.path.dirname(__file__), 'logs', 'procure_ai.log'))
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)


class MockMessage:
    def __init__(self, content):
        self.content = content


class MockChoice:
    def __init__(self, content):
        self.message = MockMessage(content)


class MockResponse:
    def __init__(self, content, model):
        self.choices = [MockChoice(content)]
        self.created = int(datetime.utcnow().timestamp())
        self.model = model


class AllProvidersUnavailable(Exception):
    """Raised when every provider in the auto chain has failed or is unconfigured."""
    def __init__(self, tried: list[str], last_error: Exception | None = None):
        self.tried = tried
        self.last_error = last_error
        super().__init__(f'All providers failed: {tried}')


# Chain order: groq → cerebras → openrouter → phi3.
# PREFER_LOCAL_OLLAMA=true moves Phi3 to the front for zero-cost local dev.
if os.getenv('PREFER_LOCAL_OLLAMA', 'false').lower() == 'true':
    _CHAIN = [_phi3, _groq, _cerebras, _openrouter]
else:
    _CHAIN = [_groq, _cerebras, _openrouter, _phi3]


def create_chat_completion(
    messages: List[Dict[str, Any]],
    max_tokens: int = 1500,
    model_key: str = 'auto',
    provider_key: Optional[str] = None,  # alias for model_key; provider_key wins if set
) -> MockResponse:
    """Call one AI provider and return its response.

    model_key='auto' (default): run the provider chain (Groq -> Phi3 -> Cerebras ->
    OpenRouter -> Demo) and return the first successful response.

    model_key=<preset name>: call ONLY that specific provider. If the preset is unknown,
    the provider is not configured, or the call fails, return a clear error message to the
    user — NO silent fallback to a different model. The user explicitly chose this model
    and must know when it's unavailable so they can switch.
    """
    # provider_key is an alias (frontend sends 'provider_key'; some callers pass it here)
    effective_key = provider_key if provider_key else model_key

    # 'model_a', 'model_b', and 'pearl_pro' are pipeline-level keys handled in
    # procure_agent before this function is ever reached; treat them as 'auto' here so
    # internal LLM calls (query spec generation, grounding retries, map-reduce map step)
    # still use the best-available chain rather than failing on an unknown preset.
    # 'model_c' is the retired predecessor of pearl_pro, kept so stale clients
    # degrade gracefully instead of erroring.
    if effective_key and effective_key not in ('auto', 'model_a', 'model_b', 'model_c', 'pearl_pro', None):
        return _call_pinned(messages, max_tokens, effective_key)
    return _call_chain(messages, max_tokens)


def _call_pinned(messages, max_tokens, model_key) -> MockResponse:
    """Call exactly the provider named by model_key. Error out clearly if unavailable.

    model_key='demo' is the only valid way to get the DEMO canned-response provider.
    """
    if model_key == 'demo':
        text = _demo.complete(messages, max_tokens)
        return MockResponse(text, 'DEMO')

    preset = PRESET_REGISTRY.get(model_key)
    if not preset:
        known = ', '.join(PRESET_REGISTRY.keys())
        error = (
            f"Unknown model '{model_key}'. Valid options: auto, {known}. "
            "Switch the model selector to one of these and try again."
        )
        logger.error('model_key=%s status=unknown_preset', model_key)
        return MockResponse(error, 'error')

    provider = preset['provider']
    model_name = preset.get('model')

    if not provider.is_configured:
        error = (
            f"**{model_key}** is not available in this environment. "
            f"Check that the required API key or service is configured, "
            f"or switch the model selector to **Auto** to use whatever is available."
        )
        logger.warning('model_key=%s status=not_configured', model_key)
        return MockResponse(error, 'error')

    start = time.monotonic()
    try:
        text = provider.complete(messages, max_tokens, model_name=model_name)
        if not text:
            raise RuntimeError('empty response')
        elapsed = time.monotonic() - start
        logger.info('model_key=%s provider=%s status=success elapsed=%.2fs', model_key, provider.name, elapsed)
        return MockResponse(text, provider.name)
    except Exception as e:
        elapsed = time.monotonic() - start
        error = (
            f"**{model_key}** failed: {e}. "
            f"Switch the model selector to **Auto** to use the fallback chain."
        )
        logger.warning('model_key=%s provider=%s status=failed elapsed=%.2fs error=%s', model_key, provider.name, elapsed, e)
        return MockResponse(error, 'error')


def _call_chain(messages, max_tokens) -> MockResponse:
    """Run the full provider chain; raises AllProvidersUnavailable if all fail.

    Chain order (auto): groq → cerebras → openrouter → phi3.
    PREFER_LOCAL_OLLAMA=true: phi3 → groq → cerebras → openrouter.
    DEMO is never used here — only reachable via model_key='demo'.
    """
    last_error = None
    tried: list[str] = []

    for level, provider in enumerate(_CHAIN, start=1):
        if not provider.is_configured:
            logger.info('provider=%s level=%d status=skipped reason=not_configured',
                        provider.name, level)
            continue
        tried.append(provider.name)
        start = time.monotonic()
        try:
            text = provider.complete(messages, max_tokens)
            if not text:
                raise RuntimeError('empty response (likely reasoning-token budget exhausted)')
            elapsed = time.monotonic() - start
            logger.info('provider=%s level=%d status=success elapsed=%.2fs',
                        provider.name, level, elapsed)
            return MockResponse(text, provider.name)
        except Exception as e:
            elapsed = time.monotonic() - start
            last_error = e
            logger.warning('provider=%s level=%d status=failed elapsed=%.2fs error=%s',
                           provider.name, level, elapsed, e)

    logger.error('all_providers_failed tried=%s last_error=%s', tried, last_error)
    raise AllProvidersUnavailable(tried=tried, last_error=last_error)
