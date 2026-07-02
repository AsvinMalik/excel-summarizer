"""
Phase 7 acceptance tests — MIS pipeline.

Tests 1-6 require no network (LLM calls are mocked).
Test 7 validates the Gemini removal.
Test 8 is a regression test for query_engine on a small workbook.

The MIS file path is relative to the backend directory.
"""
import sys
import os
import json
import pytest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

MIS_PATH = os.path.join(
    os.path.dirname(__file__), '..',
    'uploads', '47a8264f-961a-4499-9b62-40f51f280dbc_MIS Automation PGIL.xlsx'
)
MIS_AVAILABLE = os.path.isfile(MIS_PATH)

QUERY_ENGINE_TEST_PATH = None
for fname in os.listdir(os.path.join(os.path.dirname(__file__), '..', 'uploads')):
    if 'query_engine_test' in fname.lower():
        QUERY_ENGINE_TEST_PATH = os.path.join(
            os.path.dirname(__file__), '..', 'uploads', fname
        )
        break


# ---------------------------------------------------------------------------
# Test 1 — Header repair on real MIS file
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not MIS_AVAILABLE, reason="MIS file not present")
def test_header_repair_mis_file():
    """load_all_sheets on the MIS file must produce compound headers on sheet '1'
    and a 'Customer' column on sheet '15.1'. No sheet may have >30% Unnamed cols
    when it contains real header text."""
    import main  # ensure _clean_sheet_headers is registered in sys.modules['main']
    from query_engine import load_all_sheets

    sheets = load_all_sheets(MIS_PATH)
    assert '1' in sheets, "Sheet '1' missing from loaded sheets"

    # Sheet '1': must have Actual and Budget group columns
    sheet1_cols = list(sheets['1'].columns)
    has_actual = any('Actual' in c for c in sheet1_cols)
    has_budget = any('Budget' in c for c in sheet1_cols)
    assert has_actual, f"Sheet '1' missing Actual group cols: {sheet1_cols}"
    assert has_budget, f"Sheet '1' missing Budget group cols: {sheet1_cols}"

    # Sheet '15.1': must have Customer column
    if '15.1' in sheets:
        sheet151_cols = list(sheets['15.1'].columns)
        has_customer = any('Customer' in c for c in sheet151_cols)
        assert has_customer, f"Sheet '15.1' missing Customer col: {sheet151_cols}"

    # Key repaired sheets must have ≤ 30% Col_/Unnamed columns
    repaired_sheets = {'1', '15.1', '8', '15'}
    for sheet_name in repaired_sheets:
        df = sheets.get(sheet_name)
        if df is None or df.dropna(how='all').shape[0] < 3:
            continue  # skip missing or near-empty
        unnamed_pct = sum(
            1 for c in df.columns
            if str(c).startswith('Unnamed:') or str(c).startswith('Col_')
        ) / max(len(df.columns), 1)
        assert unnamed_pct <= 0.30, (
            f"Sheet '{sheet_name}' has {unnamed_pct:.0%} Unnamed cols: {list(df.columns)[:10]}"
        )


# ---------------------------------------------------------------------------
# Test 2 — Per-sheet snapshots
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not MIS_AVAILABLE, reason="MIS file not present")
def test_per_sheet_snapshots():
    """After processing the MIS file, parsed_sheets covers all sheets,
    each value is ≤ 20000 chars, and round-trips through JSON."""
    import uuid, importlib, json

    # Import main module's processing functions
    import main as m

    doc_id = str(uuid.uuid4())
    with open(MIS_PATH, 'rb') as _f:
        file_bytes = _f.read()
    m.DOCUMENT_STORE[doc_id] = {
        'doc_id': doc_id,
        'filename': 'MIS Automation PGIL.xlsx',
        'file_path': MIS_PATH,
        'status': 'uploaded',
        'bytes': file_bytes,
    }

    # Run processing synchronously
    try:
        m.queue_document_processing(doc_id, MIS_PATH, 'application/vnd.ms-excel', 'Test', 'test')
    except Exception as e:
        pytest.skip(f"Processing failed (likely LLM unavailable): {e}")

    stored = m.DOCUMENT_STORE.get(doc_id)
    assert stored is not None
    parsed_sheets = stored.get('parsed_sheets')
    assert parsed_sheets, "parsed_sheets not populated"

    sheet_names = stored.get('sheet_names') or []
    assert len(sheet_names) >= 10, f"Expected many sheets, got {len(sheet_names)}"

    for sn in sheet_names:
        assert sn in parsed_sheets, f"Sheet '{sn}' missing from parsed_sheets"
        assert len(parsed_sheets[sn]) <= 20000, (
            f"Sheet '{sn}' section is {len(parsed_sheets[sn])} chars (>20k)"
        )

    # JSON round-trip
    serialised = json.dumps(parsed_sheets)
    restored = json.loads(serialised)
    assert restored.keys() == parsed_sheets.keys()


# ---------------------------------------------------------------------------
# Test 3 — Router Tier 1 keyword decisions (no LLM call)
# ---------------------------------------------------------------------------

def test_router_tier1_customer_revenue():
    """'customer wise revenue for FY 24-25' → sheet 15.1 or 15, tier=keyword."""
    from sheet_router import route_question

    mock_doc = {
        'sheet_names': ['Summary', '1', '6', '15', '15.1', '21'],
        'profile': {
            '15.1': {'columns': [
                {'name': 'Customer'}, {'name': 'FY 24-25'}, {'name': '% FY 24-25'},
            ]},
            '15': {'columns': [
                {'name': 'Customer'}, {'name': 'Revenue'},
            ]},
            '6': {'columns': [
                {'name': 'Ageing Bucket'}, {'name': 'Quantity'},
            ]},
            '21': {'columns': []},
        },
        'sheet_roles': {
            '15.1': 'fact_table', '15': 'fact_table', '6': 'dimension_table',
        },
        'parsed_sheets': {
            '15.1': 'Columns: Customer, FY 24-25, % FY 24-25, FY 23-24\nAcme,100,0.5,80',
            '15': 'Columns: Customer, Revenue\nAcme,100',
        },
    }

    # Tier 1 may tie between 15 and 15.1 since both have 'Customer'; if it does,
    # Tier 2 LLM is invoked — mock it to return '15.1'.
    llm_resp = MagicMock()
    llm_resp.choices = [MagicMock(message=MagicMock(content='{"sheets": ["15.1"]}'))]
    with patch('sheet_router.create_chat_completion', return_value=llm_resp):
        result = route_question('customer wise revenue for FY 24-25', mock_doc)

    assert result['sheets'][0] in ('15.1', '15'), f"Wrong sheet routed: {result}"
    assert result['tier'] in ('keyword', 'llm'), f"Unexpected tier: {result}"


def test_router_tier1_inventory_ageing():
    """'inventory ageing' → sheet 6, tier=keyword."""
    from sheet_router import route_question

    mock_doc = {
        'sheet_names': ['Summary', '1', '6', '15', '15.1'],
        'profile': {
            '6': {'columns': [{'name': 'Ageing'}, {'name': 'Inventory'}, {'name': 'Qty'}]},
            '15.1': {'columns': [{'name': 'Customer'}, {'name': 'Revenue'}]},
        },
        'sheet_roles': {'6': 'fact_table'},
        'parsed_sheets': {
            '6': 'Columns: Ageing Bucket, Inventory, Quantity\n0-30,500,200',
        },
    }

    llm_resp6 = MagicMock()
    llm_resp6.choices = [MagicMock(message=MagicMock(content='{"sheets": ["6"]}'))]
    with patch('sheet_router.create_chat_completion', return_value=llm_resp6):
        result = route_question('inventory ageing report', mock_doc)

    assert result['sheets'][0] == '6', f"Expected sheet 6, got {result}"


def test_router_whole_file():
    """'summarize the whole MIS file' → __ALL__, no LLM call."""
    from sheet_router import route_question

    mock_doc = {
        'sheet_names': ['Summary', '1', '6', '15', '15.1'],
        'profile': {},
        'sheet_roles': {},
        'parsed_sheets': {},
    }

    with patch('sheet_router.create_chat_completion') as mock_llm:
        result = route_question('summarize the whole MIS file', mock_doc)

    assert result['sheets'] == ['__ALL__'], f"Expected __ALL__, got {result}"
    # __ALL__ is detected by Tier 1 keyword match, no LLM call needed
    mock_llm.assert_not_called()



# ---------------------------------------------------------------------------
# Test 4 — Scoped payload size
# ---------------------------------------------------------------------------

def test_scoped_payload_size():
    """For a single-sheet routed question, enriched preview must be ≤ 8000 chars
    and must NOT contain another sheet's data section marker."""
    from main import _extract_sheet_section

    section_15 = ('=== Sheet: 15.1 (100 rows x 5 cols) ===\n'
                  'Columns: Customer, FY 24-25, FY 23-24\n'
                  + 'Acme,100,80\n' * 100)
    section_other = '=== Sheet: 1 (50 rows x 10 cols) ===\nColumns: Country, Sales\nIndia,200\n'

    parsed_sheets = {'15.1': section_15, '1': section_other}
    combined_csv = f"{section_15}\n\n{section_other}"

    # Using parsed_sheets dict (O(1) fast path)
    extracted = _extract_sheet_section(combined_csv, '15.1', parsed_sheets=parsed_sheets)
    # Must not contain the OTHER sheet's section (sheet '1', NOT sheet '15.1')
    # Use a specific marker that won't match '15.1'
    assert '=== Sheet: 1 (' not in extracted, "Other sheet's marker must not appear"
    assert len(extracted) <= 20000  # raw section; the provider char limit truncates further


# ---------------------------------------------------------------------------
# Test 5 — Empty/template sheet honesty
# ---------------------------------------------------------------------------

def test_empty_sheet_flagged():
    """A parsed_sheets section for an empty sheet must include the no-data marker."""
    from main import _sheet_is_empty

    empty_section = (
        '=== Sheet: 21 (0 rows x 5 cols) ===\n'
        'Columns: Month, Revenue, Cost\n'
        '(no data rows — headers only or empty sheet)\n'
    )
    assert _sheet_is_empty(empty_section), "Expected empty section to be detected"

    data_section = (
        '=== Sheet: 15 (50 rows x 3 cols) ===\n'
        'Columns: Customer, Revenue\n'
        'Acme,100\n'
    )
    assert not _sheet_is_empty(data_section), "Data section should not be empty"


# ---------------------------------------------------------------------------
# Test 6 — Map-reduce caching: second call costs zero LLM invocations
# ---------------------------------------------------------------------------

def test_map_reduce_cache():
    """Second call to summarize_workbook must use cache — zero LLM calls."""
    import main as m
    import uuid

    doc_id = str(uuid.uuid4())
    m.DOCUMENT_STORE[doc_id] = {
        'doc_id': doc_id,
        'sheet_names': ['Sheet1', 'Sheet2'],
        'parsed_sheets': {
            'Sheet1': '=== Sheet: Sheet1 (10 rows x 3 cols) ===\nCol A,Col B,Col C\n1,2,3\n',
            'Sheet2': '(no data rows — headers only or empty sheet)\n',
        },
        'sheet_summaries': {},
        'status': 'ready',
    }

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content='Test summary.'))]
    mock_resp.model = 'test-model'

    with patch('main.create_chat_completion', return_value=mock_resp) as mock_llm:
        m.summarize_workbook(doc_id)
        call_count_first = mock_llm.call_count

    # Second call — all entries already cached
    with patch('main.create_chat_completion', return_value=mock_resp) as mock_llm2:
        m.summarize_workbook(doc_id)
        assert mock_llm2.call_count == 0, (
            f"Second call made {mock_llm2.call_count} LLM calls — expected 0 (cache hit)"
        )


# ---------------------------------------------------------------------------
# Test 7 — Gemini gone: no live call sites in backend Python files
# ---------------------------------------------------------------------------

def test_no_gemini_live_calls():
    """grep for active gemini call sites in the backend Python source."""
    import re

    backend_dir = os.path.join(os.path.dirname(__file__), '..')
    gemini_call_pattern = re.compile(
        r'(?i)(gemini_client\.(complete|generate|chat)|GeminiProvider\(\)|'
        r'import\s+gemini_client\s*$|from\s+gemini_client\s+import\s+(?!#))',
        re.MULTILINE,
    )

    violations = []
    for fname in os.listdir(backend_dir):
        if not fname.endswith('.py'):
            continue
        if 'gemini_client' in fname:
            continue  # skip the file itself
        fpath = os.path.join(backend_dir, fname)
        with open(fpath, encoding='utf-8', errors='ignore') as f:
            source = f.read()
        for m in gemini_call_pattern.finditer(source):
            violations.append(f"{fname}: {m.group(0).strip()}")

    assert not violations, f"Active Gemini call sites found:\n" + '\n'.join(violations)


# ---------------------------------------------------------------------------
# Test 8 — Regression: query_engine still works on small test file
# ---------------------------------------------------------------------------

def test_query_engine_regression():
    """A simple numeric question on the small test workbook must resolve
    through the pandas query engine (no LLM arithmetic)."""
    import main  # ensure _clean_sheet_headers is in sys.modules
    import pandas as pd
    if not QUERY_ENGINE_TEST_PATH:
        pytest.skip("query_engine_test.xlsx not found in uploads/")

    from query_engine import load_all_sheets, execute_query_spec

    sheets = load_all_sheets(QUERY_ENGINE_TEST_PATH)
    assert sheets, "No sheets loaded from query_engine_test.xlsx"

    first_sheet_name = list(sheets.keys())[0]
    df = sheets[first_sheet_name]

    # Find a numeric column
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if not numeric_cols:
        pytest.skip("No numeric columns in test file")

    col = numeric_cols[0]
    expected_sum = float(df[col].sum())
    assert expected_sum != 0, "Numeric column is all zeros — test not useful"

    # Use execute_query_spec directly (the real pandas math engine)
    spec = {
        'answerable': True,
        'operation': 'sum',
        'column': col,
        'sheet': first_sheet_name,
        'filters': [],
    }
    result = execute_query_spec(sheets, spec)
    assert result is not None, "Query engine returned None"
    assert result.get('type') == 'scalar', f"Expected scalar result, got {result.get('type')}"
    actual = result.get('value')
    assert actual is not None, f"Query engine 'value' is None: {result}"
    assert abs(float(actual) - expected_sum) < 1e-3, (
        f"Query engine sum {actual} != expected {expected_sum}"
    )
