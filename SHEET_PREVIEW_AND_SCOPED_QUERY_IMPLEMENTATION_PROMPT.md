# SHEET PREVIEW PANEL + SHEET-SCOPED AI QUERYING
## Implementation Guide for Claude CLI

---

## OBJECTIVE

Two additive changes to the dashboard, no existing feature removed or altered in behavior:

1. Add a spreadsheet preview panel next to the chat (grid view of the workbook, tabs/selector
   to switch between every sheet in the uploaded file) — similar layout to a typical
   spreadsheet-plus-chat interface: data grid on one side, conversation on the other.
2. Whichever sheet is currently being previewed becomes the *only* sheet the AI uses to
   answer the next question — the assistant should reason about one sheet at a time,
   scoped to what the user is actually looking at, instead of the whole workbook at once.

A third, unrelated, small change: restyle the app's font globally. Doing this alongside the
above only because it's trivial (one CSS line), not because it's related — call it out as
its own step so it doesn't get tangled with the sheet-scoping logic during review.

---

## CURRENT STATE (VERIFIED IN CODE — READ BEFORE CHANGING ANYTHING)

**The backend already parses every sheet, this is not the gap.** `queue_document_processing`
in `backend/main.py` calls `pd.read_excel(..., sheet_name=None)`, which reads all tabs. Every
sheet gets its own entry in `profile` (data_profiler.py), `validation` (data_validator.py),
and `statistics` (statistical_analyzer.py) — all three are dicts keyed by sheet name, e.g.
`profile["Invoices"]`, `profile["Vendors"]`. This per-sheet structure already exists and
should be reused, not rebuilt.

**Two real gaps exist:**

1. `DOCUMENT_STORE[doc_id]["columns"]` (main.py, inside `queue_document_processing`) is
   hardcoded to `all_sheets[sheet_names[0]].columns.tolist()` — always the first sheet,
   regardless of which one matters. This is a leftover simplification from before multi-sheet
   support existed and should be fixed as part of this work, since the new sheet selector
   makes the bug user-visible for the first time.
2. Nothing in the frontend renders spreadsheet rows at all today. The parsed data currently
   only exists as (a) a truncated CSV text blob (`parsed_csv`/`data_preview`) fed into LLM
   prompts, and (b) the structured profile/stats objects. Neither is meant for rendering a
   grid — there is no endpoint that returns raw row data for display, and no grid component
   in `src/components/`.

**How document context reaches the AI today** — this is the mechanism the scoping has to
hook into: `ProcurementAssistant.jsx` builds a small `context.active_document` object per
request (currently just `{ doc_id, name, type, status }`, see the two call sites around
lines 69–71 and 116–118) and sends it via `sendChat`. On the backend, `/api/chat` calls
`enrich_document_context` → `_enrich_doc` (main.py, ~line 251), which looks up the full
record in `DOCUMENT_STORE` by `doc_id` and attaches `profile`, `validation`, `statistics`,
`unified_schema`, `schema_context`, and `data_preview` before handing it to `procure_agent`.
This is the single choke point where every document's full context gets assembled — it's
also the correct place to narrow that context down to one sheet.

**Font today**: one line, `body { font-family: Inter, ui-sans-serif, ... }` in
`src/styles.css` (line 15). Everything inherits from `body` (`button, input, textarea {
font: inherit; }` is already set), so this is a one-line change for 95% of the UI.
`tailwind.config.js` has no `theme.fontFamily` override — if any component uses Tailwind's
`font-sans` utility class explicitly, it currently falls back to Tailwind's default stack
instead of Inter. Set `theme.extend.fontFamily.sans` too, so the new font applies whether
text is styled via plain CSS inheritance or an explicit Tailwind class.

---

## TARGET DESIGN

### 1. Sheet data endpoint (new)

Add a backend endpoint that returns one sheet's actual rows/columns for grid rendering —
e.g. `GET /api/document/{doc_id}/sheet/{sheet_name}`. This is distinct from the existing
`data_preview` text blob (that's LLM-prompt text, not structured row data). Read from the
same `all_sheets` structure already produced during upload — either re-derive it from
`file_path` on demand, or, since large workbooks shouldn't be fully re-parsed on every tab
click, consider caching a lightweight per-sheet row/column JSON alongside the existing
`profile`/`validation` entries in `DOCUMENT_STORE` at upload time. Paginate this endpoint
(offset/limit or a fixed page size) — some uploaded sheets have thousands of rows, and the
grid should not attempt to render all of them at once even though the AI-context preview
already caps itself for prompt-size reasons.

### 2. Frontend: two-pane layout with sheet tabs

Add a spreadsheet grid component (new file, e.g. `src/components/SheetPreview.jsx`) that:
- Renders as a panel alongside the existing chat panel in `ProcurementAssistant.jsx` (grid
  on one side, chat on the other — reuse the existing layout structure, don't rebuild the
  chat pane).
- Shows a row of tabs (or a dropdown, tabs read better for typically-few sheets) listing
  every entry in the document's `sheet_names` array — already returned by the backend today
  via `_enrich_doc`, nothing new needed there.
- On tab click, fetches that sheet's rows from the new endpoint and re-renders the grid.
- A plain HTML `<table>` with sticky header is enough for a first pass; if performance with
  large sheets becomes an issue, consider a virtualized grid library later — don't add a new
  dependency up front for something a table element can handle initially.

### 3. Frontend state: track the active sheet per document

`App.jsx` already holds `documents` / `activeDoc` state (lines 35–36) passed down into
`ProcurementAssistant`. Add sibling state for the active sheet, e.g. `activeSheet` /
`setActiveSheet`, passed the same way. Two behaviors to decide and implement explicitly:
- Default to the first sheet in `sheet_names` when a document is freshly selected or
  finishes uploading.
- Decide what happens when the user switches `activeDoc` to a different document — does
  `activeSheet` reset to that document's first sheet, or is a per-document last-viewed-sheet
  remembered? A simple `{ [doc_id]: sheetName }` map alongside `activeSheet` handles the
  latter cleanly if wanted; a single flat `activeSheet` string is simpler if not. Pick one
  and note the choice in the PR description — this is a real UX decision, not a detail to
  silently default without flagging.

### 4. Threading the active sheet into the AI's context (the actual scoping)

This is the core of the feature — everything above is plumbing to get a sheet name onto the
screen, this is what makes the AI actually respect it.

- `ProcurementAssistant.jsx`'s `context.active_document` object (both call sites, ~lines
  69–71 and 116–118) gains an `active_sheet` field alongside `doc_id`/`name`/`type`/`status`.
- `ConversationMessage` in `main.py` already carries `context: Optional[dict]` — no schema
  change needed there, `active_sheet` just rides inside the existing nested `active_document`
  dict.
- `_enrich_doc` (main.py, ~line 251) is where the narrowing happens. When the incoming doc
  object carries `active_sheet`, the enriched result returned to `procure_agent` should
  contain **only that sheet's slice** of:
  - `profile` — keep only the `{active_sheet: ...}` entry instead of all sheets.
  - `validation` — same, one key instead of all.
  - `statistics` — same.
  - `data_preview` — the current text blob concatenates every sheet under `=== Sheet: X
    ===` headers (built in `queue_document_processing`); extract just the active sheet's
    section instead of sending the whole concatenation.
  - `unified_schema` / relationships — cross-sheet join relationships are meaningless once
    scoped to a single sheet (nothing to join against). Drop them from the scoped context
    entirely rather than leaving stale relationship hints pointing at data the AI no longer
    has.
  - `columns` — resolve from `profile[active_sheet]['columns']` instead of the current
    hardcoded first-sheet lookup, which also fixes gap #1 above as a side effect.
  - Keep `sheet_names` unscoped (full list) — the frontend still needs it to render the tab
    row regardless of which one is active.
- When `active_sheet` is absent (older cached frontend, or any other endpoint that doesn't
  send it — report generation, insights, RFQ flows), `_enrich_doc` must fall back to
  exactly today's whole-workbook behavior. This has to be strictly additive.

### 5. Decide which endpoints respect scoping

`/api/chat` (→ `procure_agent`) is the obvious one — "answer about what I'm looking at" is
a chat-panel interaction. Report generation, insights PDF, and RFQ flows (`/api/report`,
`/api/insights/pdf`, `/api/analyze-for-rfq`, etc.) are meant to be comprehensive summaries
of the whole document today — decide explicitly whether those should stay whole-workbook by
default (recommended, since a report scoped to whatever tab happened to be open when the
user clicked "Generate Report" would be a confusing default) or whether they should also
accept an optional `active_sheet` override later. Don't let scoping silently leak into
those paths as a side effect of changing the shared `_enrich_doc` function — gate it behind
the presence of `active_sheet` in the request, which naturally keeps every non-chat caller
on the old behavior since none of them will be sending that field.

### 6. Tell the LLM about the restriction, not just the data

Trimming the context data is necessary but not sufficient — `procure_agent`'s system-prompt
reminder block (services.py, inside `procure_agent`, the long formatting-reminder message)
should also state plainly that only sheet X is in scope for this turn, and that if the user
asks about a different sheet by name, the assistant should say it isn't currently in view
rather than answer from memory of an earlier turn's conversation history. Conversation
history (`session_state['conversation_history']`) is still included on every turn — without
an explicit instruction, the model could keep discussing an earlier sheet's numbers that are
no longer in its context, which would look like a hallucination even though it's really a
stale-memory problem.

### 7. Font change (separate, trivial)

- `src/styles.css` line 15: change the `font-family` stack on `body`.
- `tailwind.config.js`: add `theme.extend.fontFamily.sans` with the same stack, so
  Tailwind's `font-sans` utility (if used anywhere) matches rather than reverting to
  Tailwind's default.

---

## FILES TOUCHED (SUMMARY, NO CODE)

Backend:
- `backend/main.py` — new `GET /api/document/{doc_id}/sheet/{sheet_name}` endpoint; fix the
  first-sheet-only `columns` assignment in `queue_document_processing`; extend `_enrich_doc`
  to accept and apply `active_sheet` scoping (profile/validation/statistics/data_preview/
  unified_schema/columns), falling back to full-workbook behavior when absent.
- `backend/services.py` — update the system-prompt reminder block in `procure_agent` to
  state the active-sheet restriction explicitly when scoping is in effect.

Frontend:
- `src/components/SheetPreview.jsx` — new grid component with sheet tabs.
- `src/components/ProcurementAssistant.jsx` — render `SheetPreview` alongside the chat pane;
  add `active_sheet` to both `context.active_document` construction sites.
- `src/App.jsx` — add `activeSheet` (or per-document map) state, passed down alongside the
  existing `activeDoc`/`documents` state.
- `src/services/api.js` — new function to call the sheet-data endpoint.
- `src/styles.css`, `tailwind.config.js` — font stack.

---

## EDGE CASES TO HANDLE EXPLICITLY

- Single-sheet workbooks — the tab row should either not render, or render a single
  non-interactive tab; don't force a selector for something with nothing to switch between.
- Very large sheets (thousands of rows) — the grid endpoint must paginate independently of
  the AI-context preview's row cap; these are different concerns with different limits.
- Switching sheets mid-conversation — confirm whether prior chat turns referencing the old
  sheet stay visible in the transcript (yes, it's history) while only the *next* answer is
  scoped to the newly selected sheet — this should be the default, but state it as a
  deliberate choice given point 6 above about stale-memory answers.
- Deleting/re-uploading a document while a non-default sheet is active — `activeSheet` state
  needs to reset or re-validate against the new document's `sheet_names`, not silently
  reference a sheet name that no longer exists.

---

## VERIFICATION CHECKLIST

- Upload a multi-sheet workbook, confirm the tab row lists every real sheet name (not just
  the first), and that `columns` in the document record now matches the *active* sheet, not
  always sheet one.
- Ask a question answerable only from Sheet A while Sheet A is active, then switch to Sheet
  B and ask the same question — confirm the second answer says the data isn't in view rather
  than reusing Sheet A's numbers from context or memory.
- Confirm a cross-sheet question (e.g. one that would normally use the join/relationship
  detection) is declined or redirected while a single sheet is scoped, instead of silently
  attempting a join with data that's no longer in context.
- Confirm report/insights/RFQ generation still produce whole-workbook output, unaffected by
  whatever sheet happens to be active in the preview panel at the time.
- Confirm an older request with no `active_sheet` field (simulate by omitting it) reproduces
  today's exact whole-workbook behavior — regression check for backward compatibility.
- Visually confirm the font change applied consistently across chat bubbles, buttons, inputs,
  and the new grid component — not just body text.
