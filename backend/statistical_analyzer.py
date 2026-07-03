"""Statistical analysis and trend detection for uploaded workbooks.

Computed at upload time alongside the data profiler. Produces distribution
stats, outlier detection, correlation analysis, and trend detection that are
injected into LLM context as a [STATISTICAL ANALYSIS] block — giving the AI
real computed insights to cite rather than deriving them from a text preview.

Capped at 10,000 rows per sheet to keep upload latency reasonable; larger
sheets still get the basic profiler stats (sum/mean/min/max) from data_profiler.
"""
import re
import pandas as pd
import numpy as np


_MAX_ROWS_FOR_FULL_STATS = 10_000
_DATE_COL_RE = re.compile(r'date|period|month|year|quarter|week', re.IGNORECASE)


def _safe_round(val, decimals: int = 2):
    try:
        f = float(val)
        return round(f, decimals) if not (f != f) else None  # NaN check
    except (TypeError, ValueError):
        return None


def analyze_column(series: pd.Series) -> dict:
    """Full distribution statistics for a numeric series."""
    non_null = pd.to_numeric(series, errors='coerce').dropna()
    if len(non_null) < 2:
        return {}

    q25 = float(non_null.quantile(0.25))
    q75 = float(non_null.quantile(0.75))
    mean = float(non_null.mean())
    stdev = float(non_null.std())

    return {
        'count': len(non_null),
        'mean': _safe_round(mean),
        'median': _safe_round(non_null.median()),
        'stdev': _safe_round(stdev),
        'cv': _safe_round(stdev / mean, 4) if mean != 0 else None,
        'min': _safe_round(non_null.min()),
        'max': _safe_round(non_null.max()),
        'q25': _safe_round(q25),
        'q75': _safe_round(q75),
        'iqr': _safe_round(q75 - q25),
        'skewness': _safe_round(float(non_null.skew()), 3),
        'kurtosis': _safe_round(float(non_null.kurtosis()), 3),
    }


def detect_anomalies(series: pd.Series) -> dict:
    """Z-score (>3σ) and IQR Tukey-fence outlier detection."""
    non_null = pd.to_numeric(series, errors='coerce').dropna()
    if len(non_null) < 4:
        return {}

    mean = float(non_null.mean())
    stdev = float(non_null.std())

    # Z-score method
    z_count = 0
    z_sample = []
    if stdev > 0:
        z_scores = ((non_null - mean) / stdev).abs()
        z_outliers = non_null[z_scores > 3]
        z_count = len(z_outliers)
        z_sample = [_safe_round(v) for v in z_outliers.head(5).tolist()]

    # IQR / Tukey fences
    q25 = float(non_null.quantile(0.25))
    q75 = float(non_null.quantile(0.75))
    iqr = q75 - q25
    lower = q25 - 1.5 * iqr
    upper = q75 + 1.5 * iqr
    iqr_count = int(((non_null < lower) | (non_null > upper)).sum())

    result = {'zscore_count': z_count, 'iqr_count': iqr_count}
    if z_count:
        result['zscore_sample'] = z_sample
    if iqr_count:
        result['iqr_lower_fence'] = _safe_round(lower)
        result['iqr_upper_fence'] = _safe_round(upper)
    return result


def analyze_correlations(df: pd.DataFrame, numeric_cols: list) -> list:
    """Find column pairs with |r| > 0.7 (strong correlations worth flagging)."""
    if len(numeric_cols) < 2:
        return []
    work = df[numeric_cols].apply(pd.to_numeric, errors='coerce')
    try:
        corr = work.corr()
    except Exception:
        return []

    strong = []
    for i, c1 in enumerate(numeric_cols):
        for c2 in numeric_cols[i + 1:]:
            try:
                val = float(corr.loc[c1, c2])
            except (KeyError, TypeError, ValueError):
                continue
            if val != val or abs(val) <= 0.7:  # NaN or weak
                continue
            strong.append({
                'col1': c1,
                'col2': c2,
                'r': _safe_round(val, 3),
                'interpretation': 'strong positive' if val > 0 else 'strong negative',
            })
    return strong


def analyze_trends(df: pd.DataFrame, date_col: str, value_col: str) -> dict:
    """Linear trend + optional YoY growth if >= 24 data points exist."""
    try:
        work = df[[date_col, value_col]].copy()
        work[date_col] = pd.to_datetime(work[date_col], errors='coerce')
        work[value_col] = pd.to_numeric(work[value_col], errors='coerce')
        work = work.dropna().sort_values(date_col)
        if len(work) < 3:
            return {}

        series = work[value_col].reset_index(drop=True)
        x = np.arange(len(series))
        slope, _ = np.polyfit(x, series.values, 1)
        mean = float(series.mean())

        yoy = None
        if len(series) >= 24:
            last_12 = float(series.iloc[-12:].sum())
            prev_12 = float(series.iloc[-24:-12].sum())
            if prev_12 != 0:
                yoy = _safe_round((last_12 - prev_12) / prev_12 * 100, 1)

        return {
            'date_column': date_col,
            'value_column': value_col,
            'direction': 'increasing' if slope > 0 else 'decreasing',
            'slope': _safe_round(slope),
            'growth_rate_pct': _safe_round(slope / mean * 100, 2) if mean != 0 else None,
            'yoy_growth_pct': yoy,
            'forecast_next': _safe_round(float(series.iloc[-1]) + slope),
        }
    except Exception:
        return {}


def analyze_workbook(all_sheets: dict, profiles: dict) -> dict:
    """Run full statistical analysis on every sheet. Skips sheets > 10 000 rows."""
    results = {}
    for sheet_name, df in all_sheets.items():
        profile = profiles.get(sheet_name, {})
        row_count = profile.get('row_count', len(df))
        if row_count > _MAX_ROWS_FOR_FULL_STATS:
            results[sheet_name] = {'skipped': True, 'reason': f'{row_count} rows exceeds analysis cap'}
            continue

        numeric_cols = [
            c['name'] for c in profile.get('columns', [])
            if c.get('data_type') == 'numeric' and c['name'] in df.columns
        ]
        date_cols = [
            c for c in df.columns
            if _DATE_COL_RE.search(str(c))
        ]

        col_stats = {}
        col_anomalies = {}
        for col in numeric_cols:
            col_stats[col] = analyze_column(df[col])
            col_anomalies[col] = detect_anomalies(df[col])

        correlations = analyze_correlations(df, numeric_cols)

        trend = {}
        if date_cols and numeric_cols:
            trend = analyze_trends(df, date_cols[0], numeric_cols[0])

        results[sheet_name] = {
            'skipped': False,
            'column_stats': col_stats,
            'anomalies': col_anomalies,
            'correlations': correlations,
            'trend': trend,
        }
    return results


def format_statistics_block(stats: dict) -> str:
    """Render as a [STATISTICAL ANALYSIS] block for LLM context injection.

    Only emits lines with actual signal — skips columns with no anomalies,
    no correlations, and no trend to avoid padding the context with noise.
    """
    if not stats:
        return ''

    lines = ['[STATISTICAL ANALYSIS]']
    has_any_content = False

    for sheet_name, sheet_stats in stats.items():
        # Defensive: only dict-shaped per-sheet stats are usable; a bool/None here
        # means an upstream shape mismatch — skip rather than crash the whole request.
        if not isinstance(sheet_stats, dict):
            continue
        if sheet_stats.get('skipped'):
            continue

        sheet_lines = [f'\n  Sheet "{sheet_name}":']

        # Distribution summary for each numeric column
        for col, s in sheet_stats.get('column_stats', {}).items():
            if not s:
                continue
            has_any_content = True
            skew_label = (
                'right-skewed' if (s.get('skewness') or 0) > 0.5
                else 'left-skewed' if (s.get('skewness') or 0) < -0.5
                else 'symmetric'
            )
            parts = []
            if s.get('median') is not None:
                parts.append(f'median={s["median"]:,.2f}')
            if s.get('stdev') is not None:
                parts.append(f'stdev={s["stdev"]:,.2f}')
            if s.get('iqr') is not None:
                parts.append(f'IQR={s["iqr"]:,.2f}')
            parts.append(f'distribution={skew_label}')
            sheet_lines.append(f'    "{col}": ' + ', '.join(parts))

        # Outliers
        for col, anom in sheet_stats.get('anomalies', {}).items():
            z = anom.get('zscore_count', 0)
            if z > 0:
                has_any_content = True
                sample = ', '.join(f'{v:,.2f}' for v in (anom.get('zscore_sample') or []))
                sheet_lines.append(f'    OUTLIERS "{col}": {z} value(s) beyond 3σ — {sample}')
            iqr_c = anom.get('iqr_count', 0)
            if iqr_c > 0 and z == 0:
                has_any_content = True
                lo = anom.get('iqr_lower_fence')
                hi = anom.get('iqr_upper_fence')
                sheet_lines.append(
                    f'    OUTLIERS "{col}": {iqr_c} value(s) outside IQR fences '
                    f'[{lo:,.2f}, {hi:,.2f}]'
                )

        # Correlations
        for corr in sheet_stats.get('correlations', []):
            has_any_content = True
            sheet_lines.append(
                f'    CORRELATION: "{corr["col1"]}" vs "{corr["col2"]}" '
                f'r={corr["r"]} ({corr["interpretation"]})'
            )

        # Trend
        trend = sheet_stats.get('trend') or {}
        if trend.get('direction'):
            has_any_content = True
            slope_str = f'slope={trend["slope"]:,.2f}/period'
            yoy_str = f', {trend["yoy_growth_pct"]}% YoY' if trend.get('yoy_growth_pct') is not None else ''
            sheet_lines.append(
                f'    TREND "{trend["value_column"]}" by "{trend["date_column"]}": '
                f'{trend["direction"]} ({slope_str}{yoy_str})'
            )

        if len(sheet_lines) > 1:
            lines.extend(sheet_lines)

    if not has_any_content:
        return ''
    return '\n'.join(lines)
