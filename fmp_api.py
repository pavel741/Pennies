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
_RATE_DELAY = 1.2
_MAX_RETRIES = 4
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

    for attempt in range(_MAX_RETRIES):
        try:
            _throttle()
            r = requests.get(f"{_BASE}/{endpoint}", params=params, timeout=15)
            if r.status_code == 429:
                backoff = 5 * (2 ** attempt)
                logger.warning(f"FMP rate-limited on {endpoint}, retry {attempt+1}/{_MAX_RETRIES} in {backoff}s")
                time.sleep(backoff)
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(3 * (attempt + 1))
                continue
            logger.warning(f"FMP {endpoint} failed after {_MAX_RETRIES} attempts")
            return None
        except Exception as e:
            logger.warning(f"FMP {endpoint} failed: {e}")
            return None
    logger.warning(f"FMP {endpoint}: exhausted retries (rate-limited)")
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
