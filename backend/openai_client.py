import os
from typing import Any, Dict
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')

client = None
if OPENAI_API_KEY:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
    except ImportError:
        print("Warning: OpenAI package not installed. Running in demo mode.")
else:
    print("Warning: OPENAI_API_KEY not set. Running in demo mode without API calls.")


def create_chat_completion(messages: list[Dict[str, Any]], max_tokens: int = 1500) -> Dict[str, Any]:
    if not client:
        # Demo mode: return mock response
        return _create_demo_response(messages, max_tokens)
    
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        max_tokens=max_tokens,
    )
    return response


def _create_demo_response(messages: list[Dict[str, Any]], max_tokens: int):
    """Return a mock response for demo/test mode."""
    class MockChoice:
        class MockMessage:
            def __init__(self, content):
                self.content = content
        
        def __init__(self, content):
            self.message = self.MockMessage(content)
    
    class MockResponse:
        def __init__(self, content):
            self.choices = [MockChoice(content)]
            self.created = 1234567890
    
    user_message = next((m.get('content', '') for m in messages if m.get('role') == 'user'), 'No query')
    demo_content = f"[DEMO MODE] Mock response to: {user_message[:100]}...\n\nThis is a demo response. Set OPENAI_API_KEY in backend/.env to use actual OpenAI API."
    
    return MockResponse(demo_content)
