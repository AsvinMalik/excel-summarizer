"""Column semantic type inference and schema context builder.

Infers whether each column is a currency measure, percentage, date, ID,
category, entity name, etc. — turning the raw profile into a structured
[SCHEMA CONTEXT] block the LLM can use to understand table purpose,
primary keys, FK references, and which columns are aggregatable vs. filters.

Also loads business_glossary.json to enrich type inference with procurement-
domain synonyms (e.g. "Amt" -> currency, "Geo" -> region, "Risk Score" -> risk).
"""
import json
import os
import re
import pandas as pd


_GLOSSARY: dict | None = None


def _load_glossary() -> dict:
    global _GLOSSARY
    if _GLOSSARY is None:
        path = os.path.join(os.path.dirname(__file__), 'business_glossary.json')
        try:
            with open(path, 'r', encoding='utf-8') as f:
                _GLOSSARY = json.load(f)
        except Exception:
            _GLOSSARY = {}
    return _GLOSSARY


def lookup_business_category(col_name: str) -> str | None:
    """Return the glossary business category for a column name, or None.

    Categories: spending_columns, date_columns, vendor_identifiers,
                region_columns, risk_indicators, status_columns,
                quantity_columns, id_columns

    Uses word-boundary regex for single-word terms to prevent substring false
    positives: "end" must not match inside "vendor", "exp" must not match
    inside "expiry". Multi-word phrases (e.g. "po amount") use substring since
    their specificity avoids accidental matches.
    """
    glossary = _load_glossary()
    col_lower = col_name.lower()
    for category, terms in glossary.items():
        if category == 'canonical_labels':
            continue
        if not isinstance(terms, list):
            continue
        for t in terms:
            t_lower = t.lower()
            if ' ' in t_lower:
                # Multi-word phrase: plain substring is specific enough
                if t_lower in col_lower:
                    return category
            else:
                # Single word: require word boundaries so "exp" doesn't hit "expiry"
                # and "end" doesn't hit "vendor"
                if re.search(r'\b' + re.escape(t_lower) + r'\b', col_lower):
                    return category
    return None


def get_canonical_label(col_name: str) -> str | None:
    """Return a human-readable expansion for an abbreviated column name, or None."""
    glossary = _load_glossary()
    labels: dict = glossary.get('canonical_labels', {})
    col_lower = col_name.lower().strip()
    # Exact match first
    if col_lower in labels:
        return labels[col_lower]
    # Token-level match: expand abbreviations that appear as whole words in the name
    tokens = re.split(r'[\s_\-]+', col_lower)
    expanded = [labels.get(t, t) for t in tokens]
    result = ' '.join(expanded)
    return result if result.lower() != col_name.lower() else None


_CURRENCY_RE = re.compile(
    r'spend|cost|price|amount|revenue|salary|wage|budget|expense|value|total|payment|fee|charge|invoice',
    re.IGNORECASE,
)
_PERCENTAGE_RE = re.compile(r'%|percent|pct|rate|ratio|share|margin|score', re.IGNORECASE)
_DATE_RE = re.compile(
    r'date|time|period|year|month|\bday\b|quarter|week|created|updated|expir|\bstart\b|\bend\b',
    re.IGNORECASE,
)
_ID_RE = re.compile(r'\bid\b|_id|id$|^id|number$|num$|#$|code|key|ref|invoice\s*no|order\s*no|po\s*no', re.IGNORECASE)
_QUANTITY_RE = re.compile(r'count|qty|quantity|units|volume|hours|days|items|number of', re.IGNORECASE)


def infer_column_semantic_type(col_name: str, series: pd.Series) -> str:
    """Return the semantic type for a column.

    Possible values: currency, percentage, year, integer, quantity,
                     date, id, categorical, entity, text, risk, region, vendor

    Checks the business glossary first for procurement-domain synonyms, then
    falls back to regex patterns for broader coverage.
    """
    is_numeric = pd.api.types.is_numeric_dtype(series)
    is_datetime = pd.api.types.is_datetime64_any_dtype(series)

    if is_datetime or (_DATE_RE.search(col_name) and not is_numeric):
        return 'date'

    # Glossary lookup takes priority over regex for unambiguous domain terms
    biz_cat = lookup_business_category(col_name)
    if biz_cat == 'id_columns':
        return 'id'
    if biz_cat == 'date_columns' and not is_numeric:
        return 'date'
    if biz_cat == 'spending_columns' and is_numeric:
        return 'currency'
    if biz_cat == 'risk_indicators' and is_numeric:
        return 'risk'
    if biz_cat == 'quantity_columns' and is_numeric:
        return 'quantity'
    if biz_cat == 'region_columns':
        return 'region'
    if biz_cat == 'vendor_identifiers':
        return 'vendor'
    if biz_cat == 'status_columns':
        return 'categorical'

    if is_numeric:
        if _PERCENTAGE_RE.search(col_name):
            return 'percentage'
        # ID check before currency: "Invoice ID" must not be called a currency column
        if _ID_RE.search(col_name):
            return 'id'
        if _CURRENCY_RE.search(col_name):
            return 'currency'
        if _QUANTITY_RE.search(col_name):
            return 'quantity'
        # Detect year columns: all integers in the 1900-2100 range
        non_null = series.dropna()
        if len(non_null) > 0:
            try:
                int_vals = non_null.astype(int)
                if (int_vals == non_null).all() and ((int_vals >= 1900) & (int_vals <= 2100)).all():
                    return 'year'
            except (ValueError, TypeError):
                pass
        return 'integer'

    # Text column
    if _ID_RE.search(col_name):
        return 'id'
    if _DATE_RE.search(col_name):
        return 'date'

    non_null = series.dropna()
    n_total = len(non_null)
    if n_total == 0:
        return 'text'

    try:
        n_unique = non_null.nunique()
    except TypeError:
        n_unique = non_null.astype(str).nunique()
    uniqueness = n_unique / n_total

    if n_unique <= 20:
        return 'categorical'
    if uniqueness > 0.8 and n_unique > 10:
        return 'entity'  # high cardinality -> names, addresses, descriptions

    return 'text'


def identify_primary_key(df: pd.DataFrame) -> str | None:
    """Return the most likely primary-key column: all unique values + ID-like name."""
    candidates = []
    for col in df.columns:
        series = df[col].dropna()
        if len(series) == 0 or len(series) != len(df):
            continue  # skip if there are nulls at all — PK must be complete
        try:
            n_unique = series.nunique()
        except TypeError:
            n_unique = series.astype(str).nunique()
        uniqueness = n_unique / len(series)
        if uniqueness < 1.0:
            continue  # must be fully unique
        is_id_named = bool(_ID_RE.search(col))
        # Score: prefer ID-named columns, then shorter names (simpler IDs)
        score = (1 if is_id_named else 0, -len(col))
        candidates.append((score, col))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def build_schema_context(all_sheets: dict, profiles: dict, relationships: list) -> dict:
    """Assemble a full schema context dict with semantic types, PK, and FK annotations."""
    # FK lookup: (sheet, col) -> "parent_sheet.parent_col"
    fk_map: dict = {
        (r['to_sheet'], r['to_col']): f"{r['from_sheet']}.{r['from_col']}"
        for r in (relationships or [])
    }

    tables = []
    for sheet_name, df in all_sheets.items():
        profile = profiles.get(sheet_name, {})
        pk = identify_primary_key(df)
        dimensions = []
        measures = []
        issues = []

        for col_profile in profile.get('columns', []):
            col_name = col_profile['name']
            series = df[col_name] if col_name in df.columns else pd.Series(dtype=object)
            sem_type = infer_column_semantic_type(col_name, series)

            null_count = col_profile.get('null_count', 0)
            if null_count > 0:
                issues.append(f'{null_count} null value(s) in "{col_name}"')

            biz_cat = lookup_business_category(col_name)
            canonical = get_canonical_label(col_name)

            if col_profile['data_type'] == 'numeric' and sem_type not in ('id', 'year'):
                agg = 'average' if sem_type in ('percentage', 'risk') else 'sum'
                entry = {
                    'name': col_name,
                    'type': sem_type,
                    'aggregation': agg,
                    'sum': col_profile.get('sum'),
                    'mean': col_profile.get('mean'),
                    'min': col_profile.get('min'),
                    'max': col_profile.get('max'),
                }
                if biz_cat:
                    entry['business_category'] = biz_cat
                if canonical:
                    entry['canonical'] = canonical
                measures.append(entry)
            elif col_profile['data_type'] == 'numeric' and sem_type in ('id', 'year'):
                # Numeric IDs and year columns are key/dimension columns — treat them
                # like text dimensions so they appear as grouping fields, not aggregates.
                entry = {'name': col_name, 'type': sem_type}
                fk_ref = fk_map.get((sheet_name, col_name))
                if fk_ref:
                    entry['references'] = fk_ref
                dimensions.append(entry)
            else:
                entry = {'name': col_name, 'type': sem_type}
                if sem_type == 'categorical':
                    unique_vals = [str(v) for v in series.dropna().unique()[:10]]
                    entry['values'] = unique_vals
                fk_ref = fk_map.get((sheet_name, col_name))
                if fk_ref:
                    entry['references'] = fk_ref
                if biz_cat:
                    entry['business_category'] = biz_cat
                if canonical:
                    entry['canonical'] = canonical
                dimensions.append(entry)

        n_nulls = sum(col_profile.get('null_count', 0) for col_profile in profile.get('columns', []))
        n_cells = len(df) * len(df.columns)
        quality_score = round(100 * (1 - n_nulls / max(n_cells, 1)), 1) if n_cells else 100.0

        tables.append({
            'sheet_name': sheet_name,
            'row_count': len(df),
            'primary_key': pk,
            'dimensions': dimensions,
            'measures': measures,
            'issues': issues,
            'quality_score': quality_score,
        })

    return {
        'tables': tables,
        'relationships': relationships or [],
    }


def format_schema_context_block(schema_context: dict) -> str:
    """Render the schema context as a [SCHEMA CONTEXT] block for LLM injection."""
    if not schema_context or not schema_context.get('tables'):
        return ''

    lines = ['[SCHEMA CONTEXT]']
    for table in schema_context['tables']:
        lines.append(f'\n  Table: {table["sheet_name"]}')
        lines.append(f'  - Rows: {table["row_count"]:,} | Quality: {table["quality_score"]}%')

        if table.get('primary_key'):
            lines.append(f'  - Primary Key: {table["primary_key"]}')

        if table.get('dimensions'):
            dim_parts = []
            for d in table['dimensions']:
                label = d.get('canonical') or d['name']
                display = label if label == d['name'] else f'{d["name"]} [{label}]'
                if d.get('references'):
                    dim_parts.append(f'{display} (-> {d["references"]})')
                elif d['type'] == 'categorical' and d.get('values'):
                    vals = ', '.join(d['values'][:5])
                    suffix = '...' if len(d.get('values', [])) > 5 else ''
                    dim_parts.append(f'{display} ({vals}{suffix})')
                elif d.get('business_category'):
                    cat_short = d['business_category'].replace('_columns', '').replace('_identifiers', '')
                    type_str = d['type'] if d['type'] != cat_short else ''
                    suffix = f'{d["type"]}, {cat_short}' if type_str else d['type']
                    dim_parts.append(f'{display} ({suffix})')
                else:
                    dim_parts.append(f'{display} ({d["type"]})')
            lines.append(f'  - Dimensions: {"; ".join(dim_parts)}')

        if table.get('measures'):
            meas_parts = []
            for m in table['measures']:
                label = m.get('canonical') or m['name']
                display = label if label == m['name'] else f'{m["name"]} [{label}]'
                cat = m.get('business_category', '').replace('_columns', '').replace('_indicators', '')
                cat_suffix = f', {cat}' if cat and cat != m['type'] else ''
                meas_parts.append(f'{display} ({m["type"]}{cat_suffix}, {m["aggregation"]}-able)')
            lines.append(f'  - Measures: {"; ".join(meas_parts)}')

        if table.get('issues'):
            lines.append(f'  - Issues: {"; ".join(table["issues"][:5])}')

    rels = schema_context.get('relationships') or []
    if rels:
        lines.append('\n  Relationships:')
        for r in rels:
            lines.append(
                f'    {r["from_sheet"]}.{r["from_col"]} -> {r["to_sheet"]}.{r["to_col"]} '
                f'({r["type"]}, {int(r["confidence"] * 100)}% confidence)'
            )

    return '\n'.join(lines)
