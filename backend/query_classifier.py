"""
Phase 1a — Query-complexity routing (Pearl Pro).

Classifies each incoming user query into one of three types BEFORE the
active-sheet scoping in _enrich_doc applies, so routing decisions are made
on raw user intent rather than on whatever sheet happens to be in view.

  'single_hop'  Factual question about the currently active sheet.
                Active-sheet scoping applies; normal pipeline runs.

  'multi_hop'   Reasoning across multiple sheets explicitly requested.
                Active-sheet scoping is bypassed; full-workbook context used.

  'summary'     Broad summarize/analyze-everything request about the workbook.
                Routes to Phase 4 map-reduce regardless of active sheet.

Implementation: fast regex match, no LLM call. Uses the user's own words
as ground truth — published Adaptive-RAG results show 85%+ accuracy for a
three-way split like this at negligible added latency (arXiv 2604.03455).
"""
import re
from typing import Optional

# ── Whole-workbook summary / analysis ────────────────────────────────────────
# Routes to Phase 4 map-reduce; ignores the active-sheet scope entirely since
# the user is explicitly asking about the full workbook, not the current view.
_SUMMARY_RE = re.compile(
    r'\b('
    r'summar\w+'                                                # summarize/summarise/summary
    r'|overview'
    r'|whole\s+(?:workbook|file|document|spreadsheet)'
    r'|entire\s+(?:workbook|file|document|spreadsheet)'
    r'|all\s+(?:the\s+)?(?:sheet|tab)s?'
    r'|every\s+(?:sheet|tab)'
    r'|full\s+(?:workbook|report|analysis|breakdown)'
    r'|complete\s+(?:overview|summary|report|analysis)'
    r'|executive\s+(?:summary|overview)'
    r'|key\s+(?:finding|insight|takeaway)s?\s*(?:across|from\s+all)'
    r'|what\s+(?:does\s+this|is\s+in\s+this)\s+(?:workbook|file|spreadsheet)'
    r'|high.?level\s+(?:overview|summary|view)'
    r'|tell\s+me\s+(?:about|everything\s+about)\s+(?:this|the)\s+'
    r'(?:workbook|file|spreadsheet|document)'
    r'|analyze\s+(?:the\s+)?(?:whole|entire|full)\s+(?:workbook|file|document|spreadsheet)'
    r'|analyse\s+(?:the\s+)?(?:whole|entire|full)\s+(?:workbook|file|document|spreadsheet)'
    r')\b',
    re.IGNORECASE,
)

# ── Cross-sheet multi-hop ─────────────────────────────────────────────────────
# Active-sheet scoping bypassed; full-workbook context fed to the LLM so it
# can reason across sheets without being artificially constrained.
_MULTI_HOP_RE = re.compile(
    r'\b('
    r'across\s+(?:all\s+)?(?:sheet|tab)s?'
    r'|across\s+the\s+workbook'
    r'|between\s+(?:sheet|tab)s?'
    r'|compare\s+(?:sheet|tab)s?'
    r'|in\s+(?:other|another|different)\s+(?:sheet|tab)'
    r'|from\s+(?:another|different|the\s+other)\s+(?:sheet|tab)'
    r'|workbook.?wide'
    r'|cross.?sheet'
    r'|join\s+(?:sheet|tab)s?'
    r'|multiple\s+sheets?'
    r')\b',
    re.IGNORECASE,
)


def classify_query(user_query: str, active_sheet: Optional[str] = None) -> str:
    """
    Returns 'single_hop', 'multi_hop', or 'summary'.

    Parameters
    ----------
    user_query   The raw user message, un-preprocessed.
    active_sheet The sheet name currently in view in the preview panel, or None
                 if no specific sheet is selected.  Passed here so future
                 versions can use it for confidence boosting (e.g. if the user
                 references the active sheet by name, bias toward single_hop).

    Routing contract
    ----------------
    'summary'    → _map_reduce_analysis() in services.py (Phase 4).
                   The active-sheet scope is irrelevant for whole-workbook
                   requests — don't let a stray open tab narrow the answer.
    'multi_hop'  → procure_agent's normal LLM path with FULL workbook context
                   (full_profile / full_statistics / full_unified_schema from
                   _enrich_doc).  Active-sheet scoping intentionally bypassed.
    'single_hop' → procure_agent's normal LLM path with active-sheet scoping.
                   This is the common case — scoping keeps context small and
                   answers specific.
    """
    if _SUMMARY_RE.search(user_query):
        return 'summary'
    if _MULTI_HOP_RE.search(user_query):
        return 'multi_hop'
    return 'single_hop'
