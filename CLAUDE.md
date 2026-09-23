# Bourse — notes for Claude

Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) before any non-trivial change.
It covers the request pipeline, agent graph, auth, data model and hosting.

## Layout

- `backend/main.py` — FastAPI app: auth, SSE `/api/chat`, persistence, rate limiting.
- `backend/agents/` — the LangGraph desk: `supervisor` routes → specialists fan out
  in parallel → `synthesizer` merges. Wiring lives in `graph.py`.
- `frontend/src/ChatPage.tsx` — the app; everything else in `src/` is small.
- `supabase/migrations/` — schema and RLS.

## Commands

```bash
cd backend && pytest        # stubs LLM/DB/yfinance in conftest.py — no network, no keys
cd frontend && npm run test
```

## Things that are easy to get wrong

- **Two OpenAI keys, deliberately.** `OPENAI_API_KEY` is the Thesys key
  (`sk-th-…`) for the synthesizer; `DESK_OPENAI_API_KEY` is the real OpenAI key
  for the supervisor and specialists, and must be passed explicitly — see
  `agents/models.py`. Collapsing them 401s.
- **The synthesizer must stay on Thesys.** Its output *is* the C1 DSL the
  frontend renders; any other model breaks the UI.
- **Scope every DB query by `user['id']`.** The backend connects as
  `service_role`, which bypasses RLS — the query is the access control.
- **Only synthesizer text gets persisted.** Status lines and stream-error text
  are deliberately kept out of `chunks` in `main.py`.
- **Tools never raise on user input** — they return a "no data" string so the
  agent can retry with an exchange suffix. Keep that contract.
- Everything Supabase-related degrades gracefully when env vars are unset;
  local dev and tests rely on that. Don't make it required.
