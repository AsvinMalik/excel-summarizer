"""Deterministic per-sheet statistics computed with pandas.

The AI was repeatedly observed misreading numbers out of a raw CSV text
preview (e.g. treating "$999,888" as "$9.98 million", or mis-totaling a
column it was trying to add up by eye). Pandas can compute sum/mean/min/max
exactly, so we do it once at upload time and hand the AI verified numbers
instead of asking it to do arithmetic from text. This is purely additive —
the raw CSV preview is still included alongside it.
"""
import pandas as pd


def profile_sheet(df: pd.DataFrame) -> dict:
    row_count = len(df)
    duplicate_rows = int(df.duplicated().sum()) if row_count else 0
    columns = []
    for col in df.columns:
        series = df[col]
        non_null = series.dropna()
        null_count = int(series.isna().sum())
        col_profile = {'name': str(col), 'null_count': null_count}

        if pd.api.types.is_numeric_dtype(series) and len(non_null) > 0:
            col_profile.update({
                'data_type': 'numeric',
                'sum': round(float(non_null.sum()), 2),
                'mean': round(float(non_null.mean()), 2),
                'min': round(float(non_null.min()), 2),
                'max': round(float(non_null.max()), 2),
            })
        else:
            col_profile.update({
                'data_type': 'text',
                'unique_count': int(non_null.nunique()),
            })
        columns.append(col_profile)

    return {
        'row_count': row_count,
        'duplicate_rows': duplicate_rows,
        'null_total': sum(c['null_count'] for c in columns),
        'columns': columns,
    }


def compute_category_breakdowns(df: pd.DataFrame, max_dimensions: int = 3, max_measures: int = 3, max_groups: int = 15) -> list:
    """For each low-cardinality text column (a likely dimension, e.g. Vendor/Region)
    paired with each numeric column (a likely measure, e.g. Spend), pre-compute the
    sum/mean per group. Handing the model a real, already-computed cross-tab instead
    of a flat row sample is what lets a narrative answer like "spend by vendor" cite
    a correct number without doing its own multi-step aggregation in its head."""
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    text_cols = [c for c in df.columns if c not in numeric_cols]

    dimensions = []
    for col in text_cols:
        nunique = df[col].nunique()
        if 2 <= nunique <= max_groups:
            dimensions.append(col)
        if len(dimensions) >= max_dimensions:
            break

    breakdowns = []
    for dim in dimensions:
        for measure in numeric_cols[:max_measures]:
            series = pd.to_numeric(df[measure], errors='coerce')
            grouped_sum = series.groupby(df[dim]).sum().sort_values(ascending=False)
            grouped_mean = series.groupby(df[dim]).mean()
            breakdowns.append({
                'dimension': dim,
                'measure': measure,
                'groups': [
                    {'group': str(g), 'sum': round(float(grouped_sum[g]), 2), 'mean': round(float(grouped_mean[g]), 2)}
                    for g in grouped_sum.index
                ],
            })
    return breakdowns


def format_breakdowns_block(breakdowns: list) -> str:
    if not breakdowns:
        return ''
    lines = []
    for b in breakdowns:
        lines.append(f'    {b["measure"]} by {b["dimension"]}:')
        for g in b['groups']:
            lines.append(f'      - {g["group"]}: sum={g["sum"]}, mean={g["mean"]}')
    return '\n'.join(lines)


def profile_workbook(all_sheets: dict) -> dict:
    """all_sheets: {sheet_name: DataFrame} as returned by pd.read_excel(sheet_name=None)."""
    profiles = {}
    for name, df in all_sheets.items():
        profile = profile_sheet(df)
        profile['breakdowns'] = compute_category_breakdowns(df)
        profiles[name] = profile
    return profiles


def format_profile_block(profile: dict) -> str:
    """Render a profile dict as a labeled text block for LLM context injection."""
    if not profile:
        return ''
    lines = []
    for sheet_name, sheet_profile in profile.items():
        flags = []
        if sheet_profile.get('duplicate_rows'):
            flags.append(f"{sheet_profile['duplicate_rows']} duplicate row(s)")
        if sheet_profile.get('null_total'):
            flags.append(f"{sheet_profile['null_total']} missing cell(s)")
        flag_text = f" — {'; '.join(flags)}" if flags else ''
        lines.append(f'  Sheet "{sheet_name}" ({sheet_profile["row_count"]} rows){flag_text}:')
        for col in sheet_profile['columns']:
            if col['data_type'] == 'numeric':
                null_note = f", {col['null_count']} null" if col['null_count'] else ''
                lines.append(
                    f'    - "{col["name"]}": sum={col["sum"]}, mean={col["mean"]}, '
                    f'min={col["min"]}, max={col["max"]}{null_note}'
                )
            else:
                null_note = f", {col['null_count']} null" if col['null_count'] else ''
                lines.append(f'    - "{col["name"]}": {col["unique_count"]} unique value(s){null_note}')
    return '\n'.join(lines)
