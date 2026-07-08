# PEARL PRO — COMPANY-READY BACKEND
## Full Industry-Grade Implementation Guide for Claude CLI

---

## EXECUTIVE SUMMARY

Pearl Pro is the upgrade path that takes this backend from "works on clean sample data" to
"works on real company MIS files." Every item below traces to either a concrete architectural
gap already identified in the code, or a failure directly reproduced by running the existing
pipeline against a real reference file (`MIS Automation PGIL.xlsx` — a 30-sheet company MIS
workbook with cryptic sheet names, heavy merged-cell dashboards, multi-row hierarchical
headers, and mixed currencies). Nothing here is speculative.

Two failures already diagnosed motivate most of this work: (1) a typed "summarize this
workbook" request produced a response that mostly echoed pre-computed statistics blocks back
as prose, got cut off mid-sentence from an undersized token budget, and was never checked for
grounding because summary/analysis requests are explicitly exempted from the numeric-grounding
check; (2) running the actual header-cleaning and preview-building code against the reference
file found real data corruption (FX-rate values promoted into column headers, a report title
forward-filled across 70 columns as if it were the real header) and a preview text size of
~95,000 characters silently truncated against a 24,000-character budget that has no
relationship to any model's actual context window.

**This is an extension of the existing architecture, not a rewrite.** The core pipeline —
parse every sheet → profile → validate → detect relationships → query engine → grounded LLM
answer — is sound and should be preserved. Every phase below hardens or extends an existing
module; none replace the pipeline's shape.

---

## NON-NEGOTIABLE DESIGN PRINCIPLES

1. **Ground or refuse — never drift into an unwatched guess.** Every answer path must either
   produce a verifiable answer or say clearly that it can't, and why. No path is allowed to
   silently fall through to a weaker guarantee than the one before it.
2. **Provider limits are real even when your own constants aren't.** Any cap tied to model
   capacity (context window, token budget) must be resolved against the actual provider in
   use, not a single hardcoded number applied uniformly.
3. **Scope before you summarize.** Reduce what a single AI call has to reason about by
   narrowing to what's relevant (the active sheet, a properly-sized chunk) — not by
   partitioning ownership of the data itself into fixed, non-communicating silos. (See
   "Explicitly Rejected Design" below — this principle exists because of a specific proposal
   that would have violated it.)
4. **Consistency over division of labor when parallelizing.** When work is split for
   parallel processing, use the same model/quality bar across the split, and always recombine
   with a final pass that has full cross-reference context — never let parallelism become an
   excuse to lose cross-sheet relationships.

---

## PHASE 1 — ACTIVE-SHEET-FIRST SCOPING

**Status: fully specced separately** — see `SHEET_PREVIEW_AND_SCOPED_QUERY_IMPLEMENTATION_PROMPT.md`
for full detail. Summary for continuity: add a spreadsheet preview panel with sheet tabs; the
AI defaults to analyzing only the sheet currently in view (threaded through `_enrich_doc` in
`main.py`, narrowing `profile`/`validation`/`statistics`/`data_preview`/`unified_schema` down
to one sheet); cross-sheet reasoning happens only on explicit request; report/insights/RFQ
generation stay whole-workbook by default. Fixes the first-sheet-only `columns` bug found in
`queue_document_processing` as a side effect.

This is Pearl Pro's foundation — it directly solves the ~95,000-vs-24,000-character overflow
on the reference file, since one sheet's preview comfortably fits regardless of workbook size.

### 1a. Query-complexity routing — closes the Phase 1 ↔ Phase 4 gap

**This subsection resolves a real conflict identified during review and must be built
alongside Phase 1, not deferred.** Once chat defaults to the active sheet, a typed request
like "summarize the whole workbook" would incorrectly get scoped to whatever sheet happens to
be in view — silently reintroducing a version of the exact bug Phase 4 exists to fix.

Fix, grounded in the published **Adaptive-RAG** pattern (query-complexity routing): classify
every incoming chat request into one of three types before deciding how to answer it —
**single-hop** (a factual question answerable from the one sheet currently in view — routes to
Phase 1's scoping), **multi-hop** (needs reasoning across sheets — routes to the relationship-
aware cross-sheet path, bypassing single-sheet scoping deliberately), or **summary** (a broad
analyze/summarize request — routes to Phase 4's map-reduce, ignoring active-sheet scope
entirely since the request is explicitly about the whole workbook). The classifier itself can
be a small, cheap model call or a lightweight prompt — published results show this kind of
three-way routing achievable with well over 85% accuracy at negligible added latency, and it's
the same shape as query-complexity routing used broadly in production RAG systems. Build this
classifier before wiring Phase 1's default scoping into `procure_agent`, not after — it's the
gate that decides whether scoping applies at all for a given request.

---

## PHASE 2 — INGESTION & SCALE ROBUSTNESS

### 2a. Provider-aware context/preview budget

`DATA_PREVIEW_CHAR_LIMIT = 24000` in `main.py` is an arbitrary constant with no tie to any
model's real capacity — confirmed by checking Groq's `llama-3.3-70b-versatile` (the primary
provider in `ai_orchestrator.py`), which has a 131,072-token context window, well over 20x
what the current constant assumes. But the fallback chain doesn't always land on Groq — Phi3
(local Ollama) and the free OpenRouter tier have much smaller windows. **Requirement: resolve
the preview/context budget against whichever provider is actually about to answer for a given
request, or at minimum against the smallest configured provider's real limit — never a single
flat number applied uniformly across every provider in the chain.** This budget must also
account for the rest of the prompt (system prompt, conversation history, schema/relationship/
statistics blocks) competing for the same window, not just the raw data preview in isolation.

### 2b. Multi-row, title-aware header detection

Directly reproduced against the reference file: `_clean_sheet_headers` (main.py) left 10 of
30 sheets with unusable `Unnamed: N` columns, and on at least three sheets actively corrupted
headers rather than failing safely — FX-rate data values promoted to column names on one
sheet, literal backtick characters on another, and a report-title cell forward-filled across
all 70 columns of the widest sheet (destroying the real per-customer headers underneath).
Root cause: the heuristic inspects only one row to decide whether a second header row exists,
and has no concept of a title/blank row sitting above the real header — both are common in
real MIS exports. **Requirement: header detection must look multiple rows deep, explicitly
recognize and skip title/blank rows before attempting header promotion, and fail closed
(leave a column unnamed or flag it as unresolved) rather than promoting the wrong row when
uncertain.** Reference architecture for a more durable long-term replacement: Microsoft's
SpreadsheetLLM/SheetCompressor approach — structural-anchor detection for genuine table
boundaries, rather than row-position heuristics. For the eventual next step beyond that,
Microsoft Research's **TableSense** paper is the rigorous long-term target: it treats a
spreadsheet's cell grid like an image and trains a CNN to detect real table boundaries,
reporting 91.3% recall / 86.5% precision across over 22,000 real tables spanning diverse,
messy layouts — precisely the class of problem sheets `18`/`5.1`/`a` represent. This requires
a trained model, so treat it as the target once the multi-row heuristic fix (above) is shipped
and proven insufficient on a wider sample of real files, not the first move.

### 2c. Fuzzy cross-sheet relationship matching

`sheet_orchestrator.py`'s join detection currently matches on literal column-name equality
plus value overlap — will miss real naming mismatches across systems (e.g. "Vendor_ID" vs
"Supplier Code"), which is the norm rather than the exception in company data pulled from
multiple source systems. **Requirement: extend relationship detection to fuzzy/semantic
column matching**, not just literal equality. Validate against the reference file's real
cross-sheet structure only after 2a/2b are fixed — corrupted headers currently make
relationship detection results on this file unreliable to evaluate. Reference lineage: this is
the same problem text-to-SQL **schema linking** research solves (the BIRD benchmark
specifically targets "dirty and noisy" schemas and distinguishing similarly-named columns) —
the common technique treats schema linking as a named-entity-recognition problem, tagging each
term in a question against the most likely real column rather than matching strings directly.
Study an approach like AutoLink or LinkAlign's schema-linking method before designing this
fuzzy matcher from scratch.

---

## PHASE 3 — UNIVERSAL GROUNDING & HONEST FAILURE

Existing grounding mechanisms (numeric-grounding retry/discard in `procure_agent`,
`generate_report`, `generate_insights_report`) already refuse to show answers with
unverifiable figures — but only on some paths, and not consistently. **Requirement: every
answer-producing path must distinguish "verified answer" from "couldn't verify," and when it
can't, it must say so plainly and specifically — never fall back to a generic hedge, and
never silently drift into an unwatched guess.**

Concrete gap already identified: `_try_answer_data_query` (services.py) returns `None` on
spec-generation failure or execution error and falls through silently to the general prose
LLM tier — which has no structural guarantee of catching a bad answer afterward, because
`_QUALITATIVE_RE` explicitly exempts summary/analysis/overview-style questions from the
numeric-grounding check. This exact gap produced the diagnosed "useless summary" failure: the
model wasn't caught fabricating or drifting, because nothing was watching that path for this
class of question.

Requirements for the fix:
- Close the gap above — a qualitative question is exempt from *numeric*-grounding (correct,
  since narrative answers aren't purely numeric), but it still needs some other check that the
  response is actually derived from the provided data rather than free-associated structure
  mirroring the injected context block's own section labels.
- The future sandboxed code-execution fallback tier (Phase 5) must follow the same discipline:
  if generated code errors even after a retry, return an explicit "can't compute this from
  your data" message — never silently drop to a prose guess. This tier's real advantage is
  that its output is either a genuine computed number or a clean failure, nothing in between.
- Failure messages must be specific and actionable: what couldn't be verified (a figure, a
  sheet reference, a relationship), and why (not in the currently scoped sheet, no matching
  column, ambiguous request) — not a generic "something went wrong, please try again."

For the qualitative/narrative path specifically (exempt from numeric grounding but still
capable of non-numeric fabrication — the "Dr. Jane Doe" placeholder-text bug already caught
by regex is exactly this failure mode), consider **Chain-of-Verification (CoVe)** as a
supplementary check: draft the answer, generate verification questions against its own claims,
answer those independently, then rewrite. Be honest about its limits when specced further —
published results show a real but modest improvement (F1 0.39 → 0.48) and it reduces rather
than eliminates hallucination; treat it as a supplement to the checks above, not a substitute
for them.

---

## PHASE 4 — WHOLE-WORKBOOK MAP-REDUCE ANALYSIS

This replaces the single-call, token-budget-constrained path for broad "summarize/analyze the
whole workbook" requests specifically — not general per-query chat, which stays scoped to the
active sheet per Phase 1.

An earlier proposal considered splitting a workbook into three equal parts, each permanently
owned and answered by a different AI framework. Rejected — see "Explicitly Rejected Design"
below for why — but the underlying instinct (reduce what one AI call has to reason about) is
correct and should be captured properly as a map-reduce pattern instead:

- **Split by actual content size, not sheet count or a fixed number of parts.** The reference
  file's sheets range from 2 rows/5 columns to 392 rows/78 columns — an equal-count split
  badly unbalances actual complexity. Chunk boundaries should be sized against the resolved
  context budget from Phase 2a.
- **Process each chunk with the same model/quality bar, in parallel, for speed** — not
  different frameworks dividing labor. Consistency of output format and reasoning quality
  matters more than parallel diversity.
- **A final reduce pass combines the per-chunk partial summaries and must have access to the
  already-computed cross-sheet relationship data** (`unified_schema` from
  `sheet_orchestrator.py`), so a relationship spanning two chunks isn't lost just because its
  two sheets landed in different chunks. This is the critical difference from the rejected
  three-way-ownership proposal: chunking here is a processing detail invisible to the final
  answer, not a permanent boundary on what any one part of the system can reason about.
- This directly fixes the mid-sentence truncation observed in the diagnosed summary failure —
  `generate_report`'s existing per-sheet mode (`max_tokens=4000`) is closer to this shape
  already; extend that pattern to genuinely parallelize per-chunk generation rather than
  hoping one call's token budget covers an arbitrarily large workbook.
- This map-reduce pattern is a well-established, named technique, not something novel to
  Pearl Pro — map each chunk to its own summary independently, then reduce by combining. For a
  workbook this large (30 sheets), consider the **hierarchical merging** refinement over flat
  map-reduce: pair chunk-summaries and re-merge in layers rather than combining all of them in
  one final reduce step, specifically because a paper on this technique
  ("Context-Aware Hierarchical Merging for Long Document Summarization") addresses exactly the
  cross-reference-loss concern already raised above — flat reduce over many chunks at once is
  where cross-sheet relationships are most likely to get dropped.

---

## PHASE 5 — RELIABILITY INFRASTRUCTURE

- **Sandboxed code-execution fallback tier.** For questions outside the fixed query-spec
  vocabulary (custom stats, reshaping, ad hoc charts) — sits between the existing
  `_try_answer_data_query` spec engine and the general prose tier in `procure_agent`.
  Reference implementation to study: PandasAI's Docker sandbox mode, and the underlying
  academic pattern is **PAL (Program-Aided Language Models)** — have the model generate code,
  then execute it deterministically in a real interpreter rather than letting the model
  compute the answer itself; published results show substantial accuracy gains over the model
  reasoning through arithmetic in prose (~72% vs 55-65% on a standard math-reasoning
  benchmark), precisely because symbolic execution removes the arithmetic-hallucination
  failure mode. A useful side effect worth building in: the generated code is itself an
  auditable trace — consider surfacing it to users as "show your work," not just the final
  number. Must follow the Phase 3 discipline (clean failure over guessing) and should not run
  unsandboxed given this handles company financial/vendor data — document content could
  contain prompt-injection text attempting to steer generated code, so isolate with no network
  access, resource/time limits, and a restricted execution namespace at minimum.
- **Model router: existing fallback chain + one genuine frontier tier.** The current chain
  (Groq → Phi3 → Cerebras → OpenRouter free tier → demo) was built for cost-free resilience,
  not peak reasoning quality — adequate for simple lookups, not for the multi-sheet reasoning
  Pearl Pro targets. `gemini_client.py` and `openai_client.py` already exist in the repo, fully
  coded, unused by anything else — wiring one in as the "complex reasoning" option, alongside
  the existing model-selector pattern (`model_key` in `ConversationMessage`, already
  implemented), is a low-lift extension rather than new infrastructure. Route simple/
  structural questions to the existing cheap chain; route complex multi-sheet reasoning and
  Phase 4's map-reduce chunks to the frontier tier.
- **Grounding at scale.** Extend the numeric-grounding known-values corpus so it holds up
  against the much larger space of legitimate ad hoc aggregates a real multi-sheet company
  workbook produces, not just the smaller set a simple document generates.

---

## PHASE 6 — ENTERPRISE GOVERNANCE (LATER PHASE, LOWER PRIORITY)

Deeper audit trail detail, sandbox isolation hardening beyond Phase 5's minimum, per-tenant
data separation. Matters once the above is solid and this is handling real company financial/
vendor data in production — doesn't itself reduce hallucination or improve reasoning quality,
so it should not compete for priority against Phases 1-5.

---

## MODEL / API STRATEGY

Router pattern, not a single model swap: keep the existing free/cheap chain for simple
lookups, add one frontier-tier cloud model (Claude or GPT-class, given the structured-output
and tool-use reliability this architecture's query-spec generation depends on) for complex
reasoning and Phase 4's chunk processing. Cloud over self-hosting for the frontier tier —
self-hosting only pays off against a hard data-residency mandate or sustained volume that
undercuts API cost, and an open-weight model realistic to self-host still generally trails
frontier closed models on this class of reasoning. If data sensitivity (not a compliance
mandate) is the actual concern, confirm the chosen provider's business/enterprise tier terms
on data retention and training-use directly as part of the contract — don't assume based on
general reputation. Keep the local Ollama tier for the simple/structural query tier regardless
— free, private, offline-capable, and adequate where model strength barely matters.

---

## EXPLICITLY REJECTED DESIGN — DO NOT REINTRODUCE

**Proposal considered and rejected: split every incoming workbook into three equal parts,
each permanently owned and answered by a different AI framework, with queries routed to
whichever AI "owns" the relevant section.** Reasons this doesn't work, recorded so it isn't
reconsidered without addressing these specifically:
- Equal-count splitting doesn't produce equal-complexity splitting — the reference file's
  sheet sizes vary by two orders of magnitude.
- Breaks cross-sheet relationship answering by construction — any question spanning a split
  boundary becomes unanswerable, not just harder, defeating the core value the relationship-
  detection pipeline (`sheet_orchestrator.py`) already provides.
- Query routing requires already knowing which section a query concerns, which requires
  workbook-structure understanding up front — most of the work the split was meant to avoid,
  just relocated and renamed.
- Three different AI frameworks multiplies integration surface (inconsistent output formats,
  reliability, latency, cost) without a clear benefit over one capable model given properly
  scoped context.
- Overlaps and conflicts with Phase 1's dynamic active-sheet scoping, which already reduces
  per-query context based on what the user is actually looking at — a fixed partition assigned
  once at upload is a strictly worse mechanism for the same goal.

The map-reduce pattern in Phase 4 is the correct version of the underlying instinct (reduce
what one AI call reasons about at once) — chunked by content size for a specific whole-
workbook task, recombined with full cross-reference context, never a permanent ownership
boundary.

---

## STANDING REFERENCE TEST CASE

`MIS Automation PGIL.xlsx` — 30 sheets, cryptic names (`13,14`, `a`, bare numbers), heavy
merged-cell dashboards, multi-row hierarchical headers, mixed currencies side by side,
apparel/manufacturing MIS data (customer names, FX rates, factory KPIs, contract/spend data).
Already surfaced three concrete header-corruption bugs and the context-budget overflow in a
first pass — use it as the acceptance-test fixture for Phases 1-4 before considering any of
them done. Specific regression cases to check: sheet `18`'s FX-rate-as-header corruption,
sheet `5.1`'s backtick-character columns, sheet `a`'s title-forward-filled-across-70-columns
corruption, and the full-workbook preview size against whatever provider-aware budget Phase
2a establishes.

---

## VERIFICATION CHECKLIST

- Upload the reference file; confirm all three known header-corruption cases (sheets `18`,
  `5.1`, `a`) now produce real, usable column names instead of corrupted or blank ones.
- Confirm the full-workbook preview/context size no longer silently truncates a majority of
  the workbook's sheets — verify against whichever provider actually answers the request, not
  just the largest configured provider's window.
- Ask a broad "summarize this workbook" question; confirm the response covers every sheet
  (via Phase 4's map-reduce), doesn't get cut off mid-sentence, and doesn't merely restate
  injected statistics-block labels as headings without added synthesis.
- Ask a question that requires data outside what's currently verifiable; confirm the response
  states clearly and specifically what couldn't be verified, rather than producing a
  plausible-sounding unverified answer.
- Ask a cross-sheet question that spans what would have been two different partitions under
  the rejected three-way-split design; confirm it's still answerable end to end.
- With one sheet active in the preview panel, type a broad "summarize the whole workbook"
  request in chat; confirm the 1a routing classifier correctly detects this as a summary-type
  request and routes to Phase 4's map-reduce instead of answering only about the active sheet.
  This is the specific interaction bug the routing classifier exists to prevent.
- Confirm every existing feature (dual-model selector, RFQ flow, report/insights generation,
  audit logging) still functions unchanged — every phase above is additive to the existing
  pipeline, not a replacement of it.

---

## RESEARCH REFERENCES BY PHASE

- **1a (query-complexity routing):** Adaptive-RAG-style query classification —
  https://arxiv.org/html/2604.03455
- **2b (header/table detection):** TableSense (Microsoft Research) —
  https://arxiv.org/abs/2106.13500
- **2c (fuzzy relationship matching):** Text-to-SQL schema linking, BIRD benchmark —
  https://arxiv.org/pdf/2511.17190
- **3 (grounding/honest failure):** Chain-of-Verification (CoVe) —
  https://learnprompting.org/docs/advanced/self_criticism/chain_of_verification
- **4 (map-reduce / hierarchical merging):** Context-Aware Hierarchical Merging for Long
  Document Summarization — https://arxiv.org/pdf/2502.00977
- **5 (sandboxed code execution):** PAL: Program-Aided Language Models —
  https://arxiv.org/pdf/2211.10435 (reference implementation: PandasAI's Docker sandbox mode)
