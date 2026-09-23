"""Tests for the market-data tools.

conftest.py stubs `yfinance` with a MagicMock and `@tool` with a passthrough,
so the tool functions are callable directly and every Yahoo call is countable.
"""
from unittest.mock import MagicMock

import yfinance as yf          # the conftest stub

from agents.tools import get_stock_price, get_balance_sheet


def _price_ticker(close: float) -> MagicMock:
    """A yf.Ticker whose .history() returns one non-empty Close row."""
    hist = MagicMock()
    hist.empty = False
    hist.__getitem__.return_value.iloc.__getitem__.return_value = close
    ticker = MagicMock()
    ticker.history.return_value = hist
    return ticker


class TestTtlCache:
    def test_repeat_call_does_not_refetch(self):
        # The whole point: three specialists asking for the same ticker in
        # parallel must hit Yahoo once, not three times.
        yf.Ticker = MagicMock(return_value=_price_ticker(101.5))
        assert get_stock_price('CACHE1') == 101.5
        assert get_stock_price('CACHE1') == 101.5
        assert yf.Ticker.call_count == 1

    def test_different_ticker_refetches(self):
        yf.Ticker = MagicMock(return_value=_price_ticker(7.0))
        get_stock_price('CACHE2')
        get_stock_price('CACHE3')
        assert yf.Ticker.call_count == 2

    def test_cache_is_per_tool(self):
        bs = MagicMock()
        bs.empty = False
        bs.to_dict.return_value = {'assets': 1}
        yf.Ticker = MagicMock(return_value=MagicMock(balance_sheet=bs))
        # Same ticker as a cached price lookup — must not collide across tools.
        assert get_balance_sheet('CACHE1') == {'assets': 1}
        assert yf.Ticker.call_count == 1


class TestNoDataPath:
    def test_empty_history_returns_hint_not_raise(self):
        empty = MagicMock()
        empty.empty = True
        yf.Ticker = MagicMock(return_value=MagicMock(**{'history.return_value': empty}))
        result = get_stock_price('NODATA1')
        assert isinstance(result, str)
        assert 'No data' in result
