"""Tests for the SAP-derived dashboard metrics + AI insight layer."""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import sap_insights


class _FakeMsg:
    def __init__(self, content):
        self.content = content


class _FakeResp:
    def __init__(self, content, model='MOCK'):
        self.choices = [type('C', (), {'message': _FakeMsg(content)})()]
        self.model = model
        self.created = 0


def test_metrics_structure_and_sections():
    metrics = sap_insights.compute_metrics(force=True)
    for section in ('overview', 'dashboard', 'contracts', 'vendors', 'risk'):
        assert section in metrics
    assert set(metrics['available']) >= {'vendor_master', 'contracts', 'vendor_spend'}


def test_overview_numbers_are_derived_not_hardcoded():
    metrics = sap_insights.compute_metrics(force=True)
    ov = metrics['overview']
    # Derived counts must match the underlying datasets, not the old demo values.
    from sap_service import SAPService
    svc = SAPService()
    assert ov['vendor_records'] == len(svc.fetch_dataset('sap_003'))
    assert ov['active_contracts'] == len(svc.fetch_dataset('sap_005'))
    assert ov['vendor_records'] != 482  # old hardcoded demo number is gone


def test_risk_flags_match_vendor_master():
    metrics = sap_insights.compute_metrics(force=True)
    from sap_service import SAPService
    vm = SAPService().fetch_dataset('sap_003')
    expected = int((vm['Risk_Rating'].str.lower() == 'high').sum()) + int(vm['Blocked'].sum())
    assert metrics['overview']['risk_flags'] == expected


def test_spend_exposure_is_numeric():
    metrics = sap_insights.compute_metrics(force=True)
    assert isinstance(metrics['dashboard']['spend_exposure_usd'], (int, float))
    assert metrics['dashboard']['open_purchase_orders'] >= 0


def test_cache_returns_same_object_within_ttl():
    a = sap_insights.compute_metrics(force=True)
    b = sap_insights.compute_metrics(force=False)
    assert a is b  # served from cache


def test_section_insight_grounded_success():
    with patch('sap_insights.create_chat_completion',
               return_value=_FakeResp('Renewals are concentrated in the next quarter.')):
        out = sap_insights.generate_section_insight('dashboard')
    assert 'insight' in out
    assert out['metrics'] == sap_insights.compute_metrics()['dashboard']


def test_section_insight_unknown_section():
    out = sap_insights.generate_section_insight('nonsense')
    assert 'error' in out


def test_section_insight_provider_failure_keeps_metrics():
    with patch('sap_insights.create_chat_completion', side_effect=RuntimeError('down')):
        out = sap_insights.generate_section_insight('risk')
    assert 'error' in out and out['metrics'] is not None


def test_metrics_endpoint():
    from fastapi.testclient import TestClient
    import main
    client = TestClient(main.app)
    r = client.get('/api/sap-metrics')
    assert r.status_code == 200
    assert r.json()['overview']['vendor_records'] > 0


def test_insight_endpoint():
    from fastapi.testclient import TestClient
    import main
    with patch('sap_insights.create_chat_completion', return_value=_FakeResp('Grounded summary.')):
        client = TestClient(main.app)
        r = client.post('/api/sap-insight', json={'section': 'overview'})
    assert r.status_code == 200
    assert 'insight' in r.json()
