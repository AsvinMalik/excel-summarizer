import logging
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

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


# Fallback chain order per PROCURE_AI_ARCHITECTURE.md: Groq (primary) -> Phi3/Ollama
# (unlimited local) -> Cerebras (secondary cloud).
# PREFER_LOCAL_OLLAMA=true (set only in local backend/.env, never in production) moves
# Phi3 to the front so local testing burns zero Groq/Cerebras/OpenRouter quota.
if os.getenv('PREFER_LOCAL_OLLAMA', 'false').lower() == 'true':
    _CHAIN = [_phi3, _groq, _cerebras]
else:
    _CHAIN = [_groq, _phi3, _cerebras]


def create_chat_completion(
    messages: List[Dict[str, Any]],
    max_tokens: int = 1500,
    model_key: str = 'auto',
) -> MockResponse:
    """Call one AI provider and return its response.

    model_key='auto' (default): run the provider chain (Groq -> Phi3 -> Cerebras ->
    OpenRouter -> Demo) and return the first successful response.

    model_key=<preset name>: call ONLY that specific provider. If the preset is unknown,
    the provider is not configured, or the call fails, return a clear error message to the
    user — NO silent fallback to a different model. The user explicitly chose this model
    and must know when it's unavailable so they can switch.
    """
    # 'model_a' and 'model_b' are pipeline-level keys handled in procure_agent before
    # this function is ever reached; treat them as 'auto' here so internal LLM calls
    # made by model_b_agent (or any code path that passes model_a/model_b through)
    # still use the best-available chain rather than failing on an unknown preset.
    if model_key and model_key not in ('auto', 'model_a', 'model_b', None):
        return _call_pinned(messages, max_tokens, model_key)
    return _call_chain(messages, max_tokens)


def _call_pinned(messages, max_tokens, model_key) -> MockResponse:
    """Call exactly the provider named by model_key. Error out clearly if unavailable."""
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
    """Run the full provider chain; last resort is Demo mode."""
    last_error = None

    for level, provider in enumerate(_CHAIN):
        if not provider.is_configured:
            logger.info('provider=%s level=%d status=skipped reason=not_configured', provider.name, level)
            continue
        start = time.monotonic()
        try:
            text = provider.complete(messages, max_tokens)
            if not text:
                raise RuntimeError('empty response (likely reasoning-token budget exhausted)')
            elapsed = time.monotonic() - start
            logger.info('provider=%s level=%d status=success elapsed=%.2fs', provider.name, level, elapsed)
            return MockResponse(text, provider.name)
        except Exception as e:
            elapsed = time.monotonic() - start
            last_error = e
            logger.warning('provider=%s level=%d status=failed elapsed=%.2fs error=%s', provider.name, level, elapsed, e)

    # OpenRouter as an extra chance beyond the main chain
    if _openrouter.is_configured:
        start = time.monotonic()
        try:
            text = _openrouter.complete(messages, max_tokens)
            elapsed = time.monotonic() - start
            logger.info('provider=OPENROUTER level=3 status=success elapsed=%.2fs', elapsed)
            return MockResponse(text, _openrouter.name)
        except Exception as e:
            elapsed = time.monotonic() - start
            last_error = e
            logger.warning('provider=OPENROUTER level=3 status=failed elapsed=%.2fs error=%s', elapsed, e)

    logger.error('provider=DEMO level=4 status=fallback last_error=%s', last_error)
    text = _demo.complete(messages, max_tokens, error=str(last_error))
    return MockResponse(text, 'DEMO')
