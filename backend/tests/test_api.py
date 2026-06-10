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
    import main as m
    m._request_log.clear()  # reset rate-limit state between tests
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

    def test_db_false_when_no_credentials(self, client):
        data = r = client.get('/api/health').json()
        assert data['db'] is False

    def test_tables_empty_when_no_credentials(self, client):
        data = client.get('/api/health').json()
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
        r = client.get('/api/chats/11111111-1111-1111-1111-111111111111')
        assert r.status_code == 200
        assert r.json() == []


# ── /api/chat ─────────────────────────────────────────────────────────────────

CHAT_PAYLOAD = {
    'prompt': {'content': 'What is the price of AAPL?', 'id': 'msg-1', 'role': 'user'},
    'threadId': '22222222-2222-2222-2222-222222222222',
    'responseId': 'resp-1',
}


class TestChat:
    def _mock_agent_stream(self, tokens: list[str]):
        """Return a mock agent whose stream() yields (AIMessage, {}) pairs."""
        def _stream(*args, **kwargs):
            for t in tokens:
                yield (AIMessage(t), {})

        mock_agent = MagicMock()
        mock_agent.stream.side_effect = _stream
        return mock_agent

    def test_returns_streaming_response(self, client):
        import main as m
        original = m.agent
        m.agent = self._mock_agent_stream(["Hello ", "world!"])
        try:
            r = client.post('/api/chat', json=CHAT_PAYLOAD)
            assert r.status_code == 200
            assert 'text/event-stream' in r.headers['content-type']
        finally:
            m.agent = original

    def test_streams_agent_text(self, client):
        import main as m
        original = m.agent
        m.agent = self._mock_agent_stream(["Stock ", "price: ", "$182"])
        try:
            r = client.post('/api/chat', json=CHAT_PAYLOAD)
            assert b'Stock price: $182' in r.content
        finally:
            m.agent = original

    def test_tool_messages_are_filtered(self, client):
        """ToolMessage tokens should never appear in the response."""
        import main as m
        original = m.agent

        def _stream_with_tool(*args, **kwargs):
            yield (ToolMessage('{"raw": "tool data"}'), {})
            yield (AIMessage('Clean answer'), {})

        mock_agent = MagicMock()
        mock_agent.stream.side_effect = _stream_with_tool
        m.agent = mock_agent

        try:
            r = client.post('/api/chat', json=CHAT_PAYLOAD)
            assert b'tool data' not in r.content
            assert b'Clean answer' in r.content
        finally:
            m.agent = original

    def test_rejects_missing_fields(self, client):
        r = client.post('/api/chat', json={'threadId': 'x'})
        assert r.status_code == 422

    def test_rejects_non_uuid_thread_id(self, client):
        r = client.post('/api/chat', json={**CHAT_PAYLOAD, 'threadId': 'not-a-uuid'})
        assert r.status_code == 422

    def test_rejects_oversized_prompt(self, client):
        import main as m
        big = 'A' * (m.MAX_PROMPT_CHARS + 1)
        r = client.post('/api/chat', json={
            **CHAT_PAYLOAD,
            'prompt': {**CHAT_PAYLOAD['prompt'], 'content': big},
        })
        assert r.status_code == 422

    def test_rate_limit_returns_429(self, client, monkeypatch):
        import main as m
        monkeypatch.setattr(m, 'RATE_LIMIT_MAX', 2)
        original = m.agent
        m.agent = self._mock_agent_stream(['ok'])
        try:
            assert client.post('/api/chat', json=CHAT_PAYLOAD).status_code == 200
            assert client.post('/api/chat', json=CHAT_PAYLOAD).status_code == 200
            assert client.post('/api/chat', json=CHAT_PAYLOAD).status_code == 429
        finally:
            m.agent = original


class TestThreadIdPathValidation:
    def test_get_chat_rejects_non_uuid(self, client):
        """Without a db the endpoint short-circuits, so exercise the validator directly."""
        import main as m
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            m._require_valid_thread_id('../../etc/passwd')
        assert exc.value.status_code == 404

    def test_validator_accepts_uuid(self):
        import main as m
        m._require_valid_thread_id('11111111-1111-1111-1111-111111111111')

    def test_xml_wrapper_stripped_before_agent(self, client):
        """C1Chat wraps user content in <content> — the agent should receive plain text."""
        import main as m
        original = m.agent

        received: list[str] = []

        def _capture_stream(input_dict, **kwargs):
            msgs = input_dict.get('messages', [])
            for msg in msgs:
                if isinstance(msg, AIMessage.__class__):
                    pass
                # Capture HumanMessage content
                received.append(getattr(msg, 'content', ''))
            yield (AIMessage('ok'), {})

        mock_agent = MagicMock()
        mock_agent.stream.side_effect = _capture_stream
        m.agent = mock_agent

        wrapped_payload = {**CHAT_PAYLOAD, 'prompt': {
            **CHAT_PAYLOAD['prompt'],
            'content': '<content thesys="true">What is AAPL?</content>',
        }}

        try:
            client.post('/api/chat', json=wrapped_payload)
            # The HumanMessage content seen by the agent must be stripped
            human_contents = [c for c in received if c]
            assert any('What is AAPL?' in c for c in human_contents)
            assert all('<content' not in c for c in human_contents)
        finally:
            m.agent = original
