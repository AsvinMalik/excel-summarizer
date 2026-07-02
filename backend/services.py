import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_orchestrator import create_chat_completion
from data_profiler import format_profile_block, format_breakdowns_block
from query_engine import load_all_sheets, execute_query_spec
from grounding_verifier import collect_known_numeric_values, find_unverifiable_numbers, find_unverifiable_entities
from sheet_orchestrator import format_relationships_block
from schema_mapper import format_schema_context_block
from data_validator import format_validation_block
from statistical_analyzer import format_statistics_block
from viz_recommender import (
    recommend_for_query_result,
    recommend_for_workbook,
    format_viz_hint,
    format_viz_context_block,
)

BASE_PROMPT_PATH = os.path.join(os.path.dirname(__file__), '..', 'agent_system_prompt.txt')


def load_system_prompt() -> str:
    with open(BASE_PROMPT_PATH, 'r', encoding='utf-8') as f:
        return f.read()


def build_document_context_block(document_context: dict = None) -> str:
    active_document = (document_context or {}).get('active_document')
    documents = (document_context or {}).get('documents') or []
    active_doc_id = active_document.get('doc_id') if active_document else None
    if not active_document and not documents:
        return ''

    context_block = '\n\n[ACTIVE DOCUMENTS IN SESSION]\n'
    for doc in documents:
        marker = ' (currently viewing)' if active_doc_id and doc.get('doc_id') == active_doc_id else ''
        context_block += f"\n- {doc.get('name', 'Unknown')}{marker}: type={doc.get('type', 'unknown')}, status={doc.get('status', 'unknown')}\n"
        if doc.get('data_preview'):
            sheet_names = doc.get('sheet_names') or []
            if len(sheet_names) > 1:
                context_block += f"  Sheets ({len(sheet_names)}): {', '.join(sheet_names)}\n"
            else:
                context_block += f"  Columns: {', '.join(doc.get('columns') or [])}\n"
            context_block += (
                f"  Row count: {doc.get('row_count', 'unknown')}\n"
                f"  Data sample (CSV{', truncated' if doc.get('data_preview_truncated') else ''}), grouped by sheet below:\n{doc['data_preview']}\n"
            )
            profile_text = format_profile_block(doc.get('profile'))
            if profile_text:
                context_block += (
                    "  [REAL COMPUTED STATISTICS — exact pandas-computed sum/mean/min/max per numeric "
                    "column, and unique-value counts for text columns, plus null/duplicate counts. These "
                    "are verified correct. For any total, sum, average, or count claim, cite these exact "
                    "numbers instead of adding up values yourself from the sample above:\n"
                    f"{profile_text}\n"
                )
            # Per-sheet breakdowns, not just a single flattened block — a multi-sheet
            # workbook's category breakdowns must stay attributed to the right sheet.
            all_breakdowns_text = []
            for sheet_name, sheet_profile in (doc.get('profile') or {}).items():
                sheet_breakdown_text = format_breakdowns_block(sheet_profile.get('breakdowns'))
                if sheet_breakdown_text:
                    all_breakdowns_text.append(f'    Sheet "{sheet_name}":\n{sheet_breakdown_text}')
            if all_breakdowns_text:
                context_block += (
                    "  [CATEGORY BREAKDOWNS — exact pandas-computed sum/mean of each numeric column, "
                    "grouped by each low-cardinality text column (e.g. spend by vendor, spend by region). "
                    "These are pre-computed and verified — when a narrative answer needs a per-category "
                    "figure (e.g. \"X's spend in region Y\"), copy it directly from here rather than "
                    "deriving it yourself from individual rows:\n"
                    + "\n".join(all_breakdowns_text) + "\n"
                )

        schema_context_text = format_schema_context_block(doc.get('schema_context'))
        if schema_context_text:
            context_block += "  " + schema_context_text.replace("\n", "\n  ") + "\n"

        relationships_text = format_relationships_block(doc.get('unified_schema'))
        if relationships_text:
            context_block += "  " + relationships_text.replace("\n", "\n  ") + "\n"

        validation_text = format_validation_block(doc.get('validation'))
        if validation_text:
            context_block += "  " + validation_text.replace("\n", "\n  ") + "\n"

        statistics_text = format_statistics_block(doc.get('statistics'))
        if statistics_text:
            context_block += "  " + statistics_text.replace("\n", "\n  ") + "\n"

        # Viz recommendations from workbook structure (profile-only, no DataFrame needed)
        profile = doc.get('profile') or {}
        if profile:
            viz_suggestions = recommend_for_workbook(None, profile)
            viz_block = format_viz_context_block(viz_suggestions)
            if viz_block:
                context_block += "  " + viz_block.replace("\n", "\n  ") + "\n"

    return context_block


_KNOWN_VALUES_CACHE: Dict[str, set] = {}


def _collect_known_values_for_context(document_context: dict) -> set:
    """Merge real numeric values across every uploaded document in this session —
    a narrative answer could cite a figure from any of them, not just the active
    one. Cached per file_path within a process lifetime since the underlying file
    on disk doesn't change between requests for the same doc_id."""
    documents = (document_context or {}).get('documents') or []
    active_document = (document_context or {}).get('active_document')
    all_docs = list(documents)
    if active_document and active_document.get('doc_id') not in {d.get('doc_id') for d in all_docs}:
        all_docs.append(active_document)

    known: set = set()
    for doc in all_docs:
        file_path = doc.get('file_path') if doc else None
        if not file_path:
            continue
        if file_path in _KNOWN_VALUES_CACHE:
            known |= _KNOWN_VALUES_CACHE[file_path]
            continue
        try:
            all_sheets = load_all_sheets(file_path)
            values = collect_known_numeric_values(all_sheets)
        except Exception:
            continue
        _KNOWN_VALUES_CACHE[file_path] = values
        known |= values
    return known


# Structural questions about a document's shape (sheet count, sheet names, row count)
# have one objectively correct answer that we already know exactly from parsing the
# file. Answering these directly — instead of asking an LLM to "count" from a text
# preview — is instant, free, and can never hallucinate, regardless of which AI
# provider/model is active. Covers common typos (e.g. "sdheets") since the keyword
# match is substring-based, not exact-word.
_SHEET_KEYWORDS = ('sheet', 'sdheet', 'shdeet', 'tab', 'worksheet')
_COUNT_KEYWORDS = ('how many', 'number of', 'count of', 'total number')
_NAME_KEYWORDS = ('name', 'list', 'which', 'what are')
_ROW_KEYWORDS = ('how many row', 'number of row', 'row count', 'total row')


_STRUCTURAL_QUERY_MAX_CHARS = 100  # genuine structural questions are always short; long
                                    # instructional prompts (e.g. quick-action templates)
                                    # must never trigger this, even if they happen to
                                    # contain a stray word like "list" or "data sheet"


def _try_answer_structural_question(user_query: str, document_context: dict = None) -> Optional[str]:
    if len(user_query) > _STRUCTURAL_QUERY_MAX_CHARS:
        return None

    query_lower = user_query.lower()
    documents = (document_context or {}).get('documents') or []
    active_document = (document_context or {}).get('active_document')
    target_docs = [d for d in ([active_document] if active_document else documents) if d]

    if not target_docs:
        return None

    mentions_sheets = any(k in query_lower for k in _SHEET_KEYWORDS)
    asks_count = any(k in query_lower for k in _COUNT_KEYWORDS)
    asks_names = mentions_sheets and any(k in query_lower for k in _NAME_KEYWORDS)
    asks_rows = any(k in query_lower for k in _ROW_KEYWORDS)

    if not ((asks_count and mentions_sheets) or asks_names or asks_rows):
        return None

    lines = []
    for doc in target_docs:
        name = doc.get('name', 'Unknown')
        sheet_names = doc.get('sheet_names')
        row_count = doc.get('row_count')

        # row_count is only ever None when this document was never actually parsed in
        # the current backend session (e.g. the server restarted since it was uploaded,
        # wiping the in-memory store) — never assert "single-sheet" in that case, since
        # we genuinely don't know. A real single-sheet file always has sheet_names=[one
        # name] once parsed, since pandas returns at least one sheet on success.
        if row_count is None:
            lines.append(f"I don't have parsed data for **{name}** right now — please re-upload it and ask again.")
            continue

        if asks_rows and not (asks_count and mentions_sheets) and not asks_names:
            lines.append(f"**{name}** has **{row_count} rows** total across all sheets.")
            continue

        if sheet_names:
            lines.append(f"**{name}** has **{len(sheet_names)} sheet(s)**: {', '.join(sheet_names)}. ({row_count} rows total.)")
        else:
            lines.append(f"**{name}** has **{row_count} rows**.")

    return '\n'.join(lines) if lines else None


# Action verbs + document-referencing nouns that, together with a completely empty
# document context, signal "analyze something" requests with nothing to analyze —
# the exact pattern that produced a fully fabricated report (fake workbook name, fake
# spend table) when a user cleared their last document and clicked a quick action.
# This is a last line of defense — the frontend's quick actions already refuse to
# send these prompts with zero documents — but a manually-typed request can still
# reach here, so it must never be allowed to invite fabrication either.
_DOC_ACTION_VERBS = ('summarize', 'extract', 'build', 'generate', 'create', 'analyze', 'analyse')
_DOC_NOUNS = ('document', 'file', 'spreadsheet', 'contract', 'report', 'rfq', 'data', 'sheet')


def _try_refuse_empty_document_request(user_query: str, document_context: dict = None) -> Optional[str]:
    documents = (document_context or {}).get('documents') or []
    active_document = (document_context or {}).get('active_document')
    if documents or active_document:
        return None  # real document context exists — let the AI handle it normally

    query_lower = user_query.lower()
    has_verb = any(v in query_lower for v in _DOC_ACTION_VERBS)
    has_noun = any(n in query_lower for n in _DOC_NOUNS)
    if has_verb and has_noun:
        return (
            'There\'s nothing uploaded yet for me to work from. Please upload a contract or '
            'spreadsheet first, then ask again — I won\'t generate a report, summary, or RFQ '
            'from data that doesn\'t exist.'
        )
    return None


# Quantitative/filtering/ranking questions ("total spend", "top 5 vendors", "vendors
# over $1M") can be answered with verified pandas execution instead of an LLM reading
# a text preview. Gate on keywords first so the extra spec-generation model call only
# fires for questions that actually look like data queries — a qualitative question
# like "summarize this contract" never pays that cost. Word-boundary regex, not plain
# substring match — a naive `'sum' in query` false-positives on "Summarize"/"summary".
_DATA_QUERY_GATE_RE = re.compile(
    r'\btotal\b|\bsum\b|\baverage\b|\bavg\b|\bmean\b|\bcount\b|\bhow many\b|\bhow much\b|'
    r'\btop\s+\d+\b|\bbottom\s+\d+\b|\bhighest\b|\blowest\b|\bmaximum\b|\bminimum\b|\bmax\b|\bmin\b|'
    r'\bgreater than\b|\bless than\b|\bmore than\b|\bover\b|\bunder\b|\babove\b|\bbelow\b|\bbetween\b|'
    r'\brank\b|\bgroup(?:ed)?\s+by\b|\bbreakdown\b|\bby region\b|\bby category\b',
    re.IGNORECASE,
)

# Weaker local models (Phi3) are inconsistent at filling every spec field correctly
# in one shot — e.g. dropping "sort" on a "top N" question, or inventing a spurious
# filter on a plain group-by question. Rather than trust the model's JSON blindly,
# re-derive the unambiguous parts directly from the question's literal phrasing and
# let those override the model's guess. Regex on the user's own words can't
# hallucinate the way free-text generation can.
_TOP_N_RE = re.compile(r'\btop\s+(\d+)\b', re.IGNORECASE)
_BOTTOM_N_RE = re.compile(r'\b(?:bottom|lowest)\s+(\d+)\b', re.IGNORECASE)
_GROUP_BY_RE = re.compile(r'\b(?:group(?:ed)?\s+by|broken\s+down\s+by|per)\s+([a-zA-Z][\w \-/]{1,40}?)(?:[?.,]|$)', re.IGNORECASE)
_BY_COLUMN_RE = re.compile(r'\bby\s+([a-zA-Z][\w \-/]{1,40}?)(?:[?.,]|$)', re.IGNORECASE)
_FILTER_KEYWORDS = ('over', 'above', 'under', 'below', 'greater', 'less', 'more than', 'at least', 'at most', 'between', '>', '<', '=')
_HAS_NUMBER_RE = re.compile(r'\d')
# "which vendor has the lowest spend" / "what is the most expensive item" — this wants
# a single ROW (the entity), not a bare aggregate number. Captures the superlative word
# and the term right after it (e.g. "lowest spend" -> direction=lowest, term=spend).
_SUPERLATIVE_ROW_RE = re.compile(
    r'\b(?:which|what|who)\b[^.?!]{0,40}?\b(highest|lowest|top|maximum|minimum|max|min|most|least|cheapest|most expensive)\b\s+([a-zA-Z][\w \-/]{1,30})',
    re.IGNORECASE,
)
_EXPLICIT_AGG_RE = re.compile(r'\btotal\b|\bsum\b|\baverage\b|\bcount\b|\bmean\b', re.IGNORECASE)
_LOW_DIRECTION_WORDS = {'lowest', 'minimum', 'min', 'least', 'cheapest'}


def _find_column_for_term(term: str, columns: list) -> Optional[str]:
    term = term.strip().lower()
    for col in columns:
        col_lower = col.lower()
        if term == col_lower or term in col_lower or col_lower in term:
            return col
    return None


def _apply_deterministic_overrides(user_query: str, spec: dict, columns: list, numeric_columns: list = None) -> dict:
    spec = dict(spec)
    query_lower = user_query.lower()
    numeric_columns = numeric_columns or columns

    top_match = _TOP_N_RE.search(user_query)
    bottom_match = _BOTTOM_N_RE.search(user_query)
    group_match = _GROUP_BY_RE.search(user_query)

    if group_match:
        # Force this, don't just fill a gap — a model can emit a confident but WRONG
        # group_by (e.g. it left it null half the time, but the other half it guessed
        # something other than the literal "grouped by X" target). The regex match on
        # the user's own words is a stronger signal than either guess.
        found = _find_column_for_term(group_match.group(1), columns)
        if found:
            spec['group_by'] = found

    # Weak models frequently drop "column" for ranking questions ("top 3 vendors BY
    # Annual Spend") even when told to keep it — re-derive it from the literal "by X"
    # phrase in the question whenever the model left it null.
    if not spec.get('column'):
        by_match = _BY_COLUMN_RE.search(user_query)
        if by_match:
            found = _find_column_for_term(by_match.group(1), numeric_columns)
            if found:
                spec['column'] = found

    # Explicit aggregation-verb keywords are an unambiguous, stronger signal than the
    # model's own "operation" guess — seen in testing: "total spend grouped by Region"
    # sometimes came back as operation:"count" instead of "sum". Force it whenever the
    # question contains one of these words, except when ranking (top/bottom N) language
    # is also present, where "operation" must stay null (handled in the branch below).
    is_ranking_language = bool(top_match or bottom_match)
    if not is_ranking_language:
        if re.search(r'\btotal\b|\bsum\b', query_lower):
            spec['operation'] = 'sum'
        elif re.search(r'\baverage\b|\bavg\b|\bmean\b', query_lower):
            spec['operation'] = 'mean'
        elif re.search(r'\bcount\b|\bhow many\b', query_lower):
            spec['operation'] = 'count'

    # A model occasionally picks the SAME column for both "column" and "group_by" (e.g.
    # grouping "Region" sums by "Region" itself), or picks a non-numeric column for a
    # sum/mean/min/max — both silently produce all-zero/NaN results instead of an error.
    # If there's exactly one real numeric column in the sheet, that's almost always what
    # was actually meant; force it rather than let a wrong column through unnoticed.
    needs_numeric_column = spec.get('operation') in ('sum', 'mean', 'min', 'max', 'median')
    column_invalid = spec.get('column') and (spec['column'] not in numeric_columns or spec['column'] == spec.get('group_by'))
    if (needs_numeric_column and column_invalid) or (needs_numeric_column and not spec.get('column')):
        if len(numeric_columns) == 1:
            spec['column'] = numeric_columns[0]
        else:
            by_match = _BY_COLUMN_RE.search(user_query)
            found = _find_column_for_term(by_match.group(1), numeric_columns) if by_match else None
            if found:
                spec['column'] = found

    if top_match:
        # The regex match on the user's literal words is a stronger signal than the
        # model's own sort/limit guess — always override, don't just fill gaps. Seen
        # in testing: a model asked for "bottom 2" still emitted sort:"desc".
        spec['limit'] = int(top_match.group(1))
        spec['sort'] = 'desc'
        if not spec.get('group_by'):
            # Plain "top N <rows> by <column>" ranks individual rows, not an aggregate —
            # force the rows/sort/limit path even if the model guessed an operation.
            spec['operation'] = None
    elif bottom_match:
        spec['limit'] = int(bottom_match.group(1))
        spec['sort'] = 'asc'
        if not spec.get('group_by'):
            spec['operation'] = None
    else:
        superlative_match = _SUPERLATIVE_ROW_RE.search(user_query)
        if superlative_match and not _EXPLICIT_AGG_RE.search(query_lower) and not spec.get('group_by'):
            found = _find_column_for_term(superlative_match.group(2), numeric_columns)
            if found:
                spec['column'] = found
            spec['operation'] = None
            spec['sort'] = 'asc' if superlative_match.group(1).lower() in _LOW_DIRECTION_WORDS else 'desc'
            spec['limit'] = 1

    # Only trust the model's filters if the question actually contains comparison
    # language + a number — otherwise a stray filter on a plain aggregation/group-by
    # question silently zeroes out every row.
    has_filter_language = any(k in query_lower for k in _FILTER_KEYWORDS) and bool(_HAS_NUMBER_RE.search(query_lower))
    if not has_filter_language and spec.get('filters'):
        spec['filters'] = []

    return spec


def _try_build_spec_from_regex_only(user_query: str, sheet_column_map: dict, numeric_sheet_column_map: dict) -> Optional[dict]:
    """Fallback for when the LLM's own spec call fails or comes back unanswerable —
    seen intermittently in testing even on an otherwise-clear "top N by column"
    question (weak-model non-determinism). For the unambiguous top-N/bottom-N-by-
    column shape, the regex layer alone has everything needed: no LLM judgment call
    required, so it can't fail the way free-text generation can. Only handles the
    single-sheet case — multi-sheet ambiguity genuinely does need a model to pick."""
    if len(sheet_column_map) != 1:
        return None
    sheet_name = next(iter(sheet_column_map))
    numeric_columns = numeric_sheet_column_map.get(sheet_name, [])

    top_match = _TOP_N_RE.search(user_query)
    bottom_match = _BOTTOM_N_RE.search(user_query)
    if not (top_match or bottom_match):
        return None

    by_match = _BY_COLUMN_RE.search(user_query)
    column = _find_column_for_term(by_match.group(1), numeric_columns) if by_match else None
    if not column and len(numeric_columns) == 1:
        column = numeric_columns[0]
    if not column:
        return None

    return {
        'answerable': True, 'sheet': sheet_name, 'column': column, 'operation': None,
        'group_by': None, 'filters': [], 'sort': None, 'limit': None,
    }


def _format_query_result(spec: dict, result: dict) -> str:
    join_sheet = (spec.get('join') or {}).get('with_sheet')
    sheet = f'{spec.get("sheet", "Unknown")} + {join_sheet}' if join_sheet else spec.get('sheet', 'Unknown')

    if result['type'] == 'scalar':
        op_label = {'sum': 'Total', 'mean': 'Average', 'count': 'Count', 'min': 'Minimum', 'max': 'Maximum', 'median': 'Median'}.get(result['operation'], result['operation'].title())
        value = result['value']
        value_text = f'{value:,.2f}' if isinstance(value, (int, float)) else str(value)
        scope_note = f"{result['matched_row_count']} matching row(s)" if spec.get('filters') else f"{result['matched_row_count']} row(s)"
        return (
            f'**{op_label} of "{result["column"]}"**: {value_text}\n\n'
            f'*Computed directly from the full dataset — {scope_note} in Sheet "{sheet}".*'
        )

    if result['type'] == 'grouped':
        rows = result['rows']
        if not rows:
            return f'No matching data found in Sheet "{sheet}" for that grouping.'
        group_col = result['group_by']
        value_col = result['value_col']
        value_header = 'Count' if result['operation'] == 'count' else f'{result["operation"].title()} of {result["column"]}'
        lines = [f'| {group_col} | {value_header} |', '|---|---|']
        for row in rows:
            val = row.get(value_col)
            val_text = f'{val:,.2f}' if isinstance(val, (int, float)) else str(val)
            lines.append(f'| {row.get(group_col)} | {val_text} |')
        lines.append('')
        lines.append(f'*{result["matched_row_count"]} matching row(s) in Sheet "{sheet}", computed directly from the full dataset.*')
        viz_rec = recommend_for_query_result('grouped', group_col, value_col, len(rows))
        viz_hint = format_viz_hint(viz_rec)
        if viz_hint:
            lines.append('')
            lines.append(viz_hint)
        return '\n'.join(lines)

    rows = result['rows']
    if not rows:
        return f'No rows in Sheet "{sheet}" matched that filter.'
    cols = result['columns']
    lines = ['| ' + ' | '.join(str(c) for c in cols) + ' |', '|' + '---|' * len(cols)]
    for row in rows:
        lines.append('| ' + ' | '.join(str(row.get(c, '')) for c in cols) + ' |')
    lines.append('')
    lines.append(f'*Showing {len(rows)} of {result["matched_row_count"]} matching row(s) in Sheet "{sheet}".*')
    return '\n'.join(lines)


def _try_answer_data_query(user_query: str, document_context: dict = None) -> Optional[str]:
    if not _DATA_QUERY_GATE_RE.search(user_query):
        return None

    documents = (document_context or {}).get('documents') or []
    active_document = (document_context or {}).get('active_document')
    target_docs = [
        d for d in ([active_document] if active_document else documents)
        if d and d.get('file_path') and d.get('profile')
    ]
    if not target_docs:
        return None
    doc = target_docs[0]

    sheet_column_map = {
        sheet_name: [c['name'] for c in sheet_profile.get('columns', [])]
        for sheet_name, sheet_profile in (doc.get('profile') or {}).items()
    }
    numeric_sheet_column_map = {
        sheet_name: [c['name'] for c in sheet_profile.get('columns', []) if c.get('data_type') == 'numeric']
        for sheet_name, sheet_profile in (doc.get('profile') or {}).items()
    }
    if not sheet_column_map:
        return None

    # Include cross-sheet relationships in the spec prompt when they exist — the LLM
    # can then generate a join spec instead of marking the question as unanswerable.
    unified_schema = doc.get('unified_schema') or {}
    relationships = unified_schema.get('relationships') or []
    relationships_hint = ''
    if relationships:
        rel_lines = ['Detected relationships between sheets (can be used for cross-sheet joins):']
        for r in relationships:
            rel_lines.append(
                f'  {r["from_sheet"]}.{r["from_col"]} → {r["to_sheet"]}.{r["to_col"]} '
                f'({r["type"]}, {int(r["confidence"] * 100)}% confidence)'
            )
        relationships_hint = '\n' + '\n'.join(rel_lines) + '\n'

    spec_prompt = (
        'Translate this data question into a structured query spec to be executed exactly with pandas. '
        'Do NOT attempt to answer the question yourself — only describe how to compute it.\n\n'
        f'User question: "{user_query}"\n\n'
        'Available sheets and their REAL column names (use these exact names, case-sensitive):\n'
        f'{json.dumps(sheet_column_map, indent=2)}\n'
        f'{relationships_hint}\n'
        'Return ONLY valid JSON (no markdown fences, no comments) with this exact shape:\n'
        '{"answerable": true|false, "sheet": "<primary sheet name>", '
        '"join": {"with_sheet": "<second sheet>", "on": [{"left": "<col in primary sheet>", "right": "<col in second sheet>"}]} or null, '
        '"column": "<exact numeric column name or null>", '
        '"operation": "sum"|"mean"|"count"|"min"|"max"|"median"|null, "group_by": "<exact column name or null>", '
        '"filters": [{"column": "<exact column name>", "op": ">"|">="|"<"|"<="|"=="|"!=", "value": <number or string>}], '
        '"sort": "asc"|"desc"|null, "limit": <int or null>}\n\n'
        'Five worked examples (column names below are illustrative — always substitute the REAL column names):\n'
        '1. "What is the total Spend?" -> single number:\n'
        '   {"answerable": true, "sheet": "Sheet1", "join": null, "column": "Spend", "operation": "sum", "group_by": null, '
        '"filters": [], "sort": null, "limit": null}\n'
        '2. "Show total spend grouped by Region" -> one aggregated number PER region:\n'
        '   {"answerable": true, "sheet": "Sheet1", "join": null, "column": "Spend", "operation": "sum", "group_by": "Region", '
        '"filters": [], "sort": null, "limit": null}\n'
        '3. "Top 3 vendors by spend" -> ranks individual rows, NOT an aggregation:\n'
        '   {"answerable": true, "sheet": "Sheet1", "join": null, "column": "Spend", "operation": null, "group_by": null, '
        '"filters": [], "sort": "desc", "limit": 3}\n'
        '4. "How many vendors have spend over 1,000,000?" -> count of matching rows:\n'
        '   {"answerable": true, "sheet": "Sheet1", "join": null, "column": null, "operation": "count", "group_by": null, '
        '"filters": [{"column": "Spend", "op": ">", "value": 1000000}], "sort": null, "limit": null}\n'
        '5. "Total invoice amount by vendor name" where invoices link to vendors via Vendor ID -> cross-sheet join:\n'
        '   {"answerable": true, "sheet": "Invoices", "join": {"with_sheet": "Vendors", "on": [{"left": "Vendor ID", "right": "Vendor ID"}]}, '
        '"column": "Invoice Amount", "operation": "sum", "group_by": "Vendor Name", '
        '"filters": [], "sort": null, "limit": null}\n\n'
        'Set "answerable" to false only if the question requires reading free-text/narrative content '
        'or references columns not in the sheet list above. For cross-sheet questions, use the "join" field '
        'with the detected relationships above rather than setting answerable=false. '
        'Never invent a sheet or column name that is not in the list above.'
    )

    try:
        # spec-generation always uses the default chain regardless of the caller's model_key —
        # this is a structured JSON task (not a user-facing answer) and accuracy matters more
        # than matching the user's preferred provider. Weak local models are unreliable here.
        response = create_chat_completion(
            [
                {'role': 'system', 'content': 'You translate data questions into structured pandas query specs. Output JSON only, nothing else.'},
                {'role': 'user', 'content': spec_prompt},
            ],
            max_tokens=400,
        )
        spec = _extract_json(response.choices[0].message.content)
    except Exception:
        spec = None

    if not isinstance(spec, dict) or not spec.get('answerable'):
        spec = _try_build_spec_from_regex_only(user_query, sheet_column_map, numeric_sheet_column_map)
        if not spec:
            return None

    sheet_columns = list(sheet_column_map.get(spec.get('sheet'), []))
    numeric_columns = list(numeric_sheet_column_map.get(spec.get('sheet'), []))

    # When a join is specified, the merged DataFrame will include columns from both
    # sheets — extend the column lists so deterministic overrides can correctly
    # resolve "group_by" and "column" references from the joined sheet too.
    join_spec = spec.get('join') or {}
    joined_sheet = join_spec.get('with_sheet')
    if joined_sheet:
        for col in sheet_column_map.get(joined_sheet, []):
            if col not in sheet_columns:
                sheet_columns.append(col)
        for col in numeric_sheet_column_map.get(joined_sheet, []):
            if col not in numeric_columns:
                numeric_columns.append(col)

    spec = _apply_deterministic_overrides(user_query, spec, sheet_columns, numeric_columns)

    try:
        all_sheets = load_all_sheets(doc['file_path'])
        result = execute_query_spec(all_sheets, spec)
    except Exception:
        # Covers QueryError (bad sheet/column from the spec) and any pandas failure.
        # Phase 3 contract: never surface a broken/partial answer AND never silently
        # drop to the prose path without telling it the engine failed.  Return a
        # sentinel dict so procure_agent can inject an honest-failure note.
        return {'_engine_failed': True}

    return _format_query_result(spec, result)


# ── Phase 4: Whole-workbook map-reduce analysis ───────────────────────────────

# Phase 2a: provider-aware chunk budgets for the map-reduce pipeline.
# Phi3 has a 4096-token window; Groq/Cerebras have 128k-131k token windows.
# Larger chunks → fewer LLM calls → faster and cheaper map-reduce.
_PROVIDER_CHUNK_BUDGETS: dict = {
    'phi3':        6_000,   # ~1 500 tokens — fits Phi3 with overhead
    'groq':       40_000,   # ~10 000 tokens — large chunks, few calls
    'cerebras':   40_000,   # same as Groq
    'openrouter': 12_000,   # conservative for free-tier models
    'gemini':     60_000,   # Gemini 1.5 Pro — very generous
    'openai':     16_000,   # GPT-4o-mini conservative
    'auto':       12_000,   # default for auto chain (safe for all providers)
}
_CHUNK_CHAR_BUDGET = _PROVIDER_CHUNK_BUDGETS['auto']  # backward-compat default

# Cap per-chunk summary length so the reduce step's input stays manageable
# even on a 30-sheet workbook.
_MAP_MAX_TOKENS = 600
_REDUCE_MAX_TOKENS = 2_000


def _build_sheet_content_block(sheet_name: str, sheet_profile: dict, sheet_stats: dict) -> str:
    """Build a compact content block describing one sheet for the map step."""
    cols = sheet_profile.get('columns', [])
    col_names = [c['name'] for c in cols if isinstance(c, dict) and c.get('name')]
    row_count = sheet_profile.get('row_count', 0)

    parts = [f'Sheet: "{sheet_name}" | {row_count} rows × {len(cols)} columns']

    if col_names:
        shown = col_names[:25]
        suffix = f' … (+{len(col_names) - 25} more)' if len(col_names) > 25 else ''
        parts.append(f'Columns: {", ".join(shown)}{suffix}')

    # Numeric column summaries from the pre-computed statistics block
    stats_text = format_statistics_block(sheet_stats or {})
    if stats_text:
        parts.append(stats_text[:1_200])  # cap per-sheet stats contribution

    # Category breakdowns from the profile (e.g. spend by vendor)
    bd_text = format_breakdowns_block(sheet_profile.get('breakdowns'))
    if bd_text:
        parts.append(bd_text[:800])

    return '\n'.join(parts)


def _chunk_sheets(sheet_blocks: dict, budget: int = _CHUNK_CHAR_BUDGET) -> list:
    """Group sheets into chunks whose combined content fits the given budget.

    Chunks by actual content size (not sheet count) so that a 392-row × 78-col
    sheet and a 2-row × 5-col sheet don't end up in the same group just because
    they're adjacent in the workbook.  Per the MD: equal-count splitting badly
    unbalances complexity when sheet sizes vary by two orders of magnitude.
    """
    chunks: list = []
    current: list = []
    current_size = 0

    for sheet_name, block in sheet_blocks.items():
        block_size = len(block)
        if current and current_size + block_size > budget:
            chunks.append(current)
            current = [sheet_name]
            current_size = block_size
        else:
            current.append(sheet_name)
            current_size += block_size

    if current:
        chunks.append(current)
    return chunks


def _map_reduce_analysis(
    user_query: str,
    document_context: Optional[dict],
    provider_key: str = 'auto',
) -> dict:
    """Phase 4: whole-workbook map-reduce analysis.

    Algorithm
    ---------
    1. Collect all sheets from the FULL (unscoped) profile + statistics.
    2. Build a per-sheet content block for each sheet (columns + stats + breakdowns).
    3. Chunk sheets by content size against _CHUNK_CHAR_BUDGET so each map call
       fits within the active provider's context window.
    4. MAP: call the LLM once per chunk to produce a partial summary.
    5. REDUCE: combine partial summaries (with cross-sheet relationship context)
       into a final structured answer.

    For large workbooks (many chunks), applies hierarchical merging: pairs of
    partial summaries are merged in layers rather than combining all at once in
    one final step — prevents cross-sheet relationships from being dropped at the
    reduce boundary.

    Failure contract (Phase 3): every exit path either produces a grounded
    answer or explicitly states what couldn't be computed, never a silent guess.
    """
    # ── Locate the active document ───────────────────────────────────────────
    active_document = (document_context or {}).get('active_document')
    documents = (document_context or {}).get('documents') or []
    candidates = [
        d for d in ([active_document] if active_document else documents)
        if d and d.get('file_path')
    ]
    if not candidates:
        return _agent_response(
            'No document is loaded. Upload a spreadsheet first, then ask again.',
            model='map-reduce',
        )

    doc = candidates[0]

    # Use full (unscoped) profile — active-sheet scope is irrelevant here
    profile = doc.get('full_profile') or doc.get('profile') or {}
    statistics = doc.get('full_statistics') or doc.get('statistics') or {}
    unified_schema = doc.get('full_unified_schema') or doc.get('unified_schema') or {}

    if not profile:
        return _agent_response(
            'The workbook is still processing. Please try again in a moment.',
            model='map-reduce',
        )

    doc_name = doc.get('name', 'the workbook')

    # ── Build per-sheet content blocks ───────────────────────────────────────
    sheet_blocks: Dict[str, str] = {}
    for sheet_name, sheet_profile in profile.items():
        sheet_stats = statistics.get(sheet_name, {})
        sheet_blocks[sheet_name] = _build_sheet_content_block(
            sheet_name, sheet_profile, sheet_stats
        )

    all_sheet_names = list(sheet_blocks.keys())
    chunk_budget = _PROVIDER_CHUNK_BUDGETS.get(provider_key, _CHUNK_CHAR_BUDGET)
    chunks = _chunk_sheets(sheet_blocks, budget=chunk_budget)

    # ── Cross-sheet relationship context (for reduce step) ───────────────────
    relationships_text = format_relationships_block(unified_schema) or ''

    # ── MAP: one LLM call per chunk ──────────────────────────────────────────
    partial_summaries: list = []

    map_system = (
        'You are a precise data analyst summarizing part of a multi-sheet workbook. '
        'Only state facts that are directly visible in the sheet statistics shown. '
        'Never invent figures, column names, or sheet names that are not present.'
    )

    for i, chunk_sheets in enumerate(chunks):
        chunk_content = '\n\n'.join(sheet_blocks[s] for s in chunk_sheets)
        sheet_label = ', '.join(f'"{s}"' for s in chunk_sheets)

        map_prompt = (
            f'User question: "{user_query}"\n\n'
            f'You are analyzing sheet group {i + 1} of {len(chunks)} from "{doc_name}".\n\n'
            f'Sheet data:\n{chunk_content}\n\n'
            'Write a concise structured summary of what these sheets contain, what they track, '
            'and any key figures visible in the statistics. '
            'Use **bold** for key figures. Keep it under 4 short paragraphs. '
            'State only what the data above directly shows.'
        )

        try:
            resp = create_chat_completion(
                [
                    {'role': 'system', 'content': map_system},
                    {'role': 'user', 'content': map_prompt},
                ],
                max_tokens=_MAP_MAX_TOKENS,
                model_key=provider_key,
            )
            summary_text = resp.choices[0].message.content.strip()
        except Exception:
            summary_text = f'(Could not summarize this sheet group — data shown above.)'

        partial_summaries.append({
            'label': sheet_label,
            'sheets': chunk_sheets,
            'text': summary_text,
        })

    # ── REDUCE (hierarchical merging for large workbooks) ────────────────────
    # For workbooks with ≤4 chunks a flat reduce is fine.  For larger ones,
    # pair adjacent summaries and merge in layers so cross-chunk relationships
    # aren't dropped at the single reduce boundary.
    reduce_system = (
        'You synthesize workbook analysis summaries. '
        'Cite only figures and facts that appear in the partial summaries provided. '
        'Never invent new numbers or sheet names.'
    )

    def _merge_pair(a: dict, b: dict, step_label: str) -> dict:
        combined_label = f'{a["label"]} + {b["label"]}'
        merge_prompt = (
            f'Merge these two partial summaries into one cohesive summary.\n\n'
            f'Part A ({a["label"]}):\n{a["text"]}\n\n'
            f'Part B ({b["label"]}):\n{b["text"]}\n\n'
            'Produce a single merged summary. Preserve all key figures from both parts. '
            'Use **bold** for key figures. Keep it concise.'
        )
        try:
            resp = create_chat_completion(
                [
                    {'role': 'system', 'content': reduce_system},
                    {'role': 'user', 'content': merge_prompt},
                ],
                max_tokens=_MAP_MAX_TOKENS,
                model_key=provider_key,
            )
            merged_text = resp.choices[0].message.content.strip()
        except Exception:
            merged_text = f'{a["text"]}\n\n{b["text"]}'
        return {'label': combined_label, 'sheets': a['sheets'] + b['sheets'], 'text': merged_text}

    summaries = list(partial_summaries)  # copy

    if len(summaries) > 4:
        # Hierarchical merging: pair and merge in layers
        while len(summaries) > 4:
            merged: list = []
            for j in range(0, len(summaries) - 1, 2):
                merged.append(_merge_pair(summaries[j], summaries[j + 1], f'layer-merge-{j}'))
            if len(summaries) % 2 == 1:
                merged.append(summaries[-1])  # carry odd one forward
            summaries = merged

    # Final reduce: one call that sees all remaining summaries + relationships
    combined_text = '\n\n---\n\n'.join(
        f'**{s["label"]}**\n\n{s["text"]}' for s in summaries
    )

    reduce_prompt = (
        f'The following are structured summaries covering all {len(all_sheet_names)} sheets '
        f'in "{doc_name}".\n\n'
        f'User question: "{user_query}"\n\n'
        f'{combined_text}'
    )
    if relationships_text:
        reduce_prompt += f'\n\n{relationships_text}'
    reduce_prompt += (
        '\n\nWrite the final consolidated answer to the user\'s question. '
        'Use ## headers for major sections, bullet points for details, **bold** for key figures. '
        'Cover every sheet group. Mention cross-sheet relationships where they add context. '
        'Cite only figures that appear in the summaries above — never invent new numbers. '
        'End with a brief "## Key Takeaways" section.'
    )

    try:
        reduce_resp = create_chat_completion(
            [
                {'role': 'system', 'content': reduce_system},
                {'role': 'user', 'content': reduce_prompt},
            ],
            max_tokens=_REDUCE_MAX_TOKENS,
            model_key=provider_key,
        )
        final_text = reduce_resp.choices[0].message.content.strip()
    except Exception:
        # Graceful degradation: return partial summaries directly
        final_text = (
            f'## Workbook Overview: {doc_name}\n\n'
            + '\n\n'.join(f'**{s["label"]}**\n\n{s["text"]}' for s in partial_summaries)
        )

    chunk_note = f'{len(chunks)} chunk{"s" if len(chunks) != 1 else ""}, {len(all_sheet_names)} sheets'
    return _agent_response(final_text, model=f'map-reduce ({chunk_note})')


def _agent_response(text: str, model: str = 'model_a') -> dict:
    """Shared response envelope for procure_agent and map-reduce."""
    return {
        'timestamp': int(datetime.utcnow().timestamp()),
        'model': model,
        'content': [{'type': 'text', 'text': text}],
        'tool_calls': [],
    }


def _build_full_context(document_context: Optional[dict]) -> Optional[dict]:
    """Return a copy of document_context where the active document's profile,
    statistics, and unified_schema are swapped to their full (unscoped)
    versions.  Used for multi-hop queries that must bypass active-sheet scoping
    without re-reading the file or re-running the profiler."""
    if not document_context:
        return document_context
    active = document_context.get('active_document')
    if not active:
        return document_context

    full_active = {
        **active,
        'profile': active.get('full_profile') or active.get('profile'),
        'statistics': active.get('full_statistics') or active.get('statistics'),
        'unified_schema': active.get('full_unified_schema') or active.get('unified_schema'),
    }
    return {**document_context, 'active_document': full_active}


def procure_agent(user_query: str, document_context: dict = None, session_state: dict = None, model_key: str = 'model_a', provider_key: str = 'auto') -> dict:
    # MODEL_B: Pandas sandbox — LLM generates & executes code against real data.
    if model_key == 'model_b':
        from model_b_agent import model_b_agent
        return model_b_agent(user_query, document_context, session_state, provider_key=provider_key)

    # MODEL_C (Pearl Pro): always use the whole-workbook map-reduce pipeline
    # regardless of query phrasing. The user has explicitly asked for workbook-wide
    # synthesis — skip the query classifier and the active-sheet scope entirely.
    if model_key == 'model_c':
        return _map_reduce_analysis(user_query, document_context, provider_key)

    structural_answer = _try_answer_structural_question(user_query, document_context)
    if structural_answer:
        return _agent_response(structural_answer, model='deterministic')

    refusal = _try_refuse_empty_document_request(user_query, document_context)
    if refusal:
        return _agent_response(refusal, model='deterministic')

    # ── Phase 1a: Query-complexity routing (Pearl Pro) ───────────────────────
    # Classify BEFORE data_query_answer so a "summarize the whole workbook" request
    # goes directly to map-reduce, not through the spec engine (which can't cover 30
    # sheets) or the scoped-LLM path (which would only see the active sheet).
    from query_classifier import classify_query
    active_sheet_raw = (
        (document_context or {}).get('active_document', {}).get('active_sheet')
        if document_context else None
    )
    query_type = classify_query(user_query, active_sheet_raw)

    if query_type == 'summary':
        # Phase 4 map-reduce — ignores active-sheet scope entirely
        return _map_reduce_analysis(user_query, document_context, provider_key)

    # For multi-hop queries bypass active-sheet scoping: swap in full-workbook
    # profile/statistics/schema so the LLM can reason across all sheets.
    if query_type == 'multi_hop':
        document_context = _build_full_context(document_context)

    data_query_result = _try_answer_data_query(user_query, document_context)
    if isinstance(data_query_result, str):
        return _agent_response(data_query_result, model='deterministic-query-engine')
    # Sentinel: the query matched the data-query gate but execution failed.
    query_engine_failed = isinstance(data_query_result, dict) and data_query_result.get('_engine_failed')

    # Phase 5a: when the spec engine explicitly failed (not just "not a data query"),
    # try Model B (pandas sandbox) automatically before falling to the prose LLM.
    # Model B generates custom Python code, so it can handle queries the fixed spec
    # vocabulary cannot (complex aggregations, reshaping, ad-hoc filters).
    # If Model B also fails we fall through to prose with a combined failure note.
    model_b_fallback_failed = False
    if query_engine_failed:
        try:
            from model_b_agent import model_b_agent as _model_b
            mb_result = _model_b(user_query, document_context, session_state, provider_key=provider_key)
            # model_b_agent returns {'content': [{'type': 'text', 'text': ...}], ...}
            mb_content = (mb_result or {}).get('content') or []
            mb_text = mb_content[0].get('text', '') if mb_content else ''
            # Redirect responses (model_b_redirect) mean B can't handle it — fall through
            redirect = (mb_result or {}).get('model', '') == 'model_b_redirect'
            if mb_text and not redirect and 'failed' not in mb_text[:80].lower():
                return {**mb_result, 'model': 'model-b-auto-fallback'}
            model_b_fallback_failed = True
        except Exception:
            model_b_fallback_failed = True

    system_prompt = load_system_prompt()
    messages = [
        {'role': 'system', 'content': system_prompt}
    ]

    if session_state and 'conversation_history' in session_state:
        for turn in session_state['conversation_history'][-10:]:
            messages.append({'role': turn['role'], 'content': turn['content']})

    context_block = build_document_context_block(document_context)
    if context_block:
        messages.append({'role': 'system', 'content': context_block})

    active_sheet = (document_context or {}).get('active_document', {}).get('active_sheet') if document_context else None

    # For multi-hop we already expanded context — suppress the active-sheet note
    # so the LLM doesn't think it's limited to one sheet.
    if query_type == 'multi_hop':
        sheet_scope_note = (
            ' The user is asking a cross-sheet question. Full workbook context is provided — '
            'answer using data from whichever sheets are relevant.'
        )
    else:
        sheet_scope_note = (
            f' The user is currently previewing sheet "{active_sheet}" — only that sheet\'s '
            f'data is included in your context for this turn. If the user asks about data from '
            f'a different sheet by name, tell them to switch to that sheet in the preview panel '
            f'rather than answering from memory of a prior turn\'s different sheet.'
        ) if active_sheet else ''

    # Phase 3 / 5a honest-failure note: tell the LLM when both the spec engine and
    # the Model B sandbox failed, so it must be explicit rather than silently guessing.
    if query_engine_failed and model_b_fallback_failed:
        engine_failure_note = (
            ' NOTE: Both the deterministic query engine and the code-execution sandbox '
            'attempted to compute a direct answer to this question but failed (likely '
            'because the column or sheet referenced is not in the available schema). '
            'You MUST be explicit about what you can and cannot confirm — state '
            'specifically what data is missing or ambiguous rather than producing a '
            'plausible-sounding guess. If you cannot determine the answer reliably from '
            'the context provided, say so directly and suggest how the user could '
            'rephrase (e.g. by naming the exact column or sheet).'
        )
    elif query_engine_failed:
        engine_failure_note = (
            ' NOTE: The query engine attempted to compute a direct answer to this question '
            'from the data but failed (likely because the column or sheet referenced is not '
            'in the available schema). You MUST be explicit about what you can and cannot '
            'confirm — state specifically what data is missing or ambiguous rather than '
            'producing a plausible-sounding guess. If you cannot determine the answer '
            'reliably from the context provided, say so directly and suggest how the user '
            'could rephrase (e.g. by naming the exact column or sheet).'
        )
    else:
        engine_failure_note = ''

    messages.append({
        'role': 'system',
        'content': (
            'Reminder: format this reply in Markdown — use "## " headers, "- " bullet points, '
            '**bold** for key terms/figures, and tables for tabular data. Do not answer in a '
            'single unbroken paragraph if there is more than one distinct point. Never wrap the '
            'entire reply in a single ``` code fence — that renders unreadably in this UI; '
            'fences are only for short literal code/data snippets, not the whole answer. '
            'Also: never invent clause text, figures, or terms not present in the document data '
            'above. If the request doesn\'t fit the document type (e.g. clause extraction on a '
            'plain data spreadsheet with no contract language), say so directly instead of '
            'fabricating an answer. If you are unsure what the user means, ask ONE clarifying '
            'question and stop — do not also guess with fabricated numbers underneath. When the '
            'user refers to a sheet/page/tab, match it against the real sheet names listed above '
            '(a sheet named "13,14" is one sheet, not "page 13" and "page 14") — never invent a '
            'generic page-numbering scheme that doesn\'t match the real sheet names. When a '
            '[REAL COMPUTED STATISTICS] block is present for a sheet, treat those numbers as ground '
            'truth for any sum/total/average/count claim about that column — quote them directly '
            'rather than re-adding values from the CSV sample yourself, since manual arithmetic over '
            'a text preview is exactly how past answers got the scale of a number wrong.'
            + sheet_scope_note
            + engine_failure_note
        ),
    })
    messages.append({'role': 'user', 'content': user_query})

    response = create_chat_completion(messages, max_tokens=1200, model_key=provider_key)
    text = response.choices[0].message.content

    # Numeric grounding: for precise figure queries the LLM must cite real values.
    # Skip for qualitative/summary requests — the user wants narrative context, not
    # exact arithmetic, and a small model like phi3 can't reliably quote every figure
    # verbatim from a large context block. Blocking summaries wholesale is worse than
    # the occasional rounded figure in prose.
    _QUALITATIVE_RE = re.compile(
        r'\b(summar|overview|descri|explain|introduc|tell me about|what (is|are|does)|'
        r'highlight|outline|brief|report on|insights?|analys[ie]|key (point|finding|trend|takeaway))\b',
        re.IGNORECASE,
    )
    is_qualitative = bool(_QUALITATIVE_RE.search(user_query))

    known_values = _collect_known_values_for_context(document_context)
    if known_values and not is_qualitative:
        correction_messages = messages
        for retry_num in range(2):
            unverifiable = find_unverifiable_numbers(text, known_values)
            if not unverifiable:
                break
            correction_messages = correction_messages + [
                {'role': 'assistant', 'content': text},
                {'role': 'user', 'content': (
                    'Your previous answer cited these specific figures, but they don\'t match any real value '
                    'found in the document data provided: ' + ', '.join(f'{v:,.2f}' for v in unverifiable[:5])
                    + '. Real data IS available in the [REAL COMPUTED STATISTICS] and [CATEGORY BREAKDOWNS] '
                    'blocks above — rewrite your answer using THOSE exact numbers in place of the wrong ones. '
                    'Everything else about your previous answer was fine; keep it, just fix the incorrect '
                    'figures. Do not respond by refusing to cite any numbers at all — the real data is right '
                    'there in the context, use it normally.'
                )},
            ]
            retry_response = create_chat_completion(correction_messages, max_tokens=1200, model_key=provider_key)
            text = retry_response.choices[0].message.content
        else:
            if find_unverifiable_numbers(text, known_values):
                text = (
                    'I drafted an answer but one or more specific figures in it didn\'t match any real '
                    'value in your data, so I\'m not showing it rather than risk giving you a wrong number. '
                    'Try asking for a specific total, average, or ranking instead (e.g. "total spend", "top '
                    '5 vendors by spend") — those are computed directly from your data and always exact.'
                )

    # Phase 3: qualitative entity grounding — check for hallucinated proper nouns.
    # Applies only to qualitative (narrative) answers since numeric grounding already
    # covers exact-figure queries. Only triggers a correction if ≥ 2 quoted proper
    # names don't appear in the data preview, avoiding false positives from
    # incidental capitalization in otherwise correct prose.
    if is_qualitative:
        data_preview = (
            ((document_context or {}).get('active_document') or {}).get('data_preview') or ''
        )
        unverifiable_entities = find_unverifiable_entities(text, data_preview)
        if len(unverifiable_entities) >= 2:
            entity_list = ', '.join(f'"{e}"' for e in unverifiable_entities[:4])
            correction_messages = messages + [
                {'role': 'assistant', 'content': text},
                {'role': 'user', 'content': (
                    f'Your previous answer mentioned these names/entities: {entity_list}. '
                    'None of them appear in the document data I provided. Please rewrite your '
                    'answer using ONLY names, project identifiers, and entities that actually '
                    'appear in the data context above. If you cannot find a specific name in the '
                    'data, describe the concept without inventing an example name.'
                )},
            ]
            correction_resp = create_chat_completion(correction_messages, max_tokens=1200, model_key=provider_key)
            text = correction_resp.choices[0].message.content

    return {
        'timestamp': response.created,
        'model': response.model,
        'content': [{'type': 'text', 'text': text}],
        'tool_calls': [],
    }


def _extract_json(text: str) -> dict:
    cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Weaker local models sometimes add JS-style "// comment" trailing notes inside the
    # JSON, which isn't valid JSON. Strip those (but not "://" inside URLs) and retry.
    no_comments = re.sub(r'(?<!:)//[^\n"]*$', '', cleaned, flags=re.MULTILINE)
    try:
        return json.loads(no_comments)
    except json.JSONDecodeError:
        pass

    # Weaker local models occasionally mangle a two-character comparison operator value
    # like ">=" into invalid JSON such as "op": ">"="  (an extra quote splits the value).
    # Collapse that back into a single quoted token before the final parse attempts.
    operator_fixed = re.sub(r'"([<>])"\s*=\s*"', r'"\1="', no_comments)
    try:
        return json.loads(operator_fixed)
    except json.JSONDecodeError:
        pass

    # Last resort: grab the first balanced-looking {...} block in the text.
    match = re.search(r'\{.*\}', operator_fixed, re.DOTALL)
    if match:
        return json.loads(match.group(0))

    raise ValueError('Could not extract valid JSON from model response')


def generate_rfq(input_data: dict) -> dict:
    prompt = (
        'Create a professional RFQ document using the following details. '
        'Return ONLY valid JSON (no markdown code fences, no comments) with keys: executive_summary, '
        'scope_of_work, terms_and_conditions, evaluation_criteria, requested_info, legal_certifications, '
        'document_number, company_name, response_deadline. '
        '"executive_summary", "document_number", "company_name", "response_deadline" must be plain strings '
        '(never objects). "scope_of_work", "terms_and_conditions", "requested_info", "legal_certifications" '
        'must be arrays of strings. "evaluation_criteria" must be an object of category name to percentage string.'
    )
    body = f"{prompt}\n\nInput:\n{json.dumps(input_data, indent=2)}"
    response = create_chat_completion([{'role': 'system', 'content': load_system_prompt()}, {'role': 'user', 'content': body}], max_tokens=2000)
    text = response.choices[0].message.content

    try:
        parsed = _extract_json(text)
    except Exception:
        parsed = {
            'executive_summary': input_data.get('executive_summary') or 'Could not generate a structured RFQ draft — please review the fields manually.',
            'scope_of_work': input_data.get('scope_of_work', []),
            'terms_and_conditions': input_data.get('terms_and_conditions', []),
            'evaluation_criteria': input_data.get('evaluation_criteria', {}),
            'requested_info': input_data.get('requested_info', []),
            'legal_certifications': input_data.get('legal_certifications', []),
            'document_number': input_data.get('document_number'),
            'company_name': input_data.get('company_name'),
            'response_deadline': input_data.get('response_deadline'),
        }

    # date_issued/quantity/unit_of_measure/quality_standards/delivery_location/timeline are
    # user-provided form values, not something the AI needs to invent — always carry them
    # through from the original input rather than asking the model to regenerate them.
    for passthrough_field in ('date_issued', 'quantity', 'unit_of_measure', 'quality_standards', 'delivery_location', 'timeline'):
        parsed.setdefault(passthrough_field, input_data.get(passthrough_field))

    for scalar_field in ('executive_summary', 'document_number', 'company_name', 'response_deadline'):
        value = parsed.get(scalar_field)
        if isinstance(value, (dict, list)):
            parsed[scalar_field] = json.dumps(value)

    # The frontend renders these as <li>{item}</li> with no markdown/JSON handling — if the
    # model returns objects instead of strings here (seen in testing with weaker models),
    # React hard-crashes on render instead of degrading gracefully. Coerce defensively, same
    # as refine_rfq_draft() does, rather than trusting the prompt instruction alone.
    for array_field in ('scope_of_work', 'terms_and_conditions', 'requested_info', 'legal_certifications'):
        parsed[array_field] = _coerce_string_array(parsed.get(array_field), input_data.get(array_field, []))
    if isinstance(parsed.get('evaluation_criteria'), dict):
        parsed['evaluation_criteria'] = {
            str(k): (v if isinstance(v, str) else json.dumps(v) if isinstance(v, (dict, list)) else str(v))
            for k, v in parsed['evaluation_criteria'].items()
        }
    else:
        parsed['evaluation_criteria'] = input_data.get('evaluation_criteria', {})

    return parsed


_RFQ_SCALAR_FIELDS = (
    'executive_summary', 'document_number', 'company_name', 'response_deadline',
    'date_issued', 'quantity', 'unit_of_measure', 'quality_standards', 'delivery_location', 'timeline',
)
_RFQ_ARRAY_FIELDS = ('scope_of_work', 'terms_and_conditions', 'requested_info', 'legal_certifications')


_PLACEHOLDER_ITEM_PATTERN = re.compile(r'^[\.\s]*$|^\(?(unchanged|same|no change|as before)\)?\.?$', re.IGNORECASE)


def _coerce_string_array(value, fallback: list) -> list:
    """Ensure every item is a plain string. Weaker models sometimes turn a string array
    into objects like {"original_term":..., "new_term":...} when asked to edit one item —
    pull out the most likely intended string rather than discarding the edit entirely.
    Also drops lazy placeholder items (e.g. "...", "(unchanged)") some models substitute
    for items they didn't bother repeating, despite being told to return the full array."""
    if not isinstance(value, list):
        return fallback
    coerced = []
    for item in value:
        if isinstance(item, str):
            if _PLACEHOLDER_ITEM_PATTERN.match(item.strip()):
                continue
            coerced.append(item)
        elif isinstance(item, dict):
            for key in ('new_term', 'text', 'value', 'term', 'updated', 'content'):
                if isinstance(item.get(key), str):
                    coerced.append(item[key])
                    break
            else:
                continue
        else:
            coerced.append(str(item))
    return coerced if coerced else fallback


def refine_rfq_draft(current_draft: dict, instruction: str) -> dict:
    valid_keys = list(current_draft.keys())
    prompt = (
        'Here is the current draft of an RFQ (Request for Quotation) document, as JSON. The user has asked '
        f'for a specific change: "{instruction}"\n\n'
        'Return ONLY a JSON object containing the fields that actually need to change as a direct result of '
        'this instruction — and NOTHING else. Do not include fields you are leaving unchanged, even if you '
        'regenerated them in your head; omit them entirely from your response. For example, if the instruction '
        'is only about payment terms, return only "terms_and_conditions" (and "executive_summary" only if it '
        'specifically mentions the old payment terms) — never include document_number, dates, or any other '
        'untouched field.\n\n'
        'Preserve each field\'s original type exactly: "scope_of_work", "terms_and_conditions", '
        '"requested_info", "legal_certifications" must stay plain arrays of strings (never objects like '
        '{"original_term":..., "new_term":...} — just replace the string itself). The "omit unchanged fields" '
        'rule applies at the FIELD level only — if you include an array field at all, you MUST return the '
        'COMPLETE array with every item (both the changed one and all unchanged ones copied verbatim). Never '
        'use a placeholder like "..." or "(unchanged)" inside an array, and never return a shorter array than '
        'the original unless an item was genuinely supposed to be removed. "evaluation_criteria" must stay an '
        'object of category name to percentage string. Scalar fields must stay plain strings or numbers.\n\n'
        f'Valid field names in this draft: {", ".join(valid_keys)}\n\n'
        'Return ONLY valid JSON (no markdown code fences, no comments) — just the changed fields as a sparse patch.\n\n'
        f'Current draft:\n{json.dumps(current_draft, indent=2)}'
    )
    response = create_chat_completion(
        [{'role': 'system', 'content': load_system_prompt()}, {'role': 'user', 'content': prompt}],
        max_tokens=1500,
    )
    text = response.choices[0].message.content

    try:
        patch = _extract_json(text)
    except Exception:
        return {**current_draft, '_refine_error': f'Could not apply "{instruction}" — draft left unchanged. Try rephrasing the request.'}

    if not isinstance(patch, dict):
        return {**current_draft, '_refine_error': f'Could not apply "{instruction}" — draft left unchanged. Try rephrasing the request.'}

    # Only accept keys that already exist in the draft — never let the model add stray
    # new fields. Everything not in the patch is guaranteed untouched by construction.
    patch = {k: v for k, v in patch.items() if k in valid_keys}
    merged = {**current_draft, **patch}

    for scalar_field in _RFQ_SCALAR_FIELDS:
        value = merged.get(scalar_field)
        if isinstance(value, (dict, list)):
            merged[scalar_field] = json.dumps(value)
    for array_field in _RFQ_ARRAY_FIELDS:
        if array_field in patch:
            merged[array_field] = _coerce_string_array(merged.get(array_field), current_draft.get(array_field, []))
    if 'evaluation_criteria' in patch and not isinstance(merged.get('evaluation_criteria'), dict):
        merged['evaluation_criteria'] = current_draft.get('evaluation_criteria', {})

    return merged


def _sanitize_chart_data(raw_chart_data) -> list:
    sanitized = []
    if isinstance(raw_chart_data, list):
        for item in raw_chart_data:
            if isinstance(item, dict) and 'name' in item and 'value' in item:
                try:
                    sanitized.append({'name': str(item['name']), 'value': float(item['value'])})
                except (TypeError, ValueError):
                    continue
    return sanitized


def generate_report(document_context: dict = None, focus: str = None) -> dict:
    documents = (document_context or {}).get('documents') or []
    context_block = build_document_context_block(document_context)

    # Listing a document name isn't the same as having its real content. A document
    # can be present in the `documents` array but have no data_preview at all — e.g.
    # the backend restarted since it was uploaded, wiping the in-memory store the
    # doc_id pointed to. In that case the AI sees a filename with nothing behind it
    # and fabricates a full report to fill the gap (observed directly in testing).
    # Require actual parsed content, not just a non-empty list, before proceeding.
    documents_with_data = [d for d in documents if d.get('data_preview')]

    if not documents_with_data:
        return {
            'report_markdown': (
                'No usable document data is available in this session right now — either nothing has been '
                'uploaded yet, or the upload(s) listed have no readable content (try re-uploading if you '
                'believe this is wrong). Upload a contract or spend/vendor spreadsheet, then generate a '
                'report from its real data.'
            ),
            'chart_title': None,
            'chart_type': None,
            'chart_data': [],
        }

    # If any uploaded document is a multi-sheet workbook, the user wants a dedicated
    # section per sheet (labeled with its sheet number and name) rather than one
    # consolidated summary — different sheets in a workbook are often unrelated data,
    # and a single blended summary loses that structure.
    multi_sheet_docs = [d for d in documents_with_data if len(d.get('sheet_names') or []) > 1]

    focus_line = f'\n\nThe user asked the report to focus on: {focus}' if focus else ''

    if multi_sheet_docs:
        sheet_list_lines = []
        for doc in multi_sheet_docs:
            names = doc.get('sheet_names') or []
            sheet_list_lines.append(f"{doc.get('name', 'Unknown')}: " + ', '.join(f'{i+1}. {n}' for i, n in enumerate(names)))
        sheet_list = '\n'.join(sheet_list_lines)

        prompt = (
            'Write a per-sheet procurement report grounded strictly in the document data below. This workbook '
            'has multiple sheets — do NOT write one consolidated summary. Instead, write ONE section for EVERY '
            'sheet listed below, in the exact order listed, covering ALL of them — do not skip any sheet even '
            'if its content seems minor.\n\n'
            f'Sheets to cover, in order:\n{sheet_list}\n\n'
            'Each section header must be exactly: "## Sheet <number>: <sheet name>" (using the sheet\'s position '
            'number and its real name from the list above). Within each section, summarize that sheet\'s own '
            'data only — key figures, structure, notable entries — grounded strictly in that sheet\'s data as '
            'shown below. If a sheet has little or no meaningfully analyzable content, say so briefly in its '
            'section (e.g. "No notable figures in this sheet") rather than omitting the section entirely. '
            'Start with a short 1-2 sentence overview before the per-sheet sections, then end with a brief '
            '"## Overall Notes" section only if something spans multiple sheets worth flagging.'
            f'{focus_line}\n\n'
            'Return ONLY valid JSON (no markdown code fences, no comments) with keys: report_markdown, '
            'chart_title, chart_type, chart_data.\n'
            '"report_markdown" must be a SINGLE PLAIN STRING — never an array, never an object, never '
            'one-object-per-sheet. Concatenate every section (the overview, all per-sheet sections, and the '
            'optional overall notes) into ONE continuous Markdown string, with each "## " header inside that '
            'same string, separated by blank lines. Use "## " headers, bullet points, **bold** for figures, '
            'and tables where useful within that one string. Every figure, name, and date in it must trace '
            'back to the real document data shown below. If a sheet only has generic columns (e.g. '
            '"Item"/"Value") with no real category, department, or vendor names in the cells, describe it '
            'using its actual column names — do NOT invent plausible-sounding business labels (department '
            'names, vendor names, satisfaction scores) just to make a section read more polished. A real '
            'number wrapped in a fabricated label is still fabrication.\n'
            '"chart_type" is "bar", "pie", or "line" — ONLY include a chart if the data genuinely has a '
            'quantitative breakdown worth visualizing across sheets. If nothing supports a meaningful chart, '
            'set chart_type and chart_data to null/empty — never invent placeholder numbers. "chart_data", '
            'when present, is an array of 3-8 real objects shaped like {"name": "<label>", "value": <number>}.'
            f"{context_block}"
        )
        max_tokens = 4000
    else:
        prompt = (
            'Write an executive procurement report grounded strictly in the document data below. '
            'You decide the structure — choose whatever sections genuinely fit what this data actually '
            'contains (for example: Executive Summary, Spend Breakdown, Risk Flags, Contract Expiries, '
            'Vendor Performance, Recommendations — use only the ones the data supports, and add others '
            'if something else stands out). Do not force content into sections the data doesn\'t support.'
            f'{focus_line}\n\n'
            'Return ONLY valid JSON (no markdown code fences, no comments) with keys: report_markdown, '
            'chart_title, chart_type, chart_data.\n'
            '"report_markdown" is the full report as a Markdown string (use "## " headers, bullet points, '
            '**bold** for figures, and tables where useful) — this is the main content, written in your own '
            'judgment, not a fixed template. Every figure, name, and date in it must trace back to the real '
            'document data shown below. If the sheet only has generic columns (e.g. "Item"/"Value") with no '
            'real category, department, or vendor names in the cells, describe the data using its actual column '
            'and sheet names — do NOT invent plausible-sounding business labels (department names, vendor names, '
            'satisfaction scores, category names) just to make the report read more polished. A real number '
            'wrapped in a fabricated label is still fabrication.\n'
            '"chart_type" is "bar", "pie", or "line" — ONLY include a chart if the data genuinely has a '
            'quantitative breakdown worth visualizing (e.g. spend by category, vendor count by risk level). '
            'If nothing in the real data supports a meaningful chart, set chart_type and chart_data to null/empty '
            '— never invent illustrative or placeholder numbers to fill a chart. "chart_data", when present, is '
            'an array of 3-8 real objects shaped like {"name": "<label>", "value": <number>}, drawn from actual '
            'figures in the document data, not estimates.'
            f"{context_block}"
        )
        max_tokens = 2200

    known_values = _collect_known_values_for_context(document_context)
    call_messages = [{'role': 'system', 'content': load_system_prompt()}, {'role': 'user', 'content': prompt}]

    # Up to 2 attempts total: the first generation, plus one retry if a numeric-grounding
    # check below flags a figure that doesn't match any real value in the workbook (the
    # other safety nets — sheet-grounding, placeholder text — give an immediate hard
    # discard with no retry since they signal the model ignored the format entirely; a
    # bad individual number is a narrower failure worth giving one self-correction shot).
    for attempt in range(2):
        response = create_chat_completion(call_messages, max_tokens=max_tokens)
        text = response.choices[0].message.content

        try:
            parsed = _extract_json(text)
        except Exception:
            parsed = {
                'report_markdown': 'Could not generate a structured report from this document — try again, or try a more specific request.',
                'chart_title': None,
                'chart_type': None,
                'chart_data': [],
            }

        report_markdown = parsed.get('report_markdown')
        if isinstance(report_markdown, list):
            # Weaker models sometimes structure this as one object per sheet (e.g.
            # {"sheet_number": 1, "section": "Summary", "content": "..."}) despite being
            # told it must be a single string. Recover the actual text instead of dumping
            # raw JSON to the user.
            parts = []
            for item in report_markdown:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    content = next((item[k] for k in ('content', 'text', 'markdown', 'section_content') if isinstance(item.get(k), str)), None)
                    if content:
                        header = item.get('section') or item.get('sheet_name')
                        parts.append(f"## {header}\n{content}" if header and not content.lstrip().startswith('#') else content)
            parsed['report_markdown'] = '\n\n'.join(parts) if parts else json.dumps(report_markdown)
        elif isinstance(report_markdown, dict):
            parsed['report_markdown'] = json.dumps(report_markdown)
        parsed.setdefault('report_markdown', text if isinstance(text, str) else '')

        # Weaker models occasionally double-escape newlines when building the JSON string
        # (producing the literal two characters "\n" in the value instead of a real
        # newline), which json.loads() then leaves as literal backslash-n text. Markdown
        # content should never legitimately contain that literal sequence, so clean it up.
        if isinstance(parsed.get('report_markdown'), str):
            parsed['report_markdown'] = parsed['report_markdown'].replace('\\n', '\n')

        # Hard safety net for the per-sheet mode specifically: a weaker model occasionally
        # ignores the per-sheet instruction entirely and free-associates a generic-sounding
        # "typical business report" (fake categories, fake vendor names, fake contract
        # numbers) with zero connection to the actual sheets. If the report doesn't mention
        # at least half of the real sheet names, that's a strong signal it did exactly
        # that — refuse to show it rather than risk displaying fabricated content.
        if multi_sheet_docs:
            all_sheet_names = [n for doc in multi_sheet_docs for n in (doc.get('sheet_names') or [])]
            report_text = parsed.get('report_markdown') or ''
            # Word-boundary match, not plain substring — a sheet literally named "1" would
            # otherwise "match" trivially inside any generated number like "$125,000".
            mentioned = sum(
                1 for n in all_sheet_names
                if re.search(r'(?<![\w.])' + re.escape(n) + r'(?![\w.])', report_text, re.IGNORECASE)
            )
            if all_sheet_names and mentioned < max(1, len(all_sheet_names) // 2):
                parsed['report_markdown'] = (
                    'The generated report didn\'t stay grounded in this workbook\'s actual sheets — discarded '
                    'rather than shown, since this tool never displays content it can\'t verify against your '
                    'real data. Please try again.'
                )
                parsed['chart_title'] = None
                parsed['chart_type'] = None
                parsed['chart_data'] = []
                return parsed

        # General safety net for BOTH report modes: a model defaulting to a generic
        # corporate-report template produces literal placeholder brackets like
        # "[Your Name/Title]", "[Company Name]", "[Current Fiscal Year]" instead of real
        # content — sometimes alongside an entirely invented contact person (seen directly
        # in testing: a fabricated "Dr. Jane Doe" with a fake email and phone number).
        # Require a space inside the brackets (multi-word) so legitimate short labels like
        # "[HIGH]"/"[PENDING]" aren't flagged — only template-style phrases are.
        placeholder_match = re.search(r'\[[^\[\]\(\)]*\s[^\[\]\(\)]*\](?!\()', parsed.get('report_markdown') or '')
        if placeholder_match:
            parsed['report_markdown'] = (
                f'The generated report used template placeholder text (e.g. "{placeholder_match.group(0)}") instead '
                'of real content from your document — discarded rather than shown. Please try again.'
            )
            parsed['chart_title'] = None
            parsed['chart_type'] = None
            parsed['chart_data'] = []
            return parsed

        # Numeric-grounding safety net: every specific figure the report cites must trace
        # to a real cell value or a real computed aggregate (column-level or per-category)
        # in the actual workbook — not just plausible/well-formatted prose. Give the model
        # one chance to self-correct with the exact bad numbers called out before discarding.
        unverifiable = find_unverifiable_numbers(parsed.get('report_markdown') or '', known_values)
        if not unverifiable:
            parsed['chart_data'] = _sanitize_chart_data(parsed.get('chart_data'))
            parsed['chart_type'] = parsed.get('chart_type') if parsed.get('chart_type') in ('bar', 'pie', 'line') else None
            if not parsed['chart_data']:
                parsed['chart_type'] = None
            parsed.setdefault('chart_title', None)
            return parsed

        if attempt == 0:
            call_messages = call_messages + [
                {'role': 'assistant', 'content': text},
                {'role': 'user', 'content': (
                    'Your previous report cited these specific figures, but they don\'t match any real value '
                    'found in the document data provided: ' + ', '.join(f'{v:,.2f}' for v in unverifiable[:5])
                    + '. Real data IS available in the [REAL COMPUTED STATISTICS] and [CATEGORY BREAKDOWNS] '
                    'blocks above — rewrite the full report in the same JSON format, using THOSE exact numbers '
                    'in place of the wrong ones. Everything else about the previous draft was fine; keep it, '
                    'just fix the incorrect figures. Do not respond by omitting numbers altogether — the real '
                    'data is right there in the context, use it normally.'
                )},
            ]

    return {
        'report_markdown': (
            'I drafted a report but one or more specific figures in it didn\'t match any real value in your '
            'data, so I\'m not showing it rather than risk giving you a wrong number. Please try again.'
        ),
        'chart_title': None,
        'chart_type': None,
        'chart_data': [],
    }


def generate_insights_report(document_context: dict = None) -> dict:
    documents = (document_context or {}).get('documents') or []
    context_block = build_document_context_block(document_context)

    if not documents:
        prompt = (
            'No documents have been uploaded to this procurement session yet. '
            'Return ONLY valid JSON (no markdown code fences) with keys: title, overview, headlines. '
            '"title" is "Procurement Insights Report". "overview" is 1-2 sentences noting no documents '
            'are available yet and inviting the user to upload a contract or spreadsheet. '
            '"headlines" is an empty array.'
        )
    else:
        prompt = (
            'Generate an executive insights report for the documents currently in this procurement session. '
            'Return ONLY valid JSON (no markdown code fences) with keys: title, overview, headlines. '
            '"title" is a short report title. "overview" is a 2-4 sentence executive summary grounded in the '
            'actual document data provided below. "headlines" is an array of 3-6 objects, each shaped like '
            '{"headline": "<punchy headline, max 12 words>", "explanation": "<2-4 sentence explanation grounded '
            'in the actual document data, citing specific figures, dates, or terms where available>"}. '
            'Prioritize the most material findings: financial exposure, risk flags, expiring terms, anomalies.'
            f"{context_block}"
        )

    known_values = _collect_known_values_for_context(document_context) if documents else set()
    call_messages = [{'role': 'system', 'content': load_system_prompt()}, {'role': 'user', 'content': prompt}]

    for attempt in range(2):
        response = create_chat_completion(call_messages, max_tokens=1500)
        text = response.choices[0].message.content

        try:
            parsed = _extract_json(text)
        except Exception:
            parsed = {'title': 'Procurement Insights Report', 'overview': text, 'headlines': []}

        parsed.setdefault('title', 'Procurement Insights Report')
        parsed.setdefault('overview', '')
        headlines = parsed.get('headlines')
        parsed['headlines'] = headlines if isinstance(headlines, list) else []

        # Every figure cited across the overview and headline explanations must trace to
        # a real value in the workbook — same numeric-grounding check used for the full
        # report, since insight headlines are exactly the kind of punchy, number-heavy
        # claim that's easy for a model to get wrong while sounding confident.
        combined_text = parsed['overview'] + '\n' + '\n'.join(
            h.get('explanation', '') for h in parsed['headlines'] if isinstance(h, dict)
        )
        unverifiable = find_unverifiable_numbers(combined_text, known_values)
        if not unverifiable:
            return {
                'title': parsed['title'],
                'overview': parsed['overview'],
                'headlines': parsed['headlines'],
                'documents': [{'name': doc.get('name', 'Unknown'), 'type': doc.get('type', 'unknown')} for doc in documents],
            }

        if attempt == 0:
            call_messages = call_messages + [
                {'role': 'assistant', 'content': text},
                {'role': 'user', 'content': (
                    'Your previous answer cited these specific figures, but they don\'t match any real value '
                    'found in the document data provided: ' + ', '.join(f'{v:,.2f}' for v in unverifiable[:5])
                    + '. Real data IS available in the [REAL COMPUTED STATISTICS] and [CATEGORY BREAKDOWNS] '
                    'blocks above — rewrite it in the same JSON format, using THOSE exact numbers in place of '
                    'the wrong ones. Everything else about the previous draft was fine; keep it, just fix the '
                    'incorrect figures. Do not respond by omitting numbers altogether — the real data is right '
                    'there in the context, use it normally.'
                )},
            ]

    return {
        'title': 'Procurement Insights Report',
        'overview': (
            'I drafted insights but one or more specific figures didn\'t match any real value in your data, '
            'so I\'m not showing them rather than risk giving you a wrong number. Please try again.'
        ),
        'headlines': [],
        'documents': [{'name': doc.get('name', 'Unknown'), 'type': doc.get('type', 'unknown')} for doc in documents],
    }


def agentic_loop(user_query: str, document_context: dict = None, session_state: dict = None, max_iterations: int = 3) -> dict:
    return procure_agent(user_query, document_context, session_state)


_VALID_PRIORITIES = ('high', 'medium', 'low')


def _sanitize_rfq_candidates(raw_candidates) -> list:
    sanitized = []
    if not isinstance(raw_candidates, list):
        return sanitized
    for item in raw_candidates:
        if not isinstance(item, dict) or not item.get('vendor'):
            continue
        reasons = item.get('reasons')
        # expiry/source_document are rendered directly as JSX children on the frontend
        # with no type guard — coerce to string (or None) so a stray nested object from
        # the model can't crash the render.
        expiry = item.get('expiry')
        source_document = item.get('source_document')
        sanitized.append({
            'vendor': str(item['vendor']),
            'value': item.get('value'),
            'expiry': expiry if isinstance(expiry, (str, type(None))) else str(expiry),
            'score': item.get('score'),
            'reasons': [str(r) for r in reasons] if isinstance(reasons, list) else [],
            'priority': item.get('priority') if item.get('priority') in _VALID_PRIORITIES else 'medium',
            'source_document': source_document if isinstance(source_document, (str, type(None))) else str(source_document),
        })
    return sanitized


def detect_rfq_candidates(document_context: dict = None) -> dict:
    documents = (document_context or {}).get('documents') or []
    context_block = build_document_context_block(document_context)

    if not documents:
        return {
            'candidates': [],
            'analysis_note': 'No documents have been uploaded to this session yet. Upload a vendor contract register or spend spreadsheet to detect RFQ opportunities.',
            'documents_analyzed': 0,
        }

    prompt = (
        'Analyze the document data below to find vendors/contracts that are good candidates for a new RFQ '
        '(Request for Quotation). A candidate is anything that genuinely stands out in the actual data — for '
        'example: a contract or relationship nearing an expiry/renewal date, a vendor with a low performance '
        'or risk score, pricing that looks like an outlier versus similar rows, a flagged compliance issue, or '
        'any other signal actually present in the columns provided. The exact signals depend entirely on what '
        'columns this data actually has — do not assume fixed field names; read the real column headers and '
        'values shown below.\n\n'
        'Return ONLY valid JSON (no markdown code fences) with keys: candidates, analysis_note.\n'
        '"candidates" is an array of objects, each shaped like: '
        '{"vendor": "<name from the data>", "value": <number or null>, "expiry": "<date string or null>", '
        '"score": <number or null>, "reasons": ["<short reason grounded in real data>", ...], '
        '"priority": "high"|"medium"|"low", "source_document": "<document name>"}. '
        'If the data has a contract value, spend, or price column for this vendor, always populate "value" with '
        'that real number — do not leave it null when the data has it. Always populate "source_document" with '
        'the actual document name this vendor came from. "analysis_note" is 1-2 sentences summarizing what was found.\n\n'
        'Only include a candidate if there is a real, citable reason grounded in the document data — never '
        'invent vendors, figures, or dates that are not present. If no documents contain usable signals, return '
        'an empty candidates array and explain why in analysis_note.'
        f"{context_block}"
    )

    response = create_chat_completion(
        [{'role': 'system', 'content': load_system_prompt()}, {'role': 'user', 'content': prompt}],
        max_tokens=2200,
    )
    text = response.choices[0].message.content

    try:
        parsed = _extract_json(text)
    except Exception:
        parsed = {
            'candidates': [],
            'analysis_note': 'Could not complete a structured analysis of this document — try again, or try a more specific document.',
        }

    candidates = _sanitize_rfq_candidates(parsed.get('candidates'))
    priority_rank = {'high': 0, 'medium': 1, 'low': 2}
    candidates.sort(key=lambda c: priority_rank.get(c['priority'], 1))

    return {
        'candidates': candidates,
        'analysis_note': parsed.get('analysis_note', ''),
        'documents_analyzed': len(documents),
    }


def extract_rfq_template(document_context: dict, vendor: str) -> dict:
    context_block = build_document_context_block(document_context)

    prompt = (
        f'Build a pre-filled draft RFQ (Request for Quotation) for the vendor "{vendor}", grounded strictly in '
        'the document data below. Use whatever real details exist about this vendor (contract value, scope, '
        'past terms, performance, risk notes) to pre-fill the draft; where the data does not specify something, '
        'use a clearly reasonable procurement default rather than inventing vendor-specific facts.\n\n'
        'Return ONLY valid JSON (no markdown code fences, no comments) with keys: company_name, document_number, '
        'date_issued, response_deadline, executive_summary, scope_of_work, quantity, unit_of_measure, '
        'quality_standards, delivery_location, timeline, terms_and_conditions, evaluation_criteria, '
        'requested_info, legal_certifications, auto_filled_fields.\n'
        '"company_name", "document_number", "date_issued", "response_deadline", "executive_summary", '
        '"unit_of_measure", "quality_standards", "delivery_location", "timeline" must ALL be plain strings — '
        'never objects or arrays, even if you need to combine multiple facts into one sentence. "quantity" is a '
        'number. "scope_of_work", "terms_and_conditions", "requested_info", "legal_certifications" are string '
        'arrays. "evaluation_criteria" is an object of category to percentage string. "auto_filled_fields" is an '
        'array of the field names you were able to ground in real document data (as opposed to defaults).'
        f"{context_block}"
    )

    response = create_chat_completion(
        [{'role': 'system', 'content': load_system_prompt()}, {'role': 'user', 'content': prompt}],
        max_tokens=2000,
    )
    text = response.choices[0].message.content

    try:
        parsed = _extract_json(text)
    except Exception:
        parsed = {
            'company_name': vendor,
            'executive_summary': f'Could not generate a structured RFQ draft for {vendor} — please fill in the fields manually.',
            'scope_of_work': [],
            'terms_and_conditions': [],
            'evaluation_criteria': {},
            'requested_info': [],
            'legal_certifications': [],
            'auto_filled_fields': [],
        }

    parsed.setdefault('company_name', vendor)
    parsed.setdefault('scope_of_work', [])
    parsed.setdefault('terms_and_conditions', [])
    parsed.setdefault('evaluation_criteria', {})
    parsed.setdefault('requested_info', [])
    parsed.setdefault('legal_certifications', [])
    parsed.setdefault('auto_filled_fields', [])

    # Defensive: weaker models occasionally return an object/array for a field the UI
    # treats as plain text. Coerce those back to a string so the form never shows
    # "[object Object]" instead of crashing or silently corrupting the field.
    for scalar_field in (
        'company_name', 'document_number', 'date_issued', 'response_deadline',
        'executive_summary', 'unit_of_measure', 'quality_standards', 'delivery_location', 'timeline',
    ):
        value = parsed.get(scalar_field)
        if isinstance(value, (dict, list)):
            parsed[scalar_field] = json.dumps(value)

    # Same crash-prevention as generate_rfq(): the frontend renders these as plain
    # <li>{item}</li> with no defensive handling, so a stray object/dict item would
    # hard-crash the React render instead of degrading gracefull
    for array_field in ('scope_of_work', 'terms_and_conditions', 'requested_info', 'legal_certifications'):
        parsed[array_field] = _coerce_string_array(parsed.get(array_field), [])
    if isinstance(parsed.get('evaluation_criteria'), dict):
        parsed['evaluation_criteria'] = {
            str(k): (v if isinstance(v, str) else json.dumps(v) if isinstance(v, (dict, list)) else str(v))
            for k, v in parsed['evaluation_criteria'].items()
        }
    else:
        parsed['evaluation_criteria'] = {}

    return parsed
