# DUAL QUERY-ANSWERING MODEL SELECTOR
## Implementation Guide for Claude CLI

---

## OBJECTIVE

Add a user-facing control in the dashboard chat panel that lets the person choose which
LLM answers their question — analogous to the model picker in Claude's own interface
(Sonnet / Haiku / Opus). Two selectable options to start, final display names decided
later by the product owner (use placeholders `MODEL_A` / `MODEL_B` everywhere until
named). The selection must travel from the text box, through the API, to the specific
LLM call that generates the answer — and nowhere else in the system should change
behavior.

This is additive. Every existing code path that doesn't pass a selection must behave
exactly as it does today.

---

## CURRENT ARCHITECTURE (AS-IS)

Understand this before changing anything — the selector has to slot into an existing
provider-fallback design, not replace it.

**`backend/ai_orchestrator.py`** — `create_chat_completion(messages, max_tokens)` is the
single entry point every part of the backend calls to reach an LLM. It has no model
parameter today. Internally it walks a fixed provider chain in order — Groq, then Phi3
(local Ollama), then Cerebras, then OpenRouter, then a canned demo fallback — and returns
the first one that responds. The caller never picks a provider; the chain picks for them
based on what's configured/available/healthy at that moment.

**`backend/ai_providers/*.py`** — one class per provider (`GroqProvider`,
`CerebrasProvider`, `Phi3Provider`, `DemoProvider`). Each reads its model name from a
module-level environment variable at import time (`GROQ_MODEL`, `CEREBRAS_MODEL`,
`OLLAMA_MODEL`) and hardcodes that name into every `complete()` call. There is currently
no way to ask a provider to use a different model than the one baked in at startup.

**`backend/services.py`** — `procure_agent(user_query, document_context, session_state)`
is what actually answers a chat message. It calls `create_chat_completion` in three
places: the main answer, and up to two numeric-grounding correction retries if the
answer cites a figure that doesn't match real computed data. It also calls
`_try_answer_data_query`, which itself calls `create_chat_completion` once — but that
call generates an internal JSON query spec (sheet/column/operation), it is not the
user-visible answer.

**`backend/main.py`** — the `/api/chat` endpoint receives a `ConversationMessage`
(`session_id`, `user_query`, `context`), calls `procure_agent(...)`, and returns the
result. No model information is part of the request today.

**Frontend** — `src/components/ProcurementAssistant.jsx` holds the chat input (a plain
text box + send button, around the `<div className="flex gap-3">` block near the bottom
of the component). `src/services/api.js` has `sendChat({ sessionId, userQuery, context })`
which POSTs to `/api/chat`. Neither has any concept of model selection today, and no
response currently displays which model answered.

---

## TARGET DESIGN

### 1. Two named presets, not two hardcoded providers

Do not wire `MODEL_A` to "always Groq" and `MODEL_B` to "always Cerebras" in a way that's
hard to change later — the point of this feature is that the product owner will decide
the actual models later and may want both presets pointing at the same provider with
different model names (e.g. two different OpenRouter models), or completely different
providers, or one preset that's itself a fallback chain. Build a small preset registry
that maps a `model_key` string to a concrete (provider, model name, and optionally
temperature/params) combination, kept in one place so re-pointing a preset later is a
one-line config change, not a code hunt.

Suggested location: a new `backend/ai_providers/model_presets.py` (or a dict at the top
of `ai_orchestrator.py` if the team prefers fewer files) holding something like a
`MODEL_PRESETS` mapping keyed by `"model_a"` / `"model_b"`, each entry naming which
provider to use and which model string to pass it. Keep the existing fallback-chain
behavior as the *default* path when no key is given — presets are an override, not a
replacement of the resilience logic.

### 2. Providers need to accept a model override, not just read a constant

Each provider's `complete()` currently ignores everything except the env-var constant.
For a preset to actually select a different model than the provider's default, `complete()`
needs an optional model-name argument that, when given, is used instead of the module
constant. This is a small, mechanical change per provider file (`groq_provider.py`,
`cerebras_provider.py`, `phi3_provider.py`) — same call, one extra optional parameter.

### 3. Threading the selection end to end

The selection has to pass through every layer without breaking anything that doesn't
supply it:

- **`create_chat_completion`** gains an optional `model_key` parameter (default `None`
  = today's exact fallback-chain behavior, unchanged). When a key is given, it resolves
  the preset and calls that specific provider/model directly — no chain-walking, since
  the user deliberately chose this model and a silent fallback to a different model would
  defeat the point of letting them choose. Decide and document what happens if the chosen
  preset's provider is unconfigured or errors: recommend surfacing a clear error to the
  user ("MODEL_B is currently unavailable") rather than silently substituting a different
  model's answer under the label the user picked.

- **`procure_agent`** gains an optional `model_key` parameter, forwarded to its
  user-visible `create_chat_completion` calls (the main answer and its grounding-retry
  calls). Leave the internal spec-generation call inside `_try_answer_data_query` on the
  default chain — that call just emits a JSON query spec, not a user-facing answer, and
  doesn't need to vary with the user's model choice. State this explicitly as a design
  decision in the code comment so a future reader doesn't "fix" it into also switching.

- **`ConversationMessage`** in `main.py` gains an optional field, e.g. `model_key:
  Optional[str] = None`. The `/api/chat` endpoint passes it straight through to
  `procure_agent`. Every other endpoint that doesn't send this field keeps behaving
  exactly as today.

- **`sendChat`** in `src/services/api.js` gains an optional parameter that gets included
  in the POST body only when set.

- **`ProcurementAssistant.jsx`** gains a small selector control (two-option toggle or
  dropdown — a toggle reads better for exactly two choices) placed above or beside the
  existing input row. Its selected value is held in component state, included in every
  `sendChat` call, and should persist across the session (e.g. `localStorage`, which is
  fine here since this is the real deployed app, not a Claude-authored artifact sandbox).
  Default to whichever preset the product owner designates as primary if nothing is
  stored yet.

### 4. Naming stays swappable

Put the two display labels in one constant (e.g. `src/config/modelOptions.js` exporting
an array of `{ key: 'model_a', label: 'MODEL_A' }` objects) rather than inline JSX
strings, so renaming later — once the product owner picks real names — is a one-line
edit, not a search-and-replace across the component.

### 5. Show which model actually answered

`procure_agent`'s return value already includes a `model` field (currently the provider
name or `'deterministic'`/`'deterministic-query-engine'`). Once a preset system exists,
surface the resolved model name in that same field so the frontend can label each
response ("Answered by MODEL_A") in `MessageBubble` — useful for the product owner to
verify the selector is actually taking effect, and useful to end users comparing the two.

---

## FILES TOUCHED (SUMMARY, NO CODE)

Backend:
- `backend/ai_providers/model_presets.py` — new, preset registry.
- `backend/ai_providers/groq_provider.py`, `cerebras_provider.py`, `phi3_provider.py` —
  add optional model-override parameter to `complete()`.
- `backend/ai_orchestrator.py` — add optional `model_key` parameter to
  `create_chat_completion`; resolve preset and bypass the chain when supplied.
- `backend/services.py` — add optional `model_key` parameter to `procure_agent`; forward
  to its own `create_chat_completion` calls; leave `_try_answer_data_query`'s spec call
  on the default chain.
- `backend/main.py` — add optional `model_key` field to `ConversationMessage`; pass
  through in the `/api/chat` handler.

Frontend:
- `src/config/modelOptions.js` — new, holds the two `{ key, label }` entries.
- `src/services/api.js` — `sendChat` accepts and forwards the selected model key.
- `src/components/ProcurementAssistant.jsx` — add the selector UI near the input row;
  hold selection in state (persisted); pass it into `sendChat`; optionally display the
  resolved model name on each response via `MessageBubble`.

---

## BACKWARD COMPATIBILITY REQUIREMENTS

- Every existing caller of `create_chat_completion` and `procure_agent` that doesn't pass
  `model_key` must produce byte-identical behavior to today — RFQ generation, report
  generation, insights generation, `excel_analyzer.py`'s standalone analysis functions,
  all currently call these without a model key and must keep working unmodified.
- The `/api/chat` request schema change must be additive-only (`Optional`, defaulted to
  `None`) so older cached frontend bundles hitting a newly-deployed backend don't break.

---

## EDGE CASES TO HANDLE EXPLICITLY

- Chosen preset's provider not configured (missing API key) or the call errors — decide
  and implement one clear behavior (surfaced error, not a silent different-model answer).
- User switches models mid-conversation — confirm whether conversation history
  (`session_state['conversation_history']`) should be shared across both models (likely
  yes, it's the same conversation) or whether switching should be visible to the user in
  the transcript.
- Preset registry lookup on an unknown/stale `model_key` (e.g. old frontend cached a key
  that was later renamed in the registry) — should fail clearly, not silently fall back
  to the default chain and mislabel the response.

---

## VERIFICATION CHECKLIST

- Confirm both presets independently answer the same test question with visibly
  different model output/latency, proving the key is actually reaching a different
  provider/model rather than both resolving to the same one.
- Confirm every non-chat endpoint (RFQ, report, insights, analyze, query) still works
  with zero request changes — regression check for the backward-compatibility
  requirement above.
- Confirm the numeric-grounding retry logic still fires and still uses the
  user-selected model for its correction attempts (not silently reverting to the
  default chain mid-retry).
- Confirm switching the selector mid-session updates subsequent answers without needing
  a page reload, and that the stored preference survives a reload.
