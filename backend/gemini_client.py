import os
from datetime import datetime
from typing import Any, Dict, List

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')

_client = None
if GEMINI_API_KEY:
    try:
        from google import genai

        _client = genai.Client(api_key=GEMINI_API_KEY)
    except ImportError as exc:
        print('Warning: google-genai package is not installed or import failed. Running in demo mode.')
        print(f'ImportError: {exc}')
else:
    print('Warning: GEMINI_API_KEY not set. Running in demo mode without Gemini API calls.')


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


def create_chat_completion(messages: List[Dict[str, Any]], max_tokens: int = 1500) -> MockResponse:
    if not _client:
        return _create_demo_response(messages, max_tokens)

    system_parts = [m['content'] for m in messages if m.get('role') == 'system']
    conversation = [m for m in messages if m.get('role') in ('user', 'assistant')]

    prompt_lines = []
    if system_parts:
        prompt_lines.append('\n\n'.join(system_parts))

    for turn in conversation:
        role = 'User' if turn['role'] == 'user' else 'Assistant'
        prompt_lines.append(f'{role}: {turn["content"]}')

    prompt_lines.append('Assistant:')
    prompt = '\n\n'.join(prompt_lines)

    try:
        response = _client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={'max_output_tokens': max_tokens},
        )
        text = response.text if hasattr(response, 'text') else str(response)
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return _create_demo_response(messages, max_tokens, error=str(e))

    return MockResponse(text, GEMINI_MODEL)


def _create_demo_response(messages: List[Dict[str, Any]], max_tokens: int, error: str = None) -> MockResponse:
    user_message = next((m.get('content', '') for m in messages if m.get('role') == 'user'), 'No query')
    error_msg = f" (API Error: {error})" if error else ""
    demo_content = (
        f'[DEMO MODE]{error_msg} Mock Gemini response to: {user_message[:100]}...\n\n'
        'Set GEMINI_API_KEY in backend/.env to use the Gemini API.'
    )

    return MockResponse(demo_content)
