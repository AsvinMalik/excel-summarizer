import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_orchestrator import create_chat_completion
from data_profiler import format_profile_block
from query_engine import load_all_sheets, execute_query_spec

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
    return context_block


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


def _apply_deterministic_overrides(user_query: str, spec: dict, columns: list) -> dict:
    spec = dict(spec)
    query_lower = user_query.lower()

    top_match = _TOP_N_RE.search(user_query)
    bottom_match = _BOTTOM_N_RE.search(user_query)
    group_match = _GROUP_BY_RE.search(user_query)

    if group_match and not spec.get('group_by'):
        found = _find_column_for_term(group_match.group(1), columns)
        if found:
            spec['group_by'] = found

    # Weak models frequently drop "column" for ranking questions ("top 3 vendors BY
    # Annual Spend") even when told to keep it — re-derive it from the literal "by X"
    # phrase in the question whenever the model left it null.
    if not spec.get('column'):
        by_match = _BY_COLUMN_RE.search(user_query)
        if by_match:
            found = _find_column_for_term(by_match.group(1), columns)
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
            found = _find_column_for_term(superlative_match.group(2), columns)
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


def _format_query_result(spec: dict, result: dict) -> str:
    sheet = spec.get('sheet', 'Unknown')

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
    if not sheet_column_map:
        return None

    spec_prompt = (
        'Translate this data question into a structured query spec to be executed exactly with pandas. '
        'Do NOT attempt to answer the question yourself — only describe how to compute it.\n\n'
        f'User question: "{user_query}"\n\n'
        'Available sheets and their REAL column names (use these exact names, case-sensitive):\n'
        f'{json.dumps(sheet_column_map, indent=2)}\n\n'
        'Return ONLY valid JSON (no markdown fences, no comments) with this exact shape:\n'
        '{"answerable": true|false, "sheet": "<exact sheet name>", "column": "<exact numeric column name or null>", '
        '"operation": "sum"|"mean"|"count"|"min"|"max"|"median"|null, "group_by": "<exact column name or null>", '
        '"filters": [{"column": "<exact column name>", "op": ">"|">="|"<"|"<="|"=="|"!=", "value": <number or string>}], '
        '"sort": "asc"|"desc"|null, "limit": <int or null>}\n\n'
        'Four worked examples (column names below are illustrative — always substitute the REAL column names from '
        'the sheet list above, never these literal example names):\n'
        '1. "What is the total Spend?" -> single number, no breakdown, no row list needed:\n'
        '   {"answerable": true, "sheet": "Sheet1", "column": "Spend", "operation": "sum", "group_by": null, '
        '"filters": [], "sort": null, "limit": null}\n'
        '2. "Show total spend grouped by Region" -> one aggregated number PER region, so group_by is set:\n'
        '   {"answerable": true, "sheet": "Sheet1", "column": "Spend", "operation": "sum", "group_by": "Region", '
        '"filters": [], "sort": null, "limit": null}\n'
        '3. "Top 3 vendors by spend" -> this ranks individual ROWS, it is NOT an aggregation — leave operation and '
        'group_by null, and use sort+limit instead. Never put the ranking criterion in "filters":\n'
        '   {"answerable": true, "sheet": "Sheet1", "column": "Spend", "operation": null, "group_by": null, '
        '"filters": [], "sort": "desc", "limit": 3}\n'
        '4. "How many vendors have spend over 1,000,000?" -> a count of matching rows; "column" stays null since '
        'no specific column is being aggregated, only counted:\n'
        '   {"answerable": true, "sheet": "Sheet1", "column": null, "operation": "count", "group_by": null, '
        '"filters": [{"column": "Spend", "op": ">", "value": 1000000}], "sort": null, "limit": null}\n\n'
        'Set "answerable" to false (with other fields null/empty) if this question needs joining multiple sheets, '
        'reading free-text/narrative content, or anything beyond a single-sheet aggregation/filter/group-by/ranking. '
        'Never invent a sheet or column name that is not in the list above — if there is no confident match, set '
        '"answerable" to false instead of guessing.'
    )

    try:
        response = create_chat_completion(
            [
                {'role': 'system', 'content': 'You translate data questions into structured pandas query specs. Output JSON only, nothing else.'},
                {'role': 'user', 'content': spec_prompt},
            ],
            max_tokens=400,
        )
        spec = _extract_json(response.choices[0].message.content)
    except Exception:
        return None

    if not isinstance(spec, dict) or not spec.get('answerable'):
        return None

    sheet_columns = sheet_column_map.get(spec.get('sheet'), [])
    spec = _apply_deterministic_overrides(user_query, spec, sheet_columns)

    try:
        all_sheets = load_all_sheets(doc['file_path'])
        result = execute_query_spec(all_sheets, spec)
    except Exception:
        # Covers QueryError (bad sheet/column from the spec) and any pandas failure.
        # Never surface a broken/partial answer — fall through to the normal grounded
        # LLM-with-profile-context flow instead.
        return None

    return _format_query_result(spec, result)


def procure_agent(user_query: str, document_context: dict = None, session_state: dict = None) -> dict:
    structural_answer = _try_answer_structural_question(user_query, document_context)
    if structural_answer:
        return {
            'timestamp': int(datetime.utcnow().timestamp()),
            'model': 'deterministic',
            'content': [{'type': 'text', 'text': structural_answer}],
            'tool_calls': [],
        }

    refusal = _try_refuse_empty_document_request(user_query, document_context)
    if refusal:
        return {
            'timestamp': int(datetime.utcnow().timestamp()),
            'model': 'deterministic',
            'content': [{'type': 'text', 'text': refusal}],
            'tool_calls': [],
        }

    data_query_answer = _try_answer_data_query(user_query, document_context)
    if data_query_answer:
        return {
            'timestamp': int(datetime.utcnow().timestamp()),
            'model': 'deterministic-query-engine',
            'content': [{'type': 'text', 'text': data_query_answer}],
            'tool_calls': [],
        }

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
        ),
    })
    messages.append({'role': 'user', 'content': user_query})

    response = create_chat_completion(messages, max_tokens=1200)
    text = response.choices[0].message.content

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

    response = create_chat_completion(
        [{'role': 'system', 'content': load_system_prompt()}, {'role': 'user', 'content': prompt}],
        max_tokens=max_tokens,
    )
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

    parsed['chart_data'] = _sanitize_chart_data(parsed.get('chart_data'))
    parsed['chart_type'] = parsed.get('chart_type') if parsed.get('chart_type') in ('bar', 'pie', 'line') else None
    if not parsed['chart_data']:
        parsed['chart_type'] = None
    parsed.setdefault('chart_title', None)

    return parsed


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

    response = create_chat_completion(
        [{'role': 'system', 'content': load_system_prompt()}, {'role': 'user', 'content': prompt}],
        max_tokens=1500,
    )
    text = response.choices[0].message.content

    try:
        parsed = _extract_json(text)
    except Exception:
        parsed = {'title': 'Procurement Insights Report', 'overview': text, 'headlines': []}

    parsed.setdefault('title', 'Procurement Insights Report')
    parsed.setdefault('overview', '')
    headlines = parsed.get('headlines')
    parsed['headlines'] = headlines if isinstance(headlines, list) else []

    return {
        'title': parsed['title'],
        'overview': parsed['overview'],
        'headlines': parsed['headlines'],
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
