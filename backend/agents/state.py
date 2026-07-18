"""
Shared graph state for the analyst desk.

Parallel-fan-out note: each specialist node writes its OWN findings key
(`fundamentals` / `news` / `market`). Because no two concurrent nodes write the
same key, LangGraph merges their partial updates without needing a reducer.
Only the supervisor writes `route`; only the entry sets `query`.
"""
from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages
from typing_extensions import NotRequired

# Canonical specialist names. The supervisor's `route` is a subset of these,
# and each value here is exactly the state key the matching node writes.
SPECIALISTS = ('fundamentals', 'news', 'market')

# Canonical graph node names (shared so the supervisor's routing edge and the
# step-4 graph builder agree without importing each other).
SUPERVISOR = 'supervisor'
SYNTHESIZER = 'synthesizer'


class DeskState(TypedDict):
    # ── cross-turn memory ────────────────────────────────────────────────────
    # The conversation, persisted by the checkpointer keyed on thread_id. The
    # frontend sends only the latest user turn, so this is the ONLY place history
    # survives between requests. `add_messages` appends rather than overwrites.
    messages: Annotated[list, add_messages]

    # ── input ────────────────────────────────────────────────────────────────
    query: str                       # the user's latest question (plain text)

    # ── supervisor decision (step 2) ─────────────────────────────────────────
    route: NotRequired[list[str]]    # which specialists to run; [] ⇒ answer directly

    # ── specialist findings (filled in parallel; each node owns one key) ──────
    fundamentals: NotRequired[str]   # financial-health / balance-sheet read
    news: NotRequired[str]           # recent events + sentiment read
    market: NotRequired[str]         # price level + trend read

    # ── synthesizer output (step 3) ──────────────────────────────────────────
    # Final merged answer as C1 DSL. Streams to the user token-by-token (step 5);
    # the stored value here is for non-streaming callers / multi-turn memory.
    answer: NotRequired[str]
