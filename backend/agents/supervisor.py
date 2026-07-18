"""
Supervisor — routing + fast-path.

The supervisor does no analysis and calls no tools. It reads the user's query
and picks the MINIMAL set of specialists needed, writing `state['route']`. The
step-4 graph then fans out to exactly those specialists in parallel.

Routing contract:
  • Pick only the specialists whose data the answer actually needs. A bare price
    lookup → ['market']; a "should I buy?" deep-dive → all three.
  • Empty route ([]) means NO market data is needed (greeting, capability
    question, general finance concept). The synthesizer answers from general
    knowledge — it has no tools, so never return [] for a query that needs data.

This is also where the "fast-path simple queries" decision lives: routing to one
specialist (or none) is the cheap path; fanning out three is the full desk.
"""
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from .models import make_supervisor_model
from .state import SPECIALISTS, SYNTHESIZER

SUPERVISOR_PROMPT = (
    'You are the dispatcher for a stock-research desk with three analysts:\n'
    '  • "fundamentals" — balance sheet, financial health, long-range valuation.\n'
    '  • "news" — recent news and market sentiment.\n'
    '  • "market" — current price and recent price trend.\n\n'
    'Given the user\'s message, choose the MINIMAL set of analysts whose data is '
    'needed to answer it well. Guidance:\n'
    '  - Bare price / "how is it trading" → ["market"].\n'
    '  - Headlines / "what\'s happening with" → ["news"] (add "market" if price matters).\n'
    '  - "Is it healthy / undervalued / financials" → ["fundamentals"].\n'
    '  - Broad "should I buy / full analysis of X" → all three.\n'
    '  - Greeting, capability question, or a general finance concept needing NO '
    'live data → [] (empty).\n\n'
    'Return only the analyst names that genuinely add value. Do not pad the list.'
)


class RouteDecision(BaseModel):
    """Structured routing output from the supervisor model."""
    specialists: list[Literal['fundamentals', 'news', 'market']] = Field(
        default_factory=list,
        description='Minimal set of analysts to run; empty if no market data is needed.',
    )


def make_supervisor(model=None):
    """Build the routing model (structured output). Injectable for tests."""
    model = model or make_supervisor_model()
    return model.with_structured_output(RouteDecision)


def supervisor_node(state, *, router=None):
    """Classify the query → write `route` (deduped, canonical order).

    Also resets the per-turn findings scratch to None: state is checkpointed
    across turns, so without this, a specialist that ran last turn but NOT this
    turn would leave stale findings for the synthesizer to pick up."""
    router = router or make_supervisor()
    history = state.get('messages')
    convo = history if history else [HumanMessage(state['query'])]
    decision = router.invoke([SystemMessage(SUPERVISOR_PROMPT), *convo])
    chosen = set(decision.specialists)
    # Canonical order, dedup, drop anything unexpected.
    route = [s for s in SPECIALISTS if s in chosen]
    return {'route': route, 'fundamentals': None, 'news': None, 'market': None}


def route_after_supervisor(state) -> list[str]:
    """Conditional-edge fn for the graph (step 4): fan out to the chosen
    specialists, or go straight to the synthesizer when the route is empty
    (the fast-path / no-data case). Always returns a non-empty target list."""
    route = state.get('route') or []
    return route if route else [SYNTHESIZER]
