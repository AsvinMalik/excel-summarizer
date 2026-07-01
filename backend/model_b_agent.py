"""
MODEL_B: Pandas Sandbox Agent
==============================
Answers questions by generating Python/pandas code and executing it against the
actual loaded data.  Fundamentally different from MODEL_A, which feeds a text
preview to an LLM and cross-checks the answer against known computed values.

MODEL_B flow:
  1. Load every sheet of the file into pandas DataFrames.
  2. Ask the LLM to write Python/pandas code that answers the user's question.
  3. Execute the generated code in a restricted namespace (sandbox).
  4. If the code errors, give the LLM one chance to self-correct.
  5. Format the result (DataFrame -> markdown table, scalar -> bold number, etc.)
     and return it as the response.

No grounding verifier is needed — the code execution IS the ground truth.
"""
import json
import re
import threading
from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from ai_orchestrator import create_chat_completion
from query_engine import load_all_sheets

# ---------------------------------------------------------------------------
# Sandbox configuration
# ---------------------------------------------------------------------------

_SANDBOX_TIMEOUT = 30  # seconds before we give up on a runaway execution

# Minimal safe builtins — blocks open(), exec(), eval(), __import__, os, sys, etc.
# Pandas and numpy are passed explicitly in the namespace below.
_SAFE_BUILTINS: Dict[str, Any] = {
    'abs': abs, 'bool': bool, 'dict': dict, 'enumerate': enumerate,
    'filter': filter, 'float': float, 'format': format, 'int': int,
    'isinstance': isinstance, 'issubclass': issubclass,
    'iter': iter, 'len': len, 'list': list, 'map': map,
    'max': max, 'min': min, 'next': next, 'print': print,
    'range': range, 'repr': repr, 'round': round, 'set': set,
    'slice': slice, 'sorted': sorted, 'str': str, 'sum': sum,
    'tuple': tuple, 'type': type, 'zip': zip,
    'True': True, 'False': False, 'None': None,
    'Exception': Exception, 'ValueError': ValueError,
    'TypeError': TypeError, 'KeyError': KeyError, 'IndexError': IndexError,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _var_name(sheet_name: str) -> str:
    """Map a sheet name to a valid Python identifier (df_<safe_name>)."""
    safe = re.sub(r'[^\w]', '_', str(sheet_name)).strip('_') or 'sheet'
    return f'df_{safe}'


def _schema_hint(all_sheets: Dict[str, pd.DataFrame]) -> str:
    """Build a schema block for the code-generation prompt."""
    parts = []
    for i, (name, df) in enumerate(all_sheets.items()):
        var = _var_name(name)
        col_names = list(df.columns[:25])
        dtypes = {str(c): str(df[c].dtype) for c in col_names}
        aliases = f'`{var}`' + (' (also `df` — first sheet)' if i == 0 else '')
        extra = f' ... (+{len(df.columns) - 25} more)' if len(df.columns) > 25 else ''
        parts.append(
            f'Sheet "{name}" -> {aliases}\n'
            f'  Rows: {len(df)}  |  Columns ({len(df.columns)}): '
            f'{", ".join(str(c) for c in col_names)}{extra}\n'
            f'  Dtypes: {json.dumps(dtypes)}'
        )
    return '\n\n'.join(parts)


def _extract_code(text: str) -> str:
    """Strip markdown code fences from LLM output."""
    text = text.strip()
    m = re.match(r'^```(?:python)?\s*\n?(.*?)\n?```\s*$', text, re.DOTALL)
    return m.group(1).strip() if m else text


def _run_sandbox(code: str, all_sheets: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    """Execute code in a restricted namespace with a timeout.  Returns
    {'result': <value>} on success or {'error': '<message>'} on failure."""
    namespace: Dict[str, Any] = {
        '__builtins__': _SAFE_BUILTINS,
        'pd': pd,
        'np': np,
        'json': json,
    }
    for i, (name, df) in enumerate(all_sheets.items()):
        namespace[_var_name(name)] = df.copy()
        if i == 0:
            namespace['df'] = df.copy()

    out: Dict[str, Any] = {'result': None, 'error': None}

    def _exec():
        try:
            exec(code, namespace)  # noqa: S102
            out['result'] = namespace.get('result')
        except Exception as exc:
            out['error'] = f'{type(exc).__name__}: {exc}'

    t = threading.Thread(target=_exec, daemon=True)
    t.start()
    t.join(timeout=_SANDBOX_TIMEOUT)
    if t.is_alive():
        out['error'] = f'Execution timed out after {_SANDBOX_TIMEOUT}s.'
    return out


def _format_result(value: Any) -> str:
    """Convert a sandbox result into a readable markdown string."""
    if value is None:
        return (
            'The code ran successfully but did not assign anything to `result`. '
            'Try rephrasing the question more specifically (e.g. "total of column X"), '
            'or switch to **Model A**.'
        )

    # If the code set result to the "cannot determine" sentinel, pass it through cleanly.
    if isinstance(value, str) and 'cannot determine' in value.lower():
        return value

    if isinstance(value, pd.Series):
        value = value.reset_index()
        value.columns = [str(c) for c in value.columns]

    if isinstance(value, pd.DataFrame):
        if value.empty:
            return 'No matching rows.'
        rows = value.head(50)
        header = '| ' + ' | '.join(str(c) for c in rows.columns) + ' |'
        sep = '|' + '---|' * len(rows.columns)
        body = '\n'.join(
            '| ' + ' | '.join(str(v) for v in row) + ' |'
            for row in rows.itertuples(index=False)
        )
        suffix = f'\n\n*Showing {len(rows)} of {len(value)} rows.*' if len(value) > len(rows) else ''
        return f'{header}\n{sep}\n{body}{suffix}'

    if isinstance(value, (int, float)):
        return f'**{value:,.4g}**'

    return str(value)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def model_b_agent(
    user_query: str,
    document_context: Optional[dict] = None,
    session_state: Optional[dict] = None,
    provider_key: str = 'auto',
) -> dict:
    """
    MODEL_B public entry point — mirrors the shape of procure_agent's return value.
    Lazy-imports structural bypass functions from services.py to avoid circular imports.
    """
    # Reuse the same instant deterministic bypasses as MODEL_A (sheet counts, row counts).
    # Lazy import avoids circular dependency (services.py imports model_b_agent).
    from services import _try_answer_structural_question, _try_refuse_empty_document_request

    structural = _try_answer_structural_question(user_query, document_context)
    if structural:
        return _wrap('deterministic', structural)

    refusal = _try_refuse_empty_document_request(user_query, document_context)
    if refusal:
        return _wrap('deterministic', refusal)

    # Block only tasks that are inherently narrative — generating prose, writing reports,
    # extracting contract text. Everything else (rankings, filters, totals, "give me a
    # brief count", "overview of spend by region") can produce a real pandas result.
    _NARRATIVE_RE = re.compile(
        r'\b(summar\w*|write\s+a\s+(report|summary)|build\s+(a\s+)?report|'
        r'report\s+on|extract\s+clause|generate\s+rfq|tell\s+me\s+about)\b',
        re.IGNORECASE,
    )
    if _NARRATIVE_RE.search(user_query):
        return _wrap('model_b_redirect', 'Ask **Model A** for this.')

    # Find the active document with a real file path
    documents = (document_context or {}).get('documents') or []
    active_doc = (document_context or {}).get('active_document')
    candidates = [
        d for d in ([active_doc] if active_doc else documents)
        if d and d.get('file_path')
    ]
    if not candidates:
        return _wrap('model_b_redirect', 'Upload a spreadsheet first.')

    doc = candidates[0]
    try:
        all_sheets = load_all_sheets(doc['file_path'])
    except Exception:
        return _wrap('model_b_redirect', 'Could not read file — ask **Model A**.')

    # If the user has a specific sheet selected in the preview panel, scope the code
    # generation to that sheet only — simpler prompt, more reliable code.
    active_sheet = doc.get('active_sheet')
    if active_sheet and active_sheet in all_sheets:
        schema_sheets = {active_sheet: all_sheets[active_sheet]}
        scope_note = f'Focus your code on the sheet "{active_sheet}" (variable: `{_var_name(active_sheet)}`).\n'
    else:
        schema_sheets = all_sheets
        scope_note = ''

    schema = _schema_hint(schema_sheets)

    code_prompt = (
        'You are a Python/pandas data analyst. An Excel workbook has been loaded into '
        'pandas DataFrames. Use the exact variable names listed below.\n\n'
        f'Available data:\n{schema}\n\n'
        f'{scope_note}'
        f'Write Python/pandas code to answer: "{user_query}"\n\n'
        'Rules:\n'
        '- Store the final answer in a variable called `result`\n'
        '- `result` may be a string, number, pandas DataFrame, or Series\n'
        '- Do NOT use open(), os, sys, subprocess, or any file/network I/O\n'
        '- Use the EXACT variable names shown above for each sheet (e.g. df_Sheet1)\n'
        '- Always reference columns by bracket notation with the exact name from the schema '
        '(e.g. df["Column Name"], never df.column_name) — column names are case-sensitive and '
        'may contain spaces, slashes, or parentheses\n'
        '- Always call .dropna(subset=[col]) before aggregating to avoid NaN errors\n'
        '- Convert currency/number columns with pd.to_numeric(df[col], errors="coerce") '
        'if they might contain strings\n'
        '- If the data cannot answer the question, set result = '
        '"Cannot determine from the available data."\n\n'
        'Return ONLY valid Python code — no markdown fences, no explanation.'
    )

    code_resp = create_chat_completion(
        [
            {'role': 'system', 'content': (
                'You are a Python/pandas expert. Output executable Python code only. '
                'No explanation, no markdown, no fences.'
            )},
            {'role': 'user', 'content': code_prompt},
        ],
        max_tokens=700,
        model_key=provider_key,
    )
    code = _extract_code(code_resp.choices[0].message.content)

    out = _run_sandbox(code, all_sheets)

    if out.get('error'):
        # Give the LLM one self-correction attempt
        fix_resp = create_chat_completion(
            [
                {'role': 'system', 'content': (
                    'You fix broken Python/pandas code. '
                    'Output the corrected code only — no explanation, no fences.'
                )},
                {'role': 'user', 'content': (
                    f'This code raised an error:\n\n{code}\n\n'
                    f'Error: {out["error"]}\n\n'
                    'Fix it so it runs correctly and stores the answer in `result`.'
                )},
            ],
            max_tokens=700,
            model_key=provider_key,
        )
        fixed_code = _extract_code(fix_resp.choices[0].message.content)
        out = _run_sandbox(fixed_code, all_sheets)

        if out.get('error'):
            return _wrap('model_b_redirect', 'Ask **Model A** for this.')

    text = _format_result(out.get('result'))
    return _wrap('MODEL_B', text)


def _wrap(model: str, text: str) -> dict:
    return {
        'timestamp': int(datetime.utcnow().timestamp()),
        'model': model,
        'content': [{'type': 'text', 'text': text}],
        'tool_calls': [],
    }
