"""
Model factories for the desk.

Two tiers, two credentials:
  • synthesizer — the Thesys-routed C1 model. Its output IS the C1 DSL the
    frontend renders (`<content thesys="true">…`), so it must stay on Thesys.
    Auth: OPENAI_API_KEY (the Thesys `sk-th-…` key) against api.thesys.dev —
    ChatOpenAI picks this up from the env by default.
  • specialist / supervisor — cheap/fast plain-text models on real OpenAI.
    Auth: DESK_OPENAI_API_KEY (a real `sk-proj-…` key) against api.openai.com.
    This MUST be passed explicitly: if we relied on the default env lookup,
    ChatOpenAI would grab OPENAI_API_KEY (the Thesys key) and 401 on OpenAI.

Everything is env-overridable so model ids / keys can change without code edits.
"""
import os

from langchain_openai import ChatOpenAI

THESYS_BASE_URL = 'https://api.thesys.dev/v1/embed/'

# Synthesizer: Thesys C1 model (emits renderable DSL). Matches the legacy agent.
SYNTHESIZER_MODEL = os.getenv('SYNTHESIZER_MODEL', 'c1/openai/gpt-5/v-20250930')

# Cheap tier: real OpenAI. Specialists fan out 3-wide per query, so keep it small.
SPECIALIST_MODEL = os.getenv('SPECIALIST_MODEL', 'gpt-4o-mini')
# Supervisor only classifies + routes — can be the same small model or smaller.
SUPERVISOR_MODEL = os.getenv('SUPERVISOR_MODEL', SPECIALIST_MODEL)


def make_synthesizer_model() -> ChatOpenAI:
    """Thesys-routed C1 model — emits the DSL C1Chat renders."""
    return ChatOpenAI(model=SYNTHESIZER_MODEL, base_url=THESYS_BASE_URL)


def make_specialist_model() -> ChatOpenAI:
    """Cheap plain-text model on real OpenAI for the analyst specialists."""
    return ChatOpenAI(model=SPECIALIST_MODEL, api_key=os.getenv('DESK_OPENAI_API_KEY'))


def make_supervisor_model() -> ChatOpenAI:
    """Cheap plain-text model on real OpenAI for routing decisions."""
    return ChatOpenAI(model=SUPERVISOR_MODEL, api_key=os.getenv('DESK_OPENAI_API_KEY'))
