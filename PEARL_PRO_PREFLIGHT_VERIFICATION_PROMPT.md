# PEARL PRO — PRE-FLIGHT VERIFICATION AUDIT
## Run This Before Handing the App Back for Manual Testing

---

## OBJECTIVE

After implementing any phase of `PEARL PRO — COMPANY-READY BACKEND` (formerly Model C), run this
audit against your own changes before telling the user it's ready to test. This is not a
feature request — it's a self-check. Where a step below requires running something, run it
(compile checks, the reference file, the sandbox probes) and report actual results, not an
assessment of whether the code "looks correct." If any check fails, say so plainly and do not
report the phase as done.

Produce a single written report at the end in the format specified in "REPORT FORMAT" below —
pass/fail per check, with evidence, not a summary paragraph claiming everything is fine.

---

## 1. BUILD / IMPORT SANITY

- Every changed Python file must actually parse and import cleanly — run a syntax check
  (e.g. `python -m py_compile` or equivalent) on every changed `.py` file, and confirm the
  backend actually starts without import errors.
- Every changed frontend file must build — run the project's build command and confirm it
  completes without errors, not just that individual files look syntactically plausible.
- Confirm no leftover debug prints, TODO placeholders, or commented-out old code paths were
  left in changed files.

---

## 2. REGRESSION CHECK — EVERYTHING THAT WORKED BEFORE MUST STILL WORK

List every existing feature explicitly and confirm each still functions unchanged after your
changes, not just that it wasn't intentionally touched:
- RFQ generation flow (`generate_rfq`, `refine_rfq_draft`, RFQ export endpoints)
- Report and insights generation (`generate_report`, `generate_insights_report`, PDF export)
- Audit logging (`log_event`, `get_events`, `get_document_lineage`)
- The existing dual-model selector (`model_key` in `ConversationMessage` → `procure_agent` →
  `create_chat_completion`) — confirm every value it previously accepted still resolves to the
  same provider/model as before
- Document upload, processing, and snapshot persistence/reload (`_save_snapshot`,
  `_load_snapshots`) — specifically test loading a snapshot saved in the OLD data shape
  (before your changes) and confirm it still loads without crashing, or that a migration path
  handles the shape difference. This is a known gap — verify it was actually addressed, not
  assumed to be fine.
- Every endpoint that doesn't send new fields your changes introduced (e.g. no `active_sheet`,
  no new `model_key` values) must reproduce byte-identical behavior to before your changes —
  test this directly by simulating an old-shaped request, not by inspection alone.

---

## 3. SECURITY CHECK — SANDBOXED CODE EXECUTION (if Phase 5 was implemented)

This is the highest-severity category — a superficial sandbox is worse than no sandbox at all,
because it creates false confidence. Do not report this as done based on the code "looking"
isolated — actually attempt each of the following and confirm it is blocked:
- Attempt to make generated/executed code read environment variables or `.env` contents from
  within the execution context — must fail.
- Attempt network access (e.g. an outbound HTTP call) from within executed code — must fail.
- Attempt filesystem access outside the specific data the query needs (e.g. reading another
  document's file, writing outside an allowed temp path) — must fail.
- Confirm a resource/time limit actually terminates a deliberately long-running or
  memory-heavy snippet, rather than hanging or crashing the whole backend process.
- Confirm a failure inside this tier (timeout, blocked access, execution error) produces the
  explicit "can't compute this from your data" style message required by Phase 3's discipline
  — not a silent fallback to an unverified prose guess, and not an unhandled exception that
  crashes the request.

---

## 4. GROUNDING / ANTI-HALLUCINATION REGRESSION CHECK (Phase 3)

The risk here is invisible unless specifically tested — a weakened grounding check doesn't
crash, it just lets more wrong numbers through looking confident.
- Confirm the existing numeric-grounding retry/discard logic (`find_unverifiable_numbers` and
  its call sites in `procure_agent`, `generate_report`, `generate_insights_report`) still
  triggers correctly on a deliberately fabricated figure — test with a known-bad number, don't
  just read the code.
- Confirm `_QUALITATIVE_RE`'s exemption scope hasn't silently broadened beyond
  summary/analysis/overview-style questions to cover requests that should still be
  grounding-checked.
- If Phase 3's non-numeric verification step (for the qualitative path) was implemented,
  confirm it actually catches a deliberately injected non-numeric fabrication (e.g. an invented
  name, category, or claim not present in the source data) — test it, don't assume.
- If Phase 5's code-execution tier exists, confirm its failure mode is a clean stated refusal,
  not a silent handoff to the general prose tier with no grounding safety net.

---

## 5. QUERY-COMPLEXITY ROUTING CHECK (Phase 1a, if implemented)

- With one sheet active, ask a genuine single-sheet question — confirm it's answered scoped to
  that sheet, without unnecessarily invoking the more expensive multi-hop or map-reduce path.
- With one sheet active, ask "summarize the whole workbook" (or equivalent broad phrasing) —
  confirm this is classified as a summary-type request and routed to Phase 4's map-reduce,
  NOT answered using only the active sheet's data. This is the specific interaction bug the
  classifier exists to prevent — test it explicitly, it is not optional.
- Ask a genuine cross-sheet question — confirm it's classified as multi-hop and actually uses
  cross-sheet relationship data, not silently scoped to one sheet.

---

## 6. SCALE / COST GUARDRAILS (Phase 4/5, if implemented)

- Confirm there is an actual upper bound on how many parallel chunk calls or frontier-model
  calls a single request can trigger — report the bound explicitly, don't just note that
  parallelization exists.
- Confirm repeated identical whole-workbook summary requests don't blindly re-run the full
  map-reduce pipeline every time if any caching was intended — report whether caching exists
  and, if not, flag this explicitly as a known cost risk rather than silently omitting it.

---

## 7. REFERENCE FILE REGRESSION SUITE — MANDATORY

Run `MIS Automation PGIL.xlsx` through the full updated pipeline and report actual results
for each of the following, not a general impression:
- Sheet `18`: confirm column headers are no longer FX-rate data values.
- Sheet `5.1`: confirm column headers are no longer literal backtick characters.
- Sheet `a`: confirm column headers are no longer a single report-title string repeated across
  all 70 columns, and that real per-customer headers are recovered.
- Confirm the full-workbook preview/context size no longer silently truncates a majority of
  the workbook's sheets — report the actual measured size against whatever provider-aware
  budget was implemented (Phase 2a), for whichever provider actually answers.
- Ask a broad "summarize this workbook" question and confirm the response covers every sheet,
  does not get cut off mid-sentence, and does not merely restate injected statistics-block
  section labels as headings without added synthesis.

---

## 8. GENERAL CODE HEALTH

- No hardcoded secrets, API keys, or credentials introduced anywhere in changed files.
- New code follows existing patterns/conventions in the surrounding file rather than
  introducing a stylistically inconsistent approach.
- Any new dependency added is actually declared in `requirements.txt` / `package.json`, not
  just imported and assumed to be present.

---

## REPORT FORMAT

Produce one report at the end, structured as:

```
PEARL PRO PRE-FLIGHT AUDIT — [date/phase(s) covered]

1. Build/Import Sanity — PASS / FAIL (evidence)
2. Regression Check — PASS / FAIL (evidence per feature listed)
3. Sandbox Security — PASS / FAIL / N/A (evidence per probe attempted)
4. Grounding Regression — PASS / FAIL (evidence)
5. Query-Complexity Routing — PASS / FAIL / N/A (evidence)
6. Scale/Cost Guardrails — PASS / FAIL / N/A (evidence, or explicit "not addressed")
7. Reference File Regression Suite — PASS / FAIL (evidence per sheet/case listed)
8. General Code Health — PASS / FAIL (evidence)

OVERALL: READY FOR MANUAL TESTING / NOT READY — [specific blocking issues, if any]
```

If any category is FAIL, do not mark the phase complete — describe exactly what failed and
what would need to change, and stop there rather than proceeding to additional phases on top
of an unverified foundation.
