import os
from typing import Any, Dict, List

import requests

OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://localhost:11434')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'phi3')


class Phi3Provider:
    """Local fallback — Ollama running Phi3. Unlimited, private, slower (10-15s)."""

    name = 'PHI3_LOCAL'

    def __init__(self):
        self._available = None

    @property
    def is_configured(self) -> bool:
        # "Configured" means Ollama is reachable with the model pulled. Checked lazily
        # (and cached) since it requires a network call, unlike the cloud providers
        # where presence of an API key is enough to decide.
        if self._available is None:
            try:
                resp = requests.get(f'{OLLAMA_URL}/api/tags', timeout=2)
                models = [m.get('name', '').split(':')[0] for m in resp.json().get('models', [])]
                self._available = resp.ok and OLLAMA_MODEL in models
            except requests.RequestException:
                self._available = False
        return self._available

    def complete(self, messages: List[Dict[str, Any]], max_tokens: int = 1500, model_name: str = None) -> str:
        response = requests.post(
            f'{OLLAMA_URL}/api/chat',
            json={
                'model': model_name or OLLAMA_MODEL,
                'messages': messages,
                'stream': False,
                'options': {
                    'num_predict': max_tokens,
                    # Ollama defaults to 2048-token context which silently truncates
                    # our 6000-10000 token document context blocks. phi3-mini supports
                    # up to 128K — set to 12288 to fit full context without OOM risk.
                    'num_ctx': 12288,
                },
            },
            timeout=180,
        )
        response.raise_for_status()
        return response.json()['message']['content']
