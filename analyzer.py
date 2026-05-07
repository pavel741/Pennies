"""
Stock Analyzer Engine
Scores stocks on: Fundamentals, Valuation, Dividends, and Technicals.
"""

import time
import threading
import logging
import json
import os

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import data_layer
import finnhub_api
import fmp_api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
_RATE_DELAY = 0.6
_MAX_WORKERS = 4
_MAX_RETRIES = 2
_RETRY_BACKOFF = 3.0
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


# ---------------------------------------------------------------------------
# Disk cache (30 min TTL)
# ---------------------------------------------------------------------------
_CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
_CACHE_TTL = 60 * 30

os.makedirs(_CACHE_DIR, exist_ok=True)


def _cache_path(symbol: str) -> str:
    return os.path.join(_CACHE_DIR, f"{symbol}.json")


def _read_cache(symbol: str) -> Optional[dict]:
    path = _cache_path(symbol)
    try:
        if os.path.exists(path):
            age = time.time() - os.path.getmtime(path)
            if age < _CACHE_TTL:
                with open(path, "r") as f:
                    return json.load(f)
    except Exception:
        pass
    return None


def _write_cache(symbol: str, data: dict):
    try:
        with open(_cache_path(symbol), "w") as f:
            json.dump(data, f)
    except Exception:
        pass


MARKETS = {
    "us":          {"label": "US",          "exchanges": ["NMS", "NYQ"]},
    "uk":          {"label": "UK",          "exchanges": ["LSE"]},
    "germany":     {"label": "Germany",     "exchanges": ["GER"]},
    "france":      {"label": "France",      "exchanges": ["PAR"]},
    "netherlands": {"label": "Netherlands", "exchanges": ["AMS"]},
    "switzerland": {"label": "Switzerland", "exchanges": ["EBS"]},
    "spain":       {"label": "Spain",       "exchanges": ["MCE"]},
    "belgium":     {"label": "Belgium",     "exchanges": ["BRU"]},
    "nordics":     {"label": "Nordics",     "exchanges": ["CPH", "OSL", "STO"]},
    "canada":      {"label": "Canada",      "exchanges": ["TOR"]},
}

MARKET_LIST = list(MARKETS.keys())

_SCREENER_SIZE = 750
_QUICK_TOP_N = 30


@dataclass
class ScoreBreakdown:
    score: float = 0.0
    max_score: float = 0.0
    details: list = field(default_factory=list)

    @property
    def pct(self) -> float:
        return (self.score / self.max_score * 100) if self.max_score else 0


@dataclass
class StockReport:
    ticker: str
    name: str
    sector: str
    industry: str
    price: float
    currency: str
    fundamentals: ScoreBreakdown
    valuation: ScoreBreakdown
    dividends: ScoreBreakdown
    technicals: ScoreBreakdown
    sentiment: Optional[ScoreBreakdown] = None
    fair_value: Optional[ScoreBreakdown] = None
    prediction: Optional[dict] = None
    error: Optional[str] = None

    @property
    def _active_parts(self) -> list[ScoreBreakdown]:
        base = [self.fundamentals, self.valuation, self.dividends, self.technicals]
        if self.sentiment and self.sentiment.max_score > 0:
            base.append(self.sentiment)
        if self.fair_value and self.fair_value.max_score > 0:
            base.append(self.fair_value)
        return base

    @property
    def total_score(self) -> float:
        return sum(p.score for p in self._active_parts)

    @property
    def max_total(self) -> float:
        return sum(p.max_score for p in self._active_parts)

    @property
    def overall_pct(self) -> float:
        return (self.total_score / self.max_total * 100) if self.max_total else 0

    @property
    def rating(self) -> str:
        pct = self.overall_pct
        if pct >= 75:
            return "Strong Buy"
        if pct >= 60:
            return "Buy"
        if pct >= 45:
            return "Hold"
        if pct >= 30:
            return "Underperform"
        return "Sell"

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "sector": self.sector,
            "industry": self.industry,
            "price": self.price,
            "currency": self.currency,
            "overall_pct": round(self.overall_pct, 1),
            "total_score": round(self.total_score, 1),
            "max_total": round(self.max_total, 1),
            "rating": self.rating,
            "fundamentals": {
                "score": round(self.fundamentals.score, 1),
                "max": round(self.fundamentals.max_score, 1),
                "pct": round(self.fundamentals.pct, 1),
                "details": self.fundamentals.details,
            },
            "valuation": {
                "score": round(self.valuation.score, 1),
                "max": round(self.valuation.max_score, 1),
                "pct": round(self.valuation.pct, 1),
                "details": self.valuation.details,
            },
            "dividends": {
                "score": round(self.dividends.score, 1),
                "max": round(self.dividends.max_score, 1),
                "pct": round(self.dividends.pct, 1),
                "details": self.dividends.details,
            },
            "technicals": {
                "score": round(self.technicals.score, 1),
                "max": round(self.technicals.max_score, 1),
                "pct": round(self.technicals.pct, 1),
                "details": self.technicals.details,
            },
            "sentiment": {
                "score": round(self.sentiment.score, 1),
                "max": round(self.sentiment.max_score, 1),
                "pct": round(self.sentiment.pct, 1),
                "details": self.sentiment.details,
            } if self.sentiment and self.sentiment.max_score > 0 else None,
            "fair_value": {
                "score": round(self.fair_value.score, 1),
                "max": round(self.fair_value.max_score, 1),
                "pct": round(self.fair_value.pct, 1),
                "details": self.fair_value.details,
            } if self.fair_value and self.fair_value.max_score > 0 else None,
            "prediction": self.prediction,
            "error": self.error,
        }


def _safe(val):
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Quick scoring from screener data (no per-stock API calls)
# Max 100 pts: Valuation 35, Dividends 20, Momentum 25, Size 20
# ---------------------------------------------------------------------------
def _quick_score(quote: dict) -> float:
    score = 0.0

    pe = _safe(quote.get("trailingPE"))
    if pe is not None and pe > 0:
        if pe < 15:
            score += 15
        elif pe < 20:
            score += 12
        elif pe < 30:
            score += 8
        elif pe < 50:
            score += 4
        else:
            score += 1

    fpe = _safe(quote.get("forwardPE"))
    if fpe is not None and fpe > 0:
        if fpe < 12:
            score += 10
        elif fpe < 18:
            score += 8
        elif fpe < 25:
            score += 5
        elif fpe < 40:
            score += 2

    pb = _safe(quote.get("priceToBook"))
    if pb is not None and pb > 0:
        if pb < 1.5:
            score += 10
        elif pb < 3:
            score += 8
        elif pb < 5:
            score += 5
        elif pb < 10:
            score += 2

    div_yield = _safe(quote.get("dividendYield"))
    if div_yield is not None and div_yield > 0:
        if div_yield > 4:
            score += 12
        elif div_yield > 2.5:
            score += 9
        elif div_yield > 1:
            score += 6
        else:
            score += 3

    div_rate = _safe(quote.get("dividendRate"))
    if div_rate is not None and div_rate > 0:
        score += 8

    price = _safe(quote.get("regularMarketPrice"))
    sma50 = _safe(quote.get("fiftyDayAverage"))
    sma200 = _safe(quote.get("twoHundredDayAverage"))

    if price and sma50 and sma50 > 0:
        pct50 = (price - sma50) / sma50 * 100
        if pct50 > 5:
            score += 13
        elif pct50 > 0:
            score += 10
        elif pct50 > -5:
            score += 6
        else:
            score += 2

    if price and sma200 and sma200 > 0:
        pct200 = (price - sma200) / sma200 * 100
        if pct200 > 10:
            score += 12
        elif pct200 > 0:
            score += 9
        elif pct200 > -5:
            score += 5
        else:
            score += 1

    mcap = _safe(quote.get("marketCap"))
    if mcap is not None:
        if mcap > 200e9:
            score += 20
        elif mcap > 50e9:
            score += 16
        elif mcap > 10e9:
            score += 12
        elif mcap > 2e9:
            score += 8
        else:
            score += 4

    return score


# ---------------------------------------------------------------------------
# 1. Fundamentals  (max 25 pts)
# ---------------------------------------------------------------------------
def _score_fundamentals(info: dict) -> ScoreBreakdown:
    sb = ScoreBreakdown(max_score=25)

    rev_growth = _safe(info.get("revenueGrowth"))
    if rev_growth is not None:
        rg_pct = rev_growth * 100
        if rg_pct > 20:
            pts = 8
        elif rg_pct > 10:
            pts = 6
        elif rg_pct > 0:
            pts = 4
        elif rg_pct > -5:
            pts = 2
        else:
            pts = 0
        sb.score += pts
        sb.details.append({"label": "Revenue Growth (YoY)", "value": f"{rg_pct:+.1f}%", "pts": pts, "max": 8})
    else:
        sb.details.append({"label": "Revenue Growth (YoY)", "value": "N/A", "pts": 0, "max": 8})

    margin = _safe(info.get("profitMargins"))
    if margin is not None:
        m_pct = margin * 100
        if m_pct > 20:
            pts = 9
        elif m_pct > 10:
            pts = 7
        elif m_pct > 5:
            pts = 5
        elif m_pct > 0:
            pts = 3
        else:
            pts = 1
        sb.score += pts
        sb.details.append({"label": "Profit Margin", "value": f"{m_pct:.1f}%", "pts": pts, "max": 9})
    else:
        sb.details.append({"label": "Profit Margin", "value": "N/A", "pts": 0, "max": 9})

    fcf = _safe(info.get("freeCashflow"))
    mcap = _safe(info.get("marketCap"))
    if fcf is not None and mcap and mcap > 0:
        fcf_yield = fcf / mcap * 100
        if fcf_yield > 8:
            pts = 8
        elif fcf_yield > 5:
            pts = 6
        elif fcf_yield > 2:
            pts = 4
        elif fcf_yield > 0:
            pts = 2
        else:
            pts = 0
        sb.score += pts
        sb.details.append({"label": "FCF Yield", "value": f"{fcf_yield:.1f}%", "pts": pts, "max": 8})
    else:
        sb.details.append({"label": "FCF Yield", "value": "N/A", "pts": 0, "max": 8})

    return sb


# ---------------------------------------------------------------------------
# 2. Valuation  (max 25 pts)
# ---------------------------------------------------------------------------
def _score_valuation(info: dict) -> ScoreBreakdown:
    sb = ScoreBreakdown(max_score=25)

    pe = _safe(info.get("trailingPE"))
    if pe is not None:
        if pe < 0:
            pts = 0
        elif pe < 15:
            pts = 9
        elif pe < 20:
            pts = 7
        elif pe < 30:
            pts = 5
        elif pe < 50:
            pts = 3
        else:
            pts = 1
        sb.score += pts
        sb.details.append({"label": "Trailing P/E", "value": f"{pe:.1f}", "pts": pts, "max": 9})
    else:
        sb.details.append({"label": "Trailing P/E", "value": "N/A", "pts": 0, "max": 9})

    fpe = _safe(info.get("forwardPE"))
    if fpe is not None:
        if fpe < 0:
            pts = 0
        elif fpe < 12:
            pts = 8
        elif fpe < 18:
            pts = 6
        elif fpe < 25:
            pts = 4
        elif fpe < 40:
            pts = 2
        else:
            pts = 1
        sb.score += pts
        sb.details.append({"label": "Forward P/E", "value": f"{fpe:.1f}", "pts": pts, "max": 8})
    else:
        sb.details.append({"label": "Forward P/E", "value": "N/A", "pts": 0, "max": 8})

    pb = _safe(info.get("priceToBook"))
    if pb is not None:
        if pb < 0:
            pts = 0
        elif pb < 1.5:
            pts = 8
        elif pb < 3:
            pts = 6
        elif pb < 5:
            pts = 4
        elif pb < 10:
            pts = 2
        else:
            pts = 1
        sb.score += pts
        sb.details.append({"label": "Price / Book", "value": f"{pb:.2f}", "pts": pts, "max": 8})
    else:
        sb.details.append({"label": "Price / Book", "value": "N/A", "pts": 0, "max": 8})

    return sb


# ---------------------------------------------------------------------------
# 3. Dividends  (max 25 pts)
# ---------------------------------------------------------------------------
def _score_dividends(info: dict, symbol: str) -> ScoreBreakdown:
    sb = ScoreBreakdown(max_score=25)

    div_yield = _safe(info.get("dividendYield"))
    dy_pct = div_yield * 100 if div_yield is not None else None

    if dy_pct is not None and dy_pct > 0:
        if dy_pct > 4:
            pts = 8
        elif dy_pct > 2.5:
            pts = 6
        elif dy_pct > 1:
            pts = 4
        else:
            pts = 2
        sb.score += pts
        sb.details.append({"label": "Dividend Yield", "value": f"{dy_pct:.2f}%", "pts": pts, "max": 8})
    else:
        sb.details.append({"label": "Dividend Yield", "value": "None", "pts": 0, "max": 8})

    payout = _safe(info.get("payoutRatio"))
    if payout is not None:
        pr_pct = payout * 100
        if 0 < pr_pct <= 40:
            pts = 8
        elif pr_pct <= 60:
            pts = 6
        elif pr_pct <= 80:
            pts = 4
        elif pr_pct <= 100:
            pts = 2
        else:
            pts = 0
        sb.score += pts
        sb.details.append({"label": "Payout Ratio", "value": f"{pr_pct:.0f}%", "pts": pts, "max": 8})
    else:
        sb.details.append({"label": "Payout Ratio", "value": "N/A", "pts": 0, "max": 8})

    try:
        _throttle()
        divs = data_layer.get_stock_dividends(symbol)
        if divs is not None and len(divs) > 0:
            years_with_divs = divs.index.year.nunique()
            if years_with_divs >= 15:
                pts = 9
            elif years_with_divs >= 10:
                pts = 7
            elif years_with_divs >= 5:
                pts = 5
            elif years_with_divs >= 2:
                pts = 3
            else:
                pts = 1
            sb.score += pts
            sb.details.append({"label": "Dividend History", "value": f"{years_with_divs} yrs", "pts": pts, "max": 9})
        else:
            sb.details.append({"label": "Dividend History", "value": "None", "pts": 0, "max": 9})
    except Exception:
        sb.details.append({"label": "Dividend History", "value": "N/A", "pts": 0, "max": 9})

    return sb


# ---------------------------------------------------------------------------
# 4. Technicals  (max 25 pts)
# ---------------------------------------------------------------------------
def _score_technicals(hist: pd.DataFrame) -> ScoreBreakdown:
    sb = ScoreBreakdown(max_score=25)

    if hist is None or hist.empty or len(hist) < 50:
        sb.details.append({"label": "Technical Analysis", "value": "Insufficient data", "pts": 0, "max": 25})
        return sb

    close = hist["Close"].squeeze() if isinstance(hist["Close"], pd.DataFrame) else hist["Close"]
    current = close.iloc[-1]

    sma50 = close.rolling(50).mean()
    if len(sma50.dropna()) > 0:
        sma50_val = sma50.iloc[-1]
        above_50 = current > sma50_val
        pct_diff_50 = (current - sma50_val) / sma50_val * 100
        if above_50 and pct_diff_50 > 5:
            pts = 7
        elif above_50:
            pts = 5
        elif pct_diff_50 > -5:
            pts = 3
        else:
            pts = 1
        sb.score += pts
        direction = "above" if above_50 else "below"
        sb.details.append({
            "label": "Price vs SMA-50",
            "value": f"{pct_diff_50:+.1f}% ({direction})",
            "pts": pts, "max": 7,
        })

    if len(close) >= 200:
        sma200 = close.rolling(200).mean()
        if len(sma200.dropna()) > 0:
            sma200_val = sma200.iloc[-1]
            above_200 = current > sma200_val
            pct_diff_200 = (current - sma200_val) / sma200_val * 100
            if above_200 and pct_diff_200 > 10:
                pts = 7
            elif above_200:
                pts = 5
            elif pct_diff_200 > -5:
                pts = 3
            else:
                pts = 1
            sb.score += pts
            direction = "above" if above_200 else "below"
            sb.details.append({
                "label": "Price vs SMA-200",
                "value": f"{pct_diff_200:+.1f}% ({direction})",
                "pts": pts, "max": 7,
            })
    else:
        sb.details.append({"label": "Price vs SMA-200", "value": "Not enough data", "pts": 0, "max": 7})

    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    if len(rsi.dropna()) > 0:
        rsi_val = rsi.iloc[-1]
        if 40 <= rsi_val <= 60:
            pts = 6
        elif 30 <= rsi_val < 40 or 60 < rsi_val <= 70:
            pts = 4
        elif rsi_val < 30:
            pts = 3
        else:
            pts = 1
        sb.score += pts
        sb.details.append({"label": "RSI (14)", "value": f"{rsi_val:.1f}", "pts": pts, "max": 6})

    high_52 = close[-252:].max() if len(close) >= 252 else close.max()
    low_52 = close[-252:].min() if len(close) >= 252 else close.min()
    if high_52 != low_52:
        range_pos = (current - low_52) / (high_52 - low_52) * 100
        if 30 <= range_pos <= 70:
            pts = 5
        elif 20 <= range_pos < 30 or 70 < range_pos <= 85:
            pts = 3
        else:
            pts = 1
        sb.score += pts
        sb.details.append({
            "label": "52-Week Range Position",
            "value": f"{range_pos:.0f}%",
            "pts": pts, "max": 5,
        })

    return sb


# ---------------------------------------------------------------------------
# 5. Sentiment & Signals  (max 25 pts) — Finnhub
# ---------------------------------------------------------------------------
def _fetch_finnhub(symbol: str) -> Optional[dict]:
    """Fetch all Finnhub data for a symbol in one pass."""
    if not finnhub_api.is_configured():
        return None
    return {
        "recs": finnhub_api.get_recommendation_trend(symbol),
        "earnings": finnhub_api.get_earnings_surprises(symbol),
        "insider": finnhub_api.get_insider_transactions(symbol),
    }


def _fetch_fmp(symbol: str) -> Optional[dict]:
    """Fetch all FMP data for a symbol in one pass."""
    if not fmp_api.is_configured():
        return None
    return {
        "dcf": fmp_api.get_dcf(symbol),
        "ratios": fmp_api.get_financial_ratios(symbol),
    }


def _score_sentiment(fh_data: Optional[dict]) -> Optional[ScoreBreakdown]:
    if fh_data is None:
        return None

    sb = ScoreBreakdown(max_score=25)

    # --- Analyst recommendation trend (max 8) ---
    recs = fh_data["recs"]
    if recs and len(recs) >= 1:
        latest = recs[0]
        strong_buy = latest.get("strongBuy", 0)
        buy = latest.get("buy", 0)
        hold = latest.get("hold", 0)
        sell = latest.get("sell", 0)
        strong_sell = latest.get("strongSell", 0)
        total = strong_buy + buy + hold + sell + strong_sell
        if total > 0:
            bullish_pct = (strong_buy + buy) / total * 100
            if bullish_pct >= 70:
                pts = 8
            elif bullish_pct >= 50:
                pts = 6
            elif bullish_pct >= 30:
                pts = 4
            else:
                pts = 2
            sb.score += pts
            sb.details.append({
                "label": "Analyst Consensus",
                "value": f"{bullish_pct:.0f}% bullish ({total} analysts)",
                "pts": pts, "max": 8,
            })
        else:
            sb.details.append({"label": "Analyst Consensus", "value": "No data", "pts": 0, "max": 8})
    else:
        sb.details.append({"label": "Analyst Consensus", "value": "N/A", "pts": 0, "max": 8})

    # --- Earnings surprises (max 9) ---
    earnings = fh_data["earnings"]
    if earnings and len(earnings) >= 1:
        recent = earnings[:4]
        beats = sum(1 for e in recent if (e.get("surprisePercent") or 0) > 0)
        avg_surprise = 0
        valid = [e for e in recent if e.get("surprisePercent") is not None]
        if valid:
            avg_surprise = sum(e["surprisePercent"] for e in valid) / len(valid)

        if beats == 4:
            pts = 9
        elif beats == 3:
            pts = 7
        elif beats == 2:
            pts = 5
        elif beats == 1:
            pts = 3
        else:
            pts = 1
        sb.score += pts
        sb.details.append({
            "label": "Earnings Surprises",
            "value": f"{beats}/{len(recent)} beats (avg {avg_surprise:+.1f}%)",
            "pts": pts, "max": 9,
        })
    else:
        sb.details.append({"label": "Earnings Surprises", "value": "N/A", "pts": 0, "max": 9})

    # --- Insider transactions (max 8) ---
    insider_data = fh_data["insider"]
    if insider_data and isinstance(insider_data, dict):
        txns = insider_data.get("data", [])
        if txns:
            net_shares = sum(t.get("change", 0) for t in txns[:20])
            if net_shares > 0:
                pts = 8
                signal = "Net buying"
            elif net_shares == 0:
                pts = 4
                signal = "Neutral"
            else:
                pts = 2
                signal = "Net selling"
            sb.score += pts
            sb.details.append({
                "label": "Insider Activity",
                "value": f"{signal} ({net_shares:+,.0f} shares)",
                "pts": pts, "max": 8,
            })
        else:
            sb.details.append({"label": "Insider Activity", "value": "No recent activity", "pts": 4, "max": 8})
            sb.score += 4
    else:
        sb.details.append({"label": "Insider Activity", "value": "N/A", "pts": 0, "max": 8})

    if sb.score == 0:
        return None
    return sb


# ---------------------------------------------------------------------------
# 6. Fair Value  (max 25 pts) — FMP
# ---------------------------------------------------------------------------
def _score_fair_value(fmp_data: Optional[dict], current_price: float) -> Optional[ScoreBreakdown]:
    if fmp_data is None:
        return None

    sb = ScoreBreakdown(max_score=25)

    # --- DCF intrinsic value vs market price (max 10) ---
    dcf_data = fmp_data["dcf"]
    if dcf_data and isinstance(dcf_data, list) and len(dcf_data) > 0:
        dcf_val = dcf_data[0].get("dcf")
        if dcf_val and current_price and current_price > 0:
            dcf_val = float(dcf_val)
            margin = (dcf_val - current_price) / current_price * 100
            if margin > 30:
                pts = 10
            elif margin > 15:
                pts = 8
            elif margin > 0:
                pts = 6
            elif margin > -15:
                pts = 4
            elif margin > -30:
                pts = 2
            else:
                pts = 1
            sb.score += pts
            sb.details.append({
                "label": "DCF Fair Value",
                "value": f"${dcf_val:.2f} ({margin:+.1f}% vs price)",
                "pts": pts, "max": 10,
            })
        else:
            sb.details.append({"label": "DCF Fair Value", "value": "N/A", "pts": 0, "max": 10})
    else:
        sb.details.append({"label": "DCF Fair Value", "value": "N/A", "pts": 0, "max": 10})

    # --- Financial health: current ratio + debt/equity (max 8) ---
    ratios = fmp_data["ratios"]
    if ratios and isinstance(ratios, list) and len(ratios) > 0:
        r = ratios[0]
        cr = r.get("currentRatio")
        de = r.get("debtToEquityRatio")
        health_pts = 0

        if cr is not None:
            cr = float(cr)
            if cr >= 2.0:
                health_pts += 4
            elif cr >= 1.5:
                health_pts += 3
            elif cr >= 1.0:
                health_pts += 2
            else:
                health_pts += 1

        if de is not None:
            de = float(de)
            if de < 0.5:
                health_pts += 4
            elif de < 1.0:
                health_pts += 3
            elif de < 2.0:
                health_pts += 2
            else:
                health_pts += 1

        sb.score += health_pts
        cr_str = f"CR={cr:.2f}" if cr is not None else "CR=N/A"
        de_str = f"D/E={de:.2f}" if de is not None else "D/E=N/A"
        sb.details.append({
            "label": "Financial Health",
            "value": f"{cr_str}, {de_str}",
            "pts": health_pts, "max": 8,
        })

        # --- Profitability: net profit margin (max 7) ---
        npm = r.get("netProfitMargin")
        if npm is not None:
            npm_pct = float(npm) * 100
            if npm_pct > 20:
                pts = 7
            elif npm_pct > 12:
                pts = 5
            elif npm_pct > 5:
                pts = 3
            elif npm_pct > 0:
                pts = 2
            else:
                pts = 1
            sb.score += pts
            sb.details.append({
                "label": "Net Profit Margin",
                "value": f"{npm_pct:.1f}%",
                "pts": pts, "max": 7,
            })
        else:
            sb.details.append({"label": "Net Profit Margin", "value": "N/A", "pts": 0, "max": 7})
    else:
        sb.details.append({"label": "Financial Health", "value": "N/A", "pts": 0, "max": 8})
        sb.details.append({"label": "Net Profit Margin", "value": "N/A", "pts": 0, "max": 7})

    if sb.score == 0:
        return None
    return sb


# ---------------------------------------------------------------------------
# 6-Month Price Prediction
# ---------------------------------------------------------------------------
def _predict_price(
    info: dict,
    hist: pd.DataFrame,
    current_price: float,
    fh_data: Optional[dict] = None,
    fmp_data: Optional[dict] = None,
) -> dict:
    """
    Multi-source 6-month price prediction.

    Signals (weighted dynamically based on availability):
      - Analyst consensus target  (Yahoo)   — base weight 40
      - Trend projection          (Yahoo)   — base weight 25
      - DCF intrinsic value       (FMP)     — base weight 20
      - Earnings momentum adj.    (Finnhub) — applied as a ±modifier
    """
    pred = {
        "current": round(current_price, 2),
        "analyst_target": None,
        "analyst_low": None,
        "analyst_high": None,
        "analyst_count": None,
        "trend_6m": None,
        "trend_direction": None,
        "dcf_value": None,
        "earnings_momentum": None,
        "combined_estimate": None,
        "upside_pct": None,
    }

    if not current_price or current_price <= 0:
        return pred

    # --- 1. Analyst consensus (Yahoo) ---
    target_mean = _safe(info.get("targetMeanPrice"))
    target_median = _safe(info.get("targetMedianPrice"))
    target_low = _safe(info.get("targetLowPrice"))
    target_high = _safe(info.get("targetHighPrice"))
    analyst_count = _safe(info.get("numberOfAnalystOpinions"))

    analyst_target = target_median or target_mean
    if analyst_target and analyst_target > 0:
        pred["analyst_target"] = round(analyst_target, 2)
        pred["analyst_low"] = round(target_low, 2) if target_low else None
        pred["analyst_high"] = round(target_high, 2) if target_high else None
        pred["analyst_count"] = int(analyst_count) if analyst_count else None

    # --- 2. Trend projection (Yahoo chart) ---
    trend_target = None
    if hist is not None and not hist.empty and len(hist) >= 60:
        close = hist["Close"].squeeze() if isinstance(hist["Close"], pd.DataFrame) else hist["Close"]
        recent = close.dropna().iloc[-126:]
        if len(recent) >= 30:
            x = np.arange(len(recent), dtype=float)
            y = recent.values.astype(float)
            slope, intercept = np.polyfit(x, y, 1)
            future_x = len(recent) + 126
            trend_target = float(slope * future_x + intercept)
            if trend_target > 0:
                pred["trend_6m"] = round(trend_target, 2)
                pred["trend_direction"] = "up" if slope > 0 else "down"

    # --- 3. DCF intrinsic value (FMP) ---
    dcf_target = None
    if fmp_data:
        dcf_list = fmp_data.get("dcf")
        if dcf_list and isinstance(dcf_list, list) and len(dcf_list) > 0:
            raw_dcf = dcf_list[0].get("dcf")
            if raw_dcf and float(raw_dcf) > 0:
                dcf_target = float(raw_dcf)
                pred["dcf_value"] = round(dcf_target, 2)

    # --- 4. Earnings momentum modifier (Finnhub) ---
    # Consistent earnings beats suggest the actual trajectory will
    # outperform consensus; misses suggest underperformance.
    earnings_modifier = 0.0
    if fh_data:
        earnings = fh_data.get("earnings")
        if earnings and len(earnings) >= 1:
            recent_q = earnings[:4]
            valid = [e for e in recent_q if e.get("surprisePercent") is not None]
            if valid:
                beats = sum(1 for e in valid if e["surprisePercent"] > 0)
                avg_surprise = sum(e["surprisePercent"] for e in valid) / len(valid)
                # +3% for 4/4 beats, +1.5% for 3/4, 0 for 2/4, -1.5% for 1/4, -3% for 0/4
                earnings_modifier = (beats - 2) * 1.5
                # Cap modifier magnitude at the avg surprise to avoid overshooting
                if abs(avg_surprise) > 0:
                    cap = min(abs(avg_surprise), 5.0)
                    earnings_modifier = max(-cap, min(cap, earnings_modifier))
                pred["earnings_momentum"] = round(earnings_modifier, 1)

    # --- Weighted combination ---
    # Assign base weights to each price-target signal and normalize
    signals = []  # (price_target, weight)
    if analyst_target and analyst_target > 0:
        signals.append((analyst_target, 40))
    if trend_target and trend_target > 0:
        signals.append((trend_target, 25))
    if dcf_target and dcf_target > 0:
        signals.append((dcf_target, 20))

    if signals:
        total_weight = sum(w for _, w in signals)
        combined = sum(price * w for price, w in signals) / total_weight

        # Apply earnings momentum as a percentage nudge
        if earnings_modifier != 0:
            combined *= 1 + (earnings_modifier / 100)

        pred["combined_estimate"] = round(combined, 2)
        pred["upside_pct"] = round((combined - current_price) / current_price * 100, 1)

    return pred


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def analyze_stock(symbol: str) -> StockReport:
    symbol = symbol.strip().upper()

    cached = _read_cache(symbol)
    if cached:
        logger.info(f"{symbol}: loaded from cache")
        return _report_from_dict(cached)

    for attempt in range(1, _MAX_RETRIES + 2):
        try:
            _throttle()
            logger.info(f"{symbol}: fetching stock data (attempt {attempt})")
            info = data_layer.get_stock_summary(symbol)
            if not info:
                return _empty_report(symbol, error=f"Ticker '{symbol}' not found.")

            name = info.get("shortName") or info.get("longName") or symbol
            raw_summary = info.get("_raw_summary", {})
            if not name or name == symbol:
                price_data = raw_summary.get("price", {})
                name = price_data.get("shortName") or price_data.get("longName") or symbol

            sector = info.get("sector", "N/A")
            industry = info.get("industry", "N/A")
            price = _safe(info.get("currentPrice")) or _safe(info.get("regularMarketPrice")) or 0
            currency = info.get("currency") or "USD"
            source = info.get("_source", "unknown")
            logger.info(f"{symbol}: data from {source}, price={price}")

            _throttle()
            logger.info(f"{symbol}: fetching chart data")
            hist = data_layer.get_historical(symbol)

            fund = _score_fundamentals(info)
            val = _score_valuation(info)
            div = _score_dividends(info, symbol)
            tech = _score_technicals(hist)

            fh_data = _fetch_finnhub(symbol)
            fmp_data = _fetch_fmp(symbol)

            sent = _score_sentiment(fh_data)
            fv = _score_fair_value(fmp_data, price)
            pred = _predict_price(info, hist, price, fh_data, fmp_data)

            report = StockReport(
                ticker=symbol, name=name, sector=sector, industry=industry,
                price=price, currency=currency,
                fundamentals=fund, valuation=val, dividends=div, technicals=tech,
                sentiment=sent, fair_value=fv,
                prediction=pred,
            )
            logger.info(f"{symbol}: score={report.overall_pct:.0f}% ({report.rating})")
            _write_cache(symbol, report.to_dict())
            return report

        except Exception as e:
            err_str = str(e).lower()
            rate_limited = any(w in err_str for w in ("429", "too many", "rate", "limit"))
            if rate_limited and attempt <= _MAX_RETRIES:
                wait = _RETRY_BACKOFF * attempt
                logger.warning(f"{symbol}: rate-limited, retrying in {wait}s")
                time.sleep(wait)
                continue
            logger.error(f"{symbol}: failed — {e}")
            return _empty_report(symbol, error=str(e))

    return _empty_report(symbol, error="Max retries exceeded")


def analyze_multiple(symbols: list[str]) -> list[dict]:
    reports = []
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(analyze_stock, s): s for s in symbols}
        for fut in as_completed(futures):
            reports.append(fut.result())
    reports.sort(key=lambda r: r.overall_pct, reverse=True)
    return [r.to_dict() for r in reports]


def suggest_stocks(top_n: int = 30, max_price: float = None, markets: list[str] = None) -> list[dict]:
    """Two-phase scan: screener -> quick score -> deep analyze top candidates."""
    if not markets:
        markets = ["us"]

    exchanges = []
    for m in markets:
        exchanges.extend(MARKETS.get(m, {}).get("exchanges", []))
    if not exchanges:
        exchanges = ["NMS", "NYQ"]

    # Phase 1: Screener fetch
    logger.info(f"Phase 1: Screening exchanges {exchanges} (max_price={max_price})")
    try:
        quotes = data_layer.screen_stocks(exchanges, max_price=max_price, size=_SCREENER_SIZE)
    except Exception as e:
        logger.error(f"Screener API failed: {e}")
        return []

    if not quotes:
        logger.warning("Screener returned no results")
        return []

    import re
    _SUFFIX_RE = re.compile(r"\.[A-Z]{1,4}$")
    filtered = []
    for q in quotes:
        sym = q.get("symbol")
        if not sym:
            continue
        # Skip preferred shares (e.g. JPM-PC, BAC-PK)
        if "-" in sym:
            parts = sym.split("-")
            if len(parts) == 2 and len(parts[1]) <= 2:
                continue
        # Skip tickers with a dot suffix (e.g. SAP.DE, MC.PA, SAN.MC)
        if _SUFFIX_RE.search(sym):
            continue
        filtered.append(q)

    logger.info(f"After filtering: {len(filtered)} of {len(quotes)}")

    # Quick-score each quote and pick top candidates
    scored = []
    for q in filtered:
        sym = q.get("symbol")
        qs = _quick_score(q)
        scored.append((qs, sym, q))

    scored.sort(key=lambda x: x[0], reverse=True)
    candidates = scored[:_QUICK_TOP_N]

    logger.info(
        f"Phase 1 complete: {len(quotes)} screened -> "
        f"top {len(candidates)} candidates for deep analysis"
    )

    # Phase 2: Deep analysis on top candidates
    symbols = [sym for _, sym, _ in candidates]
    logger.info(f"Phase 2: Deep-analyzing {len(symbols)} stocks")
    all_results = analyze_multiple(symbols)

    good = [r for r in all_results if not r.get("error")]
    return good[:top_n]


def _upside_score(quote: dict) -> float:
    """Estimate upside potential from screener data for gamble mode."""
    price = _safe(quote.get("regularMarketPrice"))
    if not price or price <= 0:
        return -999

    # Analyst upside
    analyst_upside = 0
    target = _safe(quote.get("targetMeanPrice")) or _safe(quote.get("targetMedianPrice"))
    if target and target > 0:
        analyst_upside = (target - price) / price * 100

    # Trend momentum (how far below 52-week high)
    high52 = _safe(quote.get("fiftyTwoWeekHigh"))
    recovery_pct = 0
    if high52 and high52 > price:
        recovery_pct = (high52 - price) / price * 100

    # Forward P/E discount (low forward P/E = expected earnings growth)
    fpe_bonus = 0
    fpe = _safe(quote.get("forwardPE"))
    tpe = _safe(quote.get("trailingPE"))
    if fpe and tpe and fpe > 0 and tpe > 0 and fpe < tpe:
        fpe_bonus = (tpe - fpe) / tpe * 100

    return analyst_upside * 0.5 + recovery_pct * 0.3 + fpe_bonus * 0.2


def gamble_stocks(top_n: int = 30, max_price: float = None, markets: list[str] = None) -> list[dict]:
    """Find high-upside, riskier stocks — sorted by predicted gains, not safety."""
    if not markets:
        markets = ["us"]

    exchanges = []
    for m in markets:
        exchanges.extend(MARKETS.get(m, {}).get("exchanges", []))
    if not exchanges:
        exchanges = ["NMS", "NYQ"]

    logger.info(f"Gamble mode: Screening exchanges {exchanges} (max_price={max_price})")
    try:
        quotes = data_layer.screen_stocks(exchanges, max_price=max_price, size=_SCREENER_SIZE)
    except Exception as e:
        logger.error(f"Screener API failed: {e}")
        return []

    if not quotes:
        return []

    import re
    _SUFFIX_RE = re.compile(r"\.[A-Z]{1,4}$")
    filtered = []
    for q in quotes:
        sym = q.get("symbol")
        if not sym:
            continue
        if "-" in sym:
            parts = sym.split("-")
            if len(parts) == 2 and len(parts[1]) <= 2:
                continue
        if _SUFFIX_RE.search(sym):
            continue
        filtered.append(q)

    # Rank by upside potential instead of quality
    scored = []
    for q in filtered:
        sym = q.get("symbol")
        us = _upside_score(q)
        if us > 5:  # only consider stocks with >5% predicted upside
            scored.append((us, sym, q))

    scored.sort(key=lambda x: x[0], reverse=True)
    candidates = scored[:_QUICK_TOP_N]

    logger.info(
        f"Gamble: {len(filtered)} filtered -> {len(scored)} with upside -> "
        f"top {len(candidates)} for deep analysis"
    )

    symbols = [sym for _, sym, _ in candidates]
    logger.info(f"Gamble Phase 2: Deep-analyzing {len(symbols)} stocks")
    all_results = analyze_multiple(symbols)

    good = [r for r in all_results if not r.get("error")]
    # Sort by predicted upside, not overall score
    good.sort(
        key=lambda r: (r.get("prediction") or {}).get("upside_pct") or 0,
        reverse=True,
    )
    return good[:top_n]


def _empty_report(symbol, error="Unknown error"):
    empty = ScoreBreakdown()
    return StockReport(
        ticker=symbol, name=symbol, sector="N/A", industry="N/A",
        price=0, currency="USD",
        fundamentals=empty, valuation=empty, dividends=empty, technicals=empty,
        sentiment=None, fair_value=None,
        error=error,
    )


def _report_from_dict(d: dict) -> StockReport:
    def _to_breakdown(section: dict) -> ScoreBreakdown:
        return ScoreBreakdown(
            score=section.get("score", 0),
            max_score=section.get("max", 0),
            details=section.get("details", []),
        )

    sent = None
    if d.get("sentiment"):
        sent = _to_breakdown(d["sentiment"])

    fv = None
    if d.get("fair_value"):
        fv = _to_breakdown(d["fair_value"])

    return StockReport(
        ticker=d["ticker"], name=d["name"],
        sector=d.get("sector", "N/A"), industry=d.get("industry", "N/A"),
        price=d.get("price", 0), currency=d.get("currency", "USD"),
        fundamentals=_to_breakdown(d.get("fundamentals", {})),
        valuation=_to_breakdown(d.get("valuation", {})),
        dividends=_to_breakdown(d.get("dividends", {})),
        technicals=_to_breakdown(d.get("technicals", {})),
        sentiment=sent,
        fair_value=fv,
        prediction=d.get("prediction"),
        error=d.get("error"),
    )
