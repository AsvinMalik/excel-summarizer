import os
from datetime import datetime
from typing import Any, Dict, List

from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
MODEL_NAME = os.getenv('OPENROUTER_MODEL', 'openai/gpt-oss-20b:free')

_client = None
if OPENROUTER_API_KEY:
    try:
        from openai import OpenAI

        _client = OpenAI(api_key=OPENROUTER_API_KEY, base_url='https://openrouter.ai/api/v1', timeout=15.0)
    except ImportError as exc:
        print('Warning: openai package is not installed or import failed. Running in demo mode.')
        print(f'ImportError: {exc}')
else:
    print('Warning: OPENROUTER_API_KEY not set. Running in demo mode without OpenRouter calls.')


class MockMessage:
    def __init__(self, content):
        self.content = content


class MockChoice:
    def __init__(self, content):
        self.message = MockMessage(content)


class MockResponse:
    def __init__(self, content, model='demo'):
        self.choices = [MockChoice(content)]
        self.created = int(datetime.utcnow().timestamp())
        self.model = model


# OpenRouter's ":free" models share a public rate-limit pool that fluctuates, so a single
# model can be temporarily saturated even though the account/key is fine. Try the configured
# model first, then fall back through a few other free models before giving up.
FALLBACK_MODELS = list(dict.fromkeys([
    MODEL_NAME,
    'nvidia/nemotron-nano-9b-v2:free',
    'meta-llama/llama-3.3-70b-instruct:free',
]))


class OpenRouterProvider:
    """Provider class wrapping OpenRouter — used by the preset registry for explicit model selection."""

    name = 'OPENROUTER'

    def __init__(self):
        self._client = _client

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    def complete(self, messages: List[Dict[str, Any]], max_tokens: int = 1500, model_name: str = None) -> str:
        if not self._client:
            raise RuntimeError('OpenRouter is not configured — set OPENROUTER_API_KEY in backend/.env')
        models_to_try = [model_name] if model_name else FALLBACK_MODELS
        last_error = None
        for model in models_to_try:
            try:
                response = self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                )
                text = response.choices[0].message.content if response.choices else None
                if text:
                    return text
            except Exception as e:
                last_error = e
                print(f"OpenRouter API Error ({model}): {e}")
        raise RuntimeError(f'OpenRouter failed on all tried models. Last error: {last_error}')


def create_chat_completion(messages: List[Dict[str, Any]], max_tokens: int = 1500) -> MockResponse:
    if not _client:
        return _create_demo_response(messages, max_tokens)

    last_error = None
    for model in FALLBACK_MODELS:
        try:
            response = _client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
            )
            text = response.choices[0].message.content if response.choices else None
            if text:
                return MockResponse(text, model)
        except Exception as e:
            last_error = e
            print(f"OpenRouter API Error ({model}): {e}")

    return _create_demo_response(messages, max_tokens, error=str(last_error))


def _create_demo_response(messages: List[Dict[str, Any]], max_tokens: int, error: str = None) -> MockResponse:
    user_message = next((m.get('content', '') for m in messages if m.get('role') == 'user'), 'No query')
    error_msg = f" (API Error: {error})" if error else ""
    demo_content = (
        f'[DEMO MODE]{error_msg} Mock response to: {user_message[:100]}...\n\n'
        'Set OPENROUTER_API_KEY in backend/.env to use the OpenRouter API.'
    )

    return MockResponse(demo_content)
