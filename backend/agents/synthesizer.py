"""
Synthesizer — merge + self-check + render.

The lead analyst of the desk. It calls no tools; it receives the user's question
plus the specialist notes already gathered in state and produces the single final
answer. It is the ONLY node whose output reaches the user, so it stays on the
Thesys C1 model — its tokens are the `<content thesys="true">…` DSL that C1Chat
renders.

Streaming (step 5): the graph runs with stream_mode='messages' and the SSE layer
forwards only tokens tagged `langgraph_node == 'synthesizer'`. The `answer` key
this node returns is for non-streaming callers, tests, and multi-turn memory.

Quality gate (the "minimal" critic): rather than a separate critic node, the
synthesis prompt makes the model cross-check figures across the notes and flag
disagreements or gaps instead of silently papering over them.
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from .models import make_synthesizer_model
from .state import SPECIALISTS

SYNTHESIZER_PROMPT = (
    'You are the lead analyst of a stock-research desk, writing the final answer '
    'for the user. You may be given notes from up to three specialist analysts '
    '(fundamentals, news, market). Your job:\n'
    '  1. Merge the notes into one clear, well-structured answer to the user\'s '
    'question — do not just concatenate them.\n'
    '  2. SELF-CHECK before answering: cross-reference the figures and claims '
    'across the notes. If two notes disagree (e.g. different prices), or a number '
    'looks implausible, or a needed data point is missing, say so explicitly '
    'rather than smoothing it over.\n'
    '  3. Attribute concrete numbers to what the analysts actually reported; do '
    'not invent data that is not in the notes.\n'
    '  4. If no analyst notes are provided, answer the question directly from '
    'general knowledge and do not fabricate live market data.\n'
    'Be concise and decision-useful. Use the available UI components to present '
    'prices, comparisons, and trends clearly.'
)


def _format_findings(state) -> str:
    """Render the specialist notes present in state as labelled sections."""
    sections = []
    for name in SPECIALISTS:
        note = state.get(name)
        if note:
            sections.append(f'[{name.upper()} ANALYST]\n{note}')
    return '\n\n'.join(sections)


def build_synthesis_input(state) -> list:
    """Assemble the messages for the synthesizer model.

    When conversation history is present it is threaded in (so the answer is
    coherent across turns), followed by a trailing instruction carrying this
    turn's analyst notes. Without history (standalone calls / tests) it falls
    back to packaging the query inline."""
    findings = _format_findings(state)
    if findings:
        instruction = (
            f'Analyst notes for the latest question:\n{findings}\n\n'
            'Synthesise these into the final answer, applying the self-check.'
        )
    else:
        instruction = (
            'No analyst notes were gathered (no live market data was required). '
            'Answer the latest question directly.'
        )

    history = state.get('messages')
    if history:
        return [SystemMessage(SYNTHESIZER_PROMPT), *history, HumanMessage(instruction)]
    return [
        SystemMessage(SYNTHESIZER_PROMPT),
        HumanMessage(f"User question:\n{state['query']}\n\n{instruction}"),
    ]


def synthesizer_node(state, *, model=None):
    """Merge findings → final C1 answer. Streams in step 5; returns `answer`
    and appends the answer to `messages` so the next turn has the context."""
    model = model or make_synthesizer_model()
    result = model.invoke(build_synthesis_input(state))
    return {'answer': result.content, 'messages': [AIMessage(result.content)]}
