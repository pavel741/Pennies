"""
Data abstraction layer for Pennies.

Provides unified functions that try the best available data source first,
then fall back to alternatives. Caching is handled by the underlying
yahoo_api module (MongoDB TTL cache).

Priority:
  - Historical charts:  Twelve Data (cheap, reliable) -> Yahoo (free, rate-limited)
  - Fundamentals/quote: Yahoo (free, one call) -> Twelve Data + FMP combo
  - Screener:           Yahoo only (no TD equivalent)
  - Dividends:          Yahoo (free) -> Twelve Data
"""

import logging
import pandas as pd
from typing import Optional

logger = logging.getLogger(__name__)


def get_stock_summary(symbol: str) -> dict:
    """
    Fetch comprehensive stock data matching the extract_info() output format.
    Tries Yahoo first (free, returns everything in one call).
    Falls back to Twelve Data quote + profile on Yahoo failure.
    """
    import yahoo_api
    import twelvedata_api

    try:
        summary = yahoo_api.get_quote_summary(symbol)
        if summary:
            info = yahoo_api.extract_info(summary)
            info["_raw_summary"] = summary
            info["_source"] = "yahoo"
            return info
    except Exception as e:
        logger.warning(f"[data_layer] Yahoo summary failed for {symbol}: {e}")

    if not twelvedata_api.is_configured():
        raise RuntimeError(f"Yahoo failed for {symbol} and Twelve Data not configured")

    try:
        quote = twelvedata_api.get_quote(symbol)

        info = {
            "shortName": quote.get("name") or symbol,
            "longName": quote.get("name"),
            "sector": "N/A",
            "industry": "N/A",
            "currency": quote.get("currency") or "USD",
            "currentPrice": quote.get("price"),
            "regularMarketPrice": quote.get("price"),
            "regularMarketChangePercent": quote.get("percent_change"),
            "marketCap": None,
            "trailingPE": None,
            "forwardPE": None,
            "priceToBook": None,
            "dividendYield": None,
            "payoutRatio": None,
            "revenueGrowth": None,
            "profitMargins": None,
            "freeCashflow": None,
            "targetMeanPrice": None,
            "targetMedianPrice": None,
            "targetHighPrice": None,
            "targetLowPrice": None,
            "numberOfAnalystOpinions": None,
            "recommendationMean": None,
            "_source": "twelvedata",
        }

        try:
            import fmp_api
            if fmp_api.is_configured():
                ratios = fmp_api.get_financial_ratios(symbol)
                if ratios:
                    info["trailingPE"] = ratios.get("peRatioTTM")
                    info["priceToBook"] = ratios.get("priceToBookRatioTTM")
                    info["profitMargins"] = ratios.get("netProfitMarginTTM")
                    info["dividendYield"] = ratios.get("dividendYieldTTM")
                    logger.info(f"[data_layer] Enriched {symbol} with FMP ratios")
        except Exception as e:
            logger.warning(f"[data_layer] FMP enrichment failed for {symbol}: {e}")

        return info

    except Exception as e:
        raise RuntimeError(f"All data sources failed for {symbol}: {e}")


def get_raw_summary(symbol: str) -> dict:
    """
    Get the raw Yahoo summary dict (for functions that need it directly).
    Returns empty dict if Yahoo fails.
    """
    import yahoo_api
    try:
        return yahoo_api.get_quote_summary(symbol) or {}
    except Exception:
        return {}


def get_historical(symbol: str, range_str: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """
    Fetch historical OHLCV data. Tries Twelve Data first (cheap),
    falls back to Yahoo.
    """
    import twelvedata_api
    import yahoo_api

    if twelvedata_api.is_configured():
        try:
            df = twelvedata_api.get_historical(symbol, range_str=range_str, interval=interval)
            if not df.empty:
                logger.info(f"[data_layer] Chart for {symbol} from Twelve Data ({len(df)} bars)")
                return df
        except Exception as e:
            logger.warning(f"[data_layer] TD chart failed for {symbol}: {e}")

    try:
        df = yahoo_api.get_chart(symbol, range_str=range_str, interval=interval)
        if not df.empty:
            logger.info(f"[data_layer] Chart for {symbol} from Yahoo ({len(df)} bars)")
        return df
    except Exception as e:
        logger.warning(f"[data_layer] Yahoo chart also failed for {symbol}: {e}")
        return pd.DataFrame()


def get_stock_dividends(symbol: str) -> pd.Series:
    """Fetch dividend history. Tries Yahoo first (free), falls back to Twelve Data."""
    import yahoo_api
    import twelvedata_api

    try:
        divs = yahoo_api.get_dividends(symbol)
        if divs is not None and len(divs) > 0:
            return divs
    except Exception as e:
        logger.warning(f"[data_layer] Yahoo dividends failed for {symbol}: {e}")

    if twelvedata_api.is_configured():
        try:
            divs = twelvedata_api.get_dividends(symbol)
            if divs is not None and len(divs) > 0:
                logger.info(f"[data_layer] Dividends for {symbol} from Twelve Data")
                return divs
        except Exception as e:
            logger.warning(f"[data_layer] TD dividends also failed for {symbol}: {e}")

    return pd.Series(dtype=float)


def screen_stocks(
    exchanges: list[str],
    max_price: float = None,
    size: int = 250,
) -> list[dict]:
    """
    Screen stocks by exchange and price.
    Tries Yahoo first (returns rich data), falls back to FMP screener.
    """
    import yahoo_api
    import fmp_api

    try:
        results = yahoo_api.screen_stocks(exchanges, max_price=max_price, size=size)
        if results:
            return results
    except Exception as e:
        logger.warning(f"[data_layer] Yahoo screener failed: {e}")

    if fmp_api.is_configured():
        try:
            results = fmp_api.screen_stocks(exchanges, max_price=max_price, size=size)
            if results:
                logger.info(f"[data_layer] Screener: {len(results)} stocks from FMP fallback")
                return results
        except Exception as e:
            logger.warning(f"[data_layer] FMP screener also failed: {e}")

    return []
