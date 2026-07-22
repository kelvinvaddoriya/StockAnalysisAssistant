# Bourse

A full-stack AI stock-analysis assistant. Ask a question in plain English — a small desk of specialist agents fans out over live market data, a synthesizer merges their findings, and the answer streams back as rich, rendered UI.

> **Looking for how it actually works?** See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — request pipeline, agent graph, auth, data model, hosting topology, CI/CD.

---

## How it works

The backend runs a LangGraph **multi-agent desk** rather than a single agent:

```
supervisor  →  [ fundamentals ‖ news ‖ market ]  →  synthesizer
```

- **Supervisor** (`gpt-4o-mini`) reads the question and routes it to the minimal set of specialists — possibly none, for a greeting or a general concept question.
- **Specialists** are `create_react_agent` ReAct loops, each with its own slice of the `yfinance` toolbelt, running in parallel and writing a findings note to graph state.
- **Synthesizer** (Thesys-routed GPT-5) merges the notes, cross-checks the figures, and emits C1 DSL — the renderable UI the frontend draws.

| Tool | Used by | What it does |
|---|---|---|
| `get_stock_price` | market | Current closing price for a ticker |
| `get_historical_stock_price` | market, fundamentals | Price history between two dates |
| `get_balance_sheet` | fundamentals | Balance sheet data |
| `get_stock_news` | news | Recent news articles |

Only synthesizer tokens reach the browser; specialist chatter and tool JSON are filtered out and surfaced as ephemeral "Analysing fundamentals…" status lines. Multi-turn context lives in a LangGraph checkpointer — Postgres-backed in production, in-memory locally.

The frontend is a React 19 + TypeScript SPA (Vite) built around the [`@thesysai/genui-sdk`](https://www.thesys.dev/) `C1Chat` component. Auth and chat history are backed by Supabase.

---

## Tech stack

**Backend**
- Python 3.11 · FastAPI + Uvicorn (port `8888`), SSE streaming
- LangGraph `StateGraph` — supervisor / specialists / synthesizer
- Two model tiers: Thesys-routed GPT-5 (synthesizer) + OpenAI `gpt-4o-mini` (supervisor, specialists)
- `yfinance` — market data
- Supabase (`service_role`) — auth verification + chat persistence
- `langgraph-checkpoint-postgres` — durable conversation memory

**Frontend**
- React 19 + TypeScript, Vite (port `3000`, proxies `/api/*` → `localhost:8888`)
- `@thesysai/genui-sdk` — streaming chat UI
- `@supabase/supabase-js` — login/signup direct from the browser
- Vitest + Testing Library

**Hosting** — Render (backend), Vercel (frontend), Supabase (auth + Postgres). All free tier.

---

## Project structure

```
StockAnalysisAssistant/
├── backend/
│   ├── main.py              # FastAPI app, auth, SSE endpoint, persistence
│   ├── agents/
│   │   ├── graph.py         # StateGraph wiring + fan-out edges
│   │   ├── supervisor.py    # Cheap router → `route` in state
│   │   ├── specialists.py   # ReAct sub-agents + per-domain tool slices
│   │   ├── synthesizer.py   # Merge + self-check → C1 DSL
│   │   ├── tools.py         # yfinance tools
│   │   ├── prompts.py       # System prompts
│   │   ├── models.py        # Two-tier model clients / API keys
│   │   └── state.py         # DeskState TypedDict
│   ├── tests/               # pytest (34 tests, desk + DB mocked)
│   ├── requirements.txt     # Also pyproject.toml + uv.lock (uv is the prod path)
│   └── pytest.ini
├── frontend/
│   ├── src/
│   │   ├── App.tsx          # Auth routing (login vs chat)
│   │   ├── ChatPage.tsx     # Sidebar, theme, C1Chat, processMessage
│   │   ├── LoginPage.tsx    # Login / register
│   │   ├── SettingsPage.tsx # Profile (display name, avatar)
│   │   ├── supabase.ts      # Supabase client + authedFetch
│   │   ├── utils.ts
│   │   └── __tests__/       # vitest
│   ├── vite.config.ts
│   └── package.json
├── supabase/migrations/     # chats + messages tables, RLS policies
├── docs/ARCHITECTURE.md
├── render.yaml              # Backend service definition (Render blueprint)
└── .github/workflows/python-app.yml
```

---

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- A Thesys API key and an OpenAI API key
- A Supabase project (optional locally — without it, auth and chat history are disabled)

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
python main.py                # http://localhost:8888
```

With live reload:

```bash
uvicorn main:app --host 0.0.0.0 --port 8888 --reload
```

With [uv](https://github.com/astral-sh/uv) — this is what Render uses, and it installs from the lockfile:

```bash
cd backend
uv sync --frozen
uv run python main.py
```

### Frontend

```bash
cd frontend
npm install
npm run dev                   # http://localhost:3000
```

### Environment variables

`backend/.env`:

```
OPENAI_API_KEY=sk-th-...        # Thesys-routed key — synthesizer
DESK_OPENAI_API_KEY=sk-proj-... # Real OpenAI key — supervisor + specialists
SUPABASE_URL=...                # optional locally
SUPABASE_KEY=...                # service_role JWT — never ship to the browser
```

Root `.env` (Vite reads it via `envDir: '..'`):

```
VITE_SUPABASE_URL=...
VITE_SUPABASE_ANON_KEY=...      # public anon key, baked into the bundle
```

Production-only vars (`DATABASE_URL`, `ALLOWED_ORIGINS`, `VITE_API_BASE`) are set in the Render and Vercel dashboards and are deliberate no-ops locally. Full table in [`docs/ARCHITECTURE.md` §8](docs/ARCHITECTURE.md).

> The two keys are not interchangeable. `OPENAI_API_KEY` must be the Thesys key; relying on the default env lookup for the specialists would grab it and 401 against OpenAI — hence the separate `DESK_OPENAI_API_KEY`.

---

## API

All `/api/chat*` endpoints require `Authorization: Bearer <supabase access_token>`.

| Endpoint | Purpose |
|---|---|
| `POST /api/chat` | Send a message, receive an SSE stream |
| `GET /api/chats` | List the caller's threads |
| `GET /api/chats/{thread_id}` | Fetch one thread's messages |
| `DELETE /api/chats/{thread_id}` | Delete a thread |
| `GET /api/health` | Liveness (unauthenticated). `?deep=1` also probes Supabase |

**`POST /api/chat` request body:**

```json
{
  "prompt": {
    "content": "What is the current price of AAPL?",
    "id": "<client-generated-id>",
    "role": "user"
  },
  "threadId": "<thread-id>",
  "responseId": "<response-id>"
}
```

**Response:** `text/event-stream`. Interactive docs: [http://localhost:8888/docs](http://localhost:8888/docs)

---

## Tests

```bash
cd backend && pytest           # 34 tests — desk graph and DB are mocked
cd frontend && npm run test    # vitest
```

## Frontend scripts

```bash
npm run dev            # Dev server on :3000
npm run build          # tsc -b + production build
npm run preview        # Preview the production build
npm run lint           # ESLint
npm run test           # Vitest (single run)
npm run test:coverage  # Vitest with coverage
```

---

## Deployment

Push to `main` — Render and Vercel both auto-deploy from their own Git integrations, so no cloud credentials live in CI.

| What | Where | Config |
|---|---|---|
| Backend | Render web service (`bourse-backend`, frankfurt) | `render.yaml`; secrets in the Render dashboard |
| Frontend | Vercel (Hobby, root dir `frontend/`) | Vercel dashboard |
| Auth + DB | Supabase | `supabase/migrations/` |

GitHub Actions ([`python-app.yml`](.github/workflows/python-app.yml)) runs flake8 on `backend/` for every push and PR to `main`. It has no deploy rights.

Two things worth knowing before you touch deployment: the free Render tier spins down after ~15 minutes idle, so the first request after a lull pays a 30–60s cold start; and Vercel preview deployments get unique URLs that aren't in the backend's `ALLOWED_ORIGINS`, so they'll fail CORS. See [`docs/ARCHITECTURE.md` §6–§7](docs/ARCHITECTURE.md).
