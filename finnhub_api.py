"""
Finnhub API client for analyst recommendations, earnings surprises, and insider transactions.
Reads FINNHUB_API_KEY from environment. All functions return None on failure.
"""

import os
import time
import threading
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

_API_KEY: Optional[str] = None
_BASE = "https://finnhub.io/api/v1"
_RATE_DELAY = 1.1  # Finnhub free tier: 60 req/min
_rate_lock = threading.Lock()
_last_request_time = 0.0


def _get_key() -> Optional[str]:
    global _API_KEY
    if _API_KEY is None:
        _API_KEY = os.environ.get("FINNHUB_API_KEY", "")
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


def _get(endpoint: str, params: dict) -> Optional[dict | list]:
    key = _get_key()
    if not key:
        return None
    params["token"] = key
    try:
        _throttle()
        r = requests.get(f"{_BASE}{endpoint}", params=params, timeout=15)
        if r.status_code == 429:
            logger.warning("Finnhub rate-limited, backing off 5s")
            time.sleep(5)
            r = requests.get(f"{_BASE}{endpoint}", params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"Finnhub {endpoint} failed: {e}")
        return None


def get_recommendation_trend(symbol: str) -> Optional[list[dict]]:
    """
    Returns list of monthly recommendation aggregates, most recent first.
    Each entry: {buy, hold, sell, strongBuy, strongSell, period}
    """
    return _get("/stock/recommendation", {"symbol": symbol})


def get_earnings_surprises(symbol: str) -> Optional[list[dict]]:
    """
    Returns list of quarterly earnings with actual vs estimate.
    Each entry: {actual, estimate, period, quarter, surprise, surprisePercent, symbol, year}
    """
    return _get("/stock/earnings", {"symbol": symbol})


def get_insider_transactions(symbol: str) -> Optional[dict]:
    """
    Returns insider transaction data.
    Response: {data: [{name, share, change, transactionDate, ...}], symbol}
    """
    return _get("/stock/insider-transactions", {"symbol": symbol})


def get_company_news(symbol: str, days_back: int = 7) -> Optional[list[dict]]:
    """
    Returns recent company news articles.
    Each entry: {category, datetime, headline, id, image, related, source, summary, url}
    """
    from datetime import datetime, timedelta
    today = datetime.now()
    from_date = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")
    return _get("/company-news", {"symbol": symbol, "from": from_date, "to": to_date})
