"""
Patch heavy ML / LLM dependencies before main.py is imported,
so tests run without API keys and without downloading models.
"""
import os
import sys
from unittest.mock import MagicMock

# Ensure env vars are set (empty → Supabase disabled path)
os.environ.setdefault('SUPABASE_URL', '')
os.environ.setdefault('SUPABASE_KEY', '')
# Forced empty, not setdefault: tests must take the in-memory checkpointer path
# even on a machine that has DATABASE_URL exported. load_dotenv() won't override
# an already-set var, so this also shields against a .env on disk.
os.environ['DATABASE_URL'] = ''

# ── stub out every dep that main.py imports at module level ──────────────────

_tool_passthrough = lambda *a, **kw: (lambda fn: fn)  # noqa: E731

_lc_tools = MagicMock()
_lc_tools.tool = _tool_passthrough

_lc_messages = MagicMock()
# We need real subclass-able types so isinstance() checks work in tests
class _FakeAIMessage:
    def __init__(self, content): self.content = content
class _FakeToolMessage:
    def __init__(self, content): self.content = content
class _FakeHumanMessage:
    def __init__(self, content): self.content = content
class _FakeSystemMessage:
    def __init__(self, content): self.content = content

_lc_messages.AIMessage    = _FakeAIMessage
_lc_messages.ToolMessage  = _FakeToolMessage
_lc_messages.HumanMessage = _FakeHumanMessage
_lc_messages.SystemMessage = _FakeSystemMessage

sys.modules.setdefault('langchain_core',                  MagicMock())
sys.modules.setdefault('langchain_core.tools',            _lc_tools)
sys.modules.setdefault('langchain_core.messages',         _lc_messages)
sys.modules.setdefault('langchain_openai',                MagicMock())
sys.modules.setdefault('langgraph',                       MagicMock())
sys.modules.setdefault('langgraph.prebuilt',              MagicMock())
sys.modules.setdefault('langgraph.checkpoint',            MagicMock())
sys.modules.setdefault('langgraph.checkpoint.memory',     MagicMock())
sys.modules.setdefault('langgraph.graph',                 MagicMock())

# agents.state does `Annotated[list, add_messages]` at class-definition time, so
# the stub must expose a real callable (the value is otherwise inert in tests).
_lg_graph_message = MagicMock()
_lg_graph_message.add_messages = lambda left, right: (left or []) + (right or [])
sys.modules.setdefault('langgraph.graph.message',         _lg_graph_message)

sys.modules.setdefault('yfinance',                        MagicMock())
sys.modules.setdefault('supabase',                        MagicMock())
