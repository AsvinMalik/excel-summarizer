# 🎯 PROCURE.AI - EXCEL SHEET ANALYSIS KNOWLEDGE BASE IMPROVEMENTS
## Comprehensive Implementation Guide for Claude CLI

---

## 📋 EXECUTIVE SUMMARY

The current Procure.ai project has a **strong procurement foundation** but **critical gaps in spreadsheet/data analysis capabilities**. This document outlines all modifications needed to pass enterprise acceptance testing and achieve production-grade data intelligence.

**Current State:** Basic Excel parsing + AI-driven insights
**Target State:** Enterprise-grade data analysis platform with schema understanding, validation, and intelligent querying

**Total Effort:** ~120-160 development hours across 3 phases

---

## 🔴 CRITICAL FLAWS BLOCKING ACCEPTANCE

### **Flaw #1: No Data Structure Understanding**
**Problem:**
- System treats all Excel files as "bags of text"
- Cannot infer column data types (numeric, date, categorical, currency)
- No understanding of relationships between columns
- Cannot distinguish between dimensions (vendor name, region) and measures (spend, count)

**Why It Matters:**
- Queries fail on type mismatches (e.g., "sum vendor names")
- Reports show incorrect aggregations
- NL queries produce wrong SQL
- Business users frustrated with inaccurate results

**Evidence:**
```python
# Current code (excel_analyzer.py lines 40-42):
excel_data = pd.read_excel(file_path)
data_summary = excel_data.describe(include='all').to_string()
# ❌ describe() is too generic; doesn't extract business meaning
```

---

### **Flaw #2: No Data Quality Validation**
**Problem:**
- Missing values not detected or reported
- Duplicate rows unidentified
- Outliers/anomalies ignored
- No checks for data consistency (e.g., dates out of logical range)
- Malformed data passed silently to AI model

**Why It Matters:**
- Analysis built on dirty data = unreliable insights
- Finance/procurement teams make decisions on bad info
- Compliance risk (audit trail shows analysis on invalid data)
- Wastes API tokens on analyzing garbage

**Impact Score:** 🔴 CRITICAL

---

### **Flaw #3: Weak Natural Language Query Parsing**
**Problem:**
- Current implementation: send raw data + user question to AI
- No intermediate query structure (no SQL generation, no intent parsing)
- Cannot handle:
  - Multi-step queries ("show me vendors with spend > $1M expiring next quarter")
  - Joins across sheets ("match vendor master with invoice data")
  - Complex aggregations ("group by region, show top 3 by spend")
  - Temporal logic ("last 12 months trends")

**Why It Matters:**
- Users ask moderately complex questions and get wrong answers
- System hallucinating SQL/queries instead of parsing correctly
- No auditability (can't show user what query actually ran)
- Errors not reproducible

**Current Flow:** User Query → AI → Vague Response
**Required Flow:** User Query → Intent Parser → Schema Mapper → SQL Generator → Executor → Response

**Impact Score:** 🔴 CRITICAL

---

### **Flaw #4: No Anomaly Detection or Data Quality Scoring**
**Problem:**
- System returns raw analysis without flagging data issues
- "Vendor spend increased 500%" reported as insight, not investigated
- No detection of:
  - Impossible values (negative dates, quantities > world population)
  - Statistical outliers (3-sigma violations)
  - Suspicious patterns (all values identical, sudden jumps)
  - Schema violations (text in numeric column)

**Why It Matters:**
- Bad data treated as good data = trust erosion
- Procurement teams bypass tool due to unreliability
- Regulatory risks (SOX, GDPR - unvalidated data in reports)
- API costs wasted analyzing nonsense

**Impact Score:** 🔴 CRITICAL

---

### **Flaw #5: Multi-Sheet Workbooks Not Properly Handled**
**Problem:**
- Multiple sheets dumped into single analysis
- No understanding of sheet relationships
- Cannot filter by sheet or query across sheets
- System prompt mentions "sheet_names" but backend doesn't use it

**Why It Matters:**
- Common procurement file structure: Summary sheet + Detail sheets + Lookup tables
- Users get confused/overloaded results
- Cross-sheet analysis impossible (e.g., sum invoice sheet, match to PO sheet)
- Sheet-specific queries fail

**Code Evidence (services.py lines 30-35):**
```python
if sheet_names:
    # Sheet names logged but NOT used in analysis context
    context_block += f"  Sheets ({len(sheet_names)}): {', '.join(sheet_names)}\n"
# ❌ Listed but not mapped to data types or relationships
```

**Impact Score:** 🟠 HIGH

---

## 🏗️ PHASE 1: ESSENTIAL IMPROVEMENTS (Priority 1)
**Estimated Effort:** 40-50 hours | **Risk:** Low | **ROI:** Very High

### **Requirement P1.1: Data Profiler Module**

**What to Build:**
A new file: `backend/data_profiler.py`

**Specification:**
```
Function: profile_spreadsheet(file_path, sheet_name=None)
Returns: {
  "sheet_name": "Vendors",
  "row_count": 1250,
  "column_count": 12,
  "columns": [
    {
      "name": "Vendor ID",
      "data_type": "integer",
      "null_count": 0,
      "unique_count": 1250,
      "sample_values": [1001, 1002, 1003, ...],
      "business_type": "primary_key",  # NEW
      "quality_score": 100
    },
    {
      "name": "Annual Spend",
      "data_type": "float",
      "null_count": 5,
      "min": 10000,
      "max": 2500000,
      "mean": 450000,
      "median": 320000,
      "stdev": 620000,
      "unique_count": 1120,
      "sample_values": [450000, 320000, ...],
      "business_type": "measure",  # NEW
      "outliers": 12,  # Values > 3 sigma
      "quality_score": 96  # NEW
    },
    {
      "name": "Contract Expiry",
      "data_type": "date",
      "null_count": 2,
      "min_date": "2024-01-15",
      "max_date": "2026-12-31",
      "format_detected": "YYYY-MM-DD",
      "future_count": 450,  # Dates in future
      "past_count": 800,
      "outliers": 0,
      "quality_score": 99,
      "business_type": "dimension"  # NEW
    }
  ],
  "data_quality": {
    "total_cells": 15000,
    "null_cells": 7,
    "duplicate_rows": 0,
    "quality_score": 99.95  # NEW
  }
}
```

**Detection Logic:**

| Column Pattern | Inferred Type | Logic |
|---|---|---|
| All integers, low cardinality (< 50 uniques) | Categorical | Distinct count < 0.5 * row count |
| All numbers | Numeric | try `float()` on samples |
| Contains format YYYY-MM-DD | Date | regex match `\d{4}-\d{2}-\d{2}` |
| Ends with "Total", "Sum", "Amount" | Measure | Name-based heuristic |
| Ends with "ID", "Code" | Dimension | Name-based heuristic |
| High null % (> 20%) | Sparse | `null_count / row_count` |

**Quality Scoring Formula:**
```
base_score = 100
score -= null_count / row_count * 20  (max -20)
score -= duplicate_rows / row_count * 15  (max -15)
score -= min(outlier_count / row_count * 10, 15)  (max -15)
score -= has_inconsistent_types * 25
score -= has_impossible_values * 30
final_score = max(score, 0)
```

**Anomaly Detection:**
- Null check: Flag if > 5% nulls
- Outlier detection: Values outside mean ± 3σ
- Impossible values:
  - Dates before 1900 or after 2100
  - Negative quantities
  - Spend < $0
  - % values > 100
- Pattern anomalies:
  - All values identical (stdev = 0)
  - Sudden 10x jump in consecutive rows
  - Text in numeric columns

**Implementation Notes:**
- Use `pandas` for statistical calculations
- Cache profile results (avoid re-scanning large files)
- Handle both single and multi-sheet workbooks
- Return detailed quality_score per column (not just aggregate)

---

### **Requirement P1.2: Schema Mapper & Context Builder**

**What to Build:**
New module: `backend/schema_mapper.py`

**Specification:**
```python
Function: build_schema_context(profile_result)
Returns: {
  "tables": [
    {
      "sheet_name": "Vendors",
      "row_count": 1250,
      "primary_key": "Vendor ID",  # NEW: identified by type + uniqueness
      "dimensions": [  # NEW: non-measure columns
        {"name": "Vendor Name", "type": "text", "role": "entity"},
        {"name": "Region", "type": "categorical", "values": ["APAC", "EMEA", ...]},
        {"name": "Contract Expiry", "type": "date"}
      ],
      "measures": [  # NEW: aggregatable columns
        {"name": "Annual Spend", "type": "currency", "aggregation": "sum"},
        {"name": "Invoice Count", "type": "integer", "aggregation": "sum"},
        {"name": "On-Time %", "type": "percentage", "aggregation": "average"}
      ],
      "quality_score": 99.5,
      "issues": ["5 null values in Annual Spend"]  # NEW
    },
    {
      "sheet_name": "Invoices",
      "row_count": 45000,
      "primary_key": "Invoice ID",
      "foreign_keys": [  # NEW: guessed relationships
        {
          "column": "Vendor ID",
          "references": "Vendors.Vendor ID",
          "confidence": 0.95
        }
      ],
      "dimensions": [...],
      "measures": [...]
    }
  ],
  "relationships": [  # NEW: cross-sheet relationships
    {
      "from": "Vendors.Vendor ID",
      "to": "Invoices.Vendor ID",
      "type": "1:N",
      "confidence": 0.95
    }
  ]
}
```

**Relationship Detection:**
- Column names match exactly (high confidence)
- Column names similar after normalization: "Vendor_ID" ↔ "VendorID" (medium)
- Value distributions overlap (low)

**Context String Format:**
Used to inject into LLM prompts, replacing generic data preview:

```
[SCHEMA CONTEXT]

Table: Vendors
- Rows: 1,250 | Quality: 99.5%
- Primary Key: Vendor ID (integer, all unique)
- Entities: Vendor Name (text), Region (categorical: APAC/EMEA/Americas), Industry (text)
- Metrics: Annual Spend (currency, sum-able), Contract Expiry (date), Risk Score (0-100)
- Issues: 5 null values in "Annual Spend"; 2 impossible future dates

Table: Invoices  
- Rows: 45,000 | Quality: 98%
- Primary Key: Invoice ID
- Links to: Vendors.Vendor ID (1:N relationship, 95% confidence)
- Entities: Invoice Date (date), PO Number (text)
- Metrics: Invoice Amount (currency), Days Late (integer)
- Issues: 12 orphaned invoices (no matching Vendor ID)

Recommended Queries:
- "Total spend by region this year": GROUP BY Vendors.Region, SUM(Invoices.Invoice Amount)
- "Late invoice %, by vendor": JOIN on Vendor ID, WHERE Days Late > 0, AVG(Days Late)
```

---

### **Requirement P1.3: Query Intent Parser & Executor**

**What to Build:**
New module: `backend/query_engine.py`

**Specification:**

**Step 1: Intent Classification**
Classify user query into one of:
- `aggregation` — "Total spend", "Count vendors", "Average payment days"
- `filtering` — "Show active vendors", "Contracts expiring next quarter"
- `ranking` — "Top 10 vendors by spend", "Lowest cost providers"
- `comparison` — "Compare spend by region", "Payment terms vs SLAs"
- `temporal` — "Spend trend over 12 months", "Renewal schedule"
- `anomaly` — "Show high-risk vendors", "Unusual patterns"
- `join` — "Which invoices don't match any vendor"
- `complex` — Multi-step (aggregation + filtering + ranking)

**Implementation:**
```python
def classify_intent(query: str) -> str:
    query_lower = query.lower()
    
    # Pattern matching (fast, deterministic)
    patterns = {
        'aggregation': ['total', 'sum', 'count', 'average', 'mean', 'how much'],
        'ranking': ['top', 'highest', 'lowest', 'first', 'rank', 'best', 'worst'],
        'temporal': ['trend', 'over time', 'year over year', 'monthly', 'quarterly'],
        ...
    }
    
    scores = {}
    for intent, keywords in patterns.items():
        scores[intent] = sum(query_lower.count(kw) for kw in keywords)
    
    return max(scores, key=scores.get)
```

**Step 2: Entity & Column Mapping**
Map user terms to actual schema:
- "spend" → Annual Spend, Invoice Amount, Contract Value (pick based on context)
- "vendor" → Vendor Name, Vendor ID (choose contextually)
- "this quarter" → Filter dates WHERE date >= DATE_TRUNC(NOW(), quarter)
- "risk" → Risk Score, # of late invoices, SLA violations

**Implementation:**
```python
def map_user_terms_to_schema(query: str, schema_context: dict) -> dict:
    # Use similarity matching (Levenshtein distance) + context
    column_names = [col for table in schema_context['tables'] for col in table['all_columns']]
    
    user_terms = extract_nouns(query)  # simple NLP
    mappings = {}
    for term in user_terms:
        best_match = find_closest(term, column_names)  # fuzzy match
        mappings[term] = best_match
    
    return mappings
```

**Step 3: Query Structure Generation**
Build intermediate query object (not raw SQL yet):
```python
{
  "intent": "aggregation",
  "primary_table": "Invoices",
  "joins": [
    {"table": "Vendors", "on": "Invoices.Vendor ID = Vendors.Vendor ID"}
  ],
  "filters": [
    {"column": "Invoice Date", "operator": ">=", "value": "2024-01-01"}
  ],
  "group_by": ["Vendors.Region"],
  "aggregate": [
    {"function": "sum", "column": "Invoice Amount", "alias": "Total Spend"}
  ],
  "order_by": [{"column": "Total Spend", "direction": "desc"}],
  "limit": 10
}
```

**Step 4: SQL Generation (with fallback to Pandas)**
```python
def generate_sql(query_structure: dict) -> str:
    sql = f"SELECT "
    sql += f", {query_structure['aggregate']}"
    sql += f" FROM {query_structure['primary_table']}"
    
    for join in query_structure['joins']:
        sql += f" LEFT JOIN {join['table']} ON {join['on']}"
    
    if query_structure['filters']:
        sql += " WHERE " + " AND ".join(filters)
    
    if query_structure['group_by']:
        sql += f" GROUP BY {', '.join(query_structure['group_by'])}"
    
    if query_structure['order_by']:
        sql += f" ORDER BY {query_structure['order_by']}"
    
    return sql
```

**Fallback to Pandas:**
If SQL execution fails or for complex pandas-specific operations, convert to pandas:
```python
def execute_with_pandas(excel_path: str, query_structure: dict) -> pd.DataFrame:
    # Load all sheets into memory
    dfs = pd.read_excel(excel_path, sheet_name=None)
    
    primary_table = dfs[query_structure['primary_table']]
    
    # Apply filters
    for filt in query_structure['filters']:
        primary_table = primary_table[...]
    
    # Apply joins
    for join in query_structure['joins']:
        primary_table = primary_table.merge(dfs[join['table']], ...)
    
    # Apply groupby + aggregate
    if query_structure['group_by']:
        primary_table = primary_table.groupby(...).agg(...)
    
    return primary_table
```

**Integration with Services:**
Update `backend/excel_analyzer.py`:
```python
def query_spreadsheet_data(file_path: str, natural_language_query: str) -> Dict:
    # NEW FLOW:
    profile = profile_spreadsheet(file_path)  # P1.1
    schema = build_schema_context(profile)     # P1.2
    
    intent = classify_intent(natural_language_query)  # P1.3
    query_struct = map_user_terms_to_schema(natural_language_query, schema)
    
    sql = generate_sql(query_struct)
    result = execute_with_pandas(file_path, query_struct)
    
    return {
        'success': True,
        'query_intent': intent,
        'mapped_columns': query_struct,
        'sql_generated': sql,  # NEW: show user what query ran
        'result': result.to_dict(),
        'result_count': len(result),
        'confidence': 0.95  # NEW: query confidence
    }
```

---

### **Requirement P1.4: Data Quality & Validation Layer**

**What to Build:**
New module: `backend/data_validator.py`

**Specification:**

**Quality Checks:**
```python
def validate_dataset(profile_result: dict) -> dict:
    issues = []
    
    for column in profile_result['columns']:
        # Check 1: High null count
        null_pct = column['null_count'] / profile_result['row_count']
        if null_pct > 0.05:
            issues.append({
                'severity': 'WARNING',
                'column': column['name'],
                'issue': f"High null count: {null_pct*100:.1f}%",
                'recommendation': 'Consider imputation or exclusion'
            })
        
        # Check 2: Impossible values
        if column['data_type'] == 'date':
            if column.get('min_date') < '1900-01-01' or column.get('max_date') > '2100-12-31':
                issues.append({
                    'severity': 'ERROR',
                    'column': column['name'],
                    'issue': 'Date range invalid',
                    'recommendation': 'Data entry error; verify source'
                })
        
        if column['data_type'] == 'float' and column.get('min', 0) < 0 and 'spend' in column['name'].lower():
            issues.append({
                'severity': 'ERROR',
                'column': column['name'],
                'issue': 'Negative spend detected',
                'recommendation': 'Verify if returns/credits or data error'
            })
        
        # Check 3: Outliers
        if column.get('outliers', 0) > column['unique_count'] * 0.1:  # > 10% outliers
            issues.append({
                'severity': 'CAUTION',
                'column': column['name'],
                'issue': f"High outlier count: {column['outliers']}",
                'recommendation': 'Investigate extreme values'
            })
        
        # Check 4: Zero variance
        if column['data_type'] in ['integer', 'float']:
            if column.get('stdev', 0) == 0:
                issues.append({
                    'severity': 'CAUTION',
                    'column': column['name'],
                    'issue': 'All values identical (zero variance)',
                    'recommendation': 'This column provides no differentiation'
                })
    
    # Check 5: Duplicate rows
    if profile_result['data_quality'].get('duplicate_rows', 0) > 0:
        issues.append({
            'severity': 'WARNING',
            'issue': f"{profile_result['data_quality']['duplicate_rows']} duplicate rows detected",
            'recommendation': 'De-duplicate before analysis'
        })
    
    return {
        'is_valid': len([i for i in issues if i['severity'] == 'ERROR']) == 0,
        'quality_score': profile_result['data_quality'].get('quality_score', 0),
        'issues': issues,
        'safe_to_analyze': all(i['severity'] != 'ERROR' for i in issues)
    }
```

**Validation Report in Response:**
```python
def analyze_excel_data(file_path: str, user_query: str = None) -> Dict:
    profile = profile_spreadsheet(file_path)
    validation = validate_dataset(profile)
    
    response = {
        'success': True,
        'file_quality_score': validation['quality_score'],
        'data_issues': validation['issues'],  # NEW
        'safe_to_analyze': validation['safe_to_analyze'],  # NEW
        'analysis': None
    }
    
    if not validation['safe_to_analyze']:
        response['analysis'] = f"⚠️ Data quality issues detected. Proceed with caution:\n" + \
                               "\n".join([f"- [{i['severity']}] {i['column']}: {i['issue']}" 
                                         for i in validation['issues']])
    else:
        response['analysis'] = run_full_analysis(file_path, user_query, profile)
    
    return response
```

---

## 🏢 PHASE 2: HIGH-VALUE ENHANCEMENTS (Priority 2)
**Estimated Effort:** 35-50 hours | **Risk:** Medium | **ROI:** High

### **Requirement P2.1: Multi-Sheet Orchestrator**

**What to Build:**
Enhancement to `backend/services.py` and new `backend/sheet_orchestrator.py`

**Current Problem:**
- All sheets loaded as one pile
- No way to query "which invoices don't match vendors"
- Can't distinguish primary vs lookup tables

**Solution:**

```python
def analyze_multi_sheet_workbook(file_path: str) -> dict:
    """
    Orchestrate analysis across multiple sheets.
    Detect relationships, build unified schema, enable cross-sheet queries.
    """
    
    # Step 1: Profile each sheet independently
    workbook = pd.ExcelFile(file_path)
    sheet_profiles = {}
    for sheet_name in workbook.sheet_names:
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        sheet_profiles[sheet_name] = profile_spreadsheet(file_path, sheet_name)
    
    # Step 2: Detect relationships between sheets
    relationships = detect_relationships(sheet_profiles)
    # Returns: [{"from": "Vendors.Vendor ID", "to": "Invoices.Vendor ID", "confidence": 0.95}]
    
    # Step 3: Classify sheets by role
    sheet_roles = classify_sheet_roles(sheet_profiles, relationships)
    # Returns: {"Vendors": "dimension_table", "Invoices": "fact_table", "Lookup_Status": "reference"}
    
    # Step 4: Build unified schema with relationships
    unified_schema = build_unified_schema(sheet_profiles, relationships, sheet_roles)
    
    return {
        'sheets': sheet_profiles,
        'relationships': relationships,
        'sheet_roles': sheet_roles,
        'unified_schema': unified_schema,
        'analysis_suggestions': generate_analysis_suggestions(unified_schema)
    }
```

**Relationship Detection Logic:**
```python
def detect_relationships(sheet_profiles: dict) -> list:
    relationships = []
    
    # Get all columns from all sheets
    all_columns = {}
    for sheet, profile in sheet_profiles.items():
        for col in profile['columns']:
            key = col['name'].lower().replace(' ', '_')
            if key not in all_columns:
                all_columns[key] = []
            all_columns[key].append({'sheet': sheet, 'column': col['name'], 'col_obj': col})
    
    # Find matching column names (potential FK relationships)
    for col_key, occurrences in all_columns.items():
        if len(occurrences) < 2:
            continue
        
        for i, occ1 in enumerate(occurrences):
            for occ2 in occurrences[i+1:]:
                sheet1, sheet2 = occ1['sheet'], occ2['sheet']
                col1, col2 = occ1['column'], occ2['column']
                
                # Check if values overlap
                df1 = pd.read_excel(file_path, sheet_name=sheet1)[col1]
                df2 = pd.read_excel(file_path, sheet_name=sheet2)[col2]
                
                overlap = len(set(df1) & set(df2))
                total = min(len(df1), len(df2))
                
                if overlap / total > 0.8:  # 80%+ overlap = likely FK
                    relationships.append({
                        'from': f"{sheet1}.{col1}",
                        'to': f"{sheet2}.{col2}",
                        'overlap_pct': (overlap / total) * 100,
                        'confidence': 0.95,
                        'direction': 'left-join'  # or 'inner-join' if strict
                    })
    
    return relationships
```

**Sheet Role Classification:**
```python
def classify_sheet_roles(sheet_profiles: dict, relationships: list) -> dict:
    """
    Fact table: many rows, many foreign keys, measures present
    Dimension table: fewer rows, few foreign keys, mostly text/categories
    Reference/Lookup: tiny (< 100 rows), all categorical
    """
    roles = {}
    
    for sheet, profile in sheet_profiles.items():
        fk_count = len([r for r in relationships if sheet in r['from']])
        measure_count = len([c for c in profile['columns'] if c['business_type'] == 'measure'])
        row_count = profile['row_count']
        
        if row_count < 100 and measure_count == 0:
            roles[sheet] = 'reference_table'
        elif fk_count > 1 and measure_count > 0:
            roles[sheet] = 'fact_table'
        elif row_count < 5000 and fk_count <= 1:
            roles[sheet] = 'dimension_table'
        else:
            roles[sheet] = 'unknown'
    
    return roles
```

**Cross-Sheet Query Support:**
```python
# In query_engine.py, extend to support sheet joins:

def map_columns_across_sheets(column_ref: str, schema: dict) -> list:
    """
    "spend" could be:
    - Invoices.Invoice Amount
    - Vendors.Annual Spend
    - Contracts.Contract Value
    
    Use sheet role to disambiguate.
    """
    sheet_profiles = schema['sheets']
    possible_columns = []
    
    for sheet, profile in sheet_profiles.items():
        sheet_role = schema['sheet_roles'][sheet]
        for col in profile['columns']:
            if column_ref.lower() in col['name'].lower():
                possible_columns.append({
                    'full_path': f"{sheet}.{col['name']}",
                    'sheet': sheet,
                    'column': col['name'],
                    'score': similarity(column_ref, col['name']),
                    'context': sheet_role
                })
    
    # Prefer fact table measures over dimension attributes
    possible_columns.sort(key=lambda x: (
        x['context'] == 'fact_table',  # True sorts after False (ascending)
        -x['score']  # Higher similarity first
    ), reverse=True)
    
    return possible_columns
```

**Example Usage:**
```
User: "Show me vendors with invoices still unpaid"
→ Intent: join query + filtering
→ Detected tables: Vendors (dimension) + Invoices (fact)
→ Join detected: Vendors.Vendor ID ← Invoices.Vendor ID
→ Generated SQL:
   SELECT DISTINCT Vendors.Vendor Name
   FROM Vendors
   INNER JOIN Invoices ON Vendors.Vendor ID = Invoices.Vendor ID
   WHERE Invoices.Payment Status = 'Unpaid'
```

---

### **Requirement P2.2: Statistical Analysis & Trend Detection**

**What to Build:**
New module: `backend/statistical_analyzer.py`

**Capabilities:**

```python
def analyze_numeric_column(df: pd.DataFrame, column: str, by_groups: list = None) -> dict:
    """
    Comprehensive statistical analysis of numeric columns.
    Optionally broken down by grouping columns.
    """
    
    if by_groups:
        # Grouped analysis
        results = {}
        for group_val, group_df in df.groupby(by_groups):
            results[str(group_val)] = {
                'count': len(group_df),
                'mean': group_df[column].mean(),
                'median': group_df[column].median(),
                'stdev': group_df[column].std(),
                'min': group_df[column].min(),
                'max': group_df[column].max(),
                'q25': group_df[column].quantile(0.25),
                'q75': group_df[column].quantile(0.75),
                'iqr': group_df[column].quantile(0.75) - group_df[column].quantile(0.25),
                'skewness': group_df[column].skew(),
                'kurtosis': group_df[column].kurtosis(),
            }
        return results
    else:
        # Overall analysis
        return {
            'count': len(df),
            'mean': df[column].mean(),
            'median': df[column].median(),
            'stdev': df[column].std(),
            'min': df[column].min(),
            'max': df[column].max(),
            'q25': df[column].quantile(0.25),
            'q75': df[column].quantile(0.75),
            'iqr': df[column].quantile(0.75) - df[column].quantile(0.25),
            'coefficient_of_variation': df[column].std() / df[column].mean(),
            'skewness': df[column].skew(),  # -1 = left-skewed, 0 = normal, +1 = right-skewed
            'kurtosis': df[column].kurtosis(),  # 0 = normal, >0 = heavy tails
        }
```

**Correlation Analysis:**
```python
def analyze_correlations(df: pd.DataFrame, numeric_columns: list) -> dict:
    """
    Identify relationships between numeric columns.
    Flag suspicious correlations (e.g., spend perfectly tied to invoice count).
    """
    corr_matrix = df[numeric_columns].corr()
    
    strong_correlations = []
    for i, col1 in enumerate(numeric_columns):
        for col2 in numeric_columns[i+1:]:
            corr_val = corr_matrix.loc[col1, col2]
            if abs(corr_val) > 0.7:
                strong_correlations.append({
                    'column1': col1,
                    'column2': col2,
                    'correlation': corr_val,
                    'interpretation': 'Strong positive' if corr_val > 0 else 'Strong negative'
                })
    
    return {
        'correlation_matrix': corr_matrix.to_dict(),
        'strong_correlations': strong_correlations
    }
```

**Trend Analysis (Time Series):**
```python
def analyze_trends(df: pd.DataFrame, date_column: str, value_column: str, 
                   groupby_column: str = None) -> dict:
    """
    Detect trends, seasonality, growth patterns.
    """
    # Sort by date
    df = df.sort_values(date_column)
    df.set_index(date_column, inplace=True)
    
    if groupby_column:
        trends = {}
        for group_val, group_df in df.groupby(groupby_column):
            trends[str(group_val)] = calculate_trend(group_df[value_column])
        return trends
    else:
        return calculate_trend(df[value_column])

def calculate_trend(series: pd.Series) -> dict:
    # Linear regression to find slope
    x = np.arange(len(series))
    slope, intercept = np.polyfit(x, series, 1)
    
    # YoY growth if monthly data
    if len(series) >= 24:
        yoy_growth = (series[-12:].sum() - series[-24:-12].sum()) / series[-24:-12].sum() * 100
    else:
        yoy_growth = None
    
    return {
        'slope': slope,  # $ per period (positive = growing)
        'direction': 'increasing' if slope > 0 else 'decreasing',
        'growth_rate_pct': (slope / series.mean()) * 100,
        'yoy_growth_pct': yoy_growth,
        'volatility': series.std() / series.mean(),
        'forecast_next_period': series[-1] + slope
    }
```

**Anomaly Detection:**
```python
def detect_anomalies(df: pd.DataFrame, column: str) -> list:
    """
    Identify unusual data points using multiple methods.
    """
    anomalies = []
    
    # Method 1: Z-score (> 3 sigma)
    mean = df[column].mean()
    stdev = df[column].std()
    z_scores = np.abs((df[column] - mean) / stdev)
    z_anomalies = df[z_scores > 3]
    for idx, val in z_anomalies.items():
        anomalies.append({
            'index': idx,
            'value': val,
            'method': 'z-score (>3σ)',
            'severity': 'high'
        })
    
    # Method 2: IQR (Tukey fences)
    Q1 = df[column].quantile(0.25)
    Q3 = df[column].quantile(0.75)
    IQR = Q3 - Q1
    lower_fence = Q1 - 1.5 * IQR
    upper_fence = Q3 + 1.5 * IQR
    iqr_anomalies = df[(df[column] < lower_fence) | (df[column] > upper_fence)]
    for idx, val in iqr_anomalies.items():
        if not any(a['index'] == idx for a in anomalies):
            anomalies.append({
                'index': idx,
                'value': val,
                'method': 'IQR',
                'severity': 'medium'
            })
    
    # Method 3: Sudden jumps (day-over-day > 100%)
    pct_changes = df[column].pct_change()
    jump_rows = pct_changes[pct_changes.abs() > 1.0]  # 100%+ change
    for idx, pct in jump_rows.items():
        anomalies.append({
            'index': idx,
            'value': df.loc[idx, column],
            'previous_value': df.loc[df.index[df.index.get_loc(idx)-1], column],
            'method': 'sudden jump',
            'pct_change': pct * 100,
            'severity': 'medium'
        })
    
    return anomalies
```

**Integration with Query Results:**
```python
# When returning analysis results, include:
{
    'result': df.to_dict(),
    'statistics': analyze_numeric_column(df, 'Annual Spend', by_groups=['Region']),
    'correlations': analyze_correlations(df, numeric_cols=['Annual Spend', 'Invoice Count']),
    'anomalies': detect_anomalies(df, 'Annual Spend'),
    'trends': analyze_trends(df, 'Contract Date', 'Annual Spend'),
    'insights': [
        "Spend in APAC region growing 15% YoY vs -5% overall",
        "Vendor 1042 is a statistical outlier (3.2σ above mean)",
        "Strong correlation (r=0.92) between invoice count and payment delays"
    ]
}
```

---

### **Requirement P2.3: Business Context Mapping**

**What to Build:**
New config file: `backend/business_glossary.json` + logic in `schema_mapper.py`

**Purpose:**
Help system understand business meaning, not just syntax.

**Format:**
```json
{
  "spending_columns": [
    "Annual Spend", "Contract Value", "Invoice Amount", "Total Amount",
    "Spend YTD", "Monthly Spend", "PO Amount", "estimated_cost"
  ],
  "date_columns": [
    "Contract Expiry", "Invoice Date", "Due Date", "End Date", "Renewal Date"
  ],
  "vendor_identifiers": [
    "Vendor Name", "Vendor ID", "Supplier Name", "Supplier Code"
  ],
  "regions": [
    "APAC", "EMEA", "Americas", "Asia-Pacific", "Europe", "North America",
    "Region", "Geography", "Territory"
  ],
  "risk_indicators": [
    "Risk Score", "Risk Level", "Late Payments", "Compliance Issues",
    "Days Late", "On-Time %"
  ],
  "status_values": {
    "contract_status": ["Active", "Inactive", "Expired", "Pending", "Terminated"],
    "payment_status": ["Paid", "Unpaid", "Partially Paid", "Overdue"]
  }
}
```

**Usage in Schema Mapper:**
```python
def enrich_column_with_business_context(column_name: str, data_type: str) -> dict:
    glossary = load_business_glossary()
    
    context = {
        'name': column_name,
        'data_type': data_type,
        'business_category': None,
        'aggregation_method': None,
        'unit': None
    }
    
    # Check glossary
    for category, terms in glossary.items():
        if any(term.lower() in column_name.lower() for term in terms):
            context['business_category'] = category
            
            # Infer aggregation
            if category == 'spending_columns':
                context['aggregation_method'] = 'sum'
                context['unit'] = 'currency'
            elif category == 'risk_indicators':
                context['aggregation_method'] = 'average'
                context['unit'] = 'score'
            
            break
    
    return context
```

---

## 🎨 PHASE 3: POLISH & ADVANCED (Priority 3)
**Estimated Effort:** 25-30 hours | **Risk:** Medium | **ROI:** Medium

### **Requirement P3.1: Audit Trail & Data Lineage**

**What to Build:**
New module: `backend/audit_logger.py`

**Specification:**

```python
def log_analysis_event(event_type: str, user_id: str, document_id: str, 
                       query: str, result: dict, confidence: float = None):
    """
    Log every analysis action for compliance & debugging.
    """
    event = {
        'timestamp': datetime.utcnow().isoformat(),
        'event_type': event_type,  # 'profile', 'query', 'export'
        'user_id': user_id,
        'document_id': document_id,
        'query': query,
        'result_row_count': len(result.get('data', [])),
        'columns_referenced': result.get('columns_used', []),
        'confidence_score': confidence,
        'data_quality_score': result.get('quality_score'),
        'anomalies_detected': len(result.get('anomalies', [])),
        'processing_time_ms': result.get('processing_time_ms')
    }
    
    # Store in audit table
    write_to_audit_log(event)
    
    return event
```

**Audit Trail Report:**
Users can request "Show me what analysis was run on this file" and see:
- Who accessed it
- When
- What queries
- What was changed
- Confidence scores

---

### **Requirement P3.2: Visualization Recommendations Engine**

**What to Build:**
New module: `backend/viz_recommender.py`

**Specification:**

```python
def recommend_visualizations(result_df: pd.DataFrame, query_intent: str) -> list:
    """
    Based on result shape and query intent, recommend visualization types.
    """
    recommendations = []
    
    shape = (result_df.shape[0], result_df.shape[1])
    numeric_cols = result_df.select_dtypes(include=['number']).columns.tolist()
    categorical_cols = result_df.select_dtypes(include=['object']).columns.tolist()
    date_cols = result_df.select_dtypes(include=['datetime']).columns.tolist()
    
    # Logic based on shape and intent
    if query_intent == 'aggregation' and shape[0] == 1:
        # Single row result
        recommendations.append({'type': 'metric_card', 'priority': 'high'})
    
    if query_intent == 'ranking' or query_intent == 'comparison':
        if len(numeric_cols) == 1 and len(categorical_cols) >= 1:
            recommendations.append({'type': 'bar_chart', 'priority': 'high'})
            recommendations.append({'type': 'horizontal_bar', 'priority': 'medium'})
    
    if query_intent == 'temporal' and len(date_cols) >= 1:
        if len(numeric_cols) == 1:
            recommendations.append({'type': 'line_chart', 'priority': 'high'})
        if len(numeric_cols) >= 2:
            recommendations.append({'type': 'stacked_area', 'priority': 'high'})
    
    if len(categorical_cols) >= 2:
        recommendations.append({'type': 'heatmap', 'priority': 'medium'})
    
    if len(categorical_cols) == 1 and len(numeric_cols) == 1:
        recommendations.append({'type': 'pie_chart', 'priority': 'low'})  # Only if part-to-whole
    
    return recommendations
```

---

## 📝 IMPLEMENTATION ROADMAP

### **Week 1-2: Phase 1 Core (40 hours)**
```
Monday:    Data Profiler (P1.1) + unit tests
Wednesday: Schema Mapper (P1.2) + integration tests
Friday:    Query Engine (P1.3) + E2E tests
```

### **Week 3: Phase 1 Validation (10 hours)**
```
Monday:    Data Validator (P1.4) + quality scoring
Tuesday:   End-to-end testing with real contracts
Wednesday: Fix bugs, optimize performance
```

### **Week 4-5: Phase 2 (40 hours)**
```
Monday:    Multi-sheet Orchestrator (P2.1)
Wednesday: Statistical Analysis (P2.2)
Friday:    Business Glossary (P2.3)
```

### **Week 6: Phase 3 (20 hours)**
```
Monday:    Audit Trail (P3.1)
Tuesday:   Viz Recommender (P3.2)
Wednesday: Polish, documentation, final testing
```

---

## 🧪 TESTING STRATEGY

### **Unit Tests (Per Module)**
```python
# test_data_profiler.py
def test_profile_single_sheet():
    result = profile_spreadsheet('test_vendors.xlsx')
    assert result['row_count'] == 1250
    assert result['column_count'] == 12
    assert any(c['data_type'] == 'currency' for c in result['columns'])

def test_anomaly_detection():
    result = profile_spreadsheet('test_with_outliers.xlsx')
    assert result['columns'][0]['outliers'] > 0

# test_query_engine.py
def test_classify_intent():
    assert classify_intent("show me top 10 vendors") == 'ranking'
    assert classify_intent("what's the total spend") == 'aggregation'

def test_generate_sql_aggregation():
    query_struct = {...}
    sql = generate_sql(query_struct)
    assert 'GROUP BY' in sql
    assert 'SUM' in sql
```

### **Integration Tests**
```python
# test_end_to_end.py
def test_full_workflow():
    # Upload file
    # Profile it
    # Ask question
    # Verify SQL generated
    # Check result
    # Verify audit trail logged
```

### **Acceptance Criteria**
**P1.1 (Profiler):**
- ✅ Detects all column data types correctly (>95% accuracy)
- ✅ Identifies null %, outliers, duplicates
- ✅ Runs in < 2 seconds for 10K rows
- ✅ Quality score correlates with manual inspection

**P1.2 (Schema Mapper):**
- ✅ Correctly labels dimensions vs measures
- ✅ Detects relationships with >90% accuracy
- ✅ Schema context injected into LLM prompt

**P1.3 (Query Engine):**
- ✅ Parses 10 intent types correctly (>95%)
- ✅ Generates valid SQL for aggregation, filtering, ranking
- ✅ Fallback to pandas if SQL fails
- ✅ Shows user the query that ran

**P1.4 (Validator):**
- ✅ Flags all data quality issues
- ✅ Provides actionable recommendations
- ✅ Quality score used to gate analysis ("this data is 65% quality")

**P2.1 (Multi-Sheet):**
- ✅ Detects FK relationships correctly
- ✅ Joins execute without errors
- ✅ Cross-sheet queries return correct results

**P2.2 (Statistics):**
- ✅ Correlations calculated correctly
- ✅ Trends detected with >80% accuracy
- ✅ Anomalies flagged with explanation

**P2.3 (Business Glossary):**
- ✅ Disambiguates "spend" → correct column
- ✅ Glossary updates don't require code changes

---

## 🚨 CRITICAL SUCCESS FACTORS

### **1. Data Grounding (Non-Negotiable)**
Every number, name, date in output must come from actual data.
- ❌ DO NOT hallucinate example outputs
- ❌ DO NOT invent placeholder values
- ✅ DO show "[INSUFFICIENT DATA]" instead

### **2. Query Transparency**
Users must see what query actually ran.
- ✅ Log SQL generated
- ✅ Show mapped columns
- ✅ Confidence score on result

### **3. Quality Gates**
Analysis should not proceed if data quality too low.
```python
if validation_result['quality_score'] < 70:
    return {
        'error': 'Data quality too low',
        'quality_score': 65,
        'issues': [...],
        'recommendation': 'Fix issues before analysis'
    }
```

### **4. Performance**
- Profile: < 2s for 100K rows
- Query: < 5s for complex aggregations
- Multi-sheet join: < 10s

---

## 📦 FILE STRUCTURE (POST-IMPLEMENTATION)

```
backend/
├── data_profiler.py           # P1.1: Column analysis, quality scoring
├── schema_mapper.py           # P1.2: Dimension vs measure labeling, relationships
├── query_engine.py            # P1.3: NL→SQL parsing, execution
├── data_validator.py          # P1.4: Quality checks, issue flagging
├── sheet_orchestrator.py      # P2.1: Multi-sheet relationships
├── statistical_analyzer.py    # P2.2: Correlation, trend, anomaly detection
├── business_glossary.json     # P2.3: Domain knowledge mapping
├── audit_logger.py            # P3.1: Compliance logging
├── viz_recommender.py         # P3.2: Chart suggestions
├── main.py                    # Updated with new endpoints
├── services.py                # Updated with new tools
└── requirements.txt           # Add: scipy, scikit-learn, nltk
```

---

## ✅ COMPANY ACCEPTANCE CHECKLIST

### **Functional Requirements**
- [ ] Can profile any Excel file in < 3 seconds
- [ ] Detects data quality issues (nulls, duplicates, outliers, type mismatches)
- [ ] Converts natural language to structured queries
- [ ] Handles multi-sheet workbooks with FK relationships
- [ ] Provides statistical analysis (correlations, trends, anomalies)
- [ ] Returns results with confidence scores and audit trail

### **Data Integrity**
- [ ] No hallucinated data in outputs
- [ ] Query transparency (user sees SQL/mapping)
- [ ] Quality gates prevent bad-data analysis
- [ ] All numbers traced to source

### **Performance**
- [ ] Profile < 2s, Query < 5s, Join < 10s
- [ ] Handles workbooks with 1M+ rows (streaming/chunking if needed)

### **Enterprise Features**
- [ ] Audit logging for compliance
- [ ] Business glossary for domain knowledge
- [ ] Visualization recommendations
- [ ] Error handling with actionable messages

### **Testing**
- [ ] 80%+ code coverage (unit + integration)
- [ ] Acceptance tests on real procurement files
- [ ] Performance benchmarks documented

---

## 🎯 SUCCESS METRICS

| Metric | Target | Measurement |
|--------|--------|-------------|
| Data quality detection | >95% accuracy | Compare flagged issues vs manual review |
| Query parsing accuracy | >90% | Test on 50 diverse NL queries |
| Multi-sheet relationship detection | >85% confidence | Validate on 20 real workbooks |
| Analysis confidence score | 80%+ for clean data | Quality score vs result accuracy |
| Performance (profile) | < 2 seconds | Benchmark on 100K rows |
| Performance (query) | < 5 seconds | Benchmark on 1M rows |
| User satisfaction | >8/10 | Feedback from 10 procurement managers |

---

## 📞 IMPLEMENTATION NOTES FOR CLAUDE CLI

**When using Claude CLI to implement these changes:**

```bash
# Example: Generate P1.1 (Data Profiler) implementation
claude run backend/data_profiler.py \
  --task "Implement data_profiler.py per CLAUDE_IMPLEMENTATION_PROMPT.md, Requirement P1.1" \
  --context "See full spec in CLAUDE_IMPLEMENTATION_PROMPT.md lines 150-250"

# Example: Test P1.1
claude run test_data_profiler.py \
  --task "Write comprehensive unit tests for data_profiler.py" \
  --validate "Must achieve >95% data type detection accuracy"

# Example: Integrate into services
claude run backend/services.py \
  --task "Integrate data_profiler output into analyze_excel_data() per P1.1" \
  --preserve "Keep existing API compatibility; add new response fields"
```

**Key Instructions for Claude:**
1. Follow Phase 1 → Phase 2 → Phase 3 order (don't skip ahead)
2. Each module must be tested independently before integration
3. Maintain backward compatibility with existing APIs
4. Add comprehensive docstrings and type hints
5. Include error handling for edge cases (empty files, corrupted sheets, etc.)
6. Log all processing steps for debugging

---

**END OF IMPLEMENTATION GUIDE**

This document defines the complete knowledge base improvements needed for enterprise acceptance. Focus on Phase 1 first—it alone solves 80% of current issues and unblocks company acceptance. Phases 2-3 add polish and advanced capabilities.
