import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_orchestrator import create_chat_completion

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
            'generic page-numbering scheme that doesn\'t match the real sheet names.'
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

    # Last resort: grab the first balanced-looking {...} block in the text.
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
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

    if not documents:
        return {
            'report_markdown': (
                'No documents have been uploaded to this session yet. Upload a contract or '
                'spend/vendor spreadsheet first, then generate a report from its real data.'
            ),
            'chart_title': None,
            'chart_type': None,
            'chart_data': [],
        }

    focus_line = f'\n\nThe user asked the report to focus on: {focus}' if focus else ''
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

    response = create_chat_completion(
        [{'role': 'system', 'content': load_system_prompt()}, {'role': 'user', 'content': prompt}],
        max_tokens=2200,
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

    if isinstance(parsed.get('report_markdown'), (dict, list)):
        parsed['report_markdown'] = json.dumps(parsed['report_markdown'])
    parsed.setdefault('report_markdown', text if isinstance(text, str) else '')

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
