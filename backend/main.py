import re
import os
import html
import time
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone
from uuid import UUID

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

import uvicorn
from fastapi import FastAPI, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent

import yfinance as yf
from supabase import create_client, Client as SupabaseClient

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

_extra_origins = [o.strip() for o in os.getenv('ALLOWED_ORIGINS', '').split(',') if o.strip()]
_origins = ["http://localhost:3000", "http://127.0.0.1:3000"] + _extra_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware('http')
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'no-referrer')
    return response

# ---------------------------------------------------------------------------
# LLM + agent
# ---------------------------------------------------------------------------
model = ChatOpenAI(
    model='c1/openai/gpt-5/v-20250930',
    base_url='https://api.thesys.dev/v1/embed/'
)

checkpointer = InMemorySaver()


_TICKER_HELP = (
    'Use the Yahoo Finance ticker convention: US-listed stocks use the plain '
    'symbol (AAPL, MSFT). Non-US listings require an exchange suffix — examples: '
    'India NSE ".NS" (RELIANCE.NS, TCS.NS), India BSE ".BO", London ".L" '
    '(BARC.L), Tokyo ".T" (7203.T), Hong Kong ".HK" (0700.HK), Frankfurt ".DE" '
    '(SAP.DE), Paris ".PA", Toronto ".TO", Australia ".AX". '
    'If a call returns "no data", retry once with the most likely exchange suffix '
    'based on the company\'s primary listing.'
)


@tool('get_stock_price',
      description='Returns the current closing price for a ticker symbol. ' + _TICKER_HELP)
def get_stock_price(ticker: str):
    hist = yf.Ticker(ticker).history()
    if hist.empty:
        return f'No data for ticker "{ticker}". If this is a non-US stock, retry with the exchange suffix (e.g. .NS, .L, .T, .HK).'
    return float(hist['Close'].iloc[-1])


@tool('get_historical_stock_price',
      description='Returns the closing price history between two ISO dates (YYYY-MM-DD). ' + _TICKER_HELP)
def get_historical_stock_price(ticker: str, start_date: str, end_date: str):
    hist = yf.Ticker(ticker).history(start=start_date, end=end_date)
    if hist.empty:
        return f'No data for ticker "{ticker}" between {start_date} and {end_date}. If non-US, retry with exchange suffix.'
    return hist['Close'].to_dict()


@tool('get_balance_sheet',
      description='Returns the latest balance sheet for a ticker symbol. ' + _TICKER_HELP)
def get_balance_sheet(ticker: str):
    bs = yf.Ticker(ticker).balance_sheet
    if bs.empty:
        return f'No balance sheet data for "{ticker}". If non-US, retry with exchange suffix.'
    return bs.to_dict()


@tool('get_stock_news',
      description='Returns recent news articles for a ticker symbol. ' + _TICKER_HELP)
def get_stock_news(ticker: str):
    news = yf.Ticker(ticker).news
    if not news:
        return f'No news for "{ticker}". If non-US, retry with exchange suffix.'
    return news


agent = create_react_agent(
    model=model,
    tools=[get_stock_price, get_historical_stock_price, get_balance_sheet, get_stock_news],
    checkpointer=checkpointer,
)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
# Caps the prompt size so a single request can't dump megabytes into the LLM.
MAX_PROMPT_CHARS = 8000


class PromptObject(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    id: str = Field(max_length=128)
    role: str = Field(max_length=32)


class RequestObject(BaseModel):
    prompt: PromptObject
    threadId: str
    responseId: str = Field(max_length=128)

    @field_validator('threadId')
    @classmethod
    def _thread_id_must_be_uuid(cls, v: str) -> str:
        try:
            UUID(v)
        except (ValueError, AttributeError, TypeError):
            raise ValueError('threadId must be a UUID')
        return v


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
        log.warning('Token validation failed: %s', e)
        raise HTTPException(status_code=401, detail='Invalid token')
    user = getattr(result, 'user', None)
    if not user or not user.id:
        raise HTTPException(status_code=401, detail='Invalid token')
    return {'id': user.id, 'email': user.email}


# ---------------------------------------------------------------------------
# Rate limiting — in-memory sliding window per user. Good enough for the
# single-instance EB deployment; swap for Redis if this ever scales out.
# ---------------------------------------------------------------------------
RATE_LIMIT_MAX = 20        # max /api/chat requests …
RATE_LIMIT_WINDOW = 60.0   # … per this many seconds, per user

_request_log: dict[str, deque] = defaultdict(deque)


def _check_rate_limit(user_id: str) -> None:
    now = time.monotonic()
    q = _request_log[user_id]
    while q and now - q[0] > RATE_LIMIT_WINDOW:
        q.popleft()
    if len(q) >= RATE_LIMIT_MAX:
        raise HTTPException(status_code=429, detail='Too many requests, please slow down')
    q.append(now)


def _require_valid_thread_id(thread_id: str) -> None:
    """Path-param counterpart of the RequestObject validator. 404 (not 422) so
    probing with junk ids is indistinguishable from a missing chat."""
    try:
        UUID(thread_id)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail='Chat not found')


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get('/api/health')
async def health():
    status = {'db': False, 'tables': []}
    if db:
        try:
            db.table('chats').select('id').limit(1).execute()
            status['db'] = True
            status['tables'].append('chats')
        except Exception as e:
            log.error('Health check (chats) failed: %s', e)
        try:
            db.table('messages').select('id').limit(1).execute()
            status['tables'].append('messages')
        except Exception as e:
            log.error('Health check (messages) failed: %s', e)
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
    _require_valid_thread_id(thread_id)
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
        return {'ok': False, 'error': 'delete failed'}


@app.get('/api/chats/{thread_id}')
async def get_chat(thread_id: str, user: dict = Depends(require_user)):
    if not db:
        return []
    _require_valid_thread_id(thread_id)
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
    _check_rate_limit(user['id'])
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
        for token, _ in agent.stream(
            {'messages': [
                SystemMessage(
                    'You are a stock analysis assistant. '
                    'You have the ability to get real-time stock prices, '
                    'historical stock prices (given a date range), news and balance sheet data '
                    'for a given ticker symbol. '
                    'Yahoo Finance ticker convention: US-listed use the plain symbol; '
                    'non-US listings require an exchange suffix '
                    '(e.g. RELIANCE.NS for India NSE, BARC.L for London, 7203.T for Tokyo, '
                    '0700.HK for Hong Kong, SAP.DE for Frankfurt). '
                    'When a user names a non-US company, use the suffix for its primary exchange. '
                    'If a tool returns "no data", retry once with the most likely suffix before '
                    'telling the user the ticker is unavailable.'
                ),
                HumanMessage(user_content)
            ]},
            stream_mode='messages',
            config=config
        ):
            if isinstance(token, ToolMessage):
                continue  # never yield raw tool JSON
            text = extract_text(token.content)
            if text:
                chunks.append(text)
                yield text

    # Closure captures `chunks` list by reference.
    # BackgroundTasks runs AFTER StreamingResponse is fully sent,
    # so `chunks` is complete by then.
    def save():
        _save_to_db(thread_id, user['id'], user_content, ''.join(chunks))

    background_tasks.add_task(save)

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache, no-transform', 'Connection': 'keep-alive'},
    )


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8888)
