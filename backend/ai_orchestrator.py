import logging
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_providers.groq_provider import GroqProvider
from ai_providers.phi3_provider import Phi3Provider
from ai_providers.cerebras_provider import CerebrasProvider
from ai_providers.demo_provider import DemoProvider
from openrouter_client import create_chat_completion as _openrouter_complete

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


_groq = GroqProvider()
_phi3 = Phi3Provider()
_cerebras = CerebrasProvider()
_demo = DemoProvider()

# Fallback order per PROCURE_AI_ARCHITECTURE.md: Groq (primary, fastest) -> Phi3/Ollama
# (unlimited local) -> Cerebras (secondary cloud). OpenRouter is kept as an extra layer
# beyond the doc — it was already configured and working before this upgrade, so it adds
# a free fifth chance before giving up to demo mode rather than removing capability.
_CLOUD_AND_LOCAL_PROVIDERS = [_groq, _phi3, _cerebras]


def create_chat_completion(messages: List[Dict[str, Any]], max_tokens: int = 1500) -> MockResponse:
    last_error = None

    for level, provider in enumerate(_CLOUD_AND_LOCAL_PROVIDERS):
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

    start = time.monotonic()
    response = _openrouter_complete(messages, max_tokens)
    elapsed = time.monotonic() - start
    if response.model != 'demo':
        logger.info('provider=OPENROUTER level=3 status=success elapsed=%.2fs model=%s', elapsed, response.model)
        return response
    logger.warning('provider=OPENROUTER level=3 status=failed elapsed=%.2fs', elapsed)
    last_error = last_error or 'OpenRouter unavailable or unconfigured'

    logger.error('provider=DEMO level=4 status=fallback last_error=%s', last_error)
    text = _demo.complete(messages, max_tokens, error=str(last_error))
    return MockResponse(text, 'DEMO')
