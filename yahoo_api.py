"""
Direct Yahoo Finance API client using `requests`.
Bypasses yfinance (which requires curl_cffi and has SSL issues on Windows).
"""

import requests
import time
import logging
import hashlib
import json
import pandas as pd
import numpy as np
from typing import Optional
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

CACHE_TTL_MINUTES = 15


def _cache_collection():
    """Return the MongoDB cache collection (lazy, avoids circular imports)."""
    try:
        from models import get_db
        db = get_db()
        return db.api_cache
    except Exception:
        return None


def _ensure_cache_index():
    """Create TTL index on first use so MongoDB auto-deletes expired entries."""
    col = _cache_collection()
    if col is not None:
        try:
            col.create_index("expires_at", expireAfterSeconds=0)
        except Exception:
            pass


_cache_index_created = False


def _cache_get(key: str) -> Optional[dict]:
    """Fetch a cached response by key, or None if missing/expired."""
    global _cache_index_created
    col = _cache_collection()
    if col is None:
        return None
    if not _cache_index_created:
        _ensure_cache_index()
        _cache_index_created = True
    doc = col.find_one({"_id": key, "expires_at": {"$gt": datetime.now(timezone.utc)}})
    if doc:
        logger.info(f"Cache HIT: {key}")
        return doc.get("data")
    return None


def _cache_set(key: str, data, ttl_minutes: int = CACHE_TTL_MINUTES):
    """Store a response in the cache with a TTL."""
    col = _cache_collection()
    if col is None:
        return
    try:
        col.replace_one(
            {"_id": key},
            {
                "_id": key,
                "data": data,
                "expires_at": datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
            },
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"Cache write failed: {e}")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

_session: Optional[requests.Session] = None
_crumb: Optional[str] = None


def _get_session() -> tuple[requests.Session, str]:
    """Return a session with a valid cookie + crumb for Yahoo Finance."""
    global _session, _crumb
    if _session and _crumb:
        return _session, _crumb

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            s = requests.Session()
            s.headers["User-Agent"] = _USER_AGENT

            s.get("https://fc.yahoo.com", timeout=10)
            r = s.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=10)
            r.raise_for_status()
            crumb = r.text.strip()

            _session = s
            _crumb = crumb
            logger.info("Yahoo session established, crumb acquired")
            return s, crumb
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                wait = min(2 ** attempt, 8)
                logger.warning(f"Crumb request rate-limited (attempt {attempt}/{max_retries}), waiting {wait}s")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Yahoo Finance rate limit — please try again in a few minutes")


def reset_session():
    global _session, _crumb
    _session = None
    _crumb = None


def get_quote_summary(symbol: str) -> dict:
    """Fetch quote summary (price, stats, financials, dividends) for a symbol."""
    cache_key = f"quote:{symbol.upper()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    s, crumb = _get_session()
    modules = ",".join([
        "price",
        "defaultKeyStatistics",
        "financialData",
        "summaryDetail",
        "earnings",
    ])
    url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
    params = {"modules": modules, "crumb": crumb}

    r = s.get(url, params=params, timeout=15)
    if r.status_code == 401:
        reset_session()
        s, crumb = _get_session()
        params["crumb"] = crumb
        r = s.get(url, params=params, timeout=15)

    r.raise_for_status()
    data = r.json()
    results = data.get("quoteSummary", {}).get("result")
    if not results:
        return {}
    result = results[0]
    _cache_set(cache_key, result)
    return result


def get_chart(symbol: str, range_str: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """Fetch historical price data and return as a DataFrame."""
    cache_key = f"chart:{symbol.upper()}:{range_str}:{interval}"
    cached = _cache_get(cache_key)
    if cached is not None:
        df = pd.DataFrame(cached["rows"], columns=cached["cols"])
        df.index = pd.to_datetime(cached["index"], utc=True)
        return df

    s, crumb = _get_session()
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {
        "range": range_str,
        "interval": interval,
        "includeAdjustedClose": "true",
        "crumb": crumb,
    }

    r = s.get(url, params=params, timeout=15)
    if r.status_code == 401:
        reset_session()
        s, crumb = _get_session()
        params["crumb"] = crumb
        r = s.get(url, params=params, timeout=15)

    r.raise_for_status()
    data = r.json()

    result = data.get("chart", {}).get("result")
    if not result:
        return pd.DataFrame()

    chart = result[0]
    timestamps = chart.get("timestamp", [])
    quotes = chart.get("indicators", {}).get("quote", [{}])[0]

    if not timestamps:
        return pd.DataFrame()

    df = pd.DataFrame({
        "Close": quotes.get("close", []),
        "Open": quotes.get("open", []),
        "High": quotes.get("high", []),
        "Low": quotes.get("low", []),
        "Volume": quotes.get("volume", []),
    }, index=pd.to_datetime(timestamps, unit="s", utc=True))

    df.dropna(subset=["Close"], inplace=True)
    _cache_set(cache_key, {
        "rows": df.values.tolist(),
        "cols": df.columns.tolist(),
        "index": [str(t) for t in df.index],
    })
    return df


def get_dividends(symbol: str) -> pd.Series:
    """Fetch dividend history for a symbol."""
    s, crumb = _get_session()
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {
        "range": "max",
        "interval": "1mo",
        "events": "div",
        "crumb": crumb,
    }

    r = s.get(url, params=params, timeout=15)
    if r.status_code == 401:
        reset_session()
        s, crumb = _get_session()
        params["crumb"] = crumb
        r = s.get(url, params=params, timeout=15)

    r.raise_for_status()
    data = r.json()

    result = data.get("chart", {}).get("result")
    if not result:
        return pd.Series(dtype=float)

    events = result[0].get("events", {}).get("dividends", {})
    if not events:
        return pd.Series(dtype=float)

    records = []
    for ts, info in events.items():
        records.append({
            "date": pd.to_datetime(info["date"], unit="s", utc=True),
            "amount": info["amount"],
        })

    if not records:
        return pd.Series(dtype=float)

    df = pd.DataFrame(records).set_index("date").sort_index()
    return df["amount"]


_SCREENER_BATCH = 4


def _screen_batch(
    exchanges: list[str],
    max_price: float = None,
    size: int = 250,
) -> list[dict]:
    """Run a single screener request for the given exchanges."""
    s, crumb = _get_session()

    exchange_filters = [
        {"operator": "EQ", "operands": ["exchange", ex]} for ex in exchanges
    ]
    if len(exchange_filters) == 1:
        exchange_operand = exchange_filters[0]
    else:
        exchange_operand = {"operator": "OR", "operands": exchange_filters}

    operands = [exchange_operand]
    if max_price is not None:
        operands.append({"operator": "LT", "operands": ["intradayprice", max_price]})

    body = {
        "offset": 0,
        "size": min(size, 250),
        "sortField": "intradaymarketcap",
        "sortType": "DESC",
        "quoteType": "EQUITY",
        "query": {
            "operator": "AND",
            "operands": operands,
        },
        "userId": "",
        "userIdType": "guid",
    }

    url = "https://query2.finance.yahoo.com/v1/finance/screener"
    params = {"crumb": crumb, "lang": "en-US", "region": "US"}

    all_quotes = []
    offset = 0
    while True:
        body["offset"] = offset
        r = s.post(url, params=params, json=body, timeout=20)

        if r.status_code == 401:
            reset_session()
            s, crumb = _get_session()
            params["crumb"] = crumb
            r = s.post(url, params=params, json=body, timeout=20)

        if r.status_code == 429:
            logger.warning("Screener 429, waiting 3s before retry")
            time.sleep(3)
            r = s.post(url, params=params, json=body, timeout=20)

        r.raise_for_status()
        data = r.json()

        result = data.get("finance", {}).get("result", [])
        if not result:
            break

        quotes = result[0].get("quotes", [])
        total = result[0].get("total", 0)
        all_quotes.extend(quotes)

        offset += len(quotes)
        if offset >= total or offset >= size or not quotes:
            break

    return all_quotes


def screen_stocks(
    exchanges: list[str],
    max_price: float = None,
    size: int = 250,
) -> list[dict]:
    """
    Query the Yahoo Finance screener API to get equities on the given exchanges.
    Batches requests to avoid Yahoo 500 errors when too many exchanges are passed.
    """
    cache_key = f"screen:{','.join(sorted(exchanges))}:{max_price}:{size}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    if len(exchanges) <= _SCREENER_BATCH:
        results = _screen_batch(exchanges, max_price, size)
        logger.info(f"Screener returned {len(results)} stocks for exchanges {exchanges}")
        if results:
            _cache_set(cache_key, results, ttl_minutes=30)
        return results

    all_quotes = []
    seen = set()
    for i in range(0, len(exchanges), _SCREENER_BATCH):
        if i > 0:
            time.sleep(1.5)
        batch = exchanges[i:i + _SCREENER_BATCH]
        per_batch = max(size // ((len(exchanges) + _SCREENER_BATCH - 1) // _SCREENER_BATCH), 100)
        try:
            quotes = _screen_batch(batch, max_price, per_batch)
            for q in quotes:
                sym = q.get("symbol")
                if sym and sym not in seen:
                    seen.add(sym)
                    all_quotes.append(q)
        except Exception as e:
            logger.warning(f"Screener batch {batch} failed: {e}")

    logger.info(f"Screener returned {len(all_quotes)} stocks for exchanges {exchanges}")
    if all_quotes:
        _cache_set(cache_key, all_quotes, ttl_minutes=30)
    return all_quotes


def _raw_val(module_data: dict, key: str):
    """Extract raw value from a Yahoo quoteSummary module field."""
    field = module_data.get(key, {})
    if isinstance(field, dict):
        return field.get("raw")
    return field


def extract_info(summary: dict) -> dict:
    """Flatten a quoteSummary result into a simple dict matching yfinance keys."""
    price = summary.get("price", {})
    stats = summary.get("defaultKeyStatistics", {})
    fin = summary.get("financialData", {})
    detail = summary.get("summaryDetail", {})

    return {
        "shortName": price.get("shortName"),
        "longName": price.get("longName"),
        "sector": _raw_val(price, "sector") if "sector" in price else None,
        "currency": price.get("currency"),
        "currentPrice": _raw_val(fin, "currentPrice"),
        "regularMarketPrice": _raw_val(price, "regularMarketPrice"),
        "revenueGrowth": _raw_val(fin, "revenueGrowth"),
        "profitMargins": _raw_val(fin, "profitMargins"),
        "freeCashflow": _raw_val(fin, "freeCashflow"),
        "marketCap": _raw_val(price, "marketCap"),
        "trailingPE": _raw_val(detail, "trailingPE"),
        "forwardPE": _raw_val(detail, "forwardPE") or _raw_val(stats, "forwardPE"),
        "priceToBook": _raw_val(stats, "priceToBook"),
        "dividendYield": _raw_val(detail, "dividendYield"),
        "payoutRatio": _raw_val(detail, "payoutRatio"),
        "targetMeanPrice": _raw_val(fin, "targetMeanPrice"),
        "targetMedianPrice": _raw_val(fin, "targetMedianPrice"),
        "targetHighPrice": _raw_val(fin, "targetHighPrice"),
        "targetLowPrice": _raw_val(fin, "targetLowPrice"),
        "numberOfAnalystOpinions": _raw_val(fin, "numberOfAnalystOpinions"),
        "recommendationMean": _raw_val(fin, "recommendationMean"),
        "regularMarketChangePercent": _raw_val(price, "regularMarketChangePercent"),
        "sector": price.get("sector") if isinstance(price.get("sector"), str) else "N/A",
        "industry": price.get("industry") if isinstance(price.get("industry"), str) else "N/A",
    }
