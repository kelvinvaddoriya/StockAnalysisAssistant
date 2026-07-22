# Bourse — Architecture

How the pieces fit together at runtime, in storage, and in deployment. Companion to the README (which focuses on local setup).

---

## 1. System overview

Bourse is a three-tier stack: a React SPA, a FastAPI backend that wraps a multi-agent LangGraph "analyst desk", and Supabase for auth + chat persistence. The SPA and the API are hosted separately (Vercel and Render), so the browser talks to two origins and the API is CORS-enabled.

```
┌──────────────┐
│   Browser    │
│  (React SPA) │
└──┬────────┬──┘
   │        │
   │ /*     │ /api/*  (VITE_API_BASE, cross-origin + CORS)
   ▼        ▼
┌──────────┐  ┌────────────────────────┐
│  Vercel  │  │  Render web service    │
│  static  │  │  FastAPI + LangGraph   │
└──────────┘  └───────┬────────────────┘
   │                  │
   │ Supabase JS SDK  │ service_role JWT + DATABASE_URL
   │ (auth only)      │
   ▼                  ▼
┌──────────────────────────────┐
│ Supabase                     │
│  - auth.users                │
│  - chats / messages          │
│  - langgraph checkpoints     │
└──────────────────────────────┘
```

The browser also talks **directly** to Supabase for login/signup (using the public `anon` key baked into the build). It never talks to Supabase for chat data — those queries go through the backend, which uses the secret `service_role` key.

---

## 2. Tech stack reference

| Layer | Tech | Where |
|---|---|---|
| Frontend SPA | React 19 + Vite + TypeScript | `frontend/` |
| Chat UI component | `@thesysai/genui-sdk` (`C1Chat`) | `frontend/src/ChatPage.tsx` |
| Frontend hosting | Vercel (Hobby), Vite preset | root dir `frontend/` |
| Backend API | FastAPI + Uvicorn (Python 3.11) | `backend/main.py` |
| Backend hosting | Render free web service | `render.yaml`, `bourse-backend`, frankfurt |
| Agent framework | LangGraph `StateGraph` — multi-agent desk | `backend/agents/graph.py` |
| Specialists | `create_react_agent` per domain (fundamentals / news / market) | `backend/agents/specialists.py` |
| LLMs | Synthesizer: Thesys-routed GPT-5; supervisor + specialists: OpenAI `gpt-4o-mini` | `backend/agents/models.py` |
| Market data tools | `yfinance` | `backend/agents/tools.py` |
| Auth + DB | Supabase | external (`bfggkbsjnxyptrfotrjc`) |
| CI/CD | Render + Vercel Git integration (auto-deploy on push to `main`) | `render.yaml` / Vercel dashboard |
| Lint CI | GitHub Actions (flake8) | `.github/workflows/python-app.yml` |

---

## 3. The hot path: one chat message, end to end

This is the most important diagram. It shows what happens when a logged-in user types "Should I buy RELIANCE.NS?" and hits send.

```
Browser          Render / FastAPI       Desk graph (LangGraph)                       yfinance     Supabase
   │                    │                    │                                          │            │
   │ POST /api/chat     │                    │                                          │            │
   │ Authorization:Bearer                    │                                          │            │
   ├───────────────────►│ require_user ──────┼──────────────────────────────────────────────────────►│
   │                    │ ◄ user_id          │                                          │   ◄ user   │
   │                    │ check thread owner ─┼──────────────────────────────────────────────────────►│
   │                    │                     │                                         │            │
   │                    │ desk.stream(        │                                         │            │
   │                    │   stream_mode=      │  ┌── supervisor (gpt-4o-mini) ──┐       │            │
   │                    │   ['updates',       ├─►│  route = [fundamentals,       │       │            │
   │                    │    'messages'])     │  │           news, market]       │       │            │
   │ ◄ <thinkitem> ─────┤ ◄ updates{route} ───┤  └───────────────┬───────────────┘       │            │
   │   status events    │                     │      fan-out (parallel)                  │            │
   │                    │                     │  ┌────────────┐┌────────┐┌──────────┐    │            │
   │                    │                     │  │fundamentals││ news   ││ market   │──tools──►│      │
   │                    │                     │  │ (4o-mini)  ││(4o-mini)│(4o-mini) │◄─ data ─┤      │
   │                    │                     │  └─────┬──────┘└───┬────┘└────┬─────┘    │            │
   │                    │                     │        └─── findings → state ──┘         │            │
   │                    │                     │  ┌── synthesizer (Thesys GPT-5) ──┐      │            │
   │                    │                     │  │ merge + self-check → C1 DSL    │      │            │
   │ ◄ SSE <content> ───┤ ◄ messages{synth} ──┤  └────────────────────────────────┘      │            │
   │ C1Chat renders     │  (only synthesizer  │                                          │            │
   │   thinkitems→answer│   tokens forwarded) │                                          │            │
   │                    │ background_task:    │                                          │            │
   │                    │ _save_to_db(synth   ├──────────────────────────────────────────────────────►│
   │                    │   text only)        │                                          │ INSERT msgs│
```

The supervisor may also return an **empty route** (greeting, capability question, general concept) — the graph then skips the specialists and goes straight to the synthesizer, which answers from general knowledge. A bare price lookup fast-paths to a single specialist (`[market]`) rather than the full desk.

### What each component contributes

**Browser → Render.** The frontend calls `/api/*` paths (`frontend/src/ChatPage.tsx`), which `authedFetch` rewrites to absolute URLs against `VITE_API_BASE`. That's a cross-origin request, so the backend's CORS middleware must list the SPA's origin in `ALLOWED_ORIGINS`. In local dev `VITE_API_BASE` is left unset and Vite's dev server proxies `/api` to `localhost:8888` instead.

**`processMessage` + `authedFetch`.** Instead of `C1Chat`'s default `apiUrl`, we pass a `processMessage` callback (`ChatPage.tsx:14`) that pulls the current Supabase session, attaches `Authorization: Bearer <access_token>`, and POSTs to `/api/chat`. The `authedFetch` helper in `frontend/src/supabase.ts:11` is reused for all four `/api/*` calls.

**FastAPI `require_user` dependency.** Every `/api/chats*` endpoint depends on `require_user` (`backend/main.py:209`). It strips the Bearer token, calls `db.auth.get_user(token)` against Supabase, and returns `{id, email}`. 401 if missing/invalid. 503 if the backend has no DB configured.

**Thread ownership check.** Before spending LLM tokens, `chat()` looks up the existing thread's `user_id` and 404s if it belongs to someone else (`main.py:_chat_owner`). New threads pass through; on `_save_to_db` they get inserted with the requesting user's id.

**The desk graph.** `build_desk_graph` (`backend/agents/graph.py`) compiles a LangGraph `StateGraph`: `supervisor → [fundamentals ‖ news ‖ market] → synthesizer`. The supervisor (`agents/supervisor.py`) is a cheap `gpt-4o-mini` router that picks the minimal set of specialists and writes `route` into state. Its conditional edge fans out to exactly those specialists in parallel; they each run their own `create_react_agent` ReAct loop over a slice of the `yfinance` toolbelt (`agents/specialists.py`) and write a findings note to their own state key. The synthesizer (`agents/synthesizer.py`, Thesys GPT-5) merges the notes, applies a self-check (cross-referencing figures, flagging disagreements/gaps), and emits the C1 DSL. Conversation state per `thread_id` lives in a LangGraph checkpointer via the `messages` channel (`add_messages` reducer) — Postgres-backed when `DATABASE_URL` is set, in-memory otherwise (see §10). The supervisor resets the per-turn findings scratch each turn so a specialist that ran last turn can't leak stale data into this one.

**Two model tiers, two keys.** The synthesizer stays on the Thesys-routed C1 model (its output *is* the renderable DSL), authenticated by `OPENAI_API_KEY` (the `sk-th-…` Thesys key). The supervisor and the three specialists run on real OpenAI `gpt-4o-mini` to keep the 3-wide fan-out cheap, authenticated by a separate `DESK_OPENAI_API_KEY` (`sk-proj-…`) passed explicitly in `agents/models.py` — relying on the default env lookup would grab the Thesys key and 401 against OpenAI.

**SSE streaming.** `chat()` runs `desk.stream(stream_mode=['updates', 'messages'])` (`main.py`). The `updates` events let it emit an ephemeral `<thinkitem>` status line per specialist the moment the supervisor routes ("Analysing fundamentals", …); the `messages` events stream LLM tokens, but only those tagged `langgraph_node == 'synthesizer'` reach the user — specialist findings and tool JSON are filtered by node name. C1Chat renders the think-items live and drops them from the saved message. The endpoint returns `StreamingResponse(..., media_type='text/event-stream')` with `X-Accel-Buffering: no`, which tells nginx-based proxies (Render's included) to pass tokens through unbuffered rather than accumulating the whole response. If streaming ever regresses to "long pause, then everything at once", that header is the first thing to check.

**Background save.** `BackgroundTasks` runs `_save_to_db` after the stream finishes (`main.py:save`). Only the synthesizer's tokens are accumulated into the closure-captured `chunks` list — the ephemeral status think-items are streamed but never persisted, so they don't replay on reload. The save respects ownership: if the thread already exists and the owner doesn't match, it refuses to write.

---

## 4. Authentication

```
Browser                 Supabase                  Backend
   │                       │                         │
   │ signInWithPassword    │                         │
   ├──────────────────────►│                         │
   │ ◄ session {access_    │                         │
   │   token, refresh_     │                         │
   │   token, user…}       │                         │
   │ stored in localStorage│                         │
   │                       │                         │
   │ /api/chats            │                         │
   │ Authorization: Bearer │                         │
   ├──────────────────────────────────────────────►  │
   │                       │                         │ db.auth.get_user(token)
   │                       │ ◄────────────────────── │
   │                       │ {user}                  │
   │                       │ ──────────────────────► │
   │ ◄ 200 [chats…]                                  │
```

- Frontend uses `VITE_SUPABASE_ANON_KEY` — the public `anon` JWT. Designed to be in the browser.
- Backend uses `SUPABASE_KEY` set to the `service_role` JWT. Bypasses RLS so the backend can enforce ownership in application code. **Never** ship this to the browser.
- Access tokens are short-lived (1 hr default). `@supabase/supabase-js` refreshes them transparently using the refresh token.

---

## 5. Data model

### Tables (`supabase/migrations/`)

**`chats`**
| Column | Type | Notes |
|---|---|---|
| `id` | `uuid PK` | Client-generated `crypto.randomUUID()` |
| `title` | `text` | First ~50 chars of opening message, derived in `extract_title` |
| `user_id` | `uuid NOT NULL` | FK → `auth.users(id)` ON DELETE CASCADE |
| `created_at` | `timestamptz` | default `now()` |
| `updated_at` | `timestamptz` | refreshed on each new message |

**`messages`**
| Column | Type | Notes |
|---|---|---|
| `id` | `uuid PK` | |
| `chat_id` | `uuid NOT NULL` | FK → `chats(id)` ON DELETE CASCADE |
| `role` | `text` | `user` or `assistant` |
| `content` | `text` | Full message body, including thesys component JSON for assistant turns |
| `created_at` | `timestamptz` | |

### Row-level security

RLS is enabled on both tables with per-user policies (`supabase/migrations/20260524023000_scope_chats_per_user.sql`):

- `chats`: SELECT/INSERT/UPDATE/DELETE only where `auth.uid() = user_id`.
- `messages`: access only via parent chat ownership (`EXISTS (SELECT 1 FROM chats WHERE chats.id = messages.chat_id AND chats.user_id = auth.uid())`).

The backend uses `service_role` which bypasses RLS — these policies are **defense in depth** so that if anything ever queries the DB with an end-user JWT (e.g. a future direct-from-frontend feature), it can't see cross-user data.

---

## 6. Hosting infrastructure

Everything runs on free tiers. There is no cloud account to manage beyond the three dashboards below — the project was migrated off AWS (Elastic Beanstalk + S3 + CloudFront) because the always-on EC2 instance and distribution weren't worth their cost for this traffic level.

```
      ┌──────────────────────────┐        ┌──────────────────────────────┐
      │  Vercel (Hobby)          │        │  Render (free web service)   │
      │  ─ root dir: frontend/   │        │  ─ bourse-backend, frankfurt │
      │  ─ Vite preset:          │        │  ─ Python 3.11               │
      │    SPA fallback + asset  │        │  ─ uvicorn main:app :$PORT   │
      │    hashing/caching       │        │  ─ health: /api/health       │
      │  ─ TLS + CDN included    │        │  ─ TLS included              │
      └──────────────────────────┘        └──────────────────────────────┘
                                                      │
                                                      ▼
                                          ┌──────────────────────────────┐
                                          │  Supabase (free)             │
                                          │  auth + chats + checkpoints  │
                                          └──────────────────────────────┘
```

### Why this shape

- **Split origins, explicit CORS.** Unlike the old CloudFront setup, the SPA and API are on different hosts. The frontend prefixes `/api/*` calls with `VITE_API_BASE` (`frontend/src/supabase.ts`), and the backend allows the SPA's origin via `ALLOWED_ORIGINS` (`backend/main.py`). A Vercel rewrite proxying `/api/*` would restore same-origin, but it inserts a proxy hop in front of a long-lived SSE stream — not worth the buffering and timeout risk.
- **Free tier means cold starts.** Render spins the service down after ~15 minutes idle; the next request pays ~30–60s to wake it. This is the main UX cost of leaving AWS.
- **Durable checkpointer is not optional here.** Because the process dies on every spin-down, agent memory must live outside it — see §10.
- **Deploys need no secrets in CI.** Render and Vercel both pull from GitHub directly, so there is no deploy role, no OIDC provider, and no credentials to rotate.

### Config

| Resource | Where |
|---|---|
| Backend service definition | `render.yaml` (repo root) |
| Backend secrets | Render dashboard (`sync: false` keys in `render.yaml`) |
| Frontend build + env | Vercel dashboard (root dir `frontend/`, Vite preset) |

---

## 7. CI/CD

```
git push origin main
      │
      ├── changed under backend/**   ──► Render auto-deploy
      │                                    build:  pip install uv && uv sync --frozen --no-dev
      │                                    start:  uv run uvicorn main:app --port $PORT
      │                                    gate:   /api/health must return 200
      │
      ├── changed under frontend/**  ──► Vercel auto-deploy
      │                                    build:  npm ci && npm run build
      │                                    output: dist/  (VITE_* env from dashboard)
      │
      └── changed under backend/**   ──► .github/workflows/python-app.yml
                                           flake8 lint (no deploy rights)
```

Both platforms watch the repo through their own Git integration, so `main` is the only deploy trigger and GitHub Actions holds no cloud credentials at all.

### Preview deployments and CORS

Vercel gives every preview deployment a unique URL, which won't be in the backend's `ALLOWED_ORIGINS` allowlist and will therefore fail CORS. Production is the guaranteed-working path. If previews need to reach the API, switch the CORS middleware from `allow_origins` to `allow_origin_regex` matching the Vercel preview URL pattern.

---

## 8. Local development

```bash
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py                 # listens on :8888

# Frontend (separate terminal)
cd frontend
npm install
npm run dev                    # :3000, proxies /api/* to :8888
```

`.env` files (NOT committed):

- `backend/.env`: `OPENAI_API_KEY` (Thesys `sk-th-…` key for the synthesizer), `DESK_OPENAI_API_KEY` (real OpenAI `sk-proj-…` key for the supervisor + specialists), `SUPABASE_URL`, `SUPABASE_KEY`
- Root `.env`: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` (Vite picks them up via `envDir: '..'` in `vite.config.ts`)

### Full environment variable reference

| Variable | Tier | Required? | Notes |
|---|---|---|---|
| `OPENAI_API_KEY` | backend | yes | Thesys-routed key (`sk-th-…`) for the synthesizer |
| `DESK_OPENAI_API_KEY` | backend | yes | Real OpenAI key (`sk-proj-…`) for supervisor + specialists |
| `SUPABASE_URL` / `SUPABASE_KEY` | backend | no | `service_role` key. Unset → chat persistence disabled, app still runs |
| `DATABASE_URL` | backend | prod only | Supabase Postgres URI backing the checkpointer. Unset → in-memory, wiped on restart |
| `ALLOWED_ORIGINS` | backend | prod only | Comma-separated origins appended to the CORS allowlist. Unset locally — `localhost:3000` is always allowed |
| `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` | frontend build | yes | Public `anon` key; baked into the bundle |
| `VITE_API_BASE` | frontend build | prod only | Backend origin, e.g. `https://bourse-backend.onrender.com`. **Leave unset in dev** so the Vite proxy handles `/api` |

The four `prod only` rows are the ones that must be set in the Render and Vercel dashboards; all of them are deliberately no-ops locally.

Tests:

```bash
cd backend
pytest                         # 34 tests, mocks the desk + DB
```

Frontend tests:

```bash
cd frontend
npm run test                   # vitest
```

---

## 9. Adding things — quick references

### A new tool for the desk

`backend/agents/tools.py`. Decorate a function with `@tool('name', description='…')`. Then assign it to the right specialist's tool slice in `backend/agents/specialists.py` (`FUNDAMENTALS_TOOLS` / `NEWS_TOOLS` / `MARKET_TOOLS`) — the partition is what keeps each domain prompt honest. Return a string or a dict — never raise on user input, return a "no data" string so the specialist can recover. If the tool opens a genuinely new analysis angle, consider a new specialist instead (add a node + prompt + state key + a wire in `agents/graph.py`, and a `route` option in `agents/supervisor.py`).

### A new API endpoint

`backend/main.py`. Use `Depends(require_user)` to require auth. Always scope queries by `user['id']` even though `service_role` bypasses RLS — that's the line of defense, not RLS.

### A new frontend page

Add a route in `App.tsx` (currently a single-page conditional based on session). Use `authedFetch` from `./supabase` for any `/api/*` call. The Supabase JS client (`./supabase` default export) handles auth state changes via `supabase.auth.onAuthStateChange`.

### Schema changes

Add a new timestamped SQL file under `supabase/migrations/`. Run via Supabase Dashboard → SQL Editor (or `supabase db push` if you set up the CLI). RLS policies should always check `auth.uid()` even if your backend bypasses them with `service_role`.

### Changing backend service config

Edit `render.yaml` and push — Render picks up blueprint changes on the next deploy. Secrets are the exception: keys marked `sync: false` must be set in the Render dashboard and are deliberately absent from git.

### A new environment variable

Three places, depending on tier: backend runtime → add to `render.yaml` (`sync: false` if secret) *and* set it in the Render dashboard; frontend build → add to the Vercel dashboard with a `VITE_` prefix; local dev → `backend/.env` or the root `.env`. Document it in §8.

---

## 10. Things to know that aren't obvious from reading the code

- **Conversation memory lives in the checkpointer, and it has to be durable.** The frontend only ever sends the *latest* user turn (see `ChatPage.tsx`), so the checkpointer is the **only** place multi-turn context survives between requests — the `chats`/`messages` tables feed the UI, not the agent. Render's free tier stops the process after ~15 minutes idle, so an in-process saver would silently amnesia every returning user: they'd see their history rendered but the desk would have forgotten it. Hence `PostgresSaver` against Supabase when `DATABASE_URL` is set (`backend/main.py`), falling back to `InMemorySaver` for local dev and tests.
- **The Postgres pool needs `prepare_threshold=0`.** Supabase's connection pooler runs pgbouncer in transaction mode, which can't keep server-side prepared statements alive across checkouts. Without that setting (and `autocommit=True`) the checkpointer fails intermittently under concurrency rather than cleanly at startup.
- **The supervisor clears per-turn scratch.** Because the whole `DeskState` is checkpointed, findings from a specialist that ran last turn would otherwise linger. `supervisor_node` resets `fundamentals/news/market` to `None` at the start of every turn so the synthesizer only ever sees this turn's notes.
- **Specialist history carries C1 DSL.** The cheap-tier specialists receive the full conversation (so follow-ups like "what about its debt?" resolve), which includes the synthesizer's prior answers verbatim as C1 DSL. It works but is a little noisy for `gpt-4o-mini`; trimming history to plain text before handing it to the cheap tier is a cheap future refinement.
- **Health check (`/api/health`) is unauthenticated by design.** It reports liveness and whether a DB is configured — no PII, no chat data. The dependency probe (does Supabase actually answer, which tables exist) is opt-in via `?deep=1`, because Render polls the default path every few seconds and probing Supabase on each poll burned ~34k REST queries a day to tell us nothing that "the process is up" didn't. `render.yaml`'s `healthCheckPath` deliberately points at the cheap path.
- **`/api/debug-tokens` was removed** for security — it ran the LLM on caller-supplied input with no auth, making it a cost-abuse vector. Restore with care.
- **`frontend/deploy.ps1`** is a manual escape hatch. CI is the normal path; the script is for one-off pushes when you don't want to wait for CI.
- **The Supabase project URL (`https://bfggkbsjnxyptrfotrjc.supabase.co`) is not a secret.** It's in the frontend bundle. The anon JWT is also public-by-design. The only Supabase secret is the `service_role` JWT.
