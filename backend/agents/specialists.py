"""
The three desk specialists.

Each specialist is a self-contained ReAct sub-agent (`create_react_agent`)
scoped to one domain prompt + a slice of the toolbelt. The `*_node` wrappers are
the graph nodes (step 4 wires them under the supervisor): they read
`state['query']`, run the sub-agent, and write a single findings key.

The agent is injectable so tests can pass a fake instead of hitting an LLM, and
so the graph can build each agent once and reuse it across turns.
"""
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from .models import make_specialist_model
from .prompts import FUNDAMENTALS_PROMPT, MARKET_PROMPT, NEWS_PROMPT
from .tools import (
    get_balance_sheet,
    get_historical_stock_price,
    get_stock_news,
    get_stock_price,
)

# Each specialist owns a slice of the toolbelt — this partition is what keeps the
# domain prompts honest (a news analyst can't wander into balance sheets).
FUNDAMENTALS_TOOLS = [get_balance_sheet, get_historical_stock_price]
NEWS_TOOLS = [get_stock_news]
MARKET_TOOLS = [get_stock_price, get_historical_stock_price]


def make_specialist(prompt: str, tools: list, model=None):
    """Build a ReAct sub-agent for one analyst domain."""
    return create_react_agent(model=model or make_specialist_model(), tools=tools, prompt=prompt)


def _run(agent, state) -> str:
    """Invoke a specialist on the conversation so far, return its final note.

    Passing the full history (not just the latest query) lets the specialist
    resolve follow-ups like "what about its debt?" against the prior turns."""
    history = state.get('messages')
    msgs = history if history else [HumanMessage(state['query'])]
    result = agent.invoke({'messages': msgs})
    return result['messages'][-1].content


# ── Factories (one agent per domain) ─────────────────────────────────────────

def make_fundamentals_agent(model=None):
    return make_specialist(FUNDAMENTALS_PROMPT, FUNDAMENTALS_TOOLS, model)


def make_news_agent(model=None):
    return make_specialist(NEWS_PROMPT, NEWS_TOOLS, model)


def make_market_agent(model=None):
    return make_specialist(MARKET_PROMPT, MARKET_TOOLS, model)


# ── Graph nodes (read state['query'] → write one findings key) ────────────────
# `agent` is injectable; when omitted a fresh sub-agent is built on demand.

def fundamentals_node(state, *, agent=None):
    agent = agent or make_fundamentals_agent()
    return {'fundamentals': _run(agent, state)}


def news_node(state, *, agent=None):
    agent = agent or make_news_agent()
    return {'news': _run(agent, state)}


def market_node(state, *, agent=None):
    agent = agent or make_market_agent()
    return {'market': _run(agent, state)}
