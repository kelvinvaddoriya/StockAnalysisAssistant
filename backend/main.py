import re
import os
import html
import json
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv
from pydantic import BaseModel

import uvicorn
from fastapi import FastAPI, BackgroundTasks
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
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# LLM + agent
# ---------------------------------------------------------------------------
model = ChatOpenAI(
    model='c1/openai/gpt-5/v-20250930',
    base_url='https://api.thesys.dev/v1/embed/'
)

checkpointer = InMemorySaver()


@tool('get_stock_price', description='A function that returns the current stock price based on a ticker symbol.')
def get_stock_price(ticker: str):
    stock = yf.Ticker(ticker)
    return stock.history()['Close'].iloc[-1]


@tool('get_historical_stock_price', description='A function that returns the current stock price over time based on a ticker symbol and a start and end date.')
def get_historical_stock_price(ticker: str, start_date: str, end_date: str):
    stock = yf.Ticker(ticker)
    return stock.history(start=start_date, end=end_date).to_dict()


@tool('get_balance_sheet', description='A function that returns the balance sheet based on a ticker symbol.')
def get_balance_sheet(ticker: str):
    stock = yf.Ticker(ticker)
    return stock.balance_sheet.to_dict()


@tool('get_stock_news', description='A function that returns news based on a ticker symbol.')
def get_stock_news(ticker: str):
    stock = yf.Ticker(ticker)
    return stock.news


agent = create_react_agent(
    model=model,
    tools=[get_stock_price, get_historical_stock_price, get_balance_sheet, get_stock_news],
    checkpointer=checkpointer,
)

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


# Keys whose values in a thesys component props are human-readable text
_TEXT_PROPS = {'title', 'subtitle', 'label', 'value', 'text', 'content',
               'description', 'caption', 'heading', 'body', 'summary', 'price',
               'change', 'currency', 'ticker', 'name', 'detail'}


def _walk(node, out: list[str]):
    """Recursively collect readable strings from a thesys component tree."""
    if isinstance(node, str):
        v = node.strip()
        if v:
            out.append(v)
    elif isinstance(node, (int, float)):
        out.append(str(node))
    elif isinstance(node, list):
        for item in node:
            _walk(item, out)
    elif isinstance(node, dict):
        props = node.get('props') or {}
        for key, val in props.items():
            if key in _TEXT_PROPS and isinstance(val, str) and val.strip():
                out.append(val.strip())
            elif isinstance(val, (dict, list)):
                _walk(val, out)


def thesys_to_text(raw: str) -> str:
    """
    The thesys model streams HTML-entity-encoded JSON component trees.
    Decode the entities, parse JSON, walk the tree, return readable text.
    Falls back to plain HTML-unescaped string if JSON parse fails.
    """
    if not raw:
        return ''
    decoded = html.unescape(raw)
    try:
        data = json.loads(decoded)
        parts: list[str] = []
        _walk(data, parts)
        # deduplicate while preserving order
        seen: set[str] = set()
        unique = [p for p in parts if not (p in seen or seen.add(p))]  # type: ignore[func-returns-value]
        return '\n'.join(unique) if unique else decoded
    except (json.JSONDecodeError, Exception):
        return decoded.strip()

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
            status['chats_error'] = str(e)
        try:
            db.table('messages').select('id').limit(1).execute()
            status['tables'].append('messages')
        except Exception as e:
            status['messages_error'] = str(e)
    return status


@app.get('/api/debug-tokens')
async def debug_tokens(q: str = 'What is the price of AAPL?'):
    """Runs one agent turn and returns every token's type + content — use to diagnose streaming."""
    config = {'configurable': {'thread_id': 'debug-diag'}}
    rows = []
    for token, _ in agent.stream(
        {'messages': [SystemMessage('You are a stock analysis assistant.'), HumanMessage(q)]},
        stream_mode='messages',
        config=config
    ):
        text = extract_text(token.content)
        rows.append({
            'cls':      type(token).__name__,
            'is_ai':    isinstance(token, AIMessage),
            'is_tool':  isinstance(token, ToolMessage),
            'content_type': type(token.content).__name__,
            'text_preview': text[:120] if text else None,
        })
    raw_ai = ''.join(r['text_preview'] or '' for r in rows if r['is_ai'])
    return {
        'total_tokens': len(rows),
        'tokens': rows,
        'raw_ai_preview': raw_ai[:300],
        'parsed_readable': thesys_to_text(raw_ai)[:600],
    }


@app.get('/api/chats')
async def list_chats():
    if not db:
        return []
    try:
        result = (
            db.table('chats')
            .select('id, title, updated_at')
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


@app.delete('/api/chats/{thread_id}')
async def delete_chat(thread_id: str):
    if not db:
        return {'ok': False, 'error': 'no db'}
    try:
        # messages cascade-delete via FK, but be explicit
        db.table('messages').delete().eq('chat_id', thread_id).execute()
        db.table('chats').delete().eq('id', thread_id).execute()
        log.info('Deleted thread %s', thread_id)
        return {'ok': True}
    except Exception as e:
        log.error('Delete thread failed: %s', e)
        return {'ok': False, 'error': str(e)}


@app.get('/api/chats/{thread_id}')
async def get_chat(thread_id: str):
    if not db:
        return []
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


def _save_to_db(thread_id: str, user_content: str, assistant_content: str):
    """Runs in background after streaming completes."""
    if not db:
        return
    ts = datetime.now(timezone.utc).isoformat()
    # Decode any HTML entities the model may have streamed (e.g. &quot; → ")
    # but preserve the full thesys component JSON so C1ChatViewer can render it.
    clean = html.unescape(assistant_content).strip() if assistant_content else ''
    log.info('Saving thread %s — user: %r… assistant: %d chars',
             thread_id, user_content[:40], len(clean))
    try:
        db.table('chats').upsert(
            {'id': thread_id, 'title': extract_title(user_content), 'updated_at': ts},
            on_conflict='id',
            ignore_duplicates=True,
        ).execute()
        db.table('chats').update({'updated_at': ts}).eq('id', thread_id).execute()
    except Exception as e:
        log.error('DB save chat failed: %s', e)
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
async def chat(request: RequestObject, background_tasks: BackgroundTasks):
    thread_id = request.threadId
    user_content = strip_thesys_xml(request.prompt.content)
    log.info('Chat request — thread=%s  user=%r…', thread_id, user_content[:60])

    config = {'configurable': {'thread_id': thread_id}}
    chunks: list[str] = []

    def generate():
        for token, _ in agent.stream(
            {'messages': [
                SystemMessage('You are a stock analysis assistant. '
                              'You have the ability to get real-time stock prices, '
                              'historical stock prices (given a date range), news and balance sheet data '
                              'for a given ticker symbol.'),
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
        _save_to_db(thread_id, user_content, ''.join(chunks))

    background_tasks.add_task(save)

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache, no-transform', 'Connection': 'keep-alive'},
    )


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8888)
