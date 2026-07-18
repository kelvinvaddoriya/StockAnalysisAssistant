"""
Market-data tools — thin wrappers over yfinance.

Single source of truth for the four tools the desk shares. main.py imports these
too, so the legacy single-agent path and the new desk use identical tools.

Contract: never raise on user input. On missing data, return a human-readable
"no data" string so the calling agent can recover (e.g. retry with a suffix).
"""
import yfinance as yf
from langchain_core.tools import tool

_TICKER_HELP = (
    'Use the Yahoo Finance ticker convention: US-listed stocks use the plain '
    'symbol (AAPL, MSFT). Non-US listings require an exchange suffix — examples: '
    'India NSE ".NS" (RELIANCE.NS, TCS.NS), India BSE ".BO", London ".L" '
    '(BARC.L), Tokyo ".T" (7203.T), Hong Kong ".HK" (0700.HK), Frankfurt ".DE" '
    '(SAP.DE), Paris ".PA", Toronto ".TO", Australia ".AX". '
    'If a call returns "no data", retry once with the most likely exchange suffix '
    'based on the company\'s primary listing.'
)


@tool('get_stock_price',
      description='Returns the current closing price for a ticker symbol. ' + _TICKER_HELP)
def get_stock_price(ticker: str):
    hist = yf.Ticker(ticker).history()
    if hist.empty:
        return f'No data for ticker "{ticker}". If this is a non-US stock, retry with the exchange suffix (e.g. .NS, .L, .T, .HK).'
    return float(hist['Close'].iloc[-1])


@tool('get_historical_stock_price',
      description='Returns the closing price history between two ISO dates (YYYY-MM-DD). ' + _TICKER_HELP)
def get_historical_stock_price(ticker: str, start_date: str, end_date: str):
    hist = yf.Ticker(ticker).history(start=start_date, end=end_date)
    if hist.empty:
        return f'No data for ticker "{ticker}" between {start_date} and {end_date}. If non-US, retry with exchange suffix.'
    return hist['Close'].to_dict()


@tool('get_balance_sheet',
      description='Returns the latest balance sheet for a ticker symbol. ' + _TICKER_HELP)
def get_balance_sheet(ticker: str):
    bs = yf.Ticker(ticker).balance_sheet
    if bs.empty:
        return f'No balance sheet data for "{ticker}". If non-US, retry with exchange suffix.'
    return bs.to_dict()


@tool('get_stock_news',
      description='Returns recent news articles for a ticker symbol. ' + _TICKER_HELP)
def get_stock_news(ticker: str):
    news = yf.Ticker(ticker).news
    if not news:
        return f'No news for "{ticker}". If non-US, retry with exchange suffix.'
    return news


ALL_TOOLS = [get_stock_price, get_historical_stock_price, get_balance_sheet, get_stock_news]
