# MIS SHEET ROUTER + PIPELINE FIX — IMPLEMENTATION PROMPT

You are working in the Procure AI / Excel File Summarizer repo (FastAPI backend in `backend/`, Vite+React frontend in `src/`). The system currently FAILS to analyze the real company MIS workbook (`backend/uploads/47a8264f-961a-4499-9b62-40f51f280dbc_MIS Automation PGIL.xlsx`, 26 sheets). Your job is to implement ALL phases below, then run the acceptance tests in Phase 7 and fix anything that fails. Do not stop until every acceptance test passes.

## HARD CONSTRAINTS

1. **No paid APIs.** Only the existing free providers: Groq (100k tokens/day), Cerebras, OpenRouter free models, local Ollama Phi-3. Do NOT add any provider that requires payment.
2. **Remove Gemini entirely.** The user's Gemini quota is exhausted. Delete/disable `gemini_client.py` usage, remove GEMINI entries from provider chains, presets, and `.env.example`. Leave the file itself if other code imports it defensively, but nothing may call it.
3. **The whole workbook must still be uploaded and parsed.** Never require the user to upload a single sheet. Scoping happens ONLY at LLM-call time.
4. **Per-LLM-call payload must be small.** After this change, no single LLM call may include more than ONE sheet's data. Sheet data previews sent to any LLM must be ≤ 8,000 chars (≤ 4,000 for phi3). Router calls send NO row data at all — only sheet names, roles, and column headers.
5. **Deterministic math stays deterministic.** Numeric answers must keep flowing through `query_engine.py` (pandas), never LLM arithmetic.
6. **Do not break existing endpoints** (`/api/upload`, `/api/chat`, `/api/analyze`, `/api/query`, RFQ endpoints, `/health`). Existing tests and flows for the small test files (`rfq_test.xlsx`, `query_engine_test.xlsx`, etc.) must keep working.

## CURRENT STATE (verified facts — trust these)

- `backend/main.py`
  - `_PROVIDER_PREVIEW_LIMITS` dict near line 366; `DATA_PREVIEW_CHAR_LIMIT` default 72,000.
  - `_clean_sheet_headers` (~lines 150–260): promotes a SINGLE header row, scans max 6 rows (`MAX_SCAN = 6`). Cannot handle 2–3 stacked header rows → produces `Col_0`, `Unnamed:`, or junk column names on MIS sheets.
  - `_extract_sheet_section(parsed_csv, sheet_name)` at ~line 425: regex-extracts one sheet's block out of the single flattened `parsed_csv` string.
  - Active-sheet scoping already exists at ~lines 447–494: when `doc['active_sheet']` is set, preview/profile/validation/statistics are narrowed to that sheet. BUILD ON THIS — do not duplicate it.
  - `/api/chat` at ~line 537. Snapshot persistence stores one big `parsed_csv` string (~98,632 chars for the MIS file); `_SNAPSHOT_SKIP = {'bytes', 'parsed_csv_full'}`.
- `backend/ai_orchestrator.py`
  - Auto chain is `_CHAIN = [_cerebras, _groq, _phi3]` (or phi3-first when `PREFER_LOCAL_OLLAMA=true`). There is a DEMO provider that silently returns canned text at final fallback (`provider=DEMO level=4 status=fallback` in logs). This currently masks failures as fake answers.
- `backend/query_engine.py` — `load_all_sheets()` re-reads the full workbook from disk with `pd.read_excel(sheet_name=None)` and applies `_clean_sheet_headers`.
- `backend/sheet_orchestrator.py` — `detect_relationships`, `classify_sheet_roles`, `build_unified_schema`.
- `backend/schema_mapper.py` — `lookup_business_category`, `get_canonical_label`, `build_schema_context`, backed by `business_glossary.json`.
- `backend/query_classifier.py` — `classify_query(user_query, active_sheet)`.
- `backend/excel_analyzer.py` — LEGACY: `pd.read_excel(file_path)` reads FIRST SHEET ONLY. Any endpoint still routed through it silently ignores 25 of 26 MIS sheets.
- Real-world failure mode in `backend/logs/procure_ai.log`: Groq 429 daily-token exhaustion, OpenRouter free-model 429s, Cerebras connection errors, Ollama offline → DEMO fallback. Root cause of quota burn: ~25k tokens per chat because the entire flattened workbook is sent every time.
- MIS workbook structure examples (use for testing header logic):
  - Sheet `'1'`: row 1 = `Q1` (title), row 2 = `Actual` / `Budget` (group row), row 3 = `Country, Sales, PBT, Dep, FC, EBITDA, ...` (real header). Needs compound headers like `Actual_Sales`, `Budget_PBT`.
  - Sheet `'15.1'`: row 4 is the real header (`Customer, FY 24-25, % FY 24-25, ...`) under 3 junk rows.
  - Sheet `'8'` / `'13,14'`: group row `Actual - Q1'23-24` / `Forecast - Q1'24-25` above real header row.
  - Sheets `'21'`, `'22'`, `'20'`, much of `'1'`, `'2'`, `'6'`: header-only templates with few/no data values — the system must SAY so, not hallucinate.

---

## PHASE 1 — Per-sheet snapshot storage

In `backend/main.py` document processing:

1. When parsing an uploaded workbook, build `parsed_sheets: dict[str, str]` — one CSV string per sheet (post header-cleaning), each independently generated (do NOT slice the old blob).
2. Store `parsed_sheets` in `DOCUMENT_STORE[doc_id]` and persist it in the snapshot JSON. Keep the legacy combined `parsed_csv` for backward compatibility (it may stay, but nothing new should depend on it).
3. Rewrite `_extract_sheet_section` to first try `doc['parsed_sheets'][sheet_name]` and fall back to the old regex only for legacy snapshots.
4. Snapshot loading on startup must hydrate `parsed_sheets`.

## PHASE 2 — Multi-row / merged header repair

Extend `_clean_sheet_headers` in `backend/main.py` (this automatically fixes `query_engine.load_all_sheets` too):

1. After locating the header-candidate row, look at the 1–2 rows ABOVE it. If an above-row is sparse and its non-null values sit over runs of columns (merged-cell group labels like `Actual`, `Budget`, `Forecast - Q1'24-25`), forward-fill the group labels across their span and produce compound column names: `{group}_{leaf}` (e.g. `Actual_Sales`, `Budget_PBT`). Leaf-only when no group applies.
2. Deduplicate resulting names (`Sales`, `Sales_2`, ...). Never leave `Unnamed:` or `Col_N` names when ANY string content exists in the top 6 rows for that column; fall back to `Col_N` only for truly empty columns.
3. Drop fully-empty leading columns/rows before header detection (MIS sheets often start with a blank column A).
4. Keep the fail-closed behavior: if detection is ambiguous, prefer leaving data intact over eating rows.
5. Add unit tests in `backend/tests/test_headers.py` using small in-memory DataFrames replicating sheets `'1'`, `'15.1'`, `'8'` structures shown above, plus a clean single-header sheet (must pass through unchanged).

## PHASE 3 — Sheet router (`backend/sheet_router.py`, new file)

Two-tier router deciding which sheet(s) a question is about. Signature:

```python
def route_question(question: str, doc: dict) -> dict:
    # returns {"sheets": [names...], "confidence": float, "tier": "keyword"|"llm", "reason": str}
```

**Tier 1 — zero-token keyword scoring (always runs first):**
- Score each sheet: matches of question tokens against (a) sheet name, (b) cleaned column headers, (c) `schema_mapper.lookup_business_category` / glossary categories, (d) sheet role from `classify_sheet_roles`. Weight column-header matches highest. Normalize scores.
- If top score is confident (clear margin over second place — pick and document a threshold), return that sheet, tier="keyword".
- Detect whole-file intent (tokens like: summary, summarize, overview, entire, all sheets, whole file, overall) → return `{"sheets": ["__ALL__"], ...}`.

**Tier 2 — tiny LLM call (only when Tier 1 is ambiguous):**
- Prompt contains ONLY: the question + a compact index of every sheet (name, role, first ~15 column names each). NO row data. Must be ≤ ~1,500 tokens total so it fits Phi-3's 4k window.
- Ask for a JSON answer `{"sheets": [...]}`; parse defensively; on any parse/provider failure fall back to Tier 1's best guess (never crash, never DEMO).

**Wire into `/api/chat`:** if the request carries an explicit `active_sheet` (user picked from UI), respect it. Otherwise call `route_question` and set `doc['active_sheet']` for this request so the EXISTING scoping block (lines ~447–494) does the narrowing. Include `routed_sheet` and `router_reason` in the chat response payload so the frontend can display "Answered from sheet: 15.1".

## PHASE 4 — Whole-file summary via cached map-reduce

New module or extension in `main.py` (`summarize_workbook(doc) -> str`):

1. For each sheet, produce a per-sheet summary with ONE small LLM call: input = that sheet's preview (≤ 6,000 chars) + its stats block. Sheets that are empty/template (no data rows after cleaning) get a hardcoded summary "Template sheet — headers only, no data" with ZERO LLM calls.
2. Process sheets SEQUENTIALLY with a small delay (e.g. 2s) between cloud calls; on a 429, fall to the next provider in the chain, then Phi-3; if everything fails for a sheet, record "summary unavailable" and continue.
3. **Cache**: store per-sheet summaries in the snapshot as `sheet_summaries: {sheet_name: {"summary": str, "model": str, "ts": ...}}`. On subsequent whole-file questions reuse the cache — zero new tokens. Invalidate only when the file is re-uploaded (new doc_id — free).
4. Reduce step: one LLM call combining the ≤26 mini-summaries (small payload) to answer the user's actual question. Cache the generic combined overview too.
5. Router result `__ALL__` triggers this path.

## PHASE 5 — Provider chain hygiene (`backend/ai_orchestrator.py` + presets)

1. Auto chain order: `groq → cerebras → openrouter → phi3`. Remove Gemini everywhere (constraint 2).
2. **DEMO fallback must stop masquerading as analysis.** Either remove it from the auto chain, or (preferred) return a structured error the API surfaces as `{"error": "All AI providers are currently unavailable (rate-limited). Please retry in a few minutes.", "providers_tried": [...]}` with HTTP 503 from `/api/chat`. The frontend must show this as an error banner, not a normal answer. DEMO may remain ONLY for an explicit `model_key='demo'`.
3. Provider-aware truncation stays, but with the new scoped payloads enforce: per-sheet preview cap 8,000 chars (4,000 for phi3) — update `_PROVIDER_PREVIEW_LIMITS` usage accordingly for the scoped path.
4. Route ALL remaining callers of legacy `excel_analyzer.py` (first-sheet-only) through the new scoped pipeline, or fix `excel_analyzer.py` to accept a sheet name and be called per-sheet. Grep for its callers and migrate every one.

## PHASE 6 — Frontend (`src/components/`)

1. In the chat/assistant UI (`ProcurementAssistant.jsx` + `SheetPreview.jsx`): add a sheet selector dropdown populated from the doc's `sheet_names`. Default option: **"Auto (AI picks the sheet)"**. Manual selection sends `active_sheet` with the chat request.
2. Display `routed_sheet` returned by the backend under each answer: "📄 Answered from sheet: X" (or "All sheets (summary)" for map-reduce).
3. Render the Phase-5 503 provider error as a visible error state with a Retry button — never as an assistant message.

## PHASE 7 — ACCEPTANCE TESTS (run these; all must pass)

Create `backend/tests/test_mis_pipeline.py` (pytest, no network needed for 1–5 — mock `create_chat_completion` where an LLM would be called):

1. **Header repair:** loading `uploads/47a8264f-961a-4499-9b62-40f51f280dbc_MIS Automation PGIL.xlsx` via `query_engine.load_all_sheets` yields, for sheet `'1'`, compound columns containing both `Actual` and `Budget` groups with `Sales`/`PBT` leaves; sheet `'15.1'` has a `Customer` column; NO sheet has >30% `Unnamed`/`Col_` columns when it contains header text.
2. **Per-sheet snapshots:** after processing the MIS file, `doc['parsed_sheets']` has all 26 sheets; every value ≤ 20,000 chars; snapshot JSON round-trips them.
3. **Router Tier 1:** "customer wise revenue for FY 24-25" → sheet `'15.1'` (or `'15'`), tier=keyword. "inventory ageing" → `'6'`. "summarize the whole MIS file" → `__ALL__`. No LLM call made (assert mock not called).
4. **Scoped payload size:** for a routed single-sheet question, the assembled prompt/data preview sent to the provider is ≤ 8,000 chars of sheet data and contains ONLY the routed sheet's section (assert another sheet's marker string is absent).
5. **Empty-template honesty:** question routed to sheet `'21'` or `'22'` produces a response that states the sheet has headers but no data (mock the LLM; assert the context given to it flags empty data, or the code short-circuits without an LLM call).
6. **Map-reduce caching:** call `summarize_workbook` twice with a mocked LLM; second call performs ZERO LLM invocations (cache hit) and returns the same summaries.
7. **No-DEMO leak:** with all providers mocked to fail, `/api/chat` returns the structured 503 error — response text must NOT contain demo/canned content.
8. **Regression:** existing behavior on `uploads/*query_engine_test.xlsx` still works: a simple sum/mean question resolves through `query_engine` with correct pandas math.
9. **Gemini gone:** `grep -ri gemini backend/ --include=*.py` shows no live call sites in the request path (imports guarded or removed).

Also do a live smoke test if the backend can start: `uvicorn main:app --port 8001`, upload the MIS file, ask "which customer had the highest revenue in FY 24-25", confirm the answer cites sheet 15/15.1 and a real number from the file.

## STYLE / SAFETY NOTES

- Small, reviewable commits per phase. Run tests after each phase.
- Log every routing decision at INFO: `router sheet=<x> tier=<keyword|llm> conf=<..>`.
- Never send more than one sheet's data in a single LLM call anywhere in the codebase after this change — audit `grep -n "parsed_csv" backend/*.py` at the end and justify each remaining use.
