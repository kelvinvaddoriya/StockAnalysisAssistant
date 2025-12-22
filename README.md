### Stock Analysis Assistant

A lightweight, two-tier app for exploring and analyzing stock data with an AI chat interface. The backend exposes an `API` that streams model-generated responses and can call tools for real-time market data. The frontend is a React app that provides a chat UI.

- Frontend: React + TypeScript + Vite
- Backend: FastAPI + LangChain + yfinance
- Data/tools: `yfinance` for prices, history, balance sheet, and news

> Note: The backend currently streams responses over Server-Sent Events (SSE) and uses an OpenAI-compatible API via LangChain’s `ChatOpenAI`.

---

### Features

- 📈 Get current and historical stock prices
- 📊 Fetch balance sheet data
- 📰 Retrieve recent news for a ticker
- 🤖 Chat interface that calls tools as needed
- 🔌 Dev proxy: Frontend `/api/*` requests are proxied to the backend

---

### Tech Stack

- Backend
  - Language: `Python (>=3.11)`
  - Frameworks/Libraries: `FastAPI`, `LangChain`, `langgraph`, `pydantic`, `python-dotenv`, `uvicorn`, `yfinance`
  - Entry point: `backend/main.py` (starts Uvicorn on port `8888`)
  - Package management: `pip` via top-level `requirements.txt` or `pyproject.toml` in `backend/` (also contains `uv.lock` for Astral’s `uv`)
- Frontend
  - Language: `TypeScript`
  - Frameworks/Tools: `React`, `Vite`, `@thesysai/genui-sdk`, `@crayonai/react-ui`
  - Dev server: `http://localhost:3000` with proxy to `http://localhost:8888`
  - Package manager: `npm` (repo contains `package-lock.json`)

---

### Requirements

- Python `3.11+`
- Node.js `18+` (recommended for Vite 7)
- An OpenAI-compatible API key in `OPENAI_API_KEY`

> Security note: Never commit real secrets. If sensitive values were committed previously, rotate them immediately and remove them from history.

---

### Quick Start

1) Backend (FastAPI)

```
# from repo root
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# create backend/.env (see Env Vars below)
# start the API
python backend\main.py
# The API will listen on http://localhost:8888
```

2) Frontend (React + Vite)

```
# from repo root
cd frontend
npm install
npm run dev
# Open http://localhost:3000
# Requests to /api/* are proxied to http://localhost:8888
```

---

### Environment Variables

Create a file `backend/.env` with at least:

```
OPENAI_API_KEY=your_api_key_here
```

Optional (present in repo but currently unused by the provided backend code — keep only if you plan to integrate them):

```
MONGO_URI=...
JWT_SECRET=...
JWT_ALGORITHM=HS256
```

> TODO: Confirm which provider the model is using (the code sets a custom `base_url` in `ChatOpenAI`). Document any provider-specific headers or additional environment variables if needed.

---

### How It Works

- The backend defines an agent with tools via LangChain:
  - `get_stock_price(ticker)`
  - `get_historical_stock_price(ticker, start_date, end_date)`
  - `get_balance_sheet(ticker)`
  - `get_stock_news(ticker)`
- Endpoint: `POST /api/chat`
  - Request body shape:

```
{
  "prompt": { "content": "AAPL price?", "id": "<client-id>", "role": "user" },
  "threadId": "<thread-id>",
  "responseId": "<response-id>"
}
```

  - Response: `text/event-stream` (SSE), streaming token content as it’s generated
- FastAPI interactive docs: http://localhost:8888/docs

---

### Scripts

- Frontend (`frontend/package.json`):
  - `npm run dev` — Start Vite dev server on `:3000`
  - `npm run build` — Type-check (`tsc -b`) and build for production
  - `npm run preview` — Preview production build locally
  - `npm run lint` — Run ESLint

- Backend:
  - Run directly: `python backend\main.py`
  - Alternative with reload (optional):

```
# if you prefer CLI-managed server
uvicorn backend.main:app --host 0.0.0.0 --port 8888 --reload
```

> Note: The code currently imports `CORSMiddleware` but doesn’t add it to the app. During development, the Vite proxy avoids CORS issues. Add CORS if you plan to call the API directly from browsers in production.

---

### Project Structure

```
StockAnalysisAssistant/
├─ backend/
│  ├─ main.py                 # FastAPI app, LangChain agent, /api/chat endpoint
│  ├─ .env                    # Environment variables (DO NOT COMMIT REAL SECRETS)
│  ├─ pyproject.toml          # Python metadata/deps (alternative to requirements.txt)
│  ├─ uv.lock                 # Lockfile for Astral’s uv (if using uv)
│  └─ __pycache__/
├─ frontend/
│  ├─ src/
│  │  ├─ App.tsx              # Chat UI using @thesysai/genui-sdk
│  │  └─ main.tsx
│  ├─ vite.config.ts          # Dev server proxy: /api -> http://localhost:8888
│  ├─ package.json
│  └─ package-lock.json
├─ requirements.txt           # Python deps (pip)
└─ README.md                  # This file
```

---

### Development Tips

- For Python dependencies, you can use either the root `requirements.txt` (pip) or `backend/pyproject.toml` (e.g., `uv`).
- If using Astral `uv`, you might prefer:

```
# inside backend/
uv sync
uv run python main.py
```

> TODO: Standardize on a single Python dependency workflow (pip vs uv) and document it.

---

### Testing

- No test suite is currently present in the repo.
- TODOs:
  - Add unit tests for tool functions (e.g., mock `yfinance`)
  - Add endpoint tests for `POST /api/chat` (e.g., with `httpx`/`pytest`)
  - Add frontend component tests (e.g., with `Vitest` + `React Testing Library`)

---

### Deployment

- Backend: Deploy the FastAPI app behind a reverse proxy (e.g., `uvicorn` or `gunicorn` with `uvicorn.workers.UvicornWorker`). Ensure environment variables are provided securely.
- Frontend: Build with `npm run build` and serve the static files from your preferred host/CDN.
- TODOs:
  - Add production CORS config if serving API to browsers without a proxy
  - Provide Dockerfiles or CI/CD workflows if desired

---

### Contributing

Contributions are welcome!

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit: `git commit -m "feat: add my feature"`
4. Push: `git push origin feature/my-feature`
5. Open a Pull Request

---

### License

- The previous README referenced MIT, but no `LICENSE` file is present in the repository.
- TODO: Add an explicit `LICENSE` file (MIT or your chosen license) and confirm the licensing in this README.

---

### Acknowledgements

- `FastAPI` for the backend
- `React` and `Vite` for the frontend
- `LangChain` and `langgraph` for agent orchestration
- `yfinance` for market data
- `@thesysai/genui-sdk` for the chat UI component