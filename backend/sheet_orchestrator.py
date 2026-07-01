"""Multi-sheet relationship detection and unified schema building.

Detects foreign-key relationships between sheets by matching column names
and checking value overlap. Classifies each sheet's role (fact table,
dimension table, reference table) and builds a unified schema so the query
engine and LLM context always know which sheets can be joined and how.
"""
import re
import pandas as pd


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
