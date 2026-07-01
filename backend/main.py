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


def _clean_sheet_headers(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise Excel headers that pandas reads poorly.

    Two common problems handled:
    1. Merged top-row headers create 'Unnamed: N' continuation columns.
       These are forward-filled with the parent name so 'Actual Q1' and three
       'Unnamed' siblings become 'Actual Q1', 'Actual Q1_1', 'Actual Q1_2'.
    2. Sheets with two header rows (a category row + a sub-column row) leave
       the sub-header as the first data row.  Detected when >60% of the first
       row values are short strings with <10% numeric values; those cells are
       promoted to column names combined with the parent header above them.
    """
    if df.empty or len(df.columns) == 0:
        return df

    cols = list(df.columns)
    unnamed_count = sum(1 for c in cols if str(c).startswith('Unnamed:'))

    # ── Case 1: two-row header (merged category + sub-columns) ──────────────
    if unnamed_count / max(len(cols), 1) > 0.25 and len(df) >= 1:
        first_row = df.iloc[0]
        non_null = [v for v in first_row if pd.notna(v) and str(v).strip() not in ('', 'nan')]
        if len(non_null) >= 2:
            str_vals = [v for v in non_null if isinstance(v, str)]
            num_vals = [v for v in non_null
                        if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if (len(str_vals) / len(non_null) > 0.6
                    and len(num_vals) / len(non_null) < 0.1):
                # Promote first data row into column names
                new_cols = []
                seen: dict = {}
                for orig_col, sub_val in zip(df.columns, first_row):
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
                    # Deduplicate
                    if name in seen:
                        seen[name] += 1
                        name = f'{name}_{seen[name]}'
                    else:
                        seen[name] = 0
                    new_cols.append(name)
                df = df.iloc[1:].reset_index(drop=True)
                df.columns = new_cols
                return df

    # ── Case 2: single header row with Unnamed continuation columns ──────────
    result_cols = list(df.columns)
    last_named = ''
    named_count: dict = {}
    for i, c in enumerate(result_cols):
        if str(c).startswith('Unnamed:'):
            if last_named:
                named_count[last_named] = named_count.get(last_named, 0) + 1
                result_cols[i] = f'{last_named}_{named_count[last_named]}'
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


def _enrich_doc(doc: dict) -> dict:
    if not doc or not doc.get('doc_id'):
        return doc
    stored = DOCUMENT_STORE.get(doc['doc_id'])
    if not stored or not stored.get('parsed_csv'):
        return doc
    preview = stored['parsed_csv']
    truncated = len(preview) > DATA_PREVIEW_CHAR_LIMIT
    return {
        **doc,
        'row_count': stored.get('row_count'),
        'columns': stored.get('columns'),
        'sheet_names': stored.get('sheet_names'),
        'data_preview': preview[:DATA_PREVIEW_CHAR_LIMIT],
        'data_preview_truncated': truncated,
        'profile': stored.get('profile'),
        'unified_schema': stored.get('unified_schema'),
        'schema_context': stored.get('schema_context'),
        'validation': stored.get('validation'),
        'statistics': stored.get('statistics'),
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
    return JSONResponse(doc)


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
