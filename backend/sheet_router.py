"""
Phase 3: Two-tier sheet router.

Tier 1 — zero-token keyword scoring (always runs first).
Tier 2 — tiny LLM call with sheet index only (no row data) when Tier 1 is ambiguous.
"""

import logging
import json
import re
from typing import Any

# Module-level import so tests can patch 'sheet_router.create_chat_completion'
try:
    from ai_orchestrator import create_chat_completion
except ImportError:
    create_chat_completion = None  # type: ignore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Whole-file intent detection.
# A summary VERB alone signals whole-file intent; bare scope words like
# 'all'/'every'/'across' only count when paired with a file-level noun —
# otherwise "give me all the key matters of Ajay team" wrongly routes to
# the whole-file summary path and answers from metadata instead of rows.
# ---------------------------------------------------------------------------
_SUMMARY_VERBS = {'summary', 'summaries', 'summarize', 'summarise',
                  'overview', 'overall'}
_SCOPE_TOKENS = {'whole', 'entire', 'all', 'every', 'across', 'each'}
_FILE_NOUNS = {'file', 'files', 'workbook', 'spreadsheet', 'document',
               'excel', 'sheet', 'sheets', 'tab', 'tabs', 'page', 'pages',
               'pagewise', 'xlsx', 'xls'}

# Generic words excluded from cell-value matching (they appear in every sheet)
_STOPWORDS = {'the', 'and', 'for', 'with', 'from', 'this', 'that', 'are',
              'was', 'were', 'what', 'which', 'give', 'show', 'list', 'tell',
              'get', 'of', 'in', 'to', 'me', 'my', 'please', 'their', 'there',
              'is', 'it', 'on', 'at', 'by', 'an', 'as', 'do', 'does', 'has',
              'have', 'can', 'you', 'about'}

# ---------------------------------------------------------------------------
# Tier-1 confidence threshold
# A sheet is chosen if its normalised score beats second place by this margin.
# ---------------------------------------------------------------------------
_TIER1_WIN_MARGIN = 0.15
_TIER1_MIN_SCORE = 0.05   # below this no keyword signal at all

# A sheet with this raw score AND margin wins even against whole-file wording
_STRONG_SHEET_SCORE = 4.0
_STRONG_SHEET_MARGIN = 1.5

# Only scan cell values of small (qualitative) sheets — names like 'Ajay team'
# live in cells, not headers, so header matching alone can never route them.
_VALUE_SCAN_MAX_CHARS = 4000


def _tokenise(text: str) -> set[str]:
    """Lowercase alphanumeric tokens (length ≥ 2) plus naive singulars,
    so 'matters' in a question still matches a 'Key matter' column."""
    toks = {w for w in re.findall(r'[a-z0-9]{2,}', text.lower())}
    toks |= {t[:-1] for t in toks if t.endswith('s') and len(t) >= 4}
    return toks


def _score_sheet(question_tokens: set[str], sheet_name: str,
                 columns: list[str], role: str) -> float:
    """Return a raw keyword overlap score for one sheet."""
    score = 0.0

    # sheet name tokens  (weight 1.0)
    name_tokens = _tokenise(sheet_name)
    score += len(question_tokens & name_tokens) * 1.0

    # column header tokens  (weight 2.0 — highest as per spec)
    col_tokens: set[str] = set()
    for col in columns:
        col_tokens |= _tokenise(str(col))
    score += len(question_tokens & col_tokens) * 2.0

    # role bonus  (weight 0.5)
    if role and _tokenise(role) & question_tokens:
        score += 0.5

    return score


def route_question(question: str, doc: dict, provider_key: str = 'auto') -> dict:
    """
    Returns:
        {
            "sheets": [<name>, ...],   # or ["__ALL__"]
            "confidence": float,
            "tier": "keyword" | "llm" | "fallback",
            "reason": str,
        }
    """
    sheet_names: list[str] = doc.get('sheet_names') or []
    if not sheet_names:
        return {"sheets": ["__ALL__"], "confidence": 0.0,
                "tier": "fallback", "reason": "no sheet list in doc"}

    q_tokens = _tokenise(question)
    q_content = q_tokens - _STOPWORDS - _SUMMARY_VERBS - _SCOPE_TOKENS - _FILE_NOUNS

    # --- Tier 1: keyword scoring (computed FIRST so whole-file wording can
    # be overruled by a strong sheet-specific signal) ----------------------
    profile: dict = doc.get('profile') or {}
    roles: dict = doc.get('sheet_roles') or {}
    parsed_sheets: dict = doc.get('parsed_sheets') or {}

    scores: dict[str, float] = {}
    for sn in sheet_names:
        sheet_profile = profile.get(sn, {})
        col_objs = sheet_profile.get('columns', [])
        cols = [c['name'] for c in col_objs if isinstance(c, dict) and c.get('name')]
        # also grab column names from parsed_sheets header line for sheets
        # whose profile may be absent on legacy snapshots
        if not cols and sn in parsed_sheets:
            section = parsed_sheets[sn]
            for line in section.split('\n'):
                if line.startswith('Columns:'):
                    raw = line[len('Columns:'):].strip()
                    cols = [c.strip() for c in raw.split(',') if c.strip()]
                    break
        role = roles.get(sn, '')
        score = _score_sheet(q_tokens, sn, cols, role)

        # Cell-value scoring for small qualitative sheets: entities like
        # 'Ajay team' exist only in cells, never in headers. Weight 1.5,
        # content tokens only (stopwords excluded).
        section = parsed_sheets.get(sn) or ''
        if section and len(section) <= _VALUE_SCAN_MAX_CHARS and q_content:
            score += len(q_content & _tokenise(section)) * 1.5

        scores[sn] = score

    sorted_sheets = sorted(scores.items(), key=lambda x: -x[1])
    top_name, top_score = sorted_sheets[0]
    second_score = sorted_sheets[1][1] if len(sorted_sheets) > 1 else 0.0
    total = sum(scores.values()) or 1.0
    normalised_top = top_score / total
    margin = top_score - second_score
    strong_sheet = (top_score >= _STRONG_SHEET_SCORE
                    and margin >= _STRONG_SHEET_MARGIN)

    # --- whole-file intent detection -------------------------------------
    verb_hit = bool(q_tokens & _SUMMARY_VERBS)
    scope_hit = bool((q_tokens & _SCOPE_TOKENS) and (q_tokens & _FILE_NOUNS))
    if (verb_hit or scope_hit) and not strong_sheet:
        whole_words = q_tokens & (_SUMMARY_VERBS | _SCOPE_TOKENS | _FILE_NOUNS)
        logger.info(f"router sheet=__ALL__ tier=keyword conf=1.0 "
                    f"reason=whole_file_tokens:{whole_words}")
        return {"sheets": ["__ALL__"], "confidence": 1.0,
                "tier": "keyword",
                "reason": f"whole-file intent detected ({', '.join(sorted(whole_words))})"}

    if not scores or top_score < _TIER1_MIN_SCORE:
        # no keyword signal — go straight to Tier 2
        return _tier2_route(question, doc, sheet_names, parsed_sheets, profile,
                            fallback_scores=scores, provider_key=provider_key)

    if strong_sheet or margin >= _TIER1_WIN_MARGIN * total or normalised_top >= 0.55:
        logger.info(f"router sheet={top_name} tier=keyword "
                    f"conf={normalised_top:.2f} margin={margin:.2f}")
        return {
            "sheets": [top_name],
            "confidence": round(normalised_top, 3),
            "tier": "keyword",
            "reason": f"keyword match (score={top_score:.1f}, margin={margin:.1f})",
        }

    # ambiguous — escalate to Tier 2
    return _tier2_route(question, doc, sheet_names, parsed_sheets, profile,
                        fallback_scores=scores, top_candidate=top_name,
                        provider_key=provider_key)


def _tier2_route(question: str, doc: dict, sheet_names: list[str],
                 parsed_sheets: dict, profile: dict,
                 fallback_scores: dict = None,
                 top_candidate: str = None,
                 provider_key: str = 'auto') -> dict:
    """Tiny LLM call — only sheet index (names + roles + column headers), NO row data."""
    try:
        if create_chat_completion is None:
            raise RuntimeError("create_chat_completion not available")

        # Build compact index  (≤ 1,500 tokens target)
        roles: dict = doc.get('sheet_roles') or {}
        lines = ["Sheet index:"]
        for sn in sheet_names:
            role = roles.get(sn, 'unknown')
            sheet_profile = profile.get(sn, {})
            col_objs = sheet_profile.get('columns', [])
            cols = [c['name'] for c in col_objs
                    if isinstance(c, dict) and c.get('name')][:15]
            # fallback to parsed_sheets header line
            if not cols and sn in parsed_sheets:
                for line in parsed_sheets[sn].split('\n'):
                    if line.startswith('Columns:'):
                        cols = [c.strip() for c in
                                line[len('Columns:'):].split(',') if c.strip()][:15]
                        break
            cols_str = ', '.join(cols) if cols else '(no columns)'
            # One sample data line so entity names living in cells (not
            # headers) are visible to the routing LLM, e.g. 'Ajay team'.
            sample = ''
            section = parsed_sheets.get(sn) or ''
            if section:
                for dline in section.split('\n')[1:8]:
                    dline = dline.strip()
                    if (dline and not dline.startswith('Columns:')
                            and not dline.startswith('===')
                            and dline.replace(',', '').strip()):
                        sample = dline[:90]
                        break
            entry = f"  [{sn}] role={role} cols={cols_str}"
            if sample:
                entry += f" sample={sample}"
            lines.append(entry)

        index_text = '\n'.join(lines)

        prompt = (
            f"You are a routing assistant. Given a user question and a sheet index, "
            f"output ONLY valid JSON: {{\"sheets\": [\"<sheet_name>\"]}} — one sheet name "
            f"from the index, or [\"__ALL__\"] for whole-file questions. No explanation.\n\n"
            f"Question: {question}\n\n"
            f"{index_text}"
        )

        messages = [{"role": "user", "content": prompt}]
        resp = create_chat_completion(messages, max_tokens=60, provider_key=provider_key)
        raw = (resp.choices[0].message.content or '').strip()

        # Parse JSON defensively
        m = re.search(r'\{.*?\}', raw, re.DOTALL)
        if m:
            parsed = json.loads(m.group(0))
            sheets = parsed.get('sheets', [])
            if isinstance(sheets, list) and sheets:
                valid = [s for s in sheets if s == '__ALL__' or s in sheet_names]
                if valid:
                    logger.info(f"router sheet={valid[0]} tier=llm conf=0.7")
                    return {
                        "sheets": valid,
                        "confidence": 0.7,
                        "tier": "llm",
                        "reason": f"LLM routing choice (raw={raw[:80]})",
                    }
    except Exception as e:
        logger.warning(f"Tier-2 router LLM call failed: {e}")

    # Fallback to top keyword candidate or first sheet
    fallback = top_candidate or (
        max(fallback_scores, key=lambda k: fallback_scores[k])
        if fallback_scores else (sheet_names[0] if sheet_names else '__ALL__')
    )
    logger.info(f"router sheet={fallback} tier=fallback conf=0.3")
    return {
        "sheets": [fallback],
        "confidence": 0.3,
        "tier": "fallback",
        "reason": "Tier-1 ambiguous; Tier-2 LLM failed — using best keyword match",
    }
