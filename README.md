# Stock Analysis Assistant

A full-stack AI chatbot for exploring stock data. Ask questions in plain English — the agent picks the right tool, fetches live market data, and streams back an answer.

> **Looking for how it actually works?** See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — request pipeline, auth, data model, AWS topology, CI/CD.

---

## How it works

The backend runs a [LangGraph](https://github.com/langchain-ai/langgraph) ReAct agent that has access to four tools:

| Tool | What it does |
|---|---|
| `get_stock_price` | Current closing price for a ticker |
| `get_historical_stock_price` | Price history between two dates |
| `get_balance_sheet` | Balance sheet data |
| `get_stock_news` | Recent news articles |

The agent decides which tools to call based on your message, streams its response over SSE, and maintains conversation context per thread via an in-memory checkpointer.

The frontend is a React + TypeScript app built with Vite. It wraps the [`@thesysai/genui-sdk`](https://www.thesys.dev/) `C1Chat` component which handles the streaming chat UI and renders rich structured responses.

---

## Tech stack

**Backend**
- Python 3.11+
- FastAPI — HTTP server, SSE streaming
- LangGraph — ReAct agent orchestration
- LangChain / `langchain-openai` — model client
- yfinance — market data
- Uvicorn — ASGI server (port `8888`)

**Frontend**
- React 19 + TypeScript
- Vite (port `3000`, proxies `/api/*` → `localhost:8888`)
- `@thesysai/genui-sdk` — streaming chat UI

---

## Project structure

```
StockAnalysisAssistant/
├── backend/
│   ├── main.py          # FastAPI app + LangGraph agent + tools
│   ├── .env             # Secrets (never commit)
│   ├── pyproject.toml   # Python deps (uv)
│   └── uv.lock
├── frontend/
│   ├── src/
│   │   ├── App.tsx       # Auth routing (login vs chat)
│   │   ├── ChatPage.tsx  # Sidebar + C1Chat component
│   │   ├── LoginPage.tsx # Login / register form
│   │   └── App.css
│   ├── vite.config.ts
│   └── package.json
├── supabase/
│   └── migrations/      # Postgres schema (chats + messages tables)
└── .github/
    └── workflows/
        └── python-app.yml
```

---

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- An API key for the model provider (set as `OPENAI_API_KEY`)

### Backend

```bash
# from repo root
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r backend/requirements.txt
```

Create `backend/.env`:

```
OPENAI_API_KEY=your_key_here
```

Start the server:

```bash
python backend/main.py
# Listening on http://localhost:8888
```

Or with live reload:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8888 --reload
```

If you prefer [uv](https://github.com/astral-sh/uv):

```bash
cd backend
uv sync
uv run python main.py
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# Open http://localhost:3000
```

---

## API

### `POST /api/chat`

Send a message and receive a streaming response.

**Request body:**
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

**Response:** `text/event-stream` — raw token content streamed as it's generated.

Interactive API docs: [http://localhost:8888/docs](http://localhost:8888/docs)

---

## Frontend scripts

```bash
npm run dev      # Start dev server on :3000
npm run build    # Type-check + production build
npm run preview  # Preview the production build
npm run lint     # Run ESLint
```

---

## CI

GitHub Actions runs on every push and pull request to `main`:

- **Lint** — `flake8` checks `backend/` for syntax errors and undefined names
- Python 3.11

See [`.github/workflows/python-app.yml`](.github/workflows/python-app.yml).
