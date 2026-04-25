import os
import re
import html
import json as _json
import datetime
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Cookie
from fastapi.responses import StreamingResponse, JSONResponse

from langchain.agents import create_agent
from langchain.tools import tool
from langchain.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

import yfinance as yf
import motor.motor_asyncio
import bcrypt
import jwt
import certifi
from bson import ObjectId

load_dotenv()

app = FastAPI()

_client = motor.motor_asyncio.AsyncIOMotorClient(os.environ['MONGO_URI'], tlsCAFile=certifi.where())
_db = _client['stockanalysis']
users_col = _db['users']
threads_col = _db['threads']
messages_col = _db['messages']

JWT_SECRET = os.environ['JWT_SECRET']
JWT_ALGORITHM = 'HS256'

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
    return stock.balance_sheet


@tool('get_stock_news', description='A function that returns news based on a ticker symbol.')
def get_stock_news(ticker: str):
    stock = yf.Ticker(ticker)
    return stock.news


agent = create_agent(
    model=model,
    checkpointer=checkpointer,
    tools=[get_stock_price, get_historical_stock_price, get_balance_sheet, get_stock_news]
)


@app.on_event('startup')
async def create_indexes():
    await users_col.create_index('email', unique=True)
    await threads_col.create_index([('user_id', 1), ('updated_at', -1)])
    await messages_col.create_index('thread_id')


# --- Auth helpers ---

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: str) -> str:
    exp = datetime.datetime.utcnow() + datetime.timedelta(days=7)
    return jwt.encode({'sub': user_id, 'exp': exp}, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_user(token: Optional[str] = Cookie(None)):
    if not token:
        raise HTTPException(status_code=401, detail='Not authenticated')
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail='Invalid token')
    user = await users_col.find_one({'_id': ObjectId(payload['sub'])})
    if not user:
        raise HTTPException(status_code=401, detail='User not found')
    return user


# --- Request models ---

class AuthBody(BaseModel):
    email: str
    password: str


class PromptObject(BaseModel):
    content: str
    id: str
    role: str


class RequestObject(BaseModel):
    prompt: PromptObject
    threadId: str
    responseId: str


# --- Auth routes ---

@app.post('/api/auth/register')
async def register(body: AuthBody):
    if await users_col.find_one({'email': body.email}):
        raise HTTPException(status_code=400, detail='Email already registered')
    result = await users_col.insert_one({
        'email': body.email,
        'password': hash_password(body.password),
        'created_at': datetime.datetime.utcnow()
    })
    res = JSONResponse({'email': body.email})
    res.set_cookie('token', create_token(str(result.inserted_id)),
                   httponly=True, samesite='lax', max_age=604800)
    return res


@app.post('/api/auth/login')
async def login(body: AuthBody):
    user = await users_col.find_one({'email': body.email})
    if not user or not verify_password(body.password, user['password']):
        raise HTTPException(status_code=401, detail='Invalid email or password')
    res = JSONResponse({'email': user['email']})
    res.set_cookie('token', create_token(str(user['_id'])),
                   httponly=True, samesite='lax', max_age=604800)
    return res


@app.post('/api/auth/logout')
async def logout():
    res = JSONResponse({'message': 'Logged out'})
    res.delete_cookie('token')
    return res


@app.get('/api/auth/me')
async def me(user=Depends(get_current_user)):
    return {'email': user['email'], 'id': str(user['_id'])}


# --- Helpers for cleaning stored AI messages ---

_THESYS_RE = re.compile(r'<content thesys="true">([\s\S]*?)</content>', re.IGNORECASE)


def _extract_component_texts(node, out: list) -> None:
    if not isinstance(node, dict):
        return
    comp = node.get('component')
    props = node.get('props') or {}

    if comp == 'Header':
        if isinstance(props.get('title'), str):
            out.append(props['title'])
        if isinstance(props.get('subtitle'), str):
            out.append(props['subtitle'])
    elif comp == 'TextContent' and isinstance(props.get('textMarkdown'), str):
        out.append(props['textMarkdown'])
    elif comp == 'Stats':
        label = props.get('label', '')
        number = props.get('number', '')
        if label and number:
            out.append(f"{label}: {number}")
    elif comp == 'MiniCard':
        # Extract nested ProfileTile title + Stats number from a MiniCard
        lhs = props.get('lhs') or {}
        rhs = props.get('rhs') or {}
        lhs_props = lhs.get('props') or {}
        rhs_props = rhs.get('props') or {}
        label = lhs_props.get('title', '')
        number = rhs_props.get('number', '')
        if label and number:
            out.append(f"{label}: {number}")
    elif comp == 'List':
        if isinstance(props.get('heading'), str):
            out.append(props['heading'])
        for item in (props.get('items') or []):
            title = item.get('title', '')
            subtitle = item.get('subtitle', '')
            if title:
                line = f"• {title}"
                if subtitle:
                    line += f"  ({subtitle})"
                out.append(line)
    elif comp == 'Table':
        rows = (props.get('tableBody') or {}).get('rows') or []
        for row in rows:
            cells = row.get('children') or []
            if cells:
                out.append('  '.join(str(c) for c in cells))

    # Always recurse into children props
    for val in props.values():
        if isinstance(val, dict):
            _extract_component_texts(val, out)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    _extract_component_texts(item, out)


def clean_user_message(content: str) -> str:
    # Strip thesys wrapper tags but keep the inner text (e.g. "NVDA")
    return _THESYS_RE.sub(lambda m: m.group(1).strip(), content).strip()


def clean_assistant_message(content: str) -> str:
    decoded = html.unescape(content)

    # Try full JSON parse of each thesys block for the richest extraction
    for match in _THESYS_RE.finditer(decoded):
        inner = match.group(1).strip()
        if not inner.startswith('{'):
            continue
        try:
            data = _json.loads(inner)
            lines: list[str] = []
            _extract_component_texts(data, lines)
            # Deduplicate while preserving order
            seen: set[str] = set()
            unique = [l for l in lines if l not in seen and not seen.add(l)]  # type: ignore[func-returns-value]
            if unique:
                return '\n'.join(unique)
        except Exception:
            pass

    # Fallback: pull every textMarkdown / title value out with regex
    parts: list[str] = []
    for key in ('textMarkdown', 'title', 'subtitle', 'number'):
        for val in re.findall(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', decoded):
            text = val.replace('\\n', '\n').replace('\\"', '"').strip()
            if text and text not in parts:
                parts.append(text)
    if parts:
        return '\n'.join(parts)

    return 'Formatted analysis response'


# --- Chat history routes ---

@app.get('/api/chats')
async def list_threads(user=Depends(get_current_user)):
    result = []
    async for t in threads_col.find({'user_id': str(user['_id'])}, sort=[('updated_at', -1)]):
        result.append({
            'thread_id': t['thread_id'],
            'title': clean_user_message(t['title']),
            'updated_at': t['updated_at'].isoformat()
        })
    return result


@app.get('/api/chats/{thread_id}')
async def get_thread_messages(thread_id: str, user=Depends(get_current_user)):
    thread = await threads_col.find_one({'thread_id': thread_id, 'user_id': str(user['_id'])})
    if not thread:
        raise HTTPException(status_code=404, detail='Thread not found')
    msgs = []
    async for m in messages_col.find({'thread_id': thread_id}, sort=[('created_at', 1)]):
        content = m['content']
        if m['role'] == 'assistant':
            content = clean_assistant_message(content)
        else:
            content = clean_user_message(content)
        msgs.append({'role': m['role'], 'content': content})
    return msgs


# --- Chat endpoint ---

@app.post('/api/chat')
async def chat(request: RequestObject, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    user_id = str(user['_id'])
    now = datetime.datetime.utcnow()

    await messages_col.insert_one({
        'thread_id': request.threadId,
        'user_id': user_id,
        'role': 'user',
        'content': request.prompt.content,
        'created_at': now
    })

    if not await threads_col.find_one({'thread_id': request.threadId}):
        raw_title = clean_user_message(request.prompt.content)
        title = raw_title[:60] + ('...' if len(raw_title) > 60 else '')
        await threads_col.insert_one({
            'thread_id': request.threadId,
            'user_id': user_id,
            'title': title,
            'created_at': now,
            'updated_at': now
        })

    config = {'configurable': {'thread_id': request.threadId}}
    collected = []

    def generate():
        for token, _ in agent.stream(
            {'messages': [
                SystemMessage('You are a stock analysis assistant. '
                              'You have the ability to get real-time stock prices, '
                              'historical stock prices (given a date range), news and balance sheet data '
                              'for a given ticker symbol.'),
                HumanMessage(request.prompt.content)
            ]},
            stream_mode='messages',
            config=config
        ):
            if token.content:
                collected.append(token.content)
                yield token.content

    async def save_response():
        await messages_col.insert_one({
            'thread_id': request.threadId,
            'user_id': user_id,
            'role': 'assistant',
            'content': ''.join(collected),
            'created_at': datetime.datetime.utcnow()
        })
        await threads_col.update_one(
            {'thread_id': request.threadId},
            {'$set': {'updated_at': datetime.datetime.utcnow()}}
        )

    background_tasks.add_task(save_response)

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache, no-transform', 'Connection': 'keep-alive'}
    )


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8888)
