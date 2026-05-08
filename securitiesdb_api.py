"""
SecuritiesDB API client — free, no API key required.
Provides DCF valuation and quantitative health metrics from SEC filings.
https://securitiesdb.com/developers
"""

import time
import threading
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

_BASE = "https://securitiesdb.com/api/v1"
_RATE_DELAY = 0.7
_MAX_RETRIES = 3
_rate_lock = threading.Lock()
_last_request_time = 0.0


def _throttle():
    global _last_request_time
    with _rate_lock:
        now = time.time()
        wait = _RATE_DELAY - (now - _last_request_time)
        if wait > 0:
            time.sleep(wait)
        _last_request_time = time.time()


def _get(path: str) -> Optional[dict]:
    for attempt in range(_MAX_RETRIES):
        try:
            _throttle()
            r = requests.get(f"{_BASE}/{path}", timeout=15)
            if r.status_code == 429:
                backoff = 3 * (2 ** attempt)
                logger.warning(f"SecuritiesDB rate-limited on {path}, retry {attempt+1}/{_MAX_RETRIES} in {backoff}s")
                time.sleep(backoff)
                continue
            if r.status_code == 404:
                return None
            r.raise_for_status()
            body = r.json()
            return body.get("data")
        except requests.exceptions.HTTPError:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(2 * (attempt + 1))
                continue
            logger.warning(f"SecuritiesDB {path} failed after {_MAX_RETRIES} attempts")
            return None
        except Exception as e:
            logger.warning(f"SecuritiesDB {path} failed: {e}")
            return None
    logger.warning(f"SecuritiesDB {path}: exhausted retries")
    return None


def get_dcf(symbol: str) -> Optional[dict]:
    """Return DCF valuation data.

    Returns dict with keys: fair_value, upside_pct, wacc,
    terminal_growth_rate, implied_growth_rate, sensitivity_matrix.
    """
    data = _get(f"stocks/{symbol}/dcf")
    if not data:
        return None
    dcf = data.get("dcf")
    if not dcf or not dcf.get("fair_value"):
        return None
    dcf["sensitivity_matrix"] = data.get("sensitivity_matrix")
    return dcf


def get_quant_health(symbol: str) -> Optional[dict]:
    """Return quantitative health metrics.

    Returns dict with keys: scores (piotroski, altman_z, beneish_m),
    profitability, growth, leverage, valuation, value_creation, risk.
    """
    data = _get(f"stocks/{symbol}/quant-health")
    if not data:
        return None
    return data


def get_dividends(symbol: str) -> Optional[dict]:
    """Return dividend history summary.

    Returns dict with keys: total_dividends, total_splits,
    consecutive_annual_increases, annual_totals.
    """
    data = _get(f"stocks/{symbol}/dividends")
    if not data:
        return None
    return data.get("summary")


def get_insider_activity(symbol: str) -> Optional[dict]:
    """Return insider transactions and institutional 13F flow.

    Returns dict with keys: insider_transactions (count, net_buy_sell_ratio,
    recent[]), institutional_flow[] (fund, action, shares_change, pct_change).
    """
    data = _get(f"stocks/{symbol}/insider-activity")
    if not data:
        return None
    return data
