import React, { useState, useEffect, useRef } from 'react';
import { fetchSheetData, getDocumentMeta } from '../services/api';

const PAGE_SIZE = 100;

const SheetPreview = ({ doc, activeSheet, onSheetChange }) => {
  const [sheetNames, setSheetNames] = useState([]);
  const [sheetData, setSheetData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [offset, setOffset] = useState(0);
  const tableRef = useRef(null);

  // Step 1: When doc changes, resolve sheet names (from doc prop or via API call)
  useEffect(() => {
    if (!doc?.doc_id || doc.status !== 'analyzed') {
      setSheetNames([]);
      setSheetData(null);
      setError(null);
      return;
    }

    if (doc.sheet_names?.length) {
      setSheetNames(doc.sheet_names);
      if (!activeSheet || !doc.sheet_names.includes(activeSheet)) {
        onSheetChange(doc.sheet_names[0]);
      }
      return;
    }

    // sheet_names not in the local doc object (common: they come from backend enrichment,
    // not from the upload response). Fetch metadata to discover them.
    getDocumentMeta(doc.doc_id)
      .then((meta) => {
        const names = meta.sheet_names || [];
        setSheetNames(names);
        if (names.length) onSheetChange(names[0]);
      })
      .catch(() => setError('Could not load sheet list.'));
  }, [doc?.doc_id, doc?.status]);

  // Step 2: When activeSheet is set, fetch the row data
  useEffect(() => {
    if (!doc?.doc_id || !activeSheet) {
      setSheetData(null);
      return;
    }
    setLoading(true);
    setError(null);
    setOffset(0);
    fetchSheetData({ docId: doc.doc_id, sheetName: activeSheet, offset: 0, limit: PAGE_SIZE })
      .then((data) => {
        setSheetData(data);
        // Sync sheet_names from first data response
        if (data.sheet_names?.length) setSheetNames(data.sheet_names);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [doc?.doc_id, activeSheet]);

  const loadPage = (newOffset) => {
    if (!doc?.doc_id || !activeSheet) return;
    setLoading(true);
    setError(null);
    fetchSheetData({ docId: doc.doc_id, sheetName: activeSheet, offset: newOffset, limit: PAGE_SIZE })
      .then((data) => {
        setSheetData(data);
        setOffset(newOffset);
        tableRef.current?.scrollTo({ top: 0 });
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  };

  const handleSheetTab = (name) => {
    if (name === activeSheet) return;
    setSheetData(null);
    setOffset(0);
    onSheetChange(name);
  };

  // ── No doc ────────────────────────────────────────────────────────────────
  if (!doc) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-slate-400 text-sm p-6 gap-2">
        <svg width="32" height="32" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M3 6h18M3 14h18M3 18h18" />
        </svg>
        <p>Upload a spreadsheet to preview it here</p>
      </div>
    );
  }

  if (doc.status !== 'analyzed') {
    return (
      <div className="h-full flex flex-col items-center justify-center text-slate-400 text-sm p-6 gap-2">
        <div className="w-5 h-5 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
        <p>Processing…</p>
      </div>
    );
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="h-full flex flex-col bg-white">
      {/* Sheet tab bar */}
      <div className="border-b border-slate-200 px-3 py-2 overflow-x-auto shrink-0 bg-slate-50">
        {sheetNames.length === 0 ? (
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
            <span className="text-xs text-slate-400">Loading sheets…</span>
          </div>
        ) : sheetNames.length === 1 ? (
          <span className="inline-block px-3 py-1 text-xs font-medium rounded-md bg-blue-100 text-blue-800 border border-blue-200 whitespace-nowrap">
            {sheetNames[0]}
          </span>
        ) : (
          <div className="flex gap-1">
            {sheetNames.map((name) => (
              <button
                key={name}
                type="button"
                onClick={() => handleSheetTab(name)}
                className={`px-3 py-1 text-xs font-medium rounded-md whitespace-nowrap border transition-all ${
                  activeSheet === name
                    ? 'bg-blue-600 text-white border-blue-600 shadow-sm'
                    : 'bg-white text-slate-600 border-slate-200 hover:border-blue-300 hover:text-blue-600'
                }`}
              >
                {name}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Grid */}
      <div className="flex-1 overflow-auto relative" ref={tableRef}>
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-white/80 z-10">
            <div className="w-5 h-5 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
          </div>
        )}
        {error && (
          <div className="p-4 text-xs text-red-600 bg-red-50">{error}</div>
        )}
        {!loading && !error && sheetData && sheetData.rows.length === 0 && (
          <div className="p-6 text-center text-sm text-slate-400">This sheet is empty.</div>
        )}
        {sheetData && sheetData.rows.length > 0 && (
          <table className="w-full text-xs border-collapse">
            <thead className="sticky top-0 z-10 bg-slate-100">
              <tr>
                {sheetData.columns.map((col) => (
                  <th key={col} className="border border-slate-200 px-2 py-1.5 text-left font-semibold text-slate-700 whitespace-nowrap">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sheetData.rows.map((row, i) => (
                <tr key={i} className="even:bg-slate-50 hover:bg-blue-50 transition-colors">
                  {sheetData.columns.map((col) => (
                    <td
                      key={col}
                      className="border border-slate-200 px-2 py-1 text-slate-700 max-w-[180px] overflow-hidden whitespace-nowrap"
                      title={String(row[col] ?? '')}
                    >
                      {String(row[col] ?? '')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination footer */}
      {sheetData && sheetData.total_rows > PAGE_SIZE && (
        <div className="border-t border-slate-200 px-4 py-2 flex items-center justify-between text-xs text-slate-500 shrink-0 bg-white">
          <span>{offset + 1}–{Math.min(offset + PAGE_SIZE, sheetData.total_rows)} of {sheetData.total_rows}</span>
          <div className="flex gap-1.5">
            <button
              disabled={offset === 0 || loading}
              onClick={() => loadPage(Math.max(0, offset - PAGE_SIZE))}
              className="px-2 py-1 rounded border border-slate-200 disabled:opacity-40 hover:border-blue-400 transition"
            >← Prev</button>
            <button
              disabled={offset + PAGE_SIZE >= sheetData.total_rows || loading}
              onClick={() => loadPage(offset + PAGE_SIZE)}
              className="px-2 py-1 rounded border border-slate-200 disabled:opacity-40 hover:border-blue-400 transition"
            >Next →</button>
          </div>
        </div>
      )}
    </div>
  );
};

export default SheetPreview;
