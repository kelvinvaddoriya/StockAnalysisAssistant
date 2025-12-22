import os
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import List
from datetime import datetime

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from langchain.agents import create_agent
from langchain.tools import tool
from langchain.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from supabase import create_client, Client

import yfinance as yf

load_dotenv()

app = FastAPI()

model = ChatOpenAI(
    model = 'c1/openai/gpt-5/v-20250930',
    base_url = 'https://api.thesys.dev/v1/embed/'
)

checkpointer = InMemorySaver()

supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_ANON_KEY')
supabase: Client = create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None


@tool('get_stock_price', description='A function that returns the current stock price based on a ticker symbol.')
def get_stock_price(ticker: str):
    print('get_stock_price tool is being used')
    stock = yf.Ticker(ticker)
    return stock.history()['Close'].iloc[-1]


@tool('get_historical_stock_price', description='A function that returns the current stock price over time based on a ticker symbol and a start and end date.')
def get_historical_stock_price(ticker: str, start_date: str, end_date: str):
    print('get_historical_stock_price tool is being used')
    stock = yf.Ticker(ticker)
    return stock.history(start=start_date, end=end_date).to_dict()


@tool('get_balance_sheet', description='A function that returns the balance sheet based on a ticker symbol.')
def get_balance_sheet(ticker: str):
    print('get_balance_sheet tool is being used')
    stock = yf.Ticker(ticker)
    return stock.balance_sheet


@tool('get_stock_news', description='A function that returns news based on a ticker symbol.')
def get_stock_news(ticker: str):
    print('get_stock_news tool is being used')
    stock = yf.Ticker(ticker)
    return stock.news



agent = create_agent(
    model = model,
    checkpointer = checkpointer,
    tools = [get_stock_price, get_historical_stock_price, get_balance_sheet, get_stock_news]
)


class PromptObject(BaseModel):
    content: str
    id: str
    role: str


class RequestObject(BaseModel):
    prompt: PromptObject
    threadId: str
    responseId: str


class ChatResponse(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class MessageResponse(BaseModel):
    id: str
    chat_id: str
    role: str
    content: str
    created_at: str


@app.post('/api/chat')
async def chat(request: RequestObject):
    config = {'configurable': {'thread_id': request.threadId}}

    if supabase:
        chat_exists = supabase.table('chats').select('id').eq('id', request.threadId).execute()
        if not chat_exists.data:
            supabase.table('chats').insert({
                'id': request.threadId,
                'title': request.prompt.content[:50] + ('...' if len(request.prompt.content) > 50 else ''),
                'created_at': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat()
            }).execute()

        supabase.table('messages').insert({
            'chat_id': request.threadId,
            'role': request.prompt.role,
            'content': request.prompt.content,
            'created_at': datetime.utcnow().isoformat()
        }).execute()

    def generate():
        assistant_message = ''
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
            assistant_message += token.content
            yield token.content

        if supabase and assistant_message:
            supabase.table('messages').insert({
                'chat_id': request.threadId,
                'role': 'assistant',
                'content': assistant_message,
                'created_at': datetime.utcnow().isoformat()
            }).execute()

            supabase.table('chats').update({
                'updated_at': datetime.utcnow().isoformat()
            }).eq('id', request.threadId).execute()

    return StreamingResponse(generate(), media_type='text/event-stream',
                             headers={
                                 'Cache-Control': 'no-cache, no-transform',
                                 'Connection': 'keep-alive',
                             })


@app.get('/api/chats', response_model=List[ChatResponse])
async def get_chats():
    if not supabase:
        raise HTTPException(status_code=500, detail='Database not configured')

    result = supabase.table('chats').select('*').order('updated_at', desc=True).execute()
    return result.data


@app.get('/api/chats/{chat_id}/messages', response_model=List[MessageResponse])
async def get_chat_messages(chat_id: str):
    if not supabase:
        raise HTTPException(status_code=500, detail='Database not configured')

    result = supabase.table('messages').select('*').eq('chat_id', chat_id).order('created_at').execute()
    return result.data


@app.delete('/api/chats/{chat_id}')
async def delete_chat(chat_id: str):
    if not supabase:
        raise HTTPException(status_code=500, detail='Database not configured')

    supabase.table('chats').delete().eq('id', chat_id).execute()
    return {'success': True}


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8888)