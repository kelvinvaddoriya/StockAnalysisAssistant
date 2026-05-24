"""Tests for pure utility functions in main.py (no LLM/DB required)."""
# conftest.py stubs heavy deps before this import
from main import extract_text, strip_thesys_xml, extract_title


# ── extract_text ──────────────────────────────────────────────────────────────

class TestExtractText:
    def test_plain_string(self):
        assert extract_text("hello") == "hello"

    def test_empty_string(self):
        assert extract_text("") == ""

    def test_none_returns_empty(self):
        assert extract_text(None) == ""

    def test_list_of_strings(self):
        assert extract_text(["foo", "bar"]) == "foobar"

    def test_list_of_dicts_text_key(self):
        assert extract_text([{"text": "hello"}, {"text": " world"}]) == "hello world"

    def test_list_of_dicts_content_key(self):
        assert extract_text([{"content": "hi"}]) == "hi"

    def test_list_mixed(self):
        assert extract_text(["A", {"text": "B"}]) == "AB"

    def test_integer_converted(self):
        result = extract_text(42)
        assert result == "42"


# ── strip_thesys_xml ──────────────────────────────────────────────────────────

class TestStripThesysXml:
    def test_no_wrapper_returns_stripped(self):
        assert strip_thesys_xml("  hello  ") == "hello"

    def test_extracts_inner_content(self):
        xml = '<content thesys="true">inner text</content>'
        assert strip_thesys_xml(xml) == "inner text"

    def test_case_insensitive(self):
        xml = '<CONTENT thesys="true">hello</CONTENT>'
        assert strip_thesys_xml(xml) == "hello"

    def test_multiline_inner_content(self):
        xml = '<content thesys="true">\nhello\nworld\n</content>'
        assert strip_thesys_xml(xml) == "hello\nworld"

    def test_strips_inner_whitespace(self):
        xml = '<content thesys="true">  trimmed  </content>'
        assert strip_thesys_xml(xml) == "trimmed"


# ── extract_title ─────────────────────────────────────────────────────────────

class TestExtractTitle:
    def test_dollar_ticker(self):
        assert extract_title("What is $NVDA doing today?") == "NVDA"

    def test_multiple_dollar_tickers(self):
        result = extract_title("Compare $AAPL and $MSFT performance")
        assert "AAPL" in result
        assert "MSFT" in result
        assert " · " in result

    def test_max_three_tickers(self):
        result = extract_title("$AAPL $MSFT $GOOG $TSLA analysis")
        assert result.count(" · ") == 2  # 3 tickers joined by 2 separators

    def test_bare_uppercase_ticker(self):
        result = extract_title("Tell me about TSLA earnings")
        assert "TSLA" in result

    def test_short_text_no_ellipsis(self):
        text = "What is Apple?"
        result = extract_title(text)
        assert not result.endswith("…")

    def test_long_text_gets_ellipsis(self):
        text = "a" * 60
        result = extract_title(text)
        assert result.endswith("…")
        assert len(result) <= 55

    def test_common_words_excluded(self):
        result = extract_title("Is it a good time to buy?")
        # "IS", "IT", "TO" are in _COMMON — should not become the title ticker
        assert result == "Is it a good time to buy?"[:52].strip()
