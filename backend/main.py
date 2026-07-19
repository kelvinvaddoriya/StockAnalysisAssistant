import re
import os
import html
import atexit
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv
from pydantic import BaseModel

import uvicorn
from fastapi import FastAPI, BackgroundTasks, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from supabase import create_client, Client as SupabaseClient

# The multi-agent "analyst desk" — supervisor → specialists → synthesizer.
from agents.graph import build_desk_graph
from agents.state import SUPERVISOR, SYNTHESIZER

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger(__name__)

load_dotenv()

# ---------------------------------------------------------------------------
# Supabase — optional; if env vars are absent the app runs without persistence
# ---------------------------------------------------------------------------
_sb_url = os.getenv('SUPABASE_URL', '')
_sb_key = os.getenv('SUPABASE_KEY', '')
if _sb_url and _sb_key:
    db: SupabaseClient | None = create_client(_sb_url, _sb_key)
    log.info('Supabase connected: %s', _sb_url)
else:
    db = None
    log.warning('SUPABASE_URL / SUPABASE_KEY not set — chat history disabled')

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI()

def _clean_origin(raw: str) -> str:
    # Dashboard paste artifacts: surrounding quotes and a trailing slash both
    # produce a value that silently never matches, since CORS compares origins
    # byte-for-byte. Normalise rather than fail closed with no explanation.
    return raw.strip().strip('"').strip("'").rstrip('/')


_extra_origins = [c for o in os.getenv('ALLOWED_ORIGINS', '').split(',') if (c := _clean_origin(o))]
_origins = ["http://localhost:3000", "http://127.0.0.1:3000"] + _extra_origins
# Logged so a CORS failure can be diagnosed from the deploy log alone.
log.info('CORS allowlist: %s', _origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware('http')
async def _allow_timing(request, call_next):
    """Let the SPA read Resource Timing for its own API calls.

    Now that the SPA and API are on different origins, responseStart/transferSize
    are zeroed out in the browser unless the response opts in. Without this you
    cannot tell a slow server from a proxy buffering the SSE stream — the symptom
    looks identical from the client. Scoped to allowlisted origins only.
    """
    response = await call_next(request)
    origin = _clean_origin(request.headers.get('origin', ''))
    if origin and origin in _origins:
        response.headers['Timing-Allow-Origin'] = origin
    return response

# ---------------------------------------------------------------------------
# Analyst desk (multi-agent graph)
# ---------------------------------------------------------------------------
# Per-thread conversation memory lives in this checkpointer keyed on thread_id.
# It has to outlive the process: Render's free tier spins the service down after
# 15 minutes idle, and an in-process saver would drop the agent's context every
# time that happens — the user would still see their chat history (that comes
# from Supabase) but the desk would answer follow-ups with no memory of them.
# Falls back to in-memory when DATABASE_URL is unset, which keeps local dev and
# the test suite working without a database.
_db_url = os.getenv('DATABASE_URL', '')
if _db_url:
    from psycopg_pool import ConnectionPool
    from langgraph.checkpoint.postgres import PostgresSaver

    # Supabase's pooler runs pgbouncer in transaction mode, which cannot hold
    # server-side prepared statements across checkouts — hence prepare_threshold=0.
    _pool = ConnectionPool(
        conninfo=_db_url,
        max_size=5,
        kwargs={'autocommit': True, 'prepare_threshold': 0},
        open=True,                # explicit: implicit opening is deprecated
        # Supabase's pooler hangs up on idle connections, and Render's free tier
        # leaves the service idle for long stretches. Without `check` (which
        # defaults to None — no validation) the pool happily hands out a dead
        # socket and the next chat dies mid-stream with
        # "SSL error: unexpected eof while reading".
        check=ConnectionPool.check_connection,
        max_idle=120,             # recycle well before the pooler drops us
        max_lifetime=1800,
    )
    checkpointer = PostgresSaver(_pool)
    checkpointer.setup()          # idempotent — creates the checkpoint tables
    log.info('Checkpointer: Postgres')

    # Render sends SIGTERM on every spin-down and redeploy; uvicorn exits cleanly
    # on it, so atexit fires and the pool's worker threads shut down quietly.
    atexit.register(_pool.close)
else:
    checkpointer = InMemorySaver()
    log.warning('DATABASE_URL not set — agent memory is in-process and will not survive a restart')

desk = build_desk_graph(checkpointer)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class PromptObject(BaseModel):
    content: str
    id: str
    role: str


class RequestObject(BaseModel):
    prompt: PromptObject
    threadId: str
    responseId: str


# ---------------------------------------------------------------------------
# Title extraction helper
# ---------------------------------------------------------------------------
_COMMON = {'A', 'I', 'AT', 'BY', 'IN', 'ON', 'OF', 'TO', 'AN', 'IT', 'OR', 'DO', 'US', 'MY', 'ME', 'IS'}


def extract_text(content) -> str:
    """Normalise a single token.content for streaming — returns the raw string chunk."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(
            b if isinstance(b, str) else (b.get('text') or b.get('content') or '')
            for b in content
        )
    return str(content) if content else ''


# Ephemeral status lines shown while the desk works. C1Chat renders
# <thinkitem ephemeral> live during streaming and drops it from the saved
# message, so these never get persisted (we also keep them out of `chunks`).
_STATUS = {
    'fundamentals': 'Analysing fundamentals',
    'news': 'Checking recent news',
    'market': 'Pulling market data',
}


def thinkitem(title: str) -> str:
    """Wrap a status line as a thesys ephemeral think-item."""
    return (
        f'<thinkitem ephemeral="true">'
        f'<thinkitemtitle>{html.escape(title)}</thinkitemtitle>'
        f'</thinkitem>'
    )


_XML_WRAPPER = re.compile(r'<content[^>]*>(.*?)</content>', re.DOTALL | re.IGNORECASE)

def strip_thesys_xml(text: str) -> str:
    """C1Chat wraps messages as <content thesys="true">…</content> — extract the inner text."""
    m = _XML_WRAPPER.search(text)
    return m.group(1).strip() if m else text.strip()


def extract_title(text: str) -> str:
    # $NVDA or $AAPL style
    tickers = re.findall(r'\$([A-Z]{1,5})\b', text)
    if not tickers:
        # bare uppercase 2-5 char words that look like tickers
        tickers = [w for w in re.findall(r'\b([A-Z]{2,5})\b', text) if w not in _COMMON]
    if tickers:
        seen, unique = set(), []
        for t in tickers:
            if t not in seen:
                seen.add(t)
                unique.append(t)
            if len(unique) == 3:
                break
        return ' · '.join(unique)
    return text[:52].strip() + ('…' if len(text) > 52 else '')


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

async def require_user(authorization: str | None = Header(default=None)) -> dict:
    """Validate the Supabase access token on the Authorization header and
    return the authenticated user. Raises 401 if missing/invalid."""
    if not db:
        raise HTTPException(status_code=503, detail='Auth backend unavailable')
    if not authorization or not authorization.lower().startswith('bearer '):
        raise HTTPException(status_code=401, detail='Missing bearer token')
    token = authorization.split(' ', 1)[1].strip()
    try:
        result = db.auth.get_user(token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f'Invalid token: {e}')
    user = getattr(result, 'user', None)
    if not user or not user.id:
        raise HTTPException(status_code=401, detail='Invalid token')
    return {'id': user.id, 'email': user.email}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get('/api/health')
async def health(deep: int = 0):
    """Liveness by default; full dependency probe with ?deep=1.

    Render polls this every few seconds. Probing Supabase on every poll cost
    roughly 34k needless REST queries a day and told us nothing the process
    being up didn't already — the probe is opt-in now.
    """
    if not deep:
        return {'status': 'ok', 'db_configured': db is not None}

    status = {'db': False, 'tables': []}
    if db:
        try:
            db.table('chats').select('id').limit(1).execute()
            status['db'] = True
            status['tables'].append('chats')
        except Exception as e:
            status['chats_error'] = str(e)
        try:
            db.table('messages').select('id').limit(1).execute()
            status['tables'].append('messages')
        except Exception as e:
            status['messages_error'] = str(e)
    return status


@app.get('/api/chats')
async def list_chats(user: dict = Depends(require_user)):
    if not db:
        return []
    try:
        result = (
            db.table('chats')
            .select('id, title, updated_at')
            .eq('user_id', user['id'])
            .order('updated_at', desc=True)
            .limit(50)
            .execute()
        )
        return [
            {'thread_id': r['id'], 'title': r['title'], 'updated_at': r['updated_at']}
            for r in result.data
        ]
    except Exception:
        return []


def _chat_owner(thread_id: str) -> str | None:
    """Return the user_id of the chat, or None if it doesn't exist."""
    try:
        result = db.table('chats').select('user_id').eq('id', thread_id).limit(1).execute()
        return result.data[0]['user_id'] if result.data else None
    except Exception:
        return None


@app.delete('/api/chats/{thread_id}')
async def delete_chat(thread_id: str, user: dict = Depends(require_user)):
    if not db:
        return {'ok': False, 'error': 'no db'}
    if _chat_owner(thread_id) != user['id']:
        raise HTTPException(status_code=404, detail='Chat not found')
    try:
        # messages cascade-delete via FK, but be explicit
        db.table('messages').delete().eq('chat_id', thread_id).execute()
        db.table('chats').delete().eq('id', thread_id).eq('user_id', user['id']).execute()
        log.info('Deleted thread %s for user %s', thread_id, user['id'])
        return {'ok': True}
    except Exception as e:
        log.error('Delete thread failed: %s', e)
        return {'ok': False, 'error': str(e)}


@app.get('/api/chats/{thread_id}')
async def get_chat(thread_id: str, user: dict = Depends(require_user)):
    if not db:
        return []
    if _chat_owner(thread_id) != user['id']:
        raise HTTPException(status_code=404, detail='Chat not found')
    try:
        result = (
            db.table('messages')
            .select('role, content')
            .eq('chat_id', thread_id)
            .order('created_at')
            .execute()
        )
        return result.data
    except Exception:
        return []


def _save_to_db(thread_id: str, user_id: str, user_content: str, assistant_content: str):
    """Runs in background after streaming completes."""
    if not db:
        return
    ts = datetime.now(timezone.utc).isoformat()
    # Decode any HTML entities the model may have streamed (e.g. &quot; → ")
    # but preserve the full thesys component JSON so C1ChatViewer can render it.
    clean = html.unescape(assistant_content).strip() if assistant_content else ''
    log.info('Saving thread %s for user %s — user: %r… assistant: %d chars',
             thread_id, user_id, user_content[:40], len(clean))

    # Insert-or-update: keep existing owner; never let a request hijack
    # someone else's thread_id by writing into it.
    existing_owner = _chat_owner(thread_id)
    if existing_owner is None:
        try:
            db.table('chats').insert({
                'id': thread_id,
                'title': extract_title(user_content),
                'updated_at': ts,
                'user_id': user_id,
            }).execute()
        except Exception as e:
            log.error('DB create chat failed: %s', e)
            return
    elif existing_owner != user_id:
        log.warning('Refusing to write to thread %s — owned by %s, request from %s',
                    thread_id, existing_owner, user_id)
        return
    else:
        try:
            db.table('chats').update({'updated_at': ts}).eq('id', thread_id).eq('user_id', user_id).execute()
        except Exception as e:
            log.error('DB touch chat failed: %s', e)

    try:
        db.table('messages').insert(
            {'chat_id': thread_id, 'role': 'user', 'content': user_content}
        ).execute()
    except Exception as e:
        log.error('DB save user msg failed: %s', e)
    try:
        if clean:
            db.table('messages').insert(
                {'chat_id': thread_id, 'role': 'assistant', 'content': clean}
            ).execute()
            log.info('Thread %s saved OK', thread_id)
    except Exception as e:
        log.error('DB save assistant msg failed: %s', e)


@app.post('/api/chat')
async def chat(request: RequestObject, background_tasks: BackgroundTasks, user: dict = Depends(require_user)):
    thread_id = request.threadId
    user_content = strip_thesys_xml(request.prompt.content)

    # Block before spending tokens if the thread exists and isn't theirs.
    if db:
        owner = _chat_owner(thread_id)
        if owner is not None and owner != user['id']:
            raise HTTPException(status_code=404, detail='Chat not found')

    log.info('Chat request — user=%s thread=%s  prompt=%r…',
             user['id'], thread_id, user_content[:60])

    config = {'configurable': {'thread_id': thread_id}}
    chunks: list[str] = []

    def generate():
        # 'updates' lets us emit status the moment the supervisor picks a route;
        # 'messages' streams LLM tokens. Only the synthesizer's tokens are the
        # user-facing answer — specialist tokens (cheap-model findings) and tool
        # JSON are filtered out by node name.
        #
        # The whole loop is guarded: StreamingResponse has already flushed a 200
        # by the time this runs, so an exception here cannot become an error
        # status. Unguarded it just closes the stream, and the user gets an empty
        # assistant bubble with nothing to go on. Emit something instead.
        try:
            for mode, payload in desk.stream(
                {'query': user_content, 'messages': [HumanMessage(user_content)]},
                stream_mode=['updates', 'messages'],
                config=config,
            ):
                if mode == 'updates':
                    supervisor_update = payload.get(SUPERVISOR)
                    if supervisor_update:
                        for name in supervisor_update.get('route') or []:
                            title = _STATUS.get(name)
                            if title:
                                yield thinkitem(title)   # ephemeral — not persisted
                    continue

                # mode == 'messages'
                token, meta = payload
                if meta.get('langgraph_node') != SYNTHESIZER:
                    continue                              # not the final answer
                if isinstance(token, ToolMessage):
                    continue                              # never yield raw tool JSON
                text = extract_text(token.content)
                if text:
                    chunks.append(text)                   # only synthesizer text is saved
                    yield text
        except Exception:
            log.exception('Desk stream failed — thread=%s user=%s', thread_id, user['id'])
            # Deliberately not appended to `chunks`: this must not be persisted as
            # if it were the assistant's answer.
            yield '\n\n_The analyst desk hit an error generating this answer. Please try again._'

    # Closure captures `chunks` list by reference.
    # BackgroundTasks runs AFTER StreamingResponse is fully sent,
    # so `chunks` is complete by then.
    def save():
        _save_to_db(thread_id, user['id'], user_content, ''.join(chunks))

    background_tasks.add_task(save)

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        # X-Accel-Buffering tells nginx-based proxies (Render's included) not to
        # buffer the stream. Replaces the EB-only .platform/nginx override.
        headers={
            'Cache-Control': 'no-cache, no-transform',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        },
    )


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8888)
