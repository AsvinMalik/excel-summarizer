# Procure.ai — AI-Powered Excel / MIS Analyzer

An AI assistant that understands real-world corporate Excel workbooks — multi-sheet MIS files with merged cells, stacked headers, and messy human-typed data. Upload a workbook, ask questions in plain English, and get answers grounded in the actual rows: the AI translates your question into a structured query, and **real pandas does the math** — numbers are never hallucinated.

## Key Features

- **Smart sheet routing** — a two-tier router picks the right sheet for each question (keyword scoring first with zero tokens, a tiny LLM call only when ambiguous)
- **Deterministic query engine** — sums, counts, filters, and group-bys run through pandas, never LLM arithmetic; text matching is whitespace/case-tolerant
- **Whole-workbook reports** — map-reduce per-sheet summaries, cached so repeat questions cost zero tokens
- **Target control** — choose Auto (AI routes), All sheets, or pin the sheet you're previewing
- **Multi-provider AI fallback chain** — runs entirely on free tiers or fully offline with a self-hosted model
- **Extras** — sheet preview grid, RFQ builder, PDF/DOCX report export

## Architecture

```
React + Vite + Tailwind (frontend, port 4173)
        │  REST
FastAPI + pandas (backend, port 8001)
        │
Provider chain: Groq → Ollama (local) → Cerebras → OpenRouter
```

---

## Getting Started

### Prerequisites

- **Python 3.10+**
- **Node.js 18+** (with npm)
- Optional but recommended: **[Ollama](https://ollama.ai)** for free, unlimited, self-hosted AI

### 1. Clone and install

```bash
git clone <your-repo-url>
cd "Excel File Summarizer"

# Frontend dependencies
npm install

# Backend dependencies
cd backend
pip install -r requirements.txt
```

### 2. Configure AI providers (API keys)

Copy the example env file and fill in your keys:

```bash
cd backend
cp .env.example .env
```

**Use the same providers this project already uses, in this priority order** — the fallback chain is built and tuned around them. All of them have free tiers:

| Priority | Provider | Key | Notes |
|----------|----------|-----|-------|
| 1 | **Groq** (primary cloud) | free at [console.groq.com](https://console.groq.com) | `llama-3.3-70b`, fast, 100k tokens/day free |
| 2 | **Ollama** (self-hosted, local) | no key needed | unlimited, offline, private — see below |
| 3 | **Cerebras** | free at [cloud.cerebras.ai](https://cloud.cerebras.ai) | cloud fallback |
| 4 | **OpenRouter** | free at [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys) | free models, rate-limited |

You don't need all of them — each layer is skipped automatically if unconfigured. Even one provider works. And you **can** swap in different providers or models later (the clients are OpenAI-compatible — usually just a base URL + model string change in `backend/ai_providers/`), but start with the defaults above: the routing, token budgets, and fallback logic are already calibrated for them.

### 3. Self-hosted AI with Ollama (recommended)

The pathway for self-hosting is **already built in** — no code changes needed. If you want zero cloud dependency, full data privacy, or you keep hitting free-tier rate limits:

```bash
# Install Ollama from https://ollama.ai, then:
ollama pull phi3
ollama serve
```

In `backend/.env`:

```env
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=phi3
PREFER_LOCAL_OLLAMA=true   # puts the local model FIRST in the chain — zero cloud quota used
```

With ~8 GB+ RAM you can use a stronger local model — just pull it and change one line:

```bash
ollama pull llama3.1:8b     # or qwen2.5:7b
```
```env
OLLAMA_MODEL=llama3.1:8b
```

### 4. Frontend environment

Create `.env` in the project root (or edit the existing one):

```env
VITE_API_BASE_URL=http://127.0.0.1:8001
```

Firebase settings (`VITE_FIREBASE_*`) are optional — only needed if you want login + chat history persistence.

### 5. Run it

```bash
# Terminal 1 — backend
cd backend
uvicorn main:app --port 8001

# Terminal 2 — frontend
npm run dev
```

Open the URL Vite prints (default `http://localhost:4173`), upload an Excel file, and start asking questions.

---

## Usage Tips

- **Target control** (above the chat input): leave on **Auto** for everyday use; switch to **All sheets** for cross-workbook reports; pin **Preview sheet** to lock the AI to the sheet you're viewing.
- Ask things like: *"summarize each sheet"*, *"customer wise revenue FY 24-25"*, *"key matters of the Ajay team"*, *"top 5 vendors by spend"*.
- Every numeric answer is computed by pandas from the full workbook on disk — not estimated from a text preview.

## Troubleshooting

- **"All AI providers unavailable" (503)** — free-tier rate limits hit; wait a few minutes, or enable Ollama (`PREFER_LOCAL_OLLAMA=true`) for unlimited local inference.
- **Slow answers with Ollama** — expected on CPU (30–120 s for `phi3`); cloud providers answer in ~1–2 s when available.
- **Backend won't start** — check Python ≥ 3.10 and rerun `pip install -r requirements.txt`.
- **Frontend can't reach backend** — make sure `VITE_API_BASE_URL` matches the port uvicorn is running on.

## Project Structure

- `backend/main.py` — FastAPI app: upload, chat, sheet-scope routing, snapshots
- `backend/sheet_router.py` — two-tier question→sheet router
- `backend/query_engine.py` — deterministic pandas query execution
- `backend/services.py` — LLM orchestration, prompts, grounding
- `backend/ai_providers/` — provider clients + fallback chain
- `src/components/ProcurementAssistant.jsx` — chat UI with Target control
- `src/components/SheetPreview.jsx` — paginated sheet preview grid
