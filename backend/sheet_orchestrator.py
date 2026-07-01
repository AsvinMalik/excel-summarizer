"""Multi-sheet relationship detection and unified schema building.

Detects foreign-key relationships between sheets by matching column names
and checking value overlap. Classifies each sheet's role (fact table,
dimension table, reference table) and builds a unified schema so the query
engine and LLM context always know which sheets can be joined and how.
"""
import re
import pandas as pd

# Phase 2c: synonym groups for semantic column-name matching.
# Each group is a frozenset of interchangeable terms. When every token in one
# column name has a synonym-equivalent token in another, we treat them as
# candidate join keys and verify with value overlap.
_SYNONYM_GROUPS: list = [
    # entity types
    frozenset({'vendor', 'supplier', 'provider', 'contractor', 'seller'}),
    frozenset({'customer', 'client', 'buyer', 'account', 'consumer'}),
    frozenset({'employee', 'staff', 'worker', 'personnel', 'member'}),
    frozenset({'product', 'item', 'sku', 'goods', 'material', 'article'}),
    frozenset({'order', 'purchase', 'transaction', 'requisition', 'po'}),
    frozenset({'invoice', 'bill', 'receipt', 'voucher'}),
    frozenset({'department', 'dept', 'division', 'unit', 'team', 'section'}),
    frozenset({'project', 'programme', 'program', 'initiative', 'scheme'}),
    # attribute qualifiers
    frozenset({'id', 'code', 'no', 'num', 'number', 'key', 'ref', 'reference', 'cd'}),
    frozenset({'name', 'title', 'desc', 'description', 'label', 'nm'}),
    frozenset({'amount', 'amt', 'value', 'total', 'sum', 'val', 'cost', 'price'}),
    frozenset({'quantity', 'qty', 'count', 'units', 'volume', 'vol'}),
    frozenset({'date', 'dt', 'time', 'period', 'month', 'year', 'day'}),
    frozenset({'category', 'cat', 'type', 'class', 'group', 'segment', 'kind'}),
    frozenset({'region', 'area', 'zone', 'territory', 'location', 'loc', 'place'}),
    frozenset({'status', 'state', 'flag', 'indicator', 'stage', 'phase'}),
]

# Build a fast lookup: token -> frozenset index so _are_synonyms is O(1)
_TOKEN_TO_GROUP: dict = {}
for _gi, _grp in enumerate(_SYNONYM_GROUPS):
    for _tok in _grp:
        _TOKEN_TO_GROUP[_tok] = _gi


def _are_synonyms(a: str, b: str) -> bool:
    """True when two tokens belong to the same synonym group."""
    if a == b:
        return True
    ga = _TOKEN_TO_GROUP.get(a)
    return ga is not None and ga == _TOKEN_TO_GROUP.get(b)


def _col_tokens(col_name: str) -> list:
    """Split a column name into lowercase word tokens, dropping empties."""
    return [t for t in re.split(r'[\s_\-/]+', col_name.strip().lower()) if t]


def _semantic_similarity(tokens_a: list, tokens_b: list) -> float:
    """Jaccard-style score [0, 1] counting synonym-matched tokens as equal.

    Each token in A is matched to at most one token in B (and vice versa).
    Score = matched_count / union_size.
    """
    if not tokens_a or not tokens_b:
        return 0.0
    matched_b = [False] * len(tokens_b)
    matches = 0
    for ta in tokens_a:
        for j, tb in enumerate(tokens_b):
            if not matched_b[j] and _are_synonyms(ta, tb):
                matched_b[j] = True
                matches += 1
                break
    union = len(tokens_a) + len(tokens_b) - matches
    return matches / union if union else 0.0


def _normalize_col_key(col_name: str) -> str:
    """Lowercase + collapse whitespace/underscores/hyphens for fuzzy name matching."""
    return re.sub(r'[\s_\-]+', '_', str(col_name).strip().lower())


def detect_relationships(all_sheets: dict) -> list:
    """Find FK relationships across sheets by column name similarity + value overlap.

    For each pair of sheets that share a column name (after normalization),
    check whether >= 60% of the unique values in the smaller column appear in
    the larger one. Returns a list of relationship dicts sorted by confidence.
    """
    # Map normalized key -> [(sheet_name, original_col_name)]
    col_locations: dict = {}
    for sheet_name, df in all_sheets.items():
        for col in df.columns:
            key = _normalize_col_key(col)
            col_locations.setdefault(key, []).append((sheet_name, col))

    relationships = []
    seen_pairs: set = set()

    for col_key, occurrences in col_locations.items():
        if len(occurrences) < 2:
            continue

        for i, (sheet1, col1) in enumerate(occurrences):
            for sheet2, col2 in occurrences[i + 1:]:
                if sheet1 == sheet2:
                    continue
                # Deduplicate: don't report A->B and B->A as separate entries
                pair_key = (
                    min(sheet1, sheet2), min(col1, col2),
                    max(sheet1, sheet2), max(col1, col2),
                )
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                s1 = all_sheets[sheet1][col1].dropna()
                s2 = all_sheets[sheet2][col2].dropna()
                if len(s1) == 0 or len(s2) == 0:
                    continue

                def _norm_vals(series: pd.Series) -> set:
                    if pd.api.types.is_numeric_dtype(series):
                        return set(round(float(v), 6) for v in series)
                    return set(series.astype(str).str.strip().str.lower())

                vals1 = _norm_vals(s1)
                vals2 = _norm_vals(s2)
                overlap = len(vals1 & vals2)
                total = min(len(vals1), len(vals2))
                if total == 0:
                    continue
                overlap_pct = overlap / total * 100

                if overlap_pct < 60:
                    continue

                # Cardinality: compare uniqueness ratios (unique values / row count).
                # A column that's all-unique in its sheet (ratio ≈ 1.0) is the PK/parent
                # side; repeated values (ratio < 1.0) are the FK/child side.
                uniq_ratio_1 = len(vals1) / max(len(s1), 1)
                uniq_ratio_2 = len(vals2) / max(len(s2), 1)

                if uniq_ratio_1 >= 0.95 and uniq_ratio_2 < 0.95:
                    parent_sheet, parent_col = sheet1, col1
                    child_sheet, child_col = sheet2, col2
                    cardinality = '1:N'
                elif uniq_ratio_2 >= 0.95 and uniq_ratio_1 < 0.95:
                    parent_sheet, parent_col = sheet2, col2
                    child_sheet, child_col = sheet1, col1
                    cardinality = '1:N'
                elif uniq_ratio_1 >= 0.95 and uniq_ratio_2 >= 0.95:
                    # Both fully unique — treat smaller set as parent (dimension/lookup)
                    if len(vals1) <= len(vals2):
                        parent_sheet, parent_col = sheet1, col1
                        child_sheet, child_col = sheet2, col2
                    else:
                        parent_sheet, parent_col = sheet2, col2
                        child_sheet, child_col = sheet1, col1
                    cardinality = '1:1'
                else:
                    # Both have repeated values — pick smaller unique set as parent
                    if len(vals1) <= len(vals2):
                        parent_sheet, parent_col = sheet1, col1
                        child_sheet, child_col = sheet2, col2
                    else:
                        parent_sheet, parent_col = sheet2, col2
                        child_sheet, child_col = sheet1, col1
                    cardinality = 'N:M'

                exact_name = _normalize_col_key(col1) == _normalize_col_key(col2)
                confidence = round(0.95 if (exact_name and overlap_pct >= 80) else 0.75, 2)

                relationships.append({
                    'from_sheet': parent_sheet,
                    'from_col': parent_col,
                    'to_sheet': child_sheet,
                    'to_col': child_col,
                    'overlap_pct': round(overlap_pct, 1),
                    'confidence': confidence,
                    'type': cardinality,
                    'match_type': 'exact',
                })

    # Phase 2c: semantic/fuzzy pass — detect relationships where column names use
    # different but synonymous terminology (e.g. "Vendor_ID" vs "Supplier Code").
    # Only runs for sheet pairs that have no relationship from the exact-match pass.
    sheet_names = list(all_sheets.keys())
    paired_sheets = {
        (min(r['from_sheet'], r['to_sheet']), max(r['from_sheet'], r['to_sheet']))
        for r in relationships
    }
    for i, sheet1 in enumerate(sheet_names):
        for sheet2 in sheet_names[i + 1:]:
            if (min(sheet1, sheet2), max(sheet1, sheet2)) in paired_sheets:
                continue  # already related via exact match
            df1, df2 = all_sheets[sheet1], all_sheets[sheet2]
            for col1 in df1.columns:
                tokens1 = _col_tokens(col1)
                best_score, best_col2 = 0.0, None
                for col2 in df2.columns:
                    sim = _semantic_similarity(tokens1, _col_tokens(col2))
                    if sim > best_score:
                        best_score, best_col2 = sim, col2
                # Similarity threshold: require ≥ 0.6 so single-token columns like
                # "Code" don't spuriously match every "code"-containing column.
                if best_score < 0.6 or best_col2 is None:
                    continue
                # Deduplicate against exact-pass seen_pairs
                pair_key = (
                    min(sheet1, sheet2), min(col1, best_col2),
                    max(sheet1, sheet2), max(col1, best_col2),
                )
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                s1 = df1[col1].dropna()
                s2 = df2[best_col2].dropna()
                if len(s1) == 0 or len(s2) == 0:
                    continue

                def _norm_vals_fuzzy(series: pd.Series) -> set:
                    if pd.api.types.is_numeric_dtype(series):
                        return set(round(float(v), 6) for v in series)
                    return set(series.astype(str).str.strip().str.lower())

                v1 = _norm_vals_fuzzy(s1)
                v2 = _norm_vals_fuzzy(s2)
                overlap = len(v1 & v2)
                total = min(len(v1), len(v2))
                if total == 0 or overlap / total < 0.6:
                    continue
                overlap_pct = overlap / total * 100

                uniq1 = len(v1) / max(len(s1), 1)
                uniq2 = len(v2) / max(len(s2), 1)
                if uniq1 >= 0.95 and uniq2 < 0.95:
                    parent_sheet, parent_col, child_sheet, child_col = sheet1, col1, sheet2, best_col2
                    cardinality = '1:N'
                elif uniq2 >= 0.95 and uniq1 < 0.95:
                    parent_sheet, parent_col, child_sheet, child_col = sheet2, best_col2, sheet1, col1
                    cardinality = '1:N'
                else:
                    if len(v1) <= len(v2):
                        parent_sheet, parent_col, child_sheet, child_col = sheet1, col1, sheet2, best_col2
                    else:
                        parent_sheet, parent_col, child_sheet, child_col = sheet2, best_col2, sheet1, col1
                    cardinality = '1:1' if (uniq1 >= 0.95 and uniq2 >= 0.95) else 'N:M'

                confidence = round(min(0.65, best_score * 0.7), 2)
                relationships.append({
                    'from_sheet': parent_sheet,
                    'from_col': parent_col,
                    'to_sheet': child_sheet,
                    'to_col': child_col,
                    'overlap_pct': round(overlap_pct, 1),
                    'confidence': confidence,
                    'type': cardinality,
                    'match_type': 'semantic',
                })

    relationships.sort(key=lambda r: -r['confidence'])
    return relationships


def classify_sheet_roles(all_sheets: dict, relationships: list) -> dict:
    """Classify each sheet as fact_table, dimension_table, or reference_table.

    Heuristics:
    - reference_table: ≤ 50 rows and ≤ 3 numeric columns (a lookup/code list)
    - fact_table: is on the child ("many") side of ≥ 1 relationship AND has ≥ 1 numeric column
    - dimension_table: is on the parent ("one") side and has < 5 000 rows
    - Fallback: any sheet with numeric columns -> fact_table; otherwise -> dimension_table
    """
    child_sheets = {r['to_sheet'] for r in relationships}
    parent_sheets = {r['from_sheet'] for r in relationships}

    roles = {}
    for sheet_name, df in all_sheets.items():
        n_rows = len(df)
        numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        n_numeric = len(numeric_cols)

        if n_rows <= 50 and n_numeric == 0:
            roles[sheet_name] = 'reference_table'
        elif sheet_name in child_sheets and n_numeric > 0:
            roles[sheet_name] = 'fact_table'
        elif sheet_name in parent_sheets and n_rows < 5000:
            roles[sheet_name] = 'dimension_table'
        else:
            roles[sheet_name] = 'fact_table' if n_numeric > 0 else 'dimension_table'

    return roles


def build_unified_schema(all_sheets: dict, profiles: dict, relationships: list, roles: dict) -> dict:
    """Assemble the unified schema dict used by services.py and query_engine.py."""
    sheets_info = {}
    for sheet_name, df in all_sheets.items():
        numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        text_cols = [c for c in df.columns if c not in numeric_cols]
        fk_cols = {r['to_col'] for r in relationships if r['to_sheet'] == sheet_name}
        sheets_info[sheet_name] = {
            'row_count': len(df),
            'role': roles.get(sheet_name, 'unknown'),
            'all_columns': list(df.columns),
            'numeric_columns': numeric_cols,
            'text_columns': text_cols,
            'fk_columns': list(fk_cols),
        }
    return {
        'sheets': sheets_info,
        'relationships': relationships,
    }


def format_relationships_block(unified_schema: dict) -> str:
    """Render relationship info as a [SHEET RELATIONSHIPS] block for LLM context."""
    if not unified_schema:
        return ''
    relationships = unified_schema.get('relationships') or []
    sheets = unified_schema.get('sheets') or {}
    if not relationships and len(sheets) <= 1:
        return ''

    _ROLE_LABELS = {
        'fact_table': 'fact table (transactions/events)',
        'dimension_table': 'dimension table (entities/attributes)',
        'reference_table': 'reference/lookup table',
    }

    lines = ['[SHEET RELATIONSHIPS]']
    for sheet_name, info in sheets.items():
        label = _ROLE_LABELS.get(info['role'], 'table')
        lines.append(f'  {sheet_name}: {label} ({info["row_count"]} rows)')

    if relationships:
        lines.append('')
        lines.append('  Detected foreign-key relationships:')
        for r in relationships:
            conf = f'{int(r["confidence"] * 100)}% confidence'
            lines.append(
                f'    {r["from_sheet"]}.{r["from_col"]} -> {r["to_sheet"]}.{r["to_col"]} '
                f'({r["type"]}, {conf}, {r["overlap_pct"]:.0f}% value overlap)'
            )
        lines.append('')
        lines.append(
            '  Cross-sheet queries are supported: the query engine can JOIN these sheets '
            'on the relationships above. When a question spans two sheets, include a "join" '
            'key in the query spec.'
        )
    else:
        lines.append('')
        lines.append('  No foreign-key relationships detected between sheets.')

    return '\n'.join(lines)
