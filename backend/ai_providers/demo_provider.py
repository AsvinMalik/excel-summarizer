from typing import Any, Dict, List


class DemoProvider:
    """Last resort — always succeeds so the app stays online when every real provider fails."""

    name = 'DEMO'
    is_configured = True

    def complete(self, messages: List[Dict[str, Any]], max_tokens: int = 1500, error: str = None) -> str:
        user_message = next((m.get('content', '') for m in messages if m.get('role') == 'user'), 'No query')
        error_note = f' (last error: {error})' if error else ''
        return (
            f'[DEMO MODE]{error_note} All configured AI providers are unavailable or unconfigured.\n\n'
            f'Mock response to: {user_message[:150]}...\n\n'
            'Set GROQ_API_KEY, CEREBRAS_API_KEY, or OPENROUTER_API_KEY in backend/.env to use a real model.'
        )
