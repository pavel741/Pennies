"""
Financial Modeling Prep (FMP) API client for DCF valuation and financial ratios.
Uses the stable API endpoints. Reads FMP_API_KEY from environment.
All functions return None on failure.
"""

import os
import time
import threading
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

_API_KEY: Optional[str] = None
_BASE = "https://financialmodelingprep.com/stable"
_RATE_DELAY = 0.5
_rate_lock = threading.Lock()
_last_request_time = 0.0


def _get_key() -> Optional[str]:
    global _API_KEY
    if _API_KEY is None:
        _API_KEY = os.environ.get("FMP_API_KEY", "")
    return _API_KEY or None


def is_configured() -> bool:
    return _get_key() is not None


def _throttle():
    global _last_request_time
    with _rate_lock:
        now = time.time()
        wait = _RATE_DELAY - (now - _last_request_time)
        if wait > 0:
            time.sleep(wait)
        _last_request_time = time.time()


def _get(endpoint: str, extra_params: dict = None) -> Optional[dict | list]:
    key = _get_key()
    if not key:
        return None
    params = {"apikey": key}
    if extra_params:
        params.update(extra_params)
    try:
        _throttle()
        r = requests.get(f"{_BASE}/{endpoint}", params=params, timeout=15)
        if r.status_code == 429:
            logger.warning("FMP rate-limited, backing off 5s")
            time.sleep(5)
            r = requests.get(f"{_BASE}/{endpoint}", params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"FMP {endpoint} failed: {e}")
        return None


def get_dcf(symbol: str) -> Optional[list[dict]]:
    """
    Returns DCF valuation via the stable endpoint.
    Response: [{symbol, date, dcf, "Stock Price"}]
    """
    return _get("discounted-cash-flow", {"symbol": symbol})


def get_financial_ratios(symbol: str) -> Optional[list[dict]]:
    """
    Returns latest annual financial ratios (1 entry) via the stable endpoint.
    Includes currentRatio, debtToEquityRatio, returnOnEquity, etc.
    """
    return _get("ratios", {"symbol": symbol, "period": "annual", "limit": "1"})


_EXCHANGE_MAP = {
    "NMS": "NASDAQ",
    "NYQ": "NYSE",
    "LSE": "LSE",
    "GER": "XETRA",
    "PAR": "EURONEXT",
    "AMS": "EURONEXT",
    "EBS": "SIX",
    "MCE": "BME",
    "BRU": "EURONEXT",
    "CPH": "CPH",
    "OSL": "OSE",
    "STO": "STO",
    "TOR": "TSX",
}


def screen_stocks(
    exchanges: list[str],
    max_price: float = None,
    size: int = 250,
) -> list[dict]:
    """
    Screen stocks using FMP company-screener endpoint.
    Returns results in a format compatible with Yahoo screener output
    (same keys used by _quick_score in analyzer.py).
    """
    key = _get_key()
    if not key:
        return []

    fmp_exchanges = set()
    for ex in exchanges:
        mapped = _EXCHANGE_MAP.get(ex)
        if mapped:
            fmp_exchanges.add(mapped)

    all_quotes = []
    seen = set()

    for exchange in fmp_exchanges:
        params = {
            "exchange": exchange,
            "isActivelyTrading": "true",
            "limit": str(min(size, 1000)),
        }
        if max_price is not None:
            params["priceLowerThan"] = str(max_price)

        data = _get("company-screener", params)
        if not data or not isinstance(data, list):
            continue

        for item in data:
            sym = item.get("symbol")
            if not sym or sym in seen:
                continue
            seen.add(sym)
            all_quotes.append({
                "symbol": sym,
                "shortName": item.get("companyName", sym),
                "longName": item.get("companyName"),
                "regularMarketPrice": item.get("price"),
                "marketCap": item.get("marketCap"),
                "trailingPE": item.get("pe"),
                "forwardPE": None,
                "priceToBook": None,
                "dividendYield": item.get("lastAnnualDividend", 0) / item["price"]
                    if item.get("lastAnnualDividend") and item.get("price") else None,
                "dividendRate": item.get("lastAnnualDividend"),
                "fiftyDayAverage": None,
                "twoHundredDayAverage": None,
                "sector": item.get("sector"),
                "industry": item.get("industry"),
                "exchange": item.get("exchangeShortName"),
                "country": item.get("country"),
            })

    logger.info(f"FMP screener returned {len(all_quotes)} stocks for {list(fmp_exchanges)}")
    return all_quotes[:size]
