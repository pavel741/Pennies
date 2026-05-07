"""Twelve Data API client for Pennies."""

import os
import time
import logging
import requests
import pandas as pd
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_BASE = "https://api.twelvedata.com"
_API_KEY = None
_last_call = 0.0
_MIN_INTERVAL = 0.5

_RANGE_TO_OUTPUTSIZE = {
    "5d": 5,
    "1mo": 22,
    "3mo": 66,
    "6mo": 126,
    "1y": 252,
    "2y": 504,
    "5y": 1260,
}

_EXCHANGE_MAP = {
    "NMS": "NASDAQ",
    "NYQ": "NYSE",
    "LSE": "LSE",
    "GER": "XETR",
    "PAR": "Euronext",
    "AMS": "Euronext",
    "EBS": "SIX",
    "MCE": "BME",
    "BRU": "Euronext",
    "CPH": "Copenhagen",
    "OSL": "OSE",
    "STO": "Stockholm",
    "TOR": "TSX",
}


def _get_key() -> Optional[str]:
    global _API_KEY
    if _API_KEY is None:
        _API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")
    return _API_KEY or None


def is_configured() -> bool:
    return _get_key() is not None


def _throttle():
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_call = time.time()


def _request(endpoint: str, params: dict, timeout: int = 15) -> dict:
    key = _get_key()
    if not key:
        raise RuntimeError("TWELVE_DATA_API_KEY not configured")
    params["apikey"] = key
    _throttle()
    url = f"{_BASE}/{endpoint}"
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if data.get("status") == "error":
        raise RuntimeError(f"Twelve Data error: {data.get('message', 'unknown')}")
    return data


def get_quote(symbol: str) -> dict:
    """Current quote: price, volume, change, name, exchange."""
    data = _request("quote", {
        "symbol": symbol,
        "interval": "1day",
    })
    return {
        "symbol": data.get("symbol", symbol),
        "name": data.get("name", ""),
        "exchange": data.get("exchange", ""),
        "currency": data.get("currency", "USD"),
        "price": _float(data.get("close")),
        "open": _float(data.get("open")),
        "high": _float(data.get("high")),
        "low": _float(data.get("low")),
        "volume": _int(data.get("volume")),
        "previous_close": _float(data.get("previous_close")),
        "change": _float(data.get("change")),
        "percent_change": _float(data.get("percent_change")),
        "fifty_two_week_high": _float(data.get("fifty_two_week", {}).get("high")),
        "fifty_two_week_low": _float(data.get("fifty_two_week", {}).get("low")),
        "average_volume": _int(data.get("average_volume")),
    }


def get_time_series(
    symbol: str,
    interval: str = "1day",
    outputsize: int = 252,
) -> pd.DataFrame:
    """Historical OHLCV data as a DataFrame."""
    data = _request("time_series", {
        "symbol": symbol,
        "interval": interval,
        "outputsize": min(outputsize, 5000),
        "order": "ASC",
    })
    values = data.get("values", [])
    if not values:
        return pd.DataFrame()

    rows = []
    for v in values:
        rows.append({
            "Close": _float(v.get("close")),
            "Open": _float(v.get("open")),
            "High": _float(v.get("high")),
            "Low": _float(v.get("low")),
            "Volume": _int(v.get("volume")),
        })

    df = pd.DataFrame(rows, index=pd.to_datetime(
        [v["datetime"] for v in values], utc=True
    ))
    df.dropna(subset=["Close"], inplace=True)
    return df


def get_historical(symbol: str, range_str: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """Match yahoo_api.get_chart interface: range_str like '1y', interval like '1d'."""
    td_interval = interval.replace("d", "day").replace("wk", "week").replace("mo", "month")
    if td_interval == "1day":
        pass
    elif "min" in td_interval or "h" in td_interval:
        pass
    else:
        td_interval = "1day"

    outputsize = _RANGE_TO_OUTPUTSIZE.get(range_str, 252)
    return get_time_series(symbol, interval=td_interval, outputsize=outputsize)


def get_profile(symbol: str) -> dict:
    """Company profile: sector, industry, name, description."""
    data = _request("profile", {"symbol": symbol})
    return {
        "name": data.get("name", ""),
        "sector": data.get("sector", "N/A"),
        "industry": data.get("industry", "N/A"),
        "exchange": data.get("exchange", ""),
        "country": data.get("country", ""),
        "currency": data.get("currency", "USD"),
        "description": data.get("description", ""),
        "employees": data.get("employees"),
        "ceo": data.get("CEO", ""),
    }


def get_dividends(symbol: str) -> pd.Series:
    """Dividend history as a Series of amounts indexed by date."""
    data = _request("dividends", {
        "symbol": symbol,
        "range": "full",
    })
    divs = data.get("dividends", [])
    if not divs:
        return pd.Series(dtype=float)

    records = []
    for d in divs:
        try:
            records.append({
                "date": pd.to_datetime(d["ex_date"], utc=True),
                "amount": float(d["amount"]),
            })
        except (KeyError, ValueError):
            continue

    if not records:
        return pd.Series(dtype=float)

    df = pd.DataFrame(records).set_index("date").sort_index()
    return df["amount"]


def get_statistics(symbol: str) -> dict:
    """Key statistics: P/E, market cap, margins, etc. (50 credits per call)."""
    data = _request("statistics", {"symbol": symbol})

    stats = data.get("statistics", {})
    valuations = stats.get("valuations_metrics", {})
    financials = stats.get("financials", {})
    stock_stats = stats.get("stock_statistics", {})

    return {
        "marketCap": _float(valuations.get("market_capitalization")),
        "trailingPE": _float(valuations.get("trailing_pe")),
        "forwardPE": _float(valuations.get("forward_pe")),
        "priceToBook": _float(valuations.get("price_to_book_mrq")),
        "profitMargins": _float(financials.get("profit_margin")),
        "revenueGrowth": _float(financials.get("quarterly_revenue_growth")),
        "dividendYield": _float(stock_stats.get("dividend_yield_indicated_annual")),
        "payoutRatio": _float(financials.get("payout_ratio")),
        "freeCashflow": None,
    }


def _float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return f if f == f else None  # NaN check
    except (TypeError, ValueError):
        return None


def _int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None
