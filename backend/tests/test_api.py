"""Tests for FastAPI endpoints (Supabase-disabled path + mocked agent)."""
import sys
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

# conftest.py stubs heavy deps before this import
from main import app, require_user  # noqa: E402

# Grab the fake message classes injected by conftest
_lc_messages = sys.modules['langchain_core.messages']
AIMessage   = _lc_messages.AIMessage
ToolMessage = _lc_messages.ToolMessage


def _fake_user():
    return {'id': '00000000-0000-0000-0000-000000000001', 'email': 'test@example.com'}


@pytest.fixture
def client():
    app.dependency_overrides[require_user] = _fake_user
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


# ── /api/health ───────────────────────────────────────────────────────────────

class TestHealth:
    def test_returns_200(self, client):
        r = client.get('/api/health')
        assert r.status_code == 200

    def test_shallow_probe_does_not_touch_db(self, client):
        # The default path is what Render polls every few seconds — it must stay
        # free of dependency calls.
        data = client.get('/api/health').json()
        assert data['status'] == 'ok'
        assert 'tables' not in data

    def test_db_false_when_no_credentials(self, client):
        data = client.get('/api/health?deep=1').json()
        assert data['db'] is False

    def test_tables_empty_when_no_credentials(self, client):
        data = client.get('/api/health?deep=1').json()
        assert data['tables'] == []


# ── /api/chats ────────────────────────────────────────────────────────────────

class TestListChats:
    def test_returns_empty_list_without_db(self, client):
        r = client.get('/api/chats')
        assert r.status_code == 200
        assert r.json() == []


# ── /api/chats/{thread_id} ────────────────────────────────────────────────────

class TestGetChat:
    def test_returns_empty_list_without_db(self, client):
        r = client.get('/api/chats/some-thread-id')
        assert r.status_code == 200
        assert r.json() == []


# ── /api/chat ─────────────────────────────────────────────────────────────────

CHAT_PAYLOAD = {
    'prompt': {'content': 'What is the price of AAPL?', 'id': 'msg-1', 'role': 'user'},
    'threadId': 'test-thread-001',
    'responseId': 'resp-1',
}


class TestChat:
    @staticmethod
    def _synth(text: str):
        """A 'messages' stream event tagged as the synthesizer (user-facing)."""
        return ('messages', (AIMessage(text), {'langgraph_node': 'synthesizer'}))

    def _mock_desk(self, events):
        """Return a mock desk whose stream() yields the given (mode, payload) events."""
        def _stream(*args, **kwargs):
            for ev in events:
                yield ev

        mock_desk = MagicMock()
        mock_desk.stream.side_effect = _stream
        return mock_desk

    def test_returns_streaming_response(self, client):
        import main as m
        original = m.desk
        m.desk = self._mock_desk([self._synth("Hello "), self._synth("world!")])
        try:
            r = client.post('/api/chat', json=CHAT_PAYLOAD)
            assert r.status_code == 200
            assert 'text/event-stream' in r.headers['content-type']
        finally:
            m.desk = original

    def test_mid_stream_failure_is_surfaced_not_silent(self, client):
        """A dead pooled DB connection used to kill the generator after the 200
        headers were flushed, leaving the user an empty assistant bubble."""
        import main as m
        original = m.desk

        def _boom(*args, **kwargs):
            yield self._synth('Partial answer')
            raise RuntimeError('SSL error: unexpected eof while reading')

        mock_desk = MagicMock()
        mock_desk.stream.side_effect = _boom
        m.desk = mock_desk
        try:
            r = client.post('/api/chat', json=CHAT_PAYLOAD)
            assert r.status_code == 200          # headers already sent — can't 500
            body = r.content.decode()
            assert 'Partial answer' in body      # what streamed before the fault survives
            assert 'hit an error' in body        # and the user is told something broke
        finally:
            m.desk = original

    def test_streams_synthesizer_text(self, client):
        import main as m
        original = m.desk
        m.desk = self._mock_desk([self._synth("Stock "), self._synth("price: "), self._synth("$182")])
        try:
            r = client.post('/api/chat', json=CHAT_PAYLOAD)
            assert b'Stock price: $182' in r.content
        finally:
            m.desk = original

    def test_tool_messages_are_filtered(self, client):
        """ToolMessage tokens should never appear in the response."""
        import main as m
        original = m.desk
        m.desk = self._mock_desk([
            ('messages', (ToolMessage('{"raw": "tool data"}'), {'langgraph_node': 'synthesizer'})),
            self._synth('Clean answer'),
        ])
        try:
            r = client.post('/api/chat', json=CHAT_PAYLOAD)
            assert b'tool data' not in r.content
            assert b'Clean answer' in r.content
        finally:
            m.desk = original

    def test_specialist_tokens_not_streamed(self, client):
        """Only the synthesizer's tokens reach the user; specialist findings don't."""
        import main as m
        original = m.desk
        m.desk = self._mock_desk([
            ('messages', (AIMessage('internal market note'), {'langgraph_node': 'market'})),
            self._synth('Final answer'),
        ])
        try:
            r = client.post('/api/chat', json=CHAT_PAYLOAD)
            assert b'internal market note' not in r.content
            assert b'Final answer' in r.content
        finally:
            m.desk = original

    def test_supervisor_route_emits_status_thinkitems(self, client):
        """When the supervisor picks a route, an ephemeral status line per
        specialist is streamed (and is not part of the saved answer)."""
        import main as m
        original = m.desk
        m.desk = self._mock_desk([
            ('updates', {'supervisor': {'route': ['fundamentals', 'news']}}),
            self._synth('<content thesys="true">done</content>'),
        ])
        try:
            body = client.post('/api/chat', json=CHAT_PAYLOAD).content.decode()
            assert 'ephemeral="true"' in body
            assert 'Analysing fundamentals' in body
            assert 'Checking recent news' in body
            assert 'Pulling market data' not in body   # market wasn't routed
        finally:
            m.desk = original

    def test_rejects_missing_fields(self, client):
        r = client.post('/api/chat', json={'threadId': 'x'})
        assert r.status_code == 422

    def test_xml_wrapper_stripped_before_desk(self, client):
        """C1Chat wraps user content in <content> — the desk should receive plain text."""
        import main as m
        original = m.desk

        received: dict = {}

        def _capture_stream(input_dict, *args, **kwargs):
            received['query'] = input_dict.get('query', '')
            received['messages'] = [getattr(msg, 'content', '') for msg in input_dict.get('messages', [])]
            yield self._synth('ok')

        mock_desk = MagicMock()
        mock_desk.stream.side_effect = _capture_stream
        m.desk = mock_desk

        wrapped_payload = {**CHAT_PAYLOAD, 'prompt': {
            **CHAT_PAYLOAD['prompt'],
            'content': '<content thesys="true">What is AAPL?</content>',
        }}

        try:
            client.post('/api/chat', json=wrapped_payload)
            # Both the query and the HumanMessage handed to the desk must be stripped.
            assert 'What is AAPL?' in received['query']
            assert '<content' not in received['query']
            assert any('What is AAPL?' in c for c in received['messages'])
            assert all('<content' not in c for c in received['messages'])
        finally:
            m.desk = original
