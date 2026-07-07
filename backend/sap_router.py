"""
SAP dataset router — decides which SAP Excel dataset answers a user question.

Mirrors the two-tier philosophy of sheet_router.py:

  Tier 1 (LLM):     one tiny call through the EXISTING provider fallback chain
                    (ai_orchestrator.create_chat_completion — Groq → Cerebras →
                    OpenRouter → Phi3, or Phi3-first when PREFER_LOCAL_OLLAMA).
                    The prompt carries ONLY catalog metadata, never row data,
                    and must return a bare dataset_id.
  Tier 2 (keyword): zero-token scoring of query tokens against dataset names
                    and descriptions. Used when the LLM output doesn't resolve
                    to a real id, or every provider is down — routing degrades,
                    it never crashes the request.
"""
import logging
import re
from typing import Dict, List, Optional

from ai_orchestrator import create_chat_completion

logger = logging.getLogger('procure_ai')

_STOPWORDS = {
    'the', 'and', 'for', 'with', 'from', 'this', 'that', 'are', 'was', 'were',
    'what', 'which', 'give', 'show', 'list', 'tell', 'get', 'of', 'in', 'to',
    'me', 'my', 'please', 'their', 'there', 'is', 'it', 'on', 'at', 'by', 'an',
    'as', 'do', 'does', 'has', 'have', 'can', 'you', 'about', 'all', 'our',
}


def _tokenise(text: str) -> set:
    toks = {w for w in re.findall(r'[a-z0-9]{2,}', text.lower())}
    # naive singulars so "vendors" matches "vendor"
    toks |= {t[:-1] for t in toks if t.endswith('s') and len(t) >= 4}
    return toks


class SAPRouter:
    """Routes a natural-language procurement question to one SAP dataset id."""

    def __init__(self, provider_key: str = 'auto'):
        #: Which provider answers the routing call — honors the user's UI
        #: selection exactly like every other internal LLM call (a pinned
        #: provider must never silently burn a different provider's quota).
        self.provider_key = provider_key

    def route(self, user_query: str, datasets: List[Dict]) -> Dict:
        """Pick the dataset that best matches `user_query`.

        Args:
            user_query: raw user question.
            datasets:   catalog from SAPService.get_available_datasets().

        Returns:
            {"dataset_id": str, "tier": "llm"|"keyword", "reason": str}
            dataset_id is always a REAL id from `datasets` (never invented) —
            defensive parsing plus keyword fallback guarantee it.
        """
        if not datasets:
            raise ValueError('SAP catalog is empty — nothing to route to.')

        valid_ids = {d['id'] for d in datasets}

        # ── Tier 1: LLM routing over metadata only ───────────────────────────
        index = '\n'.join(
            f"- {d['id']}: {d['name']} — {d['description']}" for d in datasets
        )
        messages = [
            {'role': 'system', 'content': (
                'You route procurement questions to the single SAP dataset most '
                'likely to contain the answer. Reply with ONLY the dataset id '
                '(e.g. sap_003). No punctuation, no explanation.'
            )},
            {'role': 'user', 'content': (
                f'Available SAP datasets:\n{index}\n\n'
                f'Question: "{user_query}"\n\nBest dataset id:'
            )},
        ]
        try:
            resp = create_chat_completion(messages, max_tokens=200,
                                          provider_key=self.provider_key)
            raw = (resp.choices[0].message.content or '').strip()
            # Defensive parse: accept the id anywhere in the reply
            match = next((i for i in valid_ids if i in raw), None)
            if match:
                logger.info(f'sap_router dataset={match} tier=llm')
                return {'dataset_id': match, 'tier': 'llm',
                        'reason': f'LLM routing choice (raw={raw[:60]!r})'}
            logger.warning(f'sap_router: LLM reply had no valid id ({raw[:80]!r}) — keyword fallback')
        except Exception as exc:
            logger.warning(f'sap_router: LLM tier failed ({exc}) — keyword fallback')

        # ── Tier 2: zero-token keyword scoring ───────────────────────────────
        return self._keyword_route(user_query, datasets)

    @staticmethod
    def _keyword_route(user_query: str, datasets: List[Dict]) -> Dict:
        q_tokens = _tokenise(user_query) - _STOPWORDS
        scores: Dict[str, float] = {}
        for d in datasets:
            meta_tokens = _tokenise(f"{d['name']} {d['description']}")
            scores[d['id']] = len(q_tokens & meta_tokens)
        best = max(scores, key=scores.get)
        logger.info(f'sap_router dataset={best} tier=keyword score={scores[best]}')
        return {'dataset_id': best, 'tier': 'keyword',
                'reason': f'keyword overlap score={scores[best]}'}
