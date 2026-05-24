# Bourse — Architecture

How the pieces fit together at runtime, in storage, and in deployment. Companion to the README (which focuses on local setup).

---

## 1. System overview

Bourse is a three-tier stack: a React SPA, a FastAPI backend that wraps a LangGraph agent, and Supabase for auth + chat persistence. Everything sits behind a single CloudFront distribution so the browser sees one origin.

```
┌──────────────┐    HTTPS     ┌──────────────────────┐
│   Browser    │ ───────────► │  CloudFront          │
│  (React SPA) │              │  d3mukf9pb7pzyg.…    │
└──────┬───────┘              └─────┬────────────┬───┘
       │                            │            │
       │ Supabase JS SDK            │ /*         │ /api/*
       │ (auth only)                ▼            ▼
       │                  ┌───────────────┐  ┌────────────────────────┐
       │                  │   S3 bucket    │  │ Elastic Beanstalk EC2 │
       │                  │ bourse-frontend│  │ FastAPI + LangGraph   │
       │                  └───────────────┘  └─────────┬──────────────┘
       │                                               │
       ▼                                               │ service_role JWT
┌──────────────────────────┐                           ▼
│ Supabase (auth + chats)  │ ◄─────────────────────────┘
│  - auth.users (Supabase) │
│  - chats / messages      │
└──────────────────────────┘
```

The browser also talks **directly** to Supabase for login/signup (using the public `anon` key baked into the build). It never talks to Supabase for chat data — those queries go through the backend, which uses the secret `service_role` key.

---

## 2. Tech stack reference

| Layer | Tech | Where |
|---|---|---|
| Frontend SPA | React 19 + Vite + TypeScript | `frontend/` |
| Chat UI component | `@thesysai/genui-sdk` (`C1Chat`) | `frontend/src/ChatPage.tsx` |
| Frontend hosting | S3 (private) + CloudFront + OAC | `bourse-frontend-218160094200` bucket |
| Backend API | FastAPI + Uvicorn (Python 3.11) | `backend/main.py` |
| Backend hosting | Elastic Beanstalk single-instance | `bourse-backend` env, `eu-central-1` |
| Agent framework | LangGraph `create_react_agent` | `backend/main.py:93` |
| LLM | Thesys-routed GPT-5 via `langchain-openai` `ChatOpenAI` | `backend/main.py:61` |
| Market data tools | `yfinance` | `backend/main.py:69`–`105` |
| Auth + DB | Supabase | external (`bfggkbsjnxyptrfotrjc`) |
| CI/CD | GitHub Actions + OIDC | `.github/workflows/deploy-*.yml` |

---

## 3. The hot path: one chat message, end to end

This is the most important diagram. It shows what happens when a logged-in user types "What is the price of RELIANCE.NS?" and hits send.

```
Browser                CloudFront         EB / FastAPI           LangGraph         yfinance       Supabase
   │                       │                  │                     │                │              │
   │ POST /api/chat        │                  │                     │                │              │
   │ Authorization: Bearer │                  │                     │                │              │
   ├──────────────────────►│                  │                     │                │              │
   │                       │  /api/* origin → │                     │                │              │
   │                       ├─────────────────►│                     │                │              │
   │                       │                  │ require_user        │                │              │
   │                       │                  │   → db.auth.get_user│                │              │
   │                       │                  ├─────────────────────┼────────────────┼─────────────►│
   │                       │                  │ ◄ user_id           │                │              │
   │                       │                  │                     │                │              │
   │                       │                  │ check thread owner  │                │              │
   │                       │                  ├─────────────────────┼────────────────┼─────────────►│
   │                       │                  │                     │                │              │
   │                       │                  │ agent.stream(…)     │                │              │
   │                       │                  ├────────────────────►│                │              │
   │                       │                  │                     │ tool call:     │              │
   │                       │                  │                     │ get_stock_price│              │
   │                       │                  │                     ├───────────────►│              │
   │                       │                  │                     │ ◄ 1432.5       │              │
   │                       │                  │                     │ model formats  │              │
   │                       │ ◄ SSE chunks ────┤ ◄ SSE chunks ───────┤ response       │              │
   │ ◄ SSE chunks (text/   │                  │                     │                │              │
   │   event-stream)       │                  │                     │                │              │
   │ C1Chat renders tokens │                  │                     │                │              │
   │                       │                  │ background_task:    │                │              │
   │                       │                  │ _save_to_db(…)      │                │              │
   │                       │                  ├─────────────────────┼────────────────┼─────────────►│
   │                       │                  │ upsert chat (with   │                │ INSERT chat  │
   │                       │                  │  user_id),          │                │ INSERT msgs  │
   │                       │                  │  insert msgs        │                │              │
```

### What each component contributes

**Browser → CloudFront → EB.** The frontend calls relative `/api/*` paths (`frontend/src/ChatPage.tsx`). CloudFront has two origins: `/*` → S3, `/api/*` → EB (HTTP, port 80). Same origin from the browser's perspective, so no CORS preflight.

**`processMessage` + `authedFetch`.** Instead of `C1Chat`'s default `apiUrl`, we pass a `processMessage` callback (`ChatPage.tsx:14`) that pulls the current Supabase session, attaches `Authorization: Bearer <access_token>`, and POSTs to `/api/chat`. The `authedFetch` helper in `frontend/src/supabase.ts:11` is reused for all four `/api/*` calls.

**FastAPI `require_user` dependency.** Every `/api/chats*` endpoint depends on `require_user` (`backend/main.py:209`). It strips the Bearer token, calls `db.auth.get_user(token)` against Supabase, and returns `{id, email}`. 401 if missing/invalid. 503 if the backend has no DB configured.

**Thread ownership check.** Before spending LLM tokens, `chat()` looks up the existing thread's `user_id` and 404s if it belongs to someone else (`main.py:_chat_owner`). New threads pass through; on `_save_to_db` they get inserted with the requesting user's id.

**LangGraph agent.** `create_react_agent` (`main.py:93`) drives a ReAct loop over four `@tool`-decorated functions wrapping `yfinance`. Conversation state per `thread_id` lives in an `InMemorySaver` checkpointer — so multi-turn context survives between requests, but only as long as the EB instance lives (a redeploy or restart wipes it).

**SSE streaming.** The endpoint returns `StreamingResponse(generate(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache, no-transform'})`. nginx on EB has `proxy_buffering off` configured in `.platform/nginx/conf.d/streaming.conf` so tokens reach CloudFront unbuffered. CloudFront's `/api/*` cache behavior uses the AWS-managed `CachingDisabled` policy and forwards everything except the `Host` header.

**Background save.** `BackgroundTasks` runs `_save_to_db` after the stream finishes (`main.py:save`). The full assistant text is in a closure-captured list. The save respects ownership: if the thread already exists and the owner doesn't match, it refuses to write.

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

## 6. AWS infrastructure

Account `218160094200`, primary region `eu-central-1` (CloudFront is global, ACM certs for CF must live in `us-east-1`).

```
                          ┌────────────────────────────────────────┐
                          │           CloudFront distribution      │
                          │           E2XQ3GPU9YS7D3               │
                          │                                        │
                          │  Default behavior   /api/* behavior    │
                          │  ─ S3 origin via    ─ EB origin (HTTP) │
                          │    OAC              ─ no caching       │
                          │  ─ Compress: on     ─ forwards all     │
                          │  ─ SPA fallback        except Host     │
                          │    403/404 → /                         │
                          │    index.html (200)                    │
                          └────────────────────────────────────────┘
                                  │                       │
                                  ▼                       ▼
                  ┌─────────────────────────┐  ┌─────────────────────────┐
                  │  S3 bourse-frontend-…   │  │  EB env bourse-backend  │
                  │  - private              │  │  - single-instance      │
                  │  - OAC reads only       │  │  - t3.micro             │
                  │  - versioning on        │  │  - Python 3.11 / AL2023 │
                  │  - public access block  │  │  - nginx → uvicorn:8000 │
                  └─────────────────────────┘  └─────────────────────────┘
```

### Why this shape

- **Single CloudFront, two origins.** Frontend hits `/api/*` as relative URLs → same origin → no CORS → no preflight tax.
- **OAC (Origin Access Control)** keeps the S3 bucket private. CloudFront signs requests with SigV4; the bucket policy only allows reads from the specific distribution ARN.
- **Single-instance EB** (no ALB) was the cheap choice for an MVP. The trade-off: HTTPS can't be terminated at a load balancer. We sidestep this because CloudFront terminates TLS at the edge and talks to EB over plain HTTP within AWS — the public never sees the EB origin directly.
- **`PriceClass_100`** on CloudFront (NA + EU only) is cheapest. Switch to `PriceClass_All` if you ever care about APAC latency.

### Key files for AWS config

| Resource | File |
|---|---|
| EB platform + env | `backend/.elasticbeanstalk/config.yml` |
| Python platform config | `backend/.ebextensions/01_python.config` |
| nginx tuning for SSE | `backend/.platform/nginx/conf.d/streaming.conf` |
| EB process command | `backend/Procfile` |
| Files excluded from EB deploy zip | `backend/.ebignore` |
| Frontend deploy script (local) | `frontend/deploy.ps1` |

---

## 7. CI/CD

```
git push origin main
      │
      ├── changed under backend/**  ──► .github/workflows/deploy-backend.yml
      │                                     │
      │                                     │ 1. checkout
      │                                     │ 2. setup-python + install awsebcli
      │                                     │ 3. configure-aws-credentials via OIDC
      │                                     │    (assumes github-actions-bourse-deploy)
      │                                     │ 4. write [eb-cli] credentials file
      │                                     │ 5. eb deploy bourse-backend
      │                                     ▼
      │                                  EB env redeployed
      │
      └── changed under frontend/** ──► .github/workflows/deploy-frontend.yml
                                            │
                                            │ 1. checkout
                                            │ 2. setup-node, npm ci
                                            │ 3. npm run build (with VITE_ secrets)
                                            │ 4. configure-aws-credentials via OIDC
                                            │ 5. aws s3 sync dist/ → bucket
                                            │ 6. aws s3 cp index.html (fix Content-Type
                                            │    + no-cache)
                                            │ 7. cloudfront create-invalidation /index.html
                                            ▼
                                         S3 + CF updated
```

### How OIDC works here

- GitHub Actions presents an OIDC token at job start. AWS trusts it because we created an `OpenIDConnectProvider` with thumbprint `6938fd4d…`.
- The role `github-actions-bourse-deploy` has a trust policy that *only* allows `repo:kelvinvaddoriya/StockAnalysisAssistant:ref:refs/heads/main`. PRs from forks, other branches, other repos — all rejected.
- The role has `AdministratorAccess-AWSElasticBeanstalk` (backend) + an inline policy scoped to the specific S3 bucket and CF distribution (frontend). No long-lived access keys anywhere.

### Why the EB workflow has the "write `[eb-cli]` profile" step

`backend/.elasticbeanstalk/config.yml` pins `profile: eb-cli`. boto3 with `profile_name='eb-cli'` only looks at `~/.aws/credentials`, not env vars. So we synthesize that profile from the env credentials `configure-aws-credentials` sets. Easier than rewriting `config.yml` per environment.

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

- `backend/.env`: `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`
- Root `.env`: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` (Vite picks them up via `envDir: '..'` in `vite.config.ts`)

Tests:

```bash
cd backend
pytest                         # 37 tests, mocks the agent + DB
```

Frontend tests:

```bash
cd frontend
npm run test                   # vitest
```

---

## 9. Adding things — quick references

### A new tool for the agent

`backend/main.py:69`. Decorate a function with `@tool('name', description='…')`. Add it to the `tools=[…]` list in `create_react_agent`. Return a string or a dict — never raise on user input, return a "no data" string so the agent can recover.

### A new API endpoint

`backend/main.py`. Use `Depends(require_user)` to require auth. Always scope queries by `user['id']` even though `service_role` bypasses RLS — that's the line of defense, not RLS.

### A new frontend page

Add a route in `App.tsx` (currently a single-page conditional based on session). Use `authedFetch` from `./supabase` for any `/api/*` call. The Supabase JS client (`./supabase` default export) handles auth state changes via `supabase.auth.onAuthStateChange`.

### Schema changes

Add a new timestamped SQL file under `supabase/migrations/`. Run via Supabase Dashboard → SQL Editor (or `supabase db push` if you set up the CLI). RLS policies should always check `auth.uid()` even if your backend bypasses them with `service_role`.

### Updating CloudFront behavior

Edit a JSON of the current config: `aws cloudfront get-distribution-config --id E2XQ3GPU9YS7D3 > cf.json`, modify, `aws cloudfront update-distribution --id E2XQ3GPU9YS7D3 --distribution-config file://cf.json --if-match <ETag from get-distribution-config>`. Wait 5–10 min for propagation.

---

## 10. Things to know that aren't obvious from reading the code

- **Conversation memory is in-process.** `InMemorySaver` means an EB restart loses every active conversation's context. For an MVP this is fine; if you scale to multi-instance or care about durability, swap in a persistent checkpointer (`langgraph.checkpoint.postgres` / `langgraph.checkpoint.sqlite`).
- **Health check (`/api/health`) is unauthenticated by design.** It only reports whether the DB connection works and which tables exist. No PII, no chat data.
- **`/api/debug-tokens` was removed** for security — it ran the LLM on caller-supplied input with no auth, making it a cost-abuse vector. Restore with care.
- **`frontend/deploy.ps1`** is a manual escape hatch. CI is the normal path; the script is for one-off pushes when you don't want to wait for CI.
- **The Supabase project URL (`https://bfggkbsjnxyptrfotrjc.supabase.co`) is not a secret.** It's in the frontend bundle. The anon JWT is also public-by-design. The only Supabase secret is the `service_role` JWT.
