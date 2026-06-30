"""Post-generation numeric grounding check for free-form narrative answers.

The deterministic query engine (query_engine.py) guarantees correct arithmetic
for direct data questions ("total spend", "top 3 vendors") because it never
lets the LLM do the math. But open-ended narrative answers (report prose, chat
summaries like "summarize the key trends") are still generated as free text,
and a model can still misstate an individual figure even when the right data
was right there in its context — e.g. reading "$1,800,000" out of a CSV
sample and writing "$180,000" in its answer.

This module extracts every dollar/quantity-looking number a narrative answer
claims and checks it against a flat set of every real value actually present
in the workbook: individual cell values, column-level aggregates (sum, mean,
min, max), and per-category rollups (e.g. sum of Spend per Vendor, per
Region) — since compound figures like "TechVendor Inc's spend in EMEA" are
exactly the kind of claim that isn't a single raw cell or a simple column
total. Any claimed number that doesn't match a real one within a small
tolerance is flagged, so the caller can ask the model to correct itself or
discard the answer rather than show an unverifiable figure.
"""
import re
import pandas as pd

_MAGNITUDE = {
    'k': 1_000, 'thousand': 1_000,
    'm': 1_000_000, 'mn': 1_000_000, 'million': 1_000_000,
    'b': 1_000_000_000, 'bn': 1_000_000_000, 'billion': 1_000_000_000,
}

# Matches "$1,800,000", "1800000", "1.8 million", "2.5M", etc. — a leading $ or a
# magnitude word/letter immediately after the digits both count as "this is a real
# quantity claim", not incidental text.
_NUMBER_RE = re.compile(
    r'(?<![\w.])\$?(\d[\d,]*(?:\.\d+)?)\s*(thousand|million|billion|mn|bn|[kmb])?(?![\w%])',
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r'^(19|20)\d{2}$')


def collect_known_numeric_values(all_sheets: dict, max_groupby_categories: int = 30) -> set:
    """Every real number a grounded narrative answer could legitimately cite:
    raw cell values, column aggregates, and per-category (dimension x measure)
    rollups — computed fresh from the full workbook, not a truncated preview."""
    known = set()
    for df in all_sheets.values():
        if not len(df.columns):
            continue
        numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        categorical_cols = [c for c in df.columns if c not in numeric_cols]

        known.add(float(len(df)))

        for col in numeric_cols:
            series = pd.to_numeric(df[col], errors='coerce').dropna()
            for v in series:
                known.add(round(float(v), 2))
            if len(series):
                known.add(round(float(series.sum()), 2))
                known.add(round(float(series.mean()), 2))
                known.add(round(float(series.min()), 2))
                known.add(round(float(series.max()), 2))

        for cat_col in categorical_cols:
            try:
                nunique = df[cat_col].nunique()
            except TypeError:
                continue
            if not (2 <= nunique <= max_groupby_categories):
                continue
            known.add(float(nunique))
            for size in df[cat_col].value_counts():
                known.add(float(size))
            for num_col in numeric_cols:
                work = pd.to_numeric(df[num_col], errors='coerce')
                grouped_frame = work.groupby(df[cat_col])
                for agg in ('sum', 'mean', 'count', 'min', 'max'):
                    try:
                        grouped = getattr(grouped_frame, agg)()
                    except Exception:
                        continue
                    for v in grouped.dropna():
                        known.add(round(float(v), 2))
    return known


def _to_value(raw_number: str, suffix: str) -> float:
    value = float(raw_number.replace(',', ''))
    if suffix:
        value *= _MAGNITUDE.get(suffix.lower(), 1)
    return value


def extract_claimed_numbers(text: str) -> list:
    claims = []
    for match in _NUMBER_RE.finditer(text):
        raw_number, suffix = match.group(1), match.group(2)
        if not suffix and _YEAR_RE.match(raw_number):
            continue  # a bare 4-digit year, not a data value
        try:
            claims.append(_to_value(raw_number, suffix))
        except ValueError:
            continue
    return claims


def find_unverifiable_numbers(text: str, known_values: set, min_value: float = 100) -> list:
    """Numbers the text claims that don't match anything real, within a 2%
    relative tolerance (rounded narrative phrasing like "~$1.24 million" for a
    real 1,237,500 should still pass). Small numbers (row/column counts,
    percentages, list indices) are skipped — too noisy and too rarely the
    source of the scale errors this exists to catch."""
    if not known_values:
        return []
    unverifiable = []
    for value in extract_claimed_numbers(text):
        if abs(value) < min_value:
            continue
        tolerance = max(1.0, abs(value) * 0.02)
        if not any(abs(value - k) <= tolerance for k in known_values):
            unverifiable.append(value)
    return unverifiable
