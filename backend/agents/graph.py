"""
Desk graph wiring.

    START → supervisor → ┌─ fundamentals ─┐
                         ├─ news ─────────┤→ synthesizer → END
                         └─ market ───────┘
                         └─ (empty route) ─→ synthesizer

The supervisor's conditional edge fans out to exactly the chosen specialists
(in parallel); they converge on the synthesizer, which waits for whichever
branches were triggered. An empty route skips the desk and goes straight to the
synthesizer (the fast-path / no-data case).

Production usage is just `build_desk_graph(checkpointer)`; each node then builds
its own model lazily. The `router` / `agents` / `synth_model` hooks exist so the
graph can be driven entirely offline in tests with fakes injected — no network.
"""
from langgraph.graph import END, START, StateGraph

from .specialists import fundamentals_node, market_node, news_node
from .state import SPECIALISTS, SUPERVISOR, SYNTHESIZER, DeskState
from .supervisor import route_after_supervisor, supervisor_node
from .synthesizer import synthesizer_node


def build_desk_graph(checkpointer=None, *, router=None, agents=None, synth_model=None):
    """Compile the analyst-desk graph.

    Args:
        checkpointer: LangGraph checkpointer for per-thread memory (InMemorySaver
            in production today).
        router: injected supervisor router (test hook; None ⇒ build real one).
        agents: dict of {specialist_name: agent} test hooks (None ⇒ build real).
        synth_model: injected synthesizer model (test hook; None ⇒ build real).
    """
    agents = agents or {}

    # Thin closures bind the optional test hooks while keeping a clean single-arg
    # signature for LangGraph. With everything None, nodes build real models.
    def _supervisor(state):
        return supervisor_node(state, router=router)

    def _fundamentals(state):
        return fundamentals_node(state, agent=agents.get('fundamentals'))

    def _news(state):
        return news_node(state, agent=agents.get('news'))

    def _market(state):
        return market_node(state, agent=agents.get('market'))

    def _synthesizer(state):
        return synthesizer_node(state, model=synth_model)

    specialist_nodes = {
        'fundamentals': _fundamentals,
        'news': _news,
        'market': _market,
    }

    g = StateGraph(DeskState)
    g.add_node(SUPERVISOR, _supervisor)
    for name in SPECIALISTS:
        g.add_node(name, specialist_nodes[name])
    g.add_node(SYNTHESIZER, _synthesizer)

    g.add_edge(START, SUPERVISOR)
    # Conditional fan-out: route_after_supervisor returns the list of next nodes.
    g.add_conditional_edges(SUPERVISOR, route_after_supervisor, [*SPECIALISTS, SYNTHESIZER])
    # Fan-in: every specialist converges on the synthesizer.
    for name in SPECIALISTS:
        g.add_edge(name, SYNTHESIZER)
    g.add_edge(SYNTHESIZER, END)

    return g.compile(checkpointer=checkpointer)
