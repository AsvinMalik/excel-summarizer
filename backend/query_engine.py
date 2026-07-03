"""Deterministic execution of structured data queries against the FULL workbook
(re-read from disk), not a truncated text preview. The AI is only ever used to
translate a natural-language question into a structured query spec (sheet,
column, operation, filters) — the actual computation always runs through real
pandas, so it can never be arithmetically wrong the way free-text LLM reasoning
can be.
"""
import re

import pandas as pd


class QueryError(Exception):
    pass


_VALID_OPS = {'sum', 'mean', 'count', 'min', 'max', 'median'}
_VALID_FILTER_OPS = {'>', '>=', '<', '<=', '==', '!='}


def _norm_text(value) -> str:
    """Normalise human-typed Excel text for matching: collapse runs of
    whitespace ('Ajay  team' -> 'Ajay team'), strip edges, casefold.
    Real MIS files are full of stray double spaces and trailing spaces,
    so strict string equality silently returns zero rows."""
    return re.sub(r'\s+', ' ', str(value)).strip().casefold()


def _resolve_column(df: pd.DataFrame, column) -> str | None:
    """Resolve a spec-provided column name against real df columns,
    tolerating whitespace/case differences (e.g. spec 'From' vs header 'From ')."""
    if column is None:
        return None
    if column in df.columns:
        return column
    wanted = _norm_text(column)
    for c in df.columns:
        if _norm_text(c) == wanted:
            return c
    return None


def load_all_sheets(file_path: str) -> dict:
    import sys
    raw = pd.read_excel(file_path, sheet_name=None)
    # Late-import _clean_sheet_headers from main to avoid circular import.
    # Under pytest/imports the module is 'main'; when the server is started as
    # `python main.py` it is registered as '__main__' instead — check both, or
    # header cleaning silently never runs in production and spec columns
    # (built from the cleaned profile) stop matching the loaded DataFrames.
    clean = None
    for _mod_name in ('main', '__main__'):
        candidate = getattr(sys.modules.get(_mod_name), '_clean_sheet_headers', None)
        if callable(candidate):
            clean = candidate
            break
    if clean is None:
        try:
            from main import _clean_sheet_headers as clean
        except ImportError:
            pass
    if callable(clean):
        return {name: clean(df) for name, df in raw.items()}
    return raw


def _coerce_filter_value(raw_value):
    if isinstance(raw_value, (int, float)):
        return raw_value
    try:
        return float(str(raw_value).replace(',', '').replace('$', '').strip())
    except (TypeError, ValueError):
        return raw_value


def _apply_filter(df: pd.DataFrame, column: str, op: str, raw_value) -> pd.DataFrame:
    column = _resolve_column(df, column)
    if column is None or op not in _VALID_FILTER_OPS:
        return df

    numeric_series = pd.to_numeric(df[column], errors='coerce')
    is_mostly_numeric = numeric_series.notna().sum() >= max(1, len(df) * 0.5)

    if is_mostly_numeric:
        value = _coerce_filter_value(raw_value)
        compare_series = numeric_series
    else:
        # Text comparison: normalise both sides so stray double/trailing
        # spaces and case differences don't turn a real match into 0 rows.
        value = _norm_text(raw_value)
        compare_series = df[column].astype(str).map(_norm_text)

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
        # Fallback: exact (normalised) equality found nothing — try substring
        # containment so 'Ajay' still matches 'Ajay/ Trupti'. Only for ==,
        # never for numeric comparisons.
        if not is_mostly_numeric and not mask.any() and value:
            mask = compare_series.str.contains(re.escape(value), na=False)
    else:
        mask = compare_series != value

    return df[mask.fillna(False)]


def _apply_join(df: pd.DataFrame, all_sheets: dict, join_spec: dict) -> pd.DataFrame:
    """Merge a second sheet into df using the relationship specified in join_spec.

    join_spec shape:
      {"with_sheet": "Vendors", "on": [{"left": "Vendor ID", "right": "Vendor ID"}]}

    To avoid column-name collisions, only non-overlapping columns are brought
    over from the right sheet (except the join key itself, which is needed for
    the merge and then deduped). This means every column in the resulting df
    keeps its original name with no suffix mangling, so the rest of the spec
    (group_by, column, filters) can reference columns from either sheet by
    their original name.
    """
    right_sheet = join_spec.get('with_sheet')
    if right_sheet not in all_sheets:
        raise QueryError(f'Join sheet "{right_sheet}" not found')

    on_pairs = join_spec.get('on') or []
    if not on_pairs:
        raise QueryError('join spec is missing "on" column pairs')

    left_col = on_pairs[0]['left']
    right_col = on_pairs[0]['right']

    right_df = all_sheets[right_sheet]
    left_col_set = set(df.columns)

    # Only bring over columns from the right sheet that aren't already in the left,
    # plus the right join key itself (needed for the merge). Dropping overlapping
    # columns prevents pandas from adding _x/_y suffixes that would break column refs.
    right_keep = [right_col] + [c for c in right_df.columns if c not in left_col_set and c != right_col]
    right_df = right_df[[c for c in right_keep if c in right_df.columns]]

    if left_col == right_col:
        merged = df.merge(right_df, on=left_col, how='left')
    else:
        merged = df.merge(right_df, left_on=left_col, right_on=right_col, how='left')
        # Drop the right-side join key — it duplicates the left one and would
        # confuse downstream column references.
        merged = merged.drop(columns=[right_col], errors='ignore')

    return merged


def execute_query_spec(all_sheets: dict, spec: dict) -> dict:
    sheet = spec.get('sheet')
    if sheet not in all_sheets:
        raise QueryError(f'Sheet "{sheet}" not found')
    df = all_sheets[sheet].copy()

    join_spec = spec.get('join')
    if join_spec:
        df = _apply_join(df, all_sheets, join_spec)

    original_row_count = len(df)

    for f in spec.get('filters') or []:
        df = _apply_filter(df, f.get('column'), f.get('op'), f.get('value'))

    matched_row_count = len(df)
    group_by = _resolve_column(df, spec.get('group_by'))
    column = _resolve_column(df, spec.get('column')) or spec.get('column')
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
