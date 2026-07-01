"""Visualization recommendation engine.

Examines query results and workbook structure and suggests the most
appropriate chart type. These hints are appended to query answers and
injected into the [VIZ RECOMMENDATIONS] context block so the AI can
tell the user how to visualize their data without guessing.

Rules are heuristic and intentionally simple — the goal is one useful
hint per situation, not an exhaustive ranking.
"""
import re
from typing import Optional


# Column-name patterns used to detect axis semantics
_DATE_RE = re.compile(r'date|period|month|year|quarter|week', re.IGNORECASE)
_GEO_RE = re.compile(r'region|country|state|city|location|territory|geo', re.IGNORECASE)
_CATEGORY_RE = re.compile(
    r'category|type|class|segment|department|dept|vendor|supplier|status|group',
    re.IGNORECASE,
)


def recommend_for_query_result(
    result_type: str,           # 'grouped', 'filtered', 'scalar', 'sorted'
    group_col: Optional[str],   # the GROUP BY / dimension column name
    value_col: Optional[str],   # the aggregated measure column name
    row_count: int = 0,
) -> dict:
    """Return a chart recommendation dict for a pandas query result.

    Args:
        result_type: how the data was produced
        group_col:   dimension column (x-axis), or None for non-grouped results
        value_col:   measure column (y-axis), or None for count-only queries
        row_count:   number of rows in the result

    Returns dict with keys: chart_type, x_axis, y_axis, rationale
    """
    if result_type == 'scalar' or row_count == 0:
        return {}  # Single number — no chart needed

    if result_type in ('filtered', 'sorted') and row_count > 0:
        if value_col and _DATE_RE.search(value_col or ''):
            return {
                'chart_type': 'line',
                'x_axis': value_col,
                'y_axis': None,
                'rationale': 'Time-ordered rows are best shown on a line chart.',
            }
        return {}  # Raw list — let the user decide

    # Grouped result: the interesting case
    if result_type == 'grouped' and group_col:
        is_time = bool(_DATE_RE.search(group_col))
        is_geo = bool(_GEO_RE.search(group_col))
        is_cat = bool(_CATEGORY_RE.search(group_col))

        if is_time:
            return {
                'chart_type': 'line',
                'x_axis': group_col,
                'y_axis': value_col,
                'rationale': f'Spend over time — a line chart shows the trend for "{group_col}".',
            }
        if is_geo:
            return {
                'chart_type': 'map' if row_count >= 5 else 'bar',
                'x_axis': group_col,
                'y_axis': value_col,
                'rationale': f'Geographic breakdown — a choropleth map (or bar chart if regions are few).',
            }
        if row_count <= 5:
            return {
                'chart_type': 'pie',
                'x_axis': group_col,
                'y_axis': value_col,
                'rationale': f'Only {row_count} categories — a pie chart shows proportions clearly.',
            }
        if row_count <= 20:
            return {
                'chart_type': 'bar',
                'x_axis': group_col,
                'y_axis': value_col,
                'rationale': f'Bar chart ranks "{group_col}" by "{value_col}" at a glance.',
            }
        # Many categories
        return {
            'chart_type': 'horizontal_bar',
            'x_axis': value_col,
            'y_axis': group_col,
            'rationale': f'{row_count} categories — a horizontal bar chart avoids label overlap.',
        }

    return {}


def recommend_for_workbook(all_sheets: Optional[dict], profiles: dict) -> list:
    """Return a list of chart suggestions for the uploaded workbook overall.

    Each suggestion is a dict with keys: sheet, chart_type, x_axis, y_axis, rationale.
    Works from profiles alone (all_sheets is optional and may be None).
    """
    suggestions = []

    # Build sheet names from whichever source is available
    sheet_names = list(all_sheets.keys()) if all_sheets else list(profiles.keys())

    for sheet_name in sheet_names:
        profile = profiles.get(sheet_name, {})
        columns = profile.get('columns', [])
        col_names = [c['name'] for c in columns]

        numeric_cols = [c['name'] for c in columns if c.get('data_type') == 'numeric']
        date_cols = [c for c in col_names if _DATE_RE.search(str(c))]
        cat_cols = [c for c in col_names if _CATEGORY_RE.search(str(c)) and c not in numeric_cols]
        geo_cols = [c for c in col_names if _GEO_RE.search(str(c)) and c not in numeric_cols]

        df = (all_sheets or {}).get(sheet_name)
        row_count = profile.get('row_count', len(df) if df is not None else 0)

        # Trend: date + numeric -> line chart
        if date_cols and numeric_cols:
            suggestions.append({
                'sheet': sheet_name,
                'chart_type': 'line',
                'x_axis': date_cols[0],
                'y_axis': numeric_cols[0],
                'rationale': f'Plot "{numeric_cols[0]}" over "{date_cols[0]}" to show spend trends.',
            })

        # Breakdown: category + numeric -> bar chart
        if cat_cols and numeric_cols:
            suggestions.append({
                'sheet': sheet_name,
                'chart_type': 'bar' if row_count <= 20 else 'horizontal_bar',
                'x_axis': cat_cols[0],
                'y_axis': numeric_cols[0],
                'rationale': f'Compare "{numeric_cols[0]}" by "{cat_cols[0]}" to see top contributors.',
            })

        # Geographic: geo + numeric -> map
        if geo_cols and numeric_cols:
            suggestions.append({
                'sheet': sheet_name,
                'chart_type': 'map',
                'x_axis': geo_cols[0],
                'y_axis': numeric_cols[0],
                'rationale': f'Map "{numeric_cols[0]}" by "{geo_cols[0]}" for regional comparison.',
            })

        # Multiple numerics with no dates -> scatter to find correlations
        if len(numeric_cols) >= 2 and not date_cols:
            suggestions.append({
                'sheet': sheet_name,
                'chart_type': 'scatter',
                'x_axis': numeric_cols[0],
                'y_axis': numeric_cols[1],
                'rationale': (
                    f'Scatter "{numeric_cols[0]}" vs "{numeric_cols[1]}" '
                    'to reveal correlation structure.'
                ),
            })

    return suggestions


def format_viz_hint(recommendation: dict) -> str:
    """Return a one-liner hint to append to a query result answer.

    Returns '' when recommendation is empty (scalar / no hint needed).
    """
    if not recommendation:
        return ''
    chart = recommendation.get('chart_type', '')
    x = recommendation.get('x_axis', '')
    y = recommendation.get('y_axis', '')
    rationale = recommendation.get('rationale', '')

    label_map = {
        'bar': 'Bar chart',
        'horizontal_bar': 'Horizontal bar chart',
        'line': 'Line chart',
        'pie': 'Pie chart',
        'scatter': 'Scatter plot',
        'map': 'Choropleth map',
    }
    label = label_map.get(chart, chart.replace('_', ' ').title())

    if x and y:
        return f'[VIZ] {label} suggested: {x} (x-axis) vs {y} (y-axis). {rationale}'
    if x:
        return f'[VIZ] {label} suggested: {x}. {rationale}'
    return f'[VIZ] {label} suggested. {rationale}'


def format_viz_context_block(suggestions: list) -> str:
    """Render workbook-level suggestions as a [VIZ RECOMMENDATIONS] context block."""
    if not suggestions:
        return ''

    lines = ['[VIZ RECOMMENDATIONS - suggested charts for this workbook:]']
    for s in suggestions:
        sheet_prefix = f'  Sheet "{s["sheet"]}": ' if len({sg["sheet"] for sg in suggestions}) > 1 else '  '
        lines.append(f'{sheet_prefix}{s["chart_type"].replace("_"," ").upper()} — {s["rationale"]}')
    return '\n'.join(lines)
