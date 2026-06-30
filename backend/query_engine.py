"""Deterministic execution of structured data queries against the FULL workbook
(re-read from disk), not a truncated text preview. The AI is only ever used to
translate a natural-language question into a structured query spec (sheet,
column, operation, filters) — the actual computation always runs through real
pandas, so it can never be arithmetically wrong the way free-text LLM reasoning
can be.
"""
import pandas as pd


class QueryError(Exception):
    pass


_VALID_OPS = {'sum', 'mean', 'count', 'min', 'max', 'median'}
_VALID_FILTER_OPS = {'>', '>=', '<', '<=', '==', '!='}


def load_all_sheets(file_path: str) -> dict:
    return pd.read_excel(file_path, sheet_name=None)


def _coerce_filter_value(raw_value):
    if isinstance(raw_value, (int, float)):
        return raw_value
    try:
        return float(str(raw_value).replace(',', '').replace('$', '').strip())
    except (TypeError, ValueError):
        return raw_value


def _apply_filter(df: pd.DataFrame, column: str, op: str, raw_value) -> pd.DataFrame:
    if column not in df.columns or op not in _VALID_FILTER_OPS:
        return df

    numeric_series = pd.to_numeric(df[column], errors='coerce')
    is_mostly_numeric = numeric_series.notna().sum() >= max(1, len(df) * 0.5)

    if is_mostly_numeric:
        value = _coerce_filter_value(raw_value)
        compare_series = numeric_series
    else:
        value = str(raw_value)
        compare_series = df[column].astype(str)

    if op == '>':
        mask = compare_series > value
    elif op == '>=':
        mask = compare_series >= value
    elif op == '<':
        mask = compare_series < value
    elif op == '<=':
        mask = compare_series <= value
    elif op == '==':
        mask = compare_series == value
    else:
        mask = compare_series != value

    return df[mask.fillna(False)]


def execute_query_spec(all_sheets: dict, spec: dict) -> dict:
    sheet = spec.get('sheet')
    if sheet not in all_sheets:
        raise QueryError(f'Sheet "{sheet}" not found')
    df = all_sheets[sheet]
    original_row_count = len(df)

    for f in spec.get('filters') or []:
        df = _apply_filter(df, f.get('column'), f.get('op'), f.get('value'))

    matched_row_count = len(df)
    group_by = spec.get('group_by')
    column = spec.get('column')
    operation = spec.get('operation')
    operation = operation if operation in _VALID_OPS else None

    # An ungrouped "count" never needs a column — it's just how many rows matched
    # the filters (or the whole sheet, if no filters). Models often leave "column"
    # null for count questions, which is correct, not a missing field.
    if operation == 'count' and not group_by:
        label = column or (spec.get('filters') or [{}])[0].get('column') or 'matching rows'
        return {
            'type': 'scalar',
            'original_row_count': original_row_count,
            'matched_row_count': matched_row_count,
            'operation': 'count',
            'column': label,
            'value': matched_row_count,
        }

    if group_by and group_by in df.columns and operation:
        if operation == 'count':
            grouped = df.groupby(group_by).size().reset_index(name='count')
            value_col = 'count'
        elif column and column in df.columns:
            work = df[[group_by]].copy()
            work['_value'] = pd.to_numeric(df[column], errors='coerce')
            grouped = getattr(work.groupby(group_by)['_value'], operation)().reset_index()
            value_col = f'{operation}_{column}'
            grouped.columns = [group_by, value_col]
        else:
            raise QueryError(f'Column "{column}" not found for grouped {operation}')

        sort = spec.get('sort')
        if sort:
            grouped = grouped.sort_values(value_col, ascending=(sort == 'asc'))
        limit = spec.get('limit')
        if limit:
            grouped = grouped.head(int(limit))
        return {
            'type': 'grouped',
            'original_row_count': original_row_count,
            'matched_row_count': matched_row_count,
            'group_by': group_by,
            'operation': operation,
            'column': column or value_col,
            'value_col': value_col,
            'rows': grouped.to_dict('records'),
        }

    if column and column in df.columns and operation:
        series = pd.to_numeric(df[column], errors='coerce').dropna()
        value = getattr(series, operation)() if len(series) else None
        return {
            'type': 'scalar',
            'original_row_count': original_row_count,
            'matched_row_count': matched_row_count,
            'operation': operation,
            'column': column,
            'value': round(float(value), 2) if value is not None else None,
        }

    limit = int(spec.get('limit') or 20)
    sort = spec.get('sort')
    sort_col = column if column and column in df.columns else None
    if sort and sort_col:
        df = df.sort_values(sort_col, ascending=(sort == 'asc'))
    return {
        'type': 'rows',
        'original_row_count': original_row_count,
        'matched_row_count': matched_row_count,
        'columns': df.columns.tolist(),
        'rows': df.head(limit).to_dict('records'),
    }
