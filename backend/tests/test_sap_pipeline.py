"""Tests for the autonomous SAP RAG pipeline (mock SAP layer).

No network: every LLM call is mocked, mirroring test_mis_pipeline.py's pattern.
"""
import os
import sys
from unittest.mock import patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sap_service import SAPService
from sap_router import SAPRouter


class _FakeMsg:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMsg(content)


class _FakeResp:
    def __init__(self, content, model='MOCK'):
        self.choices = [_FakeChoice(content)]
        self.model = model
        self.created = 0


# ── SAPService ────────────────────────────────────────────────────────────────

def test_catalog_shape():
    datasets = SAPService().get_available_datasets()
    assert len(datasets) >= 3
    for d in datasets:
        assert {'id', 'name', 'description'} <= set(d.keys())


def test_fetch_known_dataset_returns_dataframe():
    df = SAPService().fetch_dataset('sap_001')
    assert isinstance(df, pd.DataFrame) and not df.empty
    assert 'Total_Spend_USD' in df.columns


def test_fetch_is_deterministic():
    svc = SAPService()
    a, b = svc.fetch_dataset('sap_002'), svc.fetch_dataset('sap_002')
    pd.testing.assert_frame_equal(a, b)


def test_fetch_unknown_dataset_raises():
    with pytest.raises(KeyError):
        SAPService().fetch_dataset('sap_999')


# ── SAPRouter ─────────────────────────────────────────────────────────────────

def test_router_llm_tier_parses_id():
    datasets = SAPService().get_available_datasets()
    with patch('sap_router.create_chat_completion',
               return_value=_FakeResp('The best dataset is sap_003.')):
        route = SAPRouter().route('which vendors are blocked for compliance?', datasets)
    assert route['dataset_id'] == 'sap_003'
    assert route['tier'] == 'llm'


def test_router_keyword_fallback_on_garbage_llm():
    datasets = SAPService().get_available_datasets()
    with patch('sap_router.create_chat_completion',
               return_value=_FakeResp('I cannot decide, sorry!')):
        route = SAPRouter().route('total spend for IT vendors this quarter', datasets)
    assert route['tier'] == 'keyword'
    assert route['dataset_id'] == 'sap_001'  # vendor spend dataset


def test_router_keyword_fallback_on_provider_failure():
    datasets = SAPService().get_available_datasets()
    with patch('sap_router.create_chat_completion', side_effect=RuntimeError('all providers down')):
        route = SAPRouter().route('open purchase orders awaiting delivery', datasets)
    assert route['tier'] == 'keyword'
    assert route['dataset_id'] == 'sap_002'


# ── analyze_sap_query (end-to-end with mocked codegen) ───────────────────────

def test_analyze_success_includes_referenced_file():
    import sap_analyzer
    code = "result = float(df['Total_Spend_USD'].sum())"
    with patch('sap_router.create_chat_completion', return_value=_FakeResp('sap_001')), \
         patch('sap_analyzer.create_chat_completion', return_value=_FakeResp(code)):
        out = sap_analyzer.analyze_sap_query('total vendor spend?')
    assert out['status'] == 'success'
    assert out['referenced_file']['id'] == 'sap_001'
    assert out['referenced_file']['name'] == 'Q3_Vendor_Spend.xlsx'
    assert any(ch.isdigit() for ch in out['answer'])


def test_analyze_honest_failure_when_code_always_breaks():
    import sap_analyzer
    with patch('sap_router.create_chat_completion', return_value=_FakeResp('sap_001')), \
         patch('sap_analyzer.create_chat_completion', return_value=_FakeResp('result = undefined_name')):
        out = sap_analyzer.analyze_sap_query('total vendor spend?')
    assert out['status'] == 'error'
    assert 'could not compute' in out['error'].lower()
    # even on failure the routed file is cited so the UI can show context
    assert out['referenced_file']['id'] == 'sap_001'


def test_analyze_empty_query_rejected():
    import sap_analyzer
    out = sap_analyzer.analyze_sap_query('   ')
    assert out['status'] == 'error'


# ── Endpoint ──────────────────────────────────────────────────────────────────

def test_sap_query_endpoint():
    from fastapi.testclient import TestClient
    import main
    code = "result = float(df['Total_Spend_USD'].sum())"
    with patch('sap_router.create_chat_completion', return_value=_FakeResp('sap_001')), \
         patch('sap_analyzer.create_chat_completion', return_value=_FakeResp(code)):
        client = TestClient(main.app)
        r = client.post('/api/sap-query', json={'query': 'total vendor spend?'})
    assert r.status_code == 200
    body = r.json()
    assert body['status'] == 'success'
    assert body['referenced_file']['name'].endswith('.xlsx')
