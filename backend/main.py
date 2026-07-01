from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uuid
import json
import sys
import os
import io
import re as _re
import pandas as pd
import logging
from datetime import datetime
from time import time


def _looks_numeric_string(v) -> bool:
    """True when v is a string that parses as a float — catches FX rates stored
    as text (e.g. '1.23', '0.85') that fool a pure isinstance check."""
    if not isinstance(v, str):
        return False
    try:
        float(v.replace(',', '').strip())
        return True
    except (ValueError, AttributeError):
        return False


def _is_title_row(row_vals: list, n_total_cols: int) -> bool:
    """Heuristic: True when a data row looks like a report-title or blank-separator
    row rather than real column headers.

    Title-row signals (any one is sufficient):
    - Fewer than 2 non-null cells (very sparse — almost always decorative)
    - A single dominant value fills >60% of the non-null cells (merged-cell title
      forward-replicated, e.g. 'CONSOLIDATED REPORT 2024' across 70 columns)
    """
    non_null = [str(v).strip() for v in row_vals
                if pd.notna(v) and str(v).strip() not in ('', 'nan')]
    if len(non_null) < 2:
        return True
    unique = set(non_null)
    if len(unique) <= 2:
        dominant = max(unique, key=lambda x: non_null.count(x))
        if non_null.count(dominant) / len(non_null) > 0.60:
            return True
    return False


def _is_header_candidate(row_vals: list) -> bool:
    """Heuristic: True when a row looks like real column headers.

    Header-row signals (ALL must hold):
    - ≥2 non-null cells
    - ≥60% are strings (not booleans, not numeric, not numeric-looking strings)
    - <15% are bare numeric values or numeric-looking strings  ← FX-rate guard
    - Average string length <50 chars (column names are short; prose/titles aren't)
    - No backtick characters (garbled encoding artifact)
    """
    non_null = [v for v in row_vals if pd.notna(v) and str(v).strip() not in ('', 'nan')]
    if len(non_null) < 2:
        return False

    str_vals   = [v for v in non_null if isinstance(v, str) and not _looks_numeric_string(v)]
    num_vals   = [v for v in non_null
                  if (isinstance(v, (int, float)) and not isinstance(v, bool))
                  or _looks_numeric_string(v)]

    str_ratio = len(str_vals) / len(non_null)
    num_ratio = len(num_vals) / len(non_null)
    avg_len   = (sum(len(str(v)) for v in str_vals) / len(str_vals)) if str_vals else 0
    has_garbled = any('`' in str(v) or str(v).startswith('=') for v in str_vals)

    return (
        str_ratio   > 0.60
        and num_ratio < 0.15       # raised from 0.10 — FX rates are ~100% numeric
        and avg_len   < 50
        and not has_garbled
    )


def _promote_row_as_headers(df: pd.DataFrame, data_row_idx: int) -> pd.DataFrame:
    """Promote df.iloc[data_row_idx] into column names, combining with any
    non-Unnamed parent header already in df.columns (two-row header pattern)."""
    candidate = df.iloc[data_row_idx]
    new_cols: list = []
    seen: dict = {}
    for orig_col, sub_val in zip(df.columns, candidate):
        parent = str(orig_col) if not str(orig_col).startswith('Unnamed') else ''
        sub = str(sub_val).strip() if pd.notna(sub_val) and str(sub_val) != 'nan' else ''
        if parent and sub and parent != sub:
            name = f'{parent} - {sub}'
        elif sub:
            name = sub
        elif parent:
            name = parent
        else:
            name = f'Col_{len(new_cols)}'
        if name in seen:
            seen[name] += 1
            name = f'{name}_{seen[name]}'
        else:
            seen[name] = 0
        new_cols.append(name)
    out = df.iloc[data_row_idx + 1:].reset_index(drop=True)
    out.columns = new_cols
    return out


def _clean_sheet_headers(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise Excel headers that pandas reads poorly.

    Three classes of real-file corruption handled (all confirmed against the
    reference MIS workbook 'MIS Automation PGIL.xlsx'):

    1. Title/blank rows above the real header — a report-title merged cell
       (e.g. 'CONSOLIDATED REPORT 2024' across 70 columns) or a blank
       separator row sits above the true column-header row.  Pandas promotes
       the title as df.columns and leaves the real headers in df.iloc[0].
       Fix: scan the first data rows, skip confirmed title/blank rows, then
       promote the first genuine header-candidate row.

    2. FX-rate or numeric values in the candidate header row — values like
       1.23 / 0.85 look like strings to isinstance() if stored as text but
       are clearly data, not column names.  Fix: _is_header_candidate() treats
       numeric-looking strings the same as bare floats when checking the
       numeric ratio threshold (raised from 10% to 15%).

    3. Merged-cell section headers forward-filled across many Unnamed columns —
       a short section-header like 'Q1 Actuals' spanning 4 sub-columns is
       legitimate and should be forward-filled (producing 'Q1 Actuals_1' etc.),
       but a 50-char report title spanning 70 columns must NOT be forwarded
       (it destroys the real sub-column names underneath).  Fix: only forward-
       fill when the parent column name is ≤40 chars.
    """
    if df.empty or len(df.columns) == 0:
        return df

    cols = list(df.columns)
    unnamed_count = sum(1 for c in cols if str(c).startswith('Unnamed:'))

    # Only attempt header repair when pandas assigned many Unnamed columns —
    # a clean sheet with real headers has at most a handful of Unnamed ones.
    if unnamed_count / max(len(cols), 1) <= 0.25:
        return df

    # ── Phase 1: scan the first data rows for the real header ────────────────
    # Skip confirmed title/blank rows, stop as soon as we find a header candidate
    # or a data row (fail closed — leave as-is rather than corrupt the frame).
    MAX_SCAN = 5  # never look more than 5 rows deep (avoids eating real data)
    rows_to_skip = 0

    for scan_idx in range(min(MAX_SCAN, len(df))):
        row_list = list(df.iloc[scan_idx])

        if _is_title_row(row_list, len(cols)):
            # Confirmed title/blank — skip it and keep scanning
            rows_to_skip = scan_idx + 1
            continue

        if _is_header_candidate(row_list):
            # This row looks like real column headers — promote it
            if scan_idx > 0 or rows_to_skip > 0:
                df = df.iloc[rows_to_skip:].reset_index(drop=True)
                # Re-index scan_idx relative to the trimmed frame
                promote_at = scan_idx - rows_to_skip
                return _promote_row_as_headers(df, promote_at)
            else:
                # scan_idx == 0: first data row IS the real header (standard two-row case)
                return _promote_row_as_headers(df, 0)

        # Row looks like data (numeric, long strings, non-header) — stop scanning.
        # We've gone as far as we safely can without eating real data rows.
        break

    # ── Phase 2: fall through — the current df.columns are the best we have.
    # Forward-fill Unnamed continuation columns produced by merged section-header
    # cells, but ONLY when the named parent is short enough to be a real section
    # label (≤40 chars).  Long strings are report titles; forward-filling them
    # would destroy the real sub-column names that follow them.
    result_cols = list(df.columns)
    last_named = ''
    named_count: dict = {}
    for i, c in enumerate(result_cols):
        if str(c).startswith('Unnamed:'):
            if last_named and len(last_named) <= 40:
                named_count[last_named] = named_count.get(last_named, 0) + 1
                result_cols[i] = f'{last_named}_{named_count[last_named]}'
            # else: parent is a long title — leave as Unnamed:N (fail closed)
        else:
            last_named = str(c)
    df.columns = result_cols
    return df

# ═══════════════════════════════════════════════════════════════
# LOGGING SETUP - Monitor all API calls on your laptop
# ═══════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from services import (
    procure_agent,
    generate_rfq,
    generate_report,
    generate_insights_report,
    detect_rfq_candidates,
    extract_rfq_template,
    refine_rfq_draft,
    create_chat_completion,
)
from excel_analyzer import analyze_excel_data, query_spreadsheet_data
from pdf_report import build_insights_pdf, build_rfq_pdf
from data_profiler import profile_workbook
from sheet_orchestrator import detect_relationships, classify_sheet_roles, build_unified_schema
from schema_mapper import build_schema_context
from data_validator import validate_workbook
from statistical_analyzer import analyze_workbook
from audit_logger import log_event, get_events, get_document_lineage, load_from_file

app = FastAPI(title="Procure.ai Backend")

# Startup initialisation is done in the lifespan handler below so that
# _load_snapshots (defined after DOCUMENT_STORE further down the file) is
# already in scope when it runs.

_default_origins = ["http://localhost:4173", "http://localhost:3000"]
_extra_origins = [o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins + _extra_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════
# API MONITORING MIDDLEWARE
# ═══════════════════════════════════════════════════════════════

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Monitor all API calls with timing and response status"""
    start_time = time()

    # Log incoming request
    logger.info(f"📨 REQUEST → {request.method} {request.url.path}")

    try:
        response = await call_next(request)
        process_time = time() - start_time

        # Log response with timing
        logger.info(f"✅ RESPONSE ← {response.status_code} ({process_time:.2f}s)")

        return response
    except Exception as e:
        process_time = time() - start_time
        logger.error(f"❌ ERROR → {str(e)} ({process_time:.2f}s)")
        raise

class DocumentUpload(BaseModel):
    file_name: str
    doc_type: str  # "contract" | "spreadsheet"
    company_name: str
    user_id: str

class ConversationMessage(BaseModel):
    session_id: str
    user_query: str
    context: Optional[dict] = None
    model_key: Optional[str] = 'model_a'    # 'model_a' | 'model_b' — pipeline selector
    provider_key: Optional[str] = 'auto'    # 'auto' | 'phi3' | 'groq' | 'cerebras' | 'openrouter'

class ExportRequest(BaseModel):
    content: dict
    format: str = "standard"  # "standard" | "executive"
    file_format: str = "docx"  # "docx" | "pdf"

class InsightsRequest(BaseModel):
    session_id: Optional[str] = None
    context: Optional[dict] = None

class RFQAutoFillRequest(BaseModel):
    session_id: Optional[str] = None
    context: Optional[dict] = None
    vendor: str

class ReportRequest(BaseModel):
    session_id: Optional[str] = None
    context: Optional[dict] = None
    focus: Optional[str] = None

class RFQRefineRequest(BaseModel):
    draft: dict
    instruction: str

class RFQExportRequest(BaseModel):
    draft: dict

# In-memory stores
DOCUMENT_STORE = {}
SESSION_STORE = {}
TASK_STORE = {}

DATA_PREVIEW_CHAR_LIMIT = 24000

# ── Snapshot persistence ──────────────────────────────────────────────────────
# Processed document data (profile, schema, stats, etc.) is saved as a JSON
# snapshot alongside each upload so it survives backend restarts. The raw bytes
# are NOT stored in the snapshot — the query engine re-reads from file_path.
_SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), 'snapshots')
os.makedirs(_SNAPSHOT_DIR, exist_ok=True)

_SNAPSHOT_SKIP = {'bytes', 'parsed_csv_full'}  # too large to serialise


def _save_snapshot(doc_id: str) -> None:
    """Persist a doc's processed metadata to disk (excludes raw bytes)."""
    entry = DOCUMENT_STORE.get(doc_id)
    if not entry or entry.get('status') != 'ready':
        return
    snapshot = {k: v for k, v in entry.items() if k not in _SNAPSHOT_SKIP}
    try:
        path = os.path.join(_SNAPSHOT_DIR, f'{doc_id}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, default=str)
    except Exception as e:
        print(f'Snapshot save failed for {doc_id}: {e}')


def _load_snapshots() -> None:
    """Reload all saved snapshots into DOCUMENT_STORE at startup."""
    if not os.path.isdir(_SNAPSHOT_DIR):
        return
    for fname in os.listdir(_SNAPSHOT_DIR):
        if not fname.endswith('.json'):
            continue
        path = os.path.join(_SNAPSHOT_DIR, fname)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                entry = json.load(f)
            doc_id = entry.get('doc_id')
            if not doc_id:
                continue
            # Restore bytes from the saved file_path if the file still exists
            fp = entry.get('file_path')
            if fp and os.path.exists(fp):
                with open(fp, 'rb') as fb:
                    entry['bytes'] = fb.read()
            DOCUMENT_STORE[doc_id] = entry
        except Exception as e:
            print(f'Snapshot load failed for {fname}: {e}')


def _extract_sheet_section(parsed_csv: str, sheet_name: str) -> str:
    """Pull one sheet's block out of the multi-sheet CSV preview string.

    Preview blocks look like:
        === Sheet: SheetName (N rows x M cols) ===
        Columns: ...
        <csv rows>

        === Sheet: NextSheet ...
    """
    escaped = _re.escape(sheet_name)
    pattern = rf'(=== Sheet: {escaped} .*?)(?=\n=== Sheet: |\Z)'
    m = _re.search(pattern, parsed_csv, _re.DOTALL)
    return m.group(1).strip() if m else ''


def _enrich_doc(doc: dict) -> dict:
    if not doc or not doc.get('doc_id'):
        return doc
    stored = DOCUMENT_STORE.get(doc['doc_id'])
    if not stored or not stored.get('parsed_csv'):
        return doc

    active_sheet = doc.get('active_sheet')

    preview = stored['parsed_csv']
    profile = stored.get('profile')
    validation = stored.get('validation')
    statistics = stored.get('statistics')
    unified_schema = stored.get('unified_schema')
    schema_context = stored.get('schema_context')
    columns = stored.get('columns')

    if active_sheet and isinstance(profile, dict) and active_sheet in profile:
        # Narrow each per-sheet dict to just the active sheet so the AI sees
        # only the data it's currently looking at.
        sheet_section = _extract_sheet_section(preview, active_sheet)
        if sheet_section:
            preview = sheet_section

        profile = {active_sheet: profile[active_sheet]}

        if isinstance(validation, dict):
            validation = {active_sheet: validation[active_sheet]} if active_sheet in validation else {}
        if isinstance(statistics, dict):
            statistics = {active_sheet: statistics[active_sheet]} if active_sheet in statistics else {}

        # Cross-sheet relationship hints are meaningless once scoped to a single sheet
        unified_schema = None
        schema_context = None

        # Resolve columns from the active sheet's profile — fixes the hardcoded
        # first-sheet-only bug in queue_document_processing as a side-effect.
        sheet_col_list = profile.get(active_sheet, {}).get('columns', [])
        if sheet_col_list:
            columns = [c['name'] for c in sheet_col_list if isinstance(c, dict) and c.get('name')]

    truncated = len(preview) > DATA_PREVIEW_CHAR_LIMIT
    return {
        **doc,
        'row_count': stored.get('row_count'),
        'columns': columns,
        'sheet_names': stored.get('sheet_names'),  # always full list (tab bar needs it)
        'data_preview': preview[:DATA_PREVIEW_CHAR_LIMIT],
        'data_preview_truncated': truncated,
        'profile': profile,
        'unified_schema': unified_schema,
        'schema_context': schema_context,
        'validation': validation,
        'statistics': statistics,
        # Full (unscoped) versions — always the whole-workbook data, never narrowed
        # by active_sheet.  Used by Phase 4 map-reduce and multi-hop routing so that
        # whole-workbook requests bypass active-sheet scoping without re-reading the
        # file or re-running the profiler.
        'full_profile': stored.get('profile'),
        'full_statistics': stored.get('statistics'),
        'full_unified_schema': stored.get('unified_schema'),
        # Server-local path, never echoed back in any API response — used internally so
        # the query engine can re-read the FULL workbook on demand instead of operating
        # on the (possibly truncated) text preview.
        'file_path': stored.get('file_path'),
    }


def enrich_document_context(context: Optional[dict]) -> Optional[dict]:
    if not context:
        return context
    return {
        **context,
        'active_document': _enrich_doc(context.get('active_document')),
        'documents': [_enrich_doc(doc) for doc in context.get('documents') or []],
    }

@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...), company: str = None, user_id: str = None):
    doc_id = str(uuid.uuid4())
    content = await file.read()
    storage_path = save_to_storage(doc_id, content, file.filename)
    task_id = queue_document_processing(
        doc_id=doc_id,
        file_path=storage_path,
        file_type=file.content_type,
        company=company,
        user_id=user_id,
    )
    return JSONResponse({
        "doc_id": doc_id,
        "filename": file.filename,
        "status": "processing",
        "task_id": task_id,
        "estimated_time": "30 seconds",
    })

@app.post("/api/chat")
async def chat(request: ConversationMessage):
    enriched_context = enrich_document_context(request.context)
    t0 = time()
    response = procure_agent(
        user_query=request.user_query,
        document_context=enriched_context,
        session_state=load_session(request.session_id),
        model_key=request.model_key or 'model_a',
        provider_key=request.provider_key or 'auto',
    )
    elapsed_ms = round((time() - t0) * 1000)
    save_conversation(request.session_id, request.user_query, response)

    # Audit the query
    active_doc = (enriched_context or {}).get('active_document') or {}
    log_event(
        'chat_query',
        user_id=(request.context or {}).get('user_id'),
        session_id=request.session_id,
        doc_id=active_doc.get('doc_id'),
        doc_name=active_doc.get('name'),
        query=request.user_query,
        answer_source=response.get('model', 'llm'),
        processing_time_ms=elapsed_ms,
    )

    return JSONResponse({
        "session_id": request.session_id,
        "response": response["content"],
        "tool_calls": response.get("tool_calls", []),
        "timestamp": response.get("timestamp"),
        "model": response.get("model"),
    })

@app.get("/api/documents")
async def list_documents(user_id: str):
    docs = get_user_documents(user_id)
    return JSONResponse({
        "documents": docs,
        "count": len(docs),
    })

@app.get("/api/document/{doc_id}")
async def get_document(doc_id: str):
    doc = retrieve_document(doc_id)
    # bytes/parsed_csv_full are not JSON-serialisable — strip them before responding
    safe = {k: v for k, v in doc.items() if not isinstance(v, (bytes, bytearray))}
    return JSONResponse(safe)


@app.get("/api/document/{doc_id}/sheets")
async def get_document_sheets(doc_id: str):
    stored = DOCUMENT_STORE.get(doc_id)
    if not stored:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({
        "doc_id": doc_id,
        "sheet_names": stored.get("sheet_names", []),
        "row_count": stored.get("row_count"),
        "status": stored.get("status"),
    })


@app.get("/api/document/{doc_id}/sheet/{sheet_name}")
async def get_sheet_data(doc_id: str, sheet_name: str, offset: int = 0, limit: int = 100):
    stored = DOCUMENT_STORE.get(doc_id)
    if not stored:
        return JSONResponse({"error": "Document not found"}, status_code=404)
    file_path = stored.get('file_path')
    if not file_path or not os.path.exists(file_path):
        return JSONResponse({"error": "File not available on server"}, status_code=404)
    try:
        all_sheets_raw = pd.read_excel(file_path, sheet_name=None)
        df_raw = all_sheets_raw.get(sheet_name)
        if df_raw is None:
            return JSONResponse({"error": f"Sheet '{sheet_name}' not found"}, status_code=404)
        df = _clean_sheet_headers(df_raw)
        columns = [str(c) for c in df.columns]
        total_rows = len(df)
        page_df = df.iloc[offset:offset + limit]

        def _safe_cell(v):
            if v is None:
                return ''
            try:
                if pd.isna(v):
                    return ''
            except (TypeError, ValueError):
                pass
            if isinstance(v, float) and v != v:
                return ''
            return v if isinstance(v, (int, float, bool)) else str(v)

        rows = [{col: _safe_cell(row[col]) for col in columns} for _, row in page_df.iterrows()]
        return JSONResponse({
            "doc_id": doc_id,
            "sheet_name": sheet_name,
            "sheet_names": stored.get('sheet_names', [sheet_name]),
            "columns": columns,
            "rows": rows,
            "total_rows": total_rows,
            "offset": offset,
            "limit": limit,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/document/{doc_id}")
async def delete_document(doc_id: str):
    # Remove from document store
    doc = DOCUMENT_STORE.pop(doc_id, None)
    if not doc:
        return JSONResponse({"status": "not_found", "doc_id": doc_id}, status_code=404)

    # Mark or remove any queued tasks related to this document
    for task_id, task in list(TASK_STORE.items()):
        if task.get('doc_id') == doc_id:
            TASK_STORE[task_id]['status'] = 'deleted'

    return JSONResponse({"status": "deleted", "doc_id": doc_id})

@app.post("/api/analyze")
async def analyze_document(request: dict):
    doc_id = request.get("doc_id")
    doc = DOCUMENT_STORE.get(doc_id)
    if not doc:
        return JSONResponse({"error": "Document not found"}, status_code=404)
    
    try:
        # Use Gemini to analyze the document
        file_path = doc.get('file_path')
        analysis = analyze_excel_data(file_path, None)
        return JSONResponse({
            "doc_id": doc_id,
            "analysis": analysis.get('analysis', analysis),
            "success": analysis.get('success', True),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/query")
async def query_spreadsheet(request: dict):
    doc_id = request.get("doc_id")
    nl_query = request.get("query")
    
    doc = DOCUMENT_STORE.get(doc_id)
    if not doc:
        return JSONResponse({"error": "Document not found"}, status_code=404)
    
    try:
        # Use Gemini to answer natural language query about the spreadsheet
        file_path = doc.get('file_path')
        result = query_spreadsheet_data(file_path, nl_query)
        return JSONResponse({
            "query": nl_query,
            "analysis": result.get('analysis', result),
            "success": result.get('success', True),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/export")
async def export_report(request: ExportRequest):
    result = execute_tool("export_to_docx", {
        "content": request.content,
        "format": request.format,
    })
    file_bytes = result.get("file_bytes", b"")
    return StreamingResponse(
        iter([file_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="report.docx"'},
    )

@app.post("/api/rfq")
async def create_rfq(request: dict):
    result = generate_rfq(request)
    return JSONResponse(result)

@app.post("/api/rfq/refine")
async def refine_rfq(request: RFQRefineRequest):
    result = refine_rfq_draft(request.draft, request.instruction)
    return JSONResponse(result)

@app.post("/api/rfq/export-pdf")
async def export_rfq_pdf(request: RFQExportRequest):
    pdf_bytes = build_rfq_pdf(request.draft)
    doc_number = request.draft.get('document_number') or 'rfq-draft'
    safe_name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in str(doc_number))
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.pdf"'},
    )

@app.post("/api/analyze-for-rfq")
async def analyze_for_rfq(request: InsightsRequest):
    result = detect_rfq_candidates(enrich_document_context(request.context))
    return JSONResponse(result)

@app.post("/api/auto-fill-rfq")
async def auto_fill_rfq(request: RFQAutoFillRequest):
    result = extract_rfq_template(enrich_document_context(request.context), request.vendor)
    return JSONResponse(result)

@app.post("/api/report")
async def create_report(request: ReportRequest):
    enriched_context = enrich_document_context(request.context)
    t0 = time()
    result = generate_report(enriched_context, focus=request.focus)
    elapsed_ms = round((time() - t0) * 1000)

    active_doc = (enriched_context or {}).get('active_document') or {}
    log_event(
        'report_generated',
        user_id=(request.context or {}).get('user_id'),
        session_id=getattr(request, 'session_id', None),
        doc_id=active_doc.get('doc_id'),
        doc_name=active_doc.get('name'),
        query=request.focus,
        answer_source='report',
        processing_time_ms=elapsed_ms,
    )
    return JSONResponse(result)


@app.get("/api/audit")
async def get_audit_events(
    user_id: str = None,
    doc_id: str = None,
    event_type: str = None,
    limit: int = 100,
):
    events = get_events(user_id=user_id, doc_id=doc_id, event_type=event_type, limit=limit)
    return JSONResponse({"events": events, "count": len(events)})


@app.get("/api/audit/lineage/{doc_id}")
async def get_doc_lineage(doc_id: str):
    lineage = get_document_lineage(doc_id)
    return JSONResponse(lineage)

@app.post("/api/insights/pdf")
async def download_insights_pdf(request: InsightsRequest):
    report_data = generate_insights_report(enrich_document_context(request.context))
    pdf_bytes = build_insights_pdf(report_data)
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="procure_ai_insights.pdf"'},
    )

@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    session = load_session(session_id)
    return JSONResponse(session)

@app.post("/api/session/{session_id}/clear")
async def clear_session(session_id: str):
    clear_conversation_history(session_id)
    return JSONResponse({"status": "cleared"})

@app.on_event("startup")
async def _startup():
    """Reload audit history and document snapshots after every restart."""
    load_from_file()
    _load_snapshots()


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "version": "1.0"})

@app.get("/api/status/{task_id}")
async def check_task_status(task_id: str):
    status = get_task_status(task_id)
    return JSONResponse(status)

# ==== Stub implementations for demo ==== #

def save_to_storage(doc_id: str, content: bytes, filename: str, company: str = None, user_id: str = None) -> str:
    import tempfile
    import os as os_module
    
    # Create a temporary directory for storing uploads
    upload_dir = os_module.path.join(os_module.path.dirname(__file__), 'uploads')
    os_module.makedirs(upload_dir, exist_ok=True)
    
    # Save file to disk
    file_path = os_module.path.join(upload_dir, f"{doc_id}_{filename}")
    with open(file_path, 'wb') as f:
        f.write(content)
    
    DOCUMENT_STORE[doc_id] = {
        "doc_id": doc_id,
        "filename": filename,
        "file_path": file_path,
        "bytes": content,
        "status": "uploaded",
        "company": company,
        "user_id": user_id,
    }
    return file_path


def queue_document_processing(doc_id: str, file_path: str, file_type: str, company: str, user_id: str) -> str:
    task_id = str(uuid.uuid4())
    TASK_STORE[task_id] = {"doc_id": doc_id, "status": "processing"}
    DOCUMENT_STORE[doc_id]["status"] = "processing"
    DOCUMENT_STORE[doc_id]["company"] = company
    DOCUMENT_STORE[doc_id]["user_id"] = user_id
    
    # Process Excel file synchronously for now (ideal for prototype)
    try:
        doc_data = DOCUMENT_STORE.get(doc_id)
        if doc_data and doc_data.get("bytes"):
            file_bytes = doc_data["bytes"]
            # sheet_name=None reads every sheet in the workbook (returns {name: DataFrame}),
            # not just the first one — a single-sheet read here was the original bug.
            all_sheets = {
                name: _clean_sheet_headers(df)
                for name, df in pd.read_excel(io.BytesIO(file_bytes), sheet_name=None).items()
            }
            sheet_names = list(all_sheets.keys())
            total_rows = sum(len(df) for df in all_sheets.values())

            # Scale rows-per-sheet down as sheet count grows, so a 27-tab workbook doesn't
            # blow the context budget while a 1-2 sheet file still gets a generous preview.
            rows_per_sheet = max(5, min(100, 800 // max(len(all_sheets), 1)))

            sheet_sections = []
            for name, df in all_sheets.items():
                header = f"=== Sheet: {name} ({len(df)} rows x {len(df.columns)} cols) ==="
                cols_line = f"Columns: {', '.join(str(c) for c in df.columns)}"
                csv_body = df.head(rows_per_sheet).to_csv(index=False)
                sheet_sections.append(f"{header}\n{cols_line}\n{csv_body}")
            csv_preview = "\n\n".join(sheet_sections)

            DOCUMENT_STORE[doc_id]["parsed_csv"] = csv_preview
            DOCUMENT_STORE[doc_id]["row_count"] = total_rows
            # Store per-sheet column lists so _enrich_doc can resolve columns for
            # whichever sheet is active, instead of always using the first sheet.
            DOCUMENT_STORE[doc_id]["columns"] = all_sheets[sheet_names[0]].columns.tolist()
            DOCUMENT_STORE[doc_id]["sheet_names"] = sheet_names
            # Real pandas-computed sum/mean/min/max per numeric column, handed to the AI
            # alongside the text preview so it cites verified numbers instead of doing
            # its own (error-prone) arithmetic on a CSV snippet.
            profile = profile_workbook(all_sheets)
            DOCUMENT_STORE[doc_id]["profile"] = profile

            # Multi-sheet relationship detection: finds FK links between sheets by
            # column name matching + value overlap, classifies each sheet's role
            # (fact/dimension/reference), and builds a unified schema. Stored at
            # upload time so every subsequent chat/report call can use it without
            # re-reading the file.
            relationships = detect_relationships(all_sheets)
            roles = classify_sheet_roles(all_sheets, relationships)
            unified_schema = build_unified_schema(all_sheets, profile, relationships, roles)
            schema_context = build_schema_context(all_sheets, profile, relationships)
            DOCUMENT_STORE[doc_id]["unified_schema"] = unified_schema
            DOCUMENT_STORE[doc_id]["schema_context"] = schema_context

            # Data quality validation and statistical analysis — both computed
            # once at upload and injected into LLM context on every request.
            validation = validate_workbook(all_sheets, profile)
            DOCUMENT_STORE[doc_id]["validation"] = validation
            DOCUMENT_STORE[doc_id]["statistics"] = analyze_workbook(all_sheets, profile)

            DOCUMENT_STORE[doc_id]["status"] = "ready"
            TASK_STORE[task_id]["status"] = "completed"
            _save_snapshot(doc_id)

            # Audit: record the upload and any data quality findings
            sheet_issue_count = sum(
                v.get('issue_count', 0) for v in validation.values()
            )
            log_event(
                'document_upload',
                user_id=user_id,
                doc_id=doc_id,
                doc_name=DOCUMENT_STORE[doc_id].get('filename'),
                result_row_count=total_rows,
                quality_score=min(
                    (v.get('quality_score', 100) for v in validation.values()),
                    default=100,
                ),
                anomaly_count=sheet_issue_count,
                extra={'sheet_count': len(sheet_names), 'sheet_names': sheet_names},
            )
    except Exception as e:
        print(f"Error processing Excel: {e}")
        DOCUMENT_STORE[doc_id]["status"] = "error"
        TASK_STORE[task_id]["status"] = "failed"
        
    return task_id


def execute_tool(tool_name: str, tool_input: dict) -> dict:
    if tool_name == "process_contract":
        doc_id = tool_input.get("doc_id")
        doc = DOCUMENT_STORE.get(doc_id)
        if doc and "parsed_csv" in doc:
            return {
                "status": "success",
                "summary": f"Excel file parsed. {doc.get('row_count', 0)} rows found.",
                "columns": doc.get("columns", []),
                "data_preview": doc["parsed_csv"]
            }
        return {"status": "error", "message": "Document not found or not an Excel file."}
    if tool_name == "execute_query":
        # For prototype, if a spreadsheet query is made, we return the parsed CSV context
        # In a real scenario, we would use an LLM to generate pandas/SQL code here.
        # Let's find the most recent spreadsheet uploaded
        docs = [doc for doc in DOCUMENT_STORE.values() if "parsed_csv" in doc]
        if docs:
            doc = docs[-1] # use latest
            return {
                "status": "success",
                "message": f"Data retrieved from {doc.get('filename')}",
                "columns": doc.get("columns", []),
                "data": doc["parsed_csv"]
            }
        return {"status": "error", "message": "No spreadsheet data available to query."}
    if tool_name == "export_to_docx":
        return {"file_bytes": b"Dummy DOCX content"}
    if tool_name == "generate_rfq":
        input_data = tool_input.get("input", {})
        return {
            "executive_summary": input_data.get("executive_summary", "RFQ draft generated."),
            "scope_of_work": input_data.get("scope_of_work", []),
            "terms_and_conditions": input_data.get("terms_and_conditions", []),
            "evaluation_criteria": input_data.get("evaluation_criteria", {}),
            "requested_info": input_data.get("requested_info", []),
            "legal_certifications": input_data.get("legal_certifications", []),
            "document_number": input_data.get("document_number"),
            "company_name": input_data.get("company_name"),
            "response_deadline": input_data.get("response_deadline"),
        }
    if tool_name == "generate_report":
        input_data = tool_input.get("input", {})
        return {
            "report_type": input_data.get("report_type", "spend"),
            "executive_summary": f"This report covers {input_data.get('scope', 'procurement scope')} for {input_data.get('timeframe', 'the selected timeframe')}",
            "key_findings": [
                "Top 3 vendors account for 42% of spend.",
                "Contracts expiring within 90 days represent $4.3M in spend.",
                "5 contracts are flagged for elevated risk due to liability and compliance items.",
            ],
        }
    return {"error": f"Unknown tool: {tool_name}"}


def load_session(session_id: str) -> dict:
    return SESSION_STORE.get(session_id, {"session_id": session_id, "conversation_history": []})


def save_conversation(session_id: str, user_query: str, response: dict):
    session = SESSION_STORE.setdefault(session_id, {"session_id": session_id, "conversation_history": []})
    session["conversation_history"].append({"role": "user", "content": user_query})
    assistant_text = ''
    if isinstance(response, dict) and response.get('content'):
        assistant_text = '\n\n'.join(
            block.get('text', '') if isinstance(block, dict) else str(block)
            for block in response.get('content', [])
        )
    session["conversation_history"].append({"role": "assistant", "content": assistant_text})


def get_user_documents(user_id: str) -> list:
    return [doc for doc in DOCUMENT_STORE.values() if doc.get("user_id") == user_id]


def retrieve_document(doc_id: str) -> dict:
    return DOCUMENT_STORE.get(doc_id, {"error": "not found"})


def nl_to_sql(nl_query: str) -> str:
    return "SELECT vendor_name, contract_value, expiry_date FROM vendor_contracts WHERE expiry_date BETWEEN CURRENT_DATE AND DATEADD(month, 3, CURRENT_DATE)"


def get_task_status(task_id: str) -> dict:
    return TASK_STORE.get(task_id, {"status": "unknown"})


def clear_conversation_history(session_id: str):
    if session_id in SESSION_STORE:
        SESSION_STORE[session_id]["conversation_history"] = []

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
