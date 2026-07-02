"""
Phase 2 unit tests — _clean_sheet_headers.

Tests use small in-memory DataFrames replicating MIS workbook sheet structures.
No network or file I/O needed.
"""
import sys
import os
import numpy as np
import pandas as pd
import pytest

# Make backend importable from the tests sub-directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Import only the pure helper functions (no FastAPI startup side-effects)
from main import _clean_sheet_headers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unnamed_pct(df):
    """Fraction of columns that are still Unnamed:N or Col_N."""
    unnamed = sum(1 for c in df.columns if str(c).startswith('Unnamed:') or str(c).startswith('Col_'))
    return unnamed / max(len(df.columns), 1)


# ---------------------------------------------------------------------------
# Test 1 — Sheet '1' pattern: Q1 title → Actual/Budget group → real header
# ---------------------------------------------------------------------------

def test_sheet1_compound_headers():
    """Sheet '1': Q1 title row, then Actual/Budget group row (SPARSE — merged cells),
    then real header row. Expected: compound cols like Actual_Sales, Budget_PBT.

    In Excel, 'Actual' is a merged cell spanning columns 1-2; 'Budget' spans 3-4.
    Pandas reads this as: one 'Actual' + NaNs under it, then 'Budget' + NaNs.
    That makes the group row sparse (2 non-null / 5 cols = 40%), which is exactly
    what _is_group_label_row detects.
    """
    # Simulate merged-cell group row: 'Actual' once (col 1), 'Budget' once (col 4).
    # In Excel, both are merged cells spanning 3 sub-columns each.
    # With 7 total columns, fill ratio = 2/7 ≈ 29% — well below the 40% threshold
    # that _is_group_label_row uses to distinguish group rows from header rows.
    data = {
        'Unnamed: 0': ['Q1',   np.nan,   'Country', 'India', 'China'],
        'Unnamed: 1': [np.nan, 'Actual', 'Sales',   100,     200   ],
        'Unnamed: 2': [np.nan, np.nan,   'PBT',     10,      20    ],
        'Unnamed: 3': [np.nan, np.nan,   'Dep',     5,       8     ],
        'Unnamed: 4': [np.nan, 'Budget', 'Sales',   90,      180   ],
        'Unnamed: 5': [np.nan, np.nan,   'PBT',     9,       18    ],
        'Unnamed: 6': [np.nan, np.nan,   'Dep',     4,       7     ],
    }
    df = pd.DataFrame(data)
    result = _clean_sheet_headers(df)

    cols = list(result.columns)
    assert any('Actual' in c for c in cols), f"Expected Actual group in columns: {cols}"
    assert any('Budget' in c for c in cols), f"Expected Budget group in columns: {cols}"
    assert any('Sales' in c for c in cols), f"Expected Sales in columns: {cols}"
    assert any('PBT' in c for c in cols), f"Expected PBT in columns: {cols}"
    assert len(result) >= 2


# ---------------------------------------------------------------------------
# Test 2 — Sheet '15.1' pattern: title → blank → junk → real header
# ---------------------------------------------------------------------------

def test_sheet_151_customer_header():
    """Sheet '15.1': 3 junk rows then real header with 'Customer'."""
    data = {
        'Unnamed: 0': [
            'Customer Wise Revenue Report',
            np.nan,
            np.nan,
            'Customer',
            'Acme Corp',
            'Beta Ltd',
        ],
        'Unnamed: 1': [
            np.nan, np.nan, np.nan,
            'FY 24-25',
            500, 300,
        ],
        'Unnamed: 2': [
            np.nan, np.nan, np.nan,
            '% FY 24-25',
            0.62, 0.38,
        ],
        'Unnamed: 3': [
            np.nan, np.nan, np.nan,
            'FY 23-24',
            400, 250,
        ],
        'Unnamed: 4': [
            np.nan, np.nan, np.nan,
            'Remarks',
            'Growth', 'Stable',
        ],
    }
    df = pd.DataFrame(data)
    result = _clean_sheet_headers(df)

    cols = list(result.columns)
    assert 'Customer' in cols, f"Expected 'Customer' column, got: {cols}"
    assert _unnamed_pct(result) < 0.30, f"Too many Unnamed cols: {cols}"
    assert len(result) >= 2


# ---------------------------------------------------------------------------
# Test 3 — Sheet '8' pattern: group row "Actual - Q1'23-24" above real header
# ---------------------------------------------------------------------------

def test_sheet8_group_row_above_header():
    """Sheet '8': blank first row, then group row, then real header."""
    group_label = "Actual - Q1'23-24"
    data = {
        'Unnamed: 0': [
            np.nan,
            group_label,
            'Profit Centre/Customer',
            'Supplier A',
            'Supplier B',
        ],
        'Unnamed: 1': [
            np.nan, np.nan,
            'Woven/Knit',
            'Woven', 'Knit',
        ],
        'Unnamed: 2': [
            np.nan, np.nan,
            'Pcs (Lacs)',
            10, 20,
        ],
    }
    df = pd.DataFrame(data)
    result = _clean_sheet_headers(df)

    cols = list(result.columns)
    has_customer_col = any('Customer' in c or 'Profit' in c for c in cols)
    assert has_customer_col, f"Expected customer-related column, got: {cols}"
    assert len(result) >= 2


# ---------------------------------------------------------------------------
# Test 4 — Clean single-header sheet passes through unchanged
# ---------------------------------------------------------------------------

def test_clean_single_header_unchanged():
    """A sheet with proper column names must be returned unchanged."""
    df = pd.DataFrame({
        'Country': ['India', 'China'],
        'Revenue': [100, 200],
        'Cost': [50, 80],
    })
    result = _clean_sheet_headers(df)
    assert list(result.columns) == ['Country', 'Revenue', 'Cost']
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Test 5 — No Unnamed columns > 30% for sheets with header text
# ---------------------------------------------------------------------------

def test_unnamed_fraction_below_threshold():
    """Any sheet containing string header content must end up with < 30% Unnamed cols."""
    data = {
        'Unnamed: 0': ['Sheet Title', np.nan, 'Item', 'Widget', 'Gadget'],
        'Unnamed: 1': [np.nan, np.nan, 'Qty', 10, 5],
        'Unnamed: 2': [np.nan, np.nan, 'Price', 99.9, 49.9],
        'Unnamed: 3': [np.nan, np.nan, 'Total', 999, 249.5],
    }
    df = pd.DataFrame(data)
    result = _clean_sheet_headers(df)
    assert _unnamed_pct(result) < 0.30, (
        f"Too many Unnamed columns after cleaning: {list(result.columns)}"
    )
