"""Audit trail and data lineage logger.

Logs every analysis action (upload, chat query, report, data query) for
compliance and debugging. Events are kept in memory (last 2000) and also
appended to a JSONL file alongside the backend so they survive restarts.

Users can ask "what analysis was run on this file?" and the audit trail
provides an exact record: who asked what, when, and what the system used
to answer.
"""
import json
import os
from collections import deque
from datetime import datetime, timezone
from typing import Optional


_AUDIT_FILE = os.path.join(os.path.dirname(__file__), 'audit_log.jsonl')
_MAX_MEMORY_EVENTS = 2000
_AUDIT_LOG: deque = deque(maxlen=_MAX_MEMORY_EVENTS)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_to_file(event: dict) -> None:
    try:
        with open(_AUDIT_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(event) + '\n')
    except Exception:
        pass  # Audit logging must never crash the main request path


def log_event(
    event_type: str,
    *,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    doc_id: Optional[str] = None,
    doc_name: Optional[str] = None,
    query: Optional[str] = None,
    answer_source: Optional[str] = None,   # 'deterministic' | 'llm' | 'grounded-llm'
    columns_referenced: Optional[list] = None,
    result_row_count: Optional[int] = None,
    quality_score: Optional[float] = None,
    anomaly_count: Optional[int] = None,
    processing_time_ms: Optional[float] = None,
    extra: Optional[dict] = None,
) -> dict:
    """Record one analysis event.

    event_type values:
      document_upload   — file successfully processed
      chat_query        — user message answered (chat endpoint)
      data_query        — deterministic pandas query executed
      report_generated  — /api/report completed
      insights_viewed   — /api/insights/pdf generated
      rfq_created       — RFQ draft generated
    """
    event = {
        'timestamp': _now_iso(),
        'event_type': event_type,
        'user_id': user_id,
        'session_id': session_id,
        'doc_id': doc_id,
        'doc_name': doc_name,
        'query': query,
        'answer_source': answer_source,
        'columns_referenced': columns_referenced or [],
        'result_row_count': result_row_count,
        'quality_score': quality_score,
        'anomaly_count': anomaly_count,
        'processing_time_ms': processing_time_ms,
    }
    if extra:
        event.update(extra)

    _AUDIT_LOG.append(event)
    _write_to_file(event)
    return event


def get_events(
    user_id: Optional[str] = None,
    doc_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100,
) -> list:
    """Return recent audit events, optionally filtered."""
    events = list(_AUDIT_LOG)
    if user_id:
        events = [e for e in events if e.get('user_id') == user_id]
    if doc_id:
        events = [e for e in events if e.get('doc_id') == doc_id]
    if event_type:
        events = [e for e in events if e.get('event_type') == event_type]
    return events[-limit:]


def get_document_lineage(doc_id: str) -> dict:
    """Return a structured lineage summary for a specific document."""
    events = get_events(doc_id=doc_id, limit=_MAX_MEMORY_EVENTS)
    upload_events = [e for e in events if e['event_type'] == 'document_upload']
    query_events = [e for e in events if e['event_type'] in ('chat_query', 'data_query')]
    report_events = [e for e in events if e['event_type'] == 'report_generated']

    unique_users = list({e['user_id'] for e in events if e.get('user_id')})
    all_columns = list({c for e in events for c in (e.get('columns_referenced') or [])})

    return {
        'doc_id': doc_id,
        'doc_name': upload_events[0].get('doc_name') if upload_events else None,
        'first_uploaded': upload_events[0]['timestamp'] if upload_events else None,
        'total_queries': len(query_events),
        'total_reports': len(report_events),
        'accessed_by': unique_users,
        'columns_queried': all_columns,
        'recent_queries': [
            {
                'timestamp': e['timestamp'],
                'user_id': e.get('user_id'),
                'query': e.get('query'),
                'source': e.get('answer_source'),
            }
            for e in query_events[-10:]
        ],
    }


def load_from_file(limit: int = _MAX_MEMORY_EVENTS) -> None:
    """Reload persisted events from the JSONL file into memory (call at startup)."""
    if not os.path.exists(_AUDIT_FILE):
        return
    try:
        with open(_AUDIT_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        for line in lines[-limit:]:
            try:
                _AUDIT_LOG.append(json.loads(line.strip()))
            except Exception:
                continue
    except Exception:
        pass
