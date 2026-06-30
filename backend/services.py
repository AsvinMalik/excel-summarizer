import json
import os
import re
import sys
from typing import Any, Dict

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
            context_block += (
                f"  Columns: {', '.join(doc.get('columns') or [])}\n"
                f"  Row count: {doc.get('row_count', 'unknown')}\n"
                f"  Data sample (CSV{', truncated' if doc.get('data_preview_truncated') else ''}):\n{doc['data_preview']}\n"
            )
    return context_block


def procure_agent(user_query: str, document_context: dict = None, session_state: dict = None) -> dict:
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
            'single unbroken paragraph if there is more than one distinct point. '
            'Also: never invent clause text, figures, or terms not present in the document data '
            'above. If the request doesn\'t fit the document type (e.g. clause extraction on a '
            'plain data spreadsheet with no contract language), say so directly instead of '
            'fabricating an answer.'
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
    return json.loads(cleaned)


def generate_rfq(input_data: dict) -> dict:
    prompt = (
        'Create a professional RFQ document using the following details. '
        'Return output in JSON with keys: executive_summary, scope_of_work, terms_and_conditions, evaluation_criteria, '
        'requested_info, legal_certifications, document_number, company_name, response_deadline.'
    )
    body = f"{prompt}\n\nInput:\n{json.dumps(input_data, indent=2)}"
    response = create_chat_completion([{'role': 'system', 'content': load_system_prompt()}, {'role': 'user', 'content': body}], max_tokens=1200)
    text = response.choices[0].message.content

    try:
        parsed = _extract_json(text)
    except Exception:
        parsed = {
            'executive_summary': text,
            'scope_of_work': input_data.get('scope_of_work', []),
            'terms_and_conditions': input_data.get('terms_and_conditions', []),
            'evaluation_criteria': input_data.get('evaluation_criteria', {}),
            'requested_info': input_data.get('requested_info', []),
            'legal_certifications': input_data.get('legal_certifications', []),
            'document_number': input_data.get('document_number'),
            'company_name': input_data.get('company_name'),
            'response_deadline': input_data.get('response_deadline'),
        }

    return parsed


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


def generate_report(input_data: dict) -> dict:
    prompt = (
        'Create an executive procurement report summary using the following details. '
        'Return ONLY valid JSON (no markdown code fences) with keys: '
        'report_type, executive_summary, key_findings, chart_title, chart_type, chart_data. '
        '"chart_type" must be exactly one of "bar", "pie", or "line", chosen to best represent the data '
        '(bar for rankings/comparisons, pie for composition/breakdown, line for trends over time). '
        '"chart_data" must be a JSON array of 3 to 8 objects shaped like {"name": "<short label>", "value": <number>}, '
        'representing the most relevant quantitative breakdown for this report (e.g. spend by category, '
        'vendor count by risk level, renewals by month). Use real numbers implied by the input data; '
        'if no numeric data is available, provide a reasonable illustrative estimate rather than omitting it.'
    )
    body = f"{prompt}\n\nInput:\n{json.dumps(input_data, indent=2)}"
    response = create_chat_completion([{'role': 'system', 'content': load_system_prompt()}, {'role': 'user', 'content': body}], max_tokens=1200)
    text = response.choices[0].message.content

    try:
        parsed = _extract_json(text)
    except Exception:
        parsed = {
            'report_type': input_data.get('report_type', 'spend'),
            'executive_summary': text,
            'key_findings': [],
            'chart_title': None,
            'chart_type': None,
            'chart_data': [],
        }

    parsed['chart_data'] = _sanitize_chart_data(parsed.get('chart_data'))
    parsed['chart_type'] = parsed.get('chart_type') if parsed.get('chart_type') in ('bar', 'pie', 'line') else None
    if not parsed['chart_data']:
        parsed['chart_type'] = None
    parsed.setdefault('chart_title', None)
    parsed.setdefault('key_findings', [])

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
