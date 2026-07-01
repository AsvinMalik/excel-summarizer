"""Row-level data quality validation for uploaded workbooks.

Runs at upload time (same as the profiler) and produces structured issue lists
per sheet. Results are injected into LLM context as a [DATA QUALITY FLAGS]
block so the AI can proactively mention data problems in its answers rather
than silently working around them.

Checks performed per sheet:
  1. High null rate (>5%) per column — WARNING
  2. Negative values in spend/currency columns — ERROR
  3. Future dates in date/expiry columns — WARNING
  4. Out-of-range dates (before 1900 or after 2100) — ERROR
  5. Zero-variance numeric columns (all identical values) — CAUTION
  6. Statistical outliers (z-score > 3) in numeric columns — CAUTION
  7. Duplicate rows — WARNING
"""
import re
import pandas as pd


_SPEND_RE = re.compile(r'spend|cost|amount|amt|price|value|val|revenue|budget|expense|fee|charge|payment', re.IGNORECASE)
_DATE_COL_RE = re.compile(r'date|expir|due|deadline|renewal|period', re.IGNORECASE)


def _is_spend_column(col_name: str) -> bool:
    return bool(_SPEND_RE.search(col_name))


def _is_date_column(col_name: str) -> bool:
    return bool(_DATE_COL_RE.search(col_name))


def validate_sheet(df: pd.DataFrame, profile: dict, sheet_name: str) -> dict:
    issues = []
    row_count = max(profile.get('row_count', len(df)), 1)

    for col in profile.get('columns', []):
        col_name = col['name']
        null_count = col.get('null_count', 0)

        # 1. High null rate
        null_pct = null_count / row_count
        if null_pct > 0.05:
            issues.append({
                'severity': 'WARNING',
                'column': col_name,
                'issue': f'High null rate: {null_pct * 100:.1f}% of values missing',
                'recommendation': 'Consider imputation or exclusion from analysis',
            })

        if col['data_type'] == 'numeric':
            col_min = col.get('min')

            # 2. Negative values in spend columns
            if col_min is not None and col_min < 0 and _is_spend_column(col_name):
                issues.append({
                    'severity': 'ERROR',
                    'column': col_name,
                    'issue': f'Negative values in currency column (min = {col_min:,.2f})',
                    'recommendation': 'Verify whether these are credits/returns or a data entry error',
                })

            col_max = col.get('max')
            # 5. Zero variance
            if col_min is not None and col_max is not None and col_min == col_max:
                issues.append({
                    'severity': 'CAUTION',
                    'column': col_name,
                    'issue': 'All values identical — zero variance',
                    'recommendation': 'Column provides no differentiation; consider removing it',
                })
            else:
                # 6. Outliers — z-score > 3 (skip zero-variance columns)
                if col_name in df.columns:
                    series = pd.to_numeric(df[col_name], errors='coerce').dropna()
                    if len(series) >= 4:
                        stdev = series.std()
                        if stdev > 0:
                            z_scores = ((series - series.mean()) / stdev).abs()
                            outlier_count = int((z_scores > 3).sum())
                            if outlier_count > 0:
                                outlier_vals = series[z_scores > 3].tolist()
                                sample = ', '.join(f'{v:,.2f}' for v in outlier_vals[:3])
                                issues.append({
                                    'severity': 'CAUTION',
                                    'column': col_name,
                                    'issue': f'{outlier_count} outlier(s) detected (>3σ from mean) — e.g. {sample}',
                                    'recommendation': 'Investigate extreme values before aggregating',
                                })

        # 3 & 4. Date range checks
        if col_name in df.columns and _is_date_column(col_name):
            try:
                # Force everything through to_datetime then re-cast the resulting
                # Series explicitly — Excel columns can hold mixed Python datetime
                # objects and integers (e.g. year numbers) that survive errors='coerce'
                # as object dtype, causing '<' to fail between datetime and int.
                raw = pd.to_datetime(df[col_name], errors='coerce')
                date_series = pd.Series(
                    pd.to_datetime(raw, errors='coerce'), dtype='datetime64[ns]'
                ).dropna()
                if len(date_series) > 0:
                    now = pd.Timestamp.now().normalize()
                    future_count = int((date_series > now).sum())
                    if future_count > 0:
                        issues.append({
                            'severity': 'WARNING',
                            'column': col_name,
                            'issue': f'{future_count} future date(s) found',
                            'recommendation': 'Verify whether these are planned/scheduled dates or data errors',
                        })
                    min_date = date_series.min()
                    max_date = date_series.max()
                    lo = pd.Timestamp('1900-01-01')
                    hi = pd.Timestamp('2100-12-31')
                    if min_date < lo or max_date > hi:
                        issues.append({
                            'severity': 'ERROR',
                            'column': col_name,
                            'issue': f'Date out of valid range ({min_date.date()} to {max_date.date()})',
                            'recommendation': 'Likely a data entry error — verify source',
                        })
            except Exception:
                pass

    # 7. Duplicate rows
    dup_count = profile.get('duplicate_rows', 0)
    if dup_count > 0:
        issues.append({
            'severity': 'WARNING',
            'column': None,
            'issue': f'{dup_count} duplicate row(s) detected',
            'recommendation': 'De-duplicate before aggregation to avoid double-counting',
        })

    # Quality score: start at 100, deduct per severity
    _DEDUCTIONS = {'ERROR': 20, 'WARNING': 5, 'CAUTION': 2}
    score = max(0, 100 - sum(_DEDUCTIONS.get(i['severity'], 0) for i in issues))

    return {
        'sheet_name': sheet_name,
        'is_valid': not any(i['severity'] == 'ERROR' for i in issues),
        'quality_score': score,
        'issue_count': len(issues),
        'issues': issues,
    }


def validate_workbook(all_sheets: dict, profiles: dict) -> dict:
    """Run validation on every sheet and return a per-sheet result dict."""
    results = {}
    for sheet_name, df in all_sheets.items():
        profile = profiles.get(sheet_name, {})
        results[sheet_name] = validate_sheet(df, profile, sheet_name)
    return results


def format_validation_block(validation: dict) -> str:
    """Render data quality issues as a [DATA QUALITY FLAGS] block for LLM context.

    Only emits a block when there are actual issues — clean sheets don't waste
    context space with an empty section.
    """
    if not validation:
        return ''

    all_issues = [
        (sheet_name, issue)
        for sheet_name, sheet_val in validation.items()
        for issue in sheet_val.get('issues', [])
    ]
    if not all_issues:
        return ''

    # Sort so ERRORs appear before WARNINGs before CAUTIONs
    _ORDER = {'ERROR': 0, 'WARNING': 1, 'CAUTION': 2}
    all_issues.sort(key=lambda x: _ORDER.get(x[1]['severity'], 3))

    lines = [
        '[DATA QUALITY FLAGS - issues detected in the uploaded data. '
        'Mention relevant flags when they affect the answer:]'
    ]
    for sheet_name, issue in all_issues:
        col_ref = f' | "{issue["column"]}"' if issue.get('column') else ''
        lines.append(f'  [{issue["severity"]}] Sheet "{sheet_name}"{col_ref}: {issue["issue"]}')
        if issue.get('recommendation'):
            lines.append(f'    Recommendation: {issue["recommendation"]}')

    return '\n'.join(lines)
