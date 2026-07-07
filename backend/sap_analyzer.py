"""
Autonomous SAP query pipeline: route → fetch → analyze → cite.

analyze_sap_query() is the single entry point behind POST /api/sap-query:

  1. SAPRouter picks the dataset whose metadata best matches the question
     (LLM tier over the existing Groq/Cerebras/OpenRouter/Phi3 fallback chain,
     keyword tier as the no-token fallback).
  2. SAPService fetches that dataset as a pandas DataFrame.
  3. A pandas agent answers the question against the DataFrame: the LLM
     (same fallback chain) generates pandas code, which executes in the
     restricted, timeout-guarded sandbox from model_b_agent. Execution is the
     ground truth — the model never does arithmetic in prose.
  4. The response carries the referenced-file metadata so the frontend can
     render the "SAP Data Sources" sidebar citation.

ARCHITECTURAL NOTE — pandas agent implementation: the spec suggested
LangChain's create_pandas_dataframe_agent. That API requires a LangChain LLM
object, which the project's custom multi-provider fallback chain is not, and
the repo already ships an equivalent, security-audited PAL implementation
(model_b_agent's restricted-builtins sandbox: no imports, no file/network
access, 30s timeout). Reusing it keeps one code path for "LLM writes pandas,
interpreter computes the answer" and honors the hard constraint that ALL AI
calls ride the existing fallback chain.

Failure contract (Phase 3 discipline): every exit returns an explicit status —
a computed answer or a specific "couldn't compute" message. No silent guesses.
"""
import logging
from typing import Dict, Optional

from ai_orchestrator import create_chat_completion
from model_b_agent import _extract_code, _format_result, _run_sandbox
from sap_router import SAPRouter
from sap_service import SAPService

logger = logging.getLogger('procure_ai')

_sap_service = SAPService()


def _generate_and_run(user_query: str, df, provider_key: str,
                      dataset_meta: Optional[Dict] = None) -> Dict:
    """LLM → pandas code → sandbox execution, with one self-correction retry.

    Returns {'answer': str} on success or {'error': str} after both attempts.
    """
    meta_line = ''
    if dataset_meta:
        # The dataset's business identity often carries context the columns
        # don't (e.g. "Q3_Vendor_Spend" answers WHICH quarter Total_Spend_USD
        # covers) — without it the model wrongly refuses time-scoped questions.
        meta_line = (f'Dataset: {dataset_meta.get("name")} — '
                     f'{dataset_meta.get("description")}\n')
    schema = (
        f'{meta_line}'
        f'DataFrame `df` — {len(df)} rows x {len(df.columns)} columns\n'
        f'Columns: {", ".join(str(c) for c in df.columns)}\n'
        f'Dtypes: {", ".join(f"{c}={df[c].dtype}" for c in df.columns)}\n'
        f'First rows:\n{df.head(3).to_string(index=False)}'
    )
    code_prompt = (
        f'{schema}\n\n'
        f'Question: "{user_query}"\n\n'
        'Write Python/pandas code that computes the answer from `df` and assigns '
        'it to a variable named `result`.\n'
        'Rules:\n'
        '- `df` is already loaded; do NOT read files or import anything\n'
        '- result must be a number, string, list, Series, or DataFrame\n'
        '- If the data cannot answer the question, set result = '
        '"Cannot determine from the available data."\n'
        'Return ONLY executable Python code — no markdown fences, no explanation.'
    )
    sheets = {'sap_data': df}

    resp = create_chat_completion(
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
    code = _extract_code(resp.choices[0].message.content)
    out = _run_sandbox(code, sheets)

    if out.get('error'):
        fix = create_chat_completion(
            [
                {'role': 'system', 'content': (
                    'You fix broken Python/pandas code. Output the corrected code '
                    'only — no explanation, no fences.'
                )},
                {'role': 'user', 'content': (
                    f'This code raised an error:\n\n{code}\n\nError: {out["error"]}\n\n'
                    'Fix it so it runs correctly and stores the answer in `result`.'
                )},
            ],
            max_tokens=700,
            model_key=provider_key,
        )
        out = _run_sandbox(_extract_code(fix.choices[0].message.content), sheets)

    if out.get('error'):
        return {'error': out['error']}
    return {'answer': _format_result(out.get('result'))}


def analyze_sap_query(user_query: str, provider_key: str = 'auto') -> Dict:
    """Answer a procurement question from the SAP dataset catalog.

    Returns a unified JSON-safe dict:
      success — {"status": "success", "answer": str,
                 "referenced_file": {"id", "name", "description", ...},
                 "router": {"tier", "reason"}}
      error   — {"status": "error", "error": <specific message>,
                 "referenced_file": <dict or None>}
    """
    if not (user_query or '').strip():
        return {'status': 'error', 'error': 'Empty query.', 'referenced_file': None}

    # 1. Route
    datasets = _sap_service.get_available_datasets()
    try:
        route = SAPRouter(provider_key=provider_key).route(user_query, datasets)
    except Exception as exc:
        logger.warning(f'analyze_sap_query: routing failed: {exc}')
        return {'status': 'error',
                'error': f'Could not determine which SAP dataset holds this answer ({exc}).',
                'referenced_file': None}

    dataset_id = route['dataset_id']
    meta = _sap_service.get_dataset_meta(dataset_id)

    # 2. Fetch
    try:
        df = _sap_service.fetch_dataset(dataset_id)
    except Exception as exc:
        logger.warning(f'analyze_sap_query: fetch failed for {dataset_id}: {exc}')
        return {'status': 'error',
                'error': f'Failed to fetch SAP dataset "{meta["name"] if meta else dataset_id}": {exc}',
                'referenced_file': meta}

    # 3. Analyze (PAL: generated pandas executed in the sandbox)
    try:
        result = _generate_and_run(user_query, df, provider_key, dataset_meta=meta)
    except Exception as exc:
        logger.warning(f'analyze_sap_query: agent failed on {dataset_id}: {exc}')
        result = {'error': str(exc)}

    if result.get('error'):
        return {
            'status': 'error',
            'error': (
                f'I located the relevant dataset ("{meta["name"]}") but could not '
                f'compute the answer from it — the generated analysis code failed '
                f'({result["error"][:120]}). Try rephrasing with the exact column '
                f'or measure you need.'
            ),
            'referenced_file': meta,
        }

    logger.info(f'analyze_sap_query: dataset={dataset_id} tier={route["tier"]} ok')
    return {
        'status': 'success',
        'answer': result['answer'],
        'referenced_file': meta,
        'router': {'tier': route['tier'], 'reason': route['reason']},
    }
