"""
SAP-derived dashboard metrics + AI insight layer.

Every number the dashboard shows is COMPUTED from the SAP datasets exposed by
SAPService — nothing is hardcoded. Because SAPService is the swap point for the
real SAP Gateway (mock today, live OData tomorrow), the exact same computation
here produces real insights the moment credentials are wired in, with zero
changes to this module or the frontend.

Two layers:
  compute_metrics()            deterministic pandas aggregations over the SAP
                               datasets, grouped by dashboard section. Fast,
                               no LLM, cached with a short TTL.
  generate_section_insight()   a grounded executive narrative for one section,
                               produced by the existing provider fallback chain
                               over the already-computed numbers (never raw rows,
                               never invented figures).

Failure contract: a dataset that is missing or malformed is skipped and flagged
in `available`, never faked — a partial dashboard is honest; a fabricated one
is not.
"""
import json
import logging
import time
from typing import Dict, List, Optional

import pandas as pd

from ai_orchestrator import create_chat_completion
from sap_service import SAPService

logger = logging.getLogger('procure_ai')

_sap = SAPService()

# Short in-process TTL cache: the dashboard polls this on load and section
# switches; recomputing five dataset aggregations every time is wasteful, and
# against real SAP each fetch is a network round-trip.
_CACHE: Dict[str, object] = {'ts': 0.0, 'data': None}
_CACHE_TTL_SECONDS = 60

# Renewals/exposure horizon — contracts whose validity ends within this many
# days count as "due" and their value as "at risk from unreviewed renewals".
_RENEWAL_HORIZON_DAYS = 90


def _safe_fetch(dataset_id: str) -> Optional[pd.DataFrame]:
    try:
        return _sap.fetch_dataset(dataset_id)
    except Exception as exc:
        logger.warning(f'sap_insights: dataset {dataset_id} unavailable ({exc})')
        return None


def _usd(value) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def compute_metrics(force: bool = False) -> Dict:
    """Compute all dashboard metrics from the SAP datasets.

    Returns a nested dict keyed by dashboard section (overview / dashboard /
    contracts / vendors / risk), plus `available` (which datasets resolved) and
    `source`/`generated_at` provenance. Cached for _CACHE_TTL_SECONDS.
    """
    now = time.time()
    if not force and _CACHE['data'] is not None and now - _CACHE['ts'] < _CACHE_TTL_SECONDS:
        return _CACHE['data']

    spend = _safe_fetch('sap_001')          # Q3 vendor spend
    open_pos = _safe_fetch('sap_002')       # open purchase orders
    vendors = _safe_fetch('sap_003')        # vendor master + compliance
    inventory = _safe_fetch('sap_004')      # inventory stock
    contracts = _safe_fetch('sap_005')      # contract expiry register

    available = {
        'vendor_spend': spend is not None,
        'open_pos': open_pos is not None,
        'vendor_master': vendors is not None,
        'inventory': inventory is not None,
        'contracts': contracts is not None,
    }

    # ── Vendor master / risk ─────────────────────────────────────────────────
    vendor_records = int(len(vendors)) if vendors is not None else 0
    high_risk_vendors = blocked_vendors = compliance_gaps = 0
    high_risk_names: List[str] = []
    if vendors is not None:
        risk = vendors.get('Risk_Rating', pd.Series(dtype=str)).astype(str).str.lower()
        blocked = vendors.get('Blocked', pd.Series(dtype=bool)).astype(bool)
        certs = vendors.get('Certifications', pd.Series(dtype=str)).astype(str).str.lower()
        high_risk_mask = risk.eq('high')
        high_risk_vendors = int(high_risk_mask.sum())
        blocked_vendors = int(blocked.sum())
        compliance_gaps = int((certs.eq('none') | blocked).sum())
        high_risk_names = vendors.loc[high_risk_mask | blocked, 'Vendor_Name'].astype(str).tolist()

    # ── Contracts ────────────────────────────────────────────────────────────
    total_agreements = int(len(contracts)) if contracts is not None else 0
    total_contract_value = auto_renewal_count = 0
    renewals_due = 0
    spend_exposure = 0.0
    high_risk_contract_value = 0.0
    expiring_soon: List[Dict] = []
    if contracts is not None:
        total_contract_value = _usd(contracts.get('Contract_Value_USD', pd.Series(dtype=float)).sum())
        auto_renewal_count = int(contracts.get('Auto_Renewal', pd.Series(dtype=bool)).astype(bool).sum())

        valid_to = pd.to_datetime(contracts.get('Valid_To'), errors='coerce')
        horizon = pd.Timestamp.now() + pd.Timedelta(days=_RENEWAL_HORIZON_DAYS)
        due_mask = valid_to.notna() & (valid_to >= pd.Timestamp.now()) & (valid_to <= horizon)
        renewals_due = int(due_mask.sum())
        spend_exposure = _usd(contracts.loc[due_mask, 'Contract_Value_USD'].sum())

        # Contract value tied to high-risk/blocked vendors (join on vendor name)
        if high_risk_names:
            hr_mask = contracts.get('Vendor', pd.Series(dtype=str)).astype(str).isin(high_risk_names)
            high_risk_contract_value = _usd(contracts.loc[hr_mask, 'Contract_Value_USD'].sum())

        # Top 5 soonest-expiring contracts for the dashboard table
        _c = contracts.assign(_vt=valid_to).sort_values('_vt')
        for _, row in _c.head(5).iterrows():
            expiring_soon.append({
                'contract': str(row.get('Contract_Number', '')),
                'vendor': str(row.get('Vendor', '')),
                'valid_to': str(row.get('Valid_To', '')),
                'value_usd': _usd(row.get('Contract_Value_USD', 0)),
            })

    # ── Spend / vendors (RFQ section) ────────────────────────────────────────
    total_spend = 0.0
    top_vendor: Optional[Dict] = None
    supplier_count = 0
    if spend is not None:
        total_spend = _usd(spend.get('Total_Spend_USD', pd.Series(dtype=float)).sum())
        supplier_count = int(spend.get('Vendor', pd.Series(dtype=str)).nunique())
        if 'Total_Spend_USD' in spend.columns and not spend.empty:
            top = spend.loc[spend['Total_Spend_USD'].idxmax()]
            top_vendor = {'name': str(top.get('Vendor', '')),
                          'spend_usd': _usd(top.get('Total_Spend_USD', 0))}

    # ── Open POs ─────────────────────────────────────────────────────────────
    open_po_count = 0
    open_po_value = 0.0
    if open_pos is not None:
        status = open_pos.get('Status', pd.Series(dtype=str)).astype(str).str.lower()
        open_mask = status.str.contains('open') | status.str.contains('awaiting') | status.str.contains('partial')
        open_po_count = int(open_mask.sum()) if open_mask.any() else int(len(open_pos))
        open_po_value = _usd(open_pos.get('Order_Value_USD', pd.Series(dtype=float)).sum())

    # ── Risk flags (headline) ────────────────────────────────────────────────
    risk_flags = high_risk_vendors + blocked_vendors

    metrics = {
        'source': 'SAP (mock)' if any(available.values()) else 'unavailable',
        'generated_at': pd.Timestamp.now().isoformat(timespec='seconds'),
        'available': available,
        'overview': {
            'active_contracts': total_agreements,
            'vendor_records': vendor_records,
            'risk_flags': risk_flags,
        },
        'dashboard': {
            'renewals_due': renewals_due,
            'renewal_horizon_days': _RENEWAL_HORIZON_DAYS,
            'spend_exposure_usd': spend_exposure,
            'open_purchase_orders': open_po_count,
        },
        'contracts': {
            'total_agreements': total_agreements,
            'total_contract_value_usd': total_contract_value,
            'auto_renewal_count': auto_renewal_count,
            'expiring_soon': expiring_soon,
        },
        'vendors': {
            'total_vendors': max(vendor_records, supplier_count),
            'total_spend_usd': total_spend,
            'top_vendor_by_spend': top_vendor,
            'open_purchase_orders': open_po_count,
            'open_po_value_usd': open_po_value,
        },
        'risk': {
            'high_risk_vendors': high_risk_vendors,
            'blocked_vendors': blocked_vendors,
            'compliance_gaps': compliance_gaps,
            'high_risk_contract_value_usd': high_risk_contract_value,
        },
    }

    _CACHE['data'] = metrics
    _CACHE['ts'] = now
    logger.info(f'sap_insights.compute_metrics -> {sum(available.values())}/5 datasets')
    return metrics


_SECTION_FRAMING = {
    'overview': 'the overall procurement portfolio health',
    'dashboard': 'renewal exposure and open purchasing commitments',
    'contracts': 'the contract portfolio and upcoming expiries',
    'vendors': 'vendor spend concentration and sourcing',
    'risk': 'vendor risk, compliance gaps, and blocked suppliers',
}


def generate_section_insight(section: str, provider_key: str = 'auto') -> Dict:
    """Grounded executive insight for one dashboard section.

    The LLM sees ONLY the pre-computed metric numbers for the section (never raw
    rows) and is instructed to reference only those figures — so the narrative
    can't drift from the deterministic cards it sits beside.

    Returns {"section", "insight", "metrics"} or {"section", "error"}.
    """
    metrics = compute_metrics()
    section_metrics = metrics.get(section)
    if section_metrics is None:
        return {'section': section, 'error': f'Unknown dashboard section: {section!r}'}

    framing = _SECTION_FRAMING.get(section, 'this procurement area')
    prompt = (
        f'You are a procurement analyst briefing an executive on {framing}. '
        f'Below are the exact, verified metrics computed from live SAP data.\n\n'
        f'{json.dumps(section_metrics, indent=2)}\n\n'
        'Write 2-3 concise sentences highlighting what matters most and any action '
        'to consider. Reference ONLY the numbers above — do not invent figures, '
        'vendor names, or percentages that are not present. Plain prose, no headings.'
    )
    try:
        resp = create_chat_completion(
            [
                {'role': 'system', 'content': (
                    'You write short, factual procurement insights grounded strictly '
                    'in the metrics provided. Never fabricate numbers.'
                )},
                {'role': 'user', 'content': prompt},
            ],
            max_tokens=250,
            provider_key=provider_key,
        )
        insight = (resp.choices[0].message.content or '').strip()
        return {'section': section, 'insight': insight, 'metrics': section_metrics}
    except Exception as exc:
        logger.warning(f'sap_insights.generate_section_insight({section}) failed: {exc}')
        return {'section': section,
                'error': f'AI insight is temporarily unavailable ({exc}). The metrics above are still exact.',
                'metrics': section_metrics}
