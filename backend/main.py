import re
import os
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv
from pydantic import BaseModel

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
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


@app.post('/api/chat')
async def chat(request: RequestObject):
    thread_id = request.threadId
    user_content = request.prompt.content
    now = lambda: datetime.now(timezone.utc).isoformat()

    # --- persist chat + user message (best-effort, never blocks stream) ---
    if db:
        try:
            # Upsert chat row; on conflict keep the existing title, only bump updated_at
            db.table('chats').upsert(
                {'id': thread_id, 'title': extract_title(user_content), 'updated_at': now()},
                on_conflict='id',
                ignore_duplicates=True,
            ).execute()
            # Always bump updated_at for returning chats
            db.table('chats').update({'updated_at': now()}).eq('id', thread_id).execute()
        except Exception as e:
            log.error('DB upsert chat failed: %s', e)
        try:
            db.table('messages').insert(
                {'chat_id': thread_id, 'role': 'user', 'content': user_content}
            ).execute()
        except Exception as e:
            log.error('DB insert user message failed: %s', e)

    config = {'configurable': {'thread_id': thread_id}}

    def generate():
        collected: list[str] = []
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
            if token.content:
                collected.append(token.content)
                yield token.content

        # Stream finished — persist assistant response
        if db and collected:
            full = ''.join(collected)
            try:
                db.table('messages').insert(
                    {'chat_id': thread_id, 'role': 'assistant', 'content': full}
                ).execute()
                log.info('Saved conversation for thread %s', thread_id)
            except Exception as e:
                log.error('DB insert assistant message failed: %s', e)

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache, no-transform', 'Connection': 'keep-alive'},
    )


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8888)
