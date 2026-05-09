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

from yahoo_api import get_quote_summary, extract_info, extract_institutional, get_chart, get_dividends, screen_stocks
import finnhub_api
import securitiesdb_api

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

# ---------------------------------------------------------------------------
# Strategy presets — screener filters + quick-score weight overrides
# ---------------------------------------------------------------------------
STRATEGIES = {
    "value": {
        "label": "Value",
        "description": "Undervalued stocks with low P/E, low P/B, and dividends",
        "screener_filters": {
            "max_pe": 15,
        },
        "score_weights": {
            "pe": 2.0, "fpe": 1.5, "pb": 2.0, "dividend": 1.5,
            "momentum": 0.5, "size": 0.5,
        },
    },
    "growth": {
        "label": "Growth",
        "description": "Fast-growing companies with strong revenue and earnings momentum",
        "screener_filters": {
            "min_revenue_growth": 10,
        },
        "score_weights": {
            "pe": 0.3, "fpe": 1.5, "pb": 0.3, "dividend": 0.2,
            "momentum": 2.0, "size": 1.0,
        },
    },
    "income": {
        "label": "Income",
        "description": "High-dividend stocks with sustainable payouts and large market caps",
        "screener_filters": {
            "min_dividend_yield": 3.0,
            "min_market_cap": 2_000_000_000,
        },
        "score_weights": {
            "pe": 0.8, "fpe": 0.8, "pb": 0.5, "dividend": 3.0,
            "momentum": 0.5, "size": 1.5,
        },
    },
    "momentum": {
        "label": "Momentum",
        "description": "Stocks in strong uptrends with positive price action",
        "screener_filters": {},
        "score_weights": {
            "pe": 0.5, "fpe": 0.8, "pb": 0.3, "dividend": 0.2,
            "momentum": 3.0, "size": 1.0,
        },
    },
    "quality": {
        "label": "Quality",
        "description": "Profitable companies with strong margins and financial health",
        "screener_filters": {
            "min_market_cap": 5_000_000_000,
        },
        "score_weights": {
            "pe": 1.0, "fpe": 1.2, "pb": 0.8, "dividend": 1.0,
            "momentum": 1.0, "size": 1.5,
        },
    },
    "bargain": {
        "label": "Bargain",
        "description": "Deeply cheap stocks with high upside potential",
        "screener_filters": {
            "max_pe": 10,
        },
        "score_weights": {
            "pe": 2.5, "fpe": 2.0, "pb": 2.5, "dividend": 1.0,
            "momentum": 0.3, "size": 0.3,
        },
    },
}

STRATEGY_LIST = list(STRATEGIES.keys())

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
    risk_quality: Optional[ScoreBreakdown] = None
    growth_efficiency: Optional[ScoreBreakdown] = None
    prediction: Optional[dict] = None
    error: Optional[str] = None

    @property
    def _active_parts(self) -> list[ScoreBreakdown]:
        base = [self.fundamentals, self.valuation, self.dividends, self.technicals]
        if self.sentiment and self.sentiment.max_score > 0:
            base.append(self.sentiment)
        if self.fair_value and self.fair_value.max_score > 0:
            base.append(self.fair_value)
        if self.risk_quality and self.risk_quality.max_score > 0:
            base.append(self.risk_quality)
        if self.growth_efficiency and self.growth_efficiency.max_score > 0:
            base.append(self.growth_efficiency)
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
            "risk_quality": {
                "score": round(self.risk_quality.score, 1),
                "max": round(self.risk_quality.max_score, 1),
                "pct": round(self.risk_quality.pct, 1),
                "details": self.risk_quality.details,
            } if self.risk_quality and self.risk_quality.max_score > 0 else None,
            "growth_efficiency": {
                "score": round(self.growth_efficiency.score, 1),
                "max": round(self.growth_efficiency.max_score, 1),
                "pct": round(self.growth_efficiency.pct, 1),
                "details": self.growth_efficiency.details,
            } if self.growth_efficiency and self.growth_efficiency.max_score > 0 else None,
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
# Base max ~100 pts. Weights dict multiplies each component.
# Default weights are all 1.0 (balanced). Strategy presets override them.
# ---------------------------------------------------------------------------
_DEFAULT_WEIGHTS = {"pe": 1.0, "fpe": 1.0, "pb": 1.0, "dividend": 1.0, "momentum": 1.0, "size": 1.0}


def _quick_score(quote: dict, weights: dict = None) -> float:
    w = _DEFAULT_WEIGHTS if not weights else {**_DEFAULT_WEIGHTS, **weights}
    score = 0.0

    # --- Valuation: P/E ---
    pe = _safe(quote.get("trailingPE"))
    if pe is not None and pe > 0:
        if pe < 15:
            score += 15 * w["pe"]
        elif pe < 20:
            score += 12 * w["pe"]
        elif pe < 30:
            score += 8 * w["pe"]
        elif pe < 50:
            score += 4 * w["pe"]
        else:
            score += 1 * w["pe"]

    # --- Valuation: Forward P/E ---
    fpe = _safe(quote.get("forwardPE"))
    if fpe is not None and fpe > 0:
        if fpe < 12:
            score += 10 * w["fpe"]
        elif fpe < 18:
            score += 8 * w["fpe"]
        elif fpe < 25:
            score += 5 * w["fpe"]
        elif fpe < 40:
            score += 2 * w["fpe"]

    # --- Valuation: P/B ---
    pb = _safe(quote.get("priceToBook"))
    if pb is not None and pb > 0:
        if pb < 1.5:
            score += 10 * w["pb"]
        elif pb < 3:
            score += 8 * w["pb"]
        elif pb < 5:
            score += 5 * w["pb"]
        elif pb < 10:
            score += 2 * w["pb"]

    # --- Dividends ---
    div_yield = _safe(quote.get("dividendYield"))
    if div_yield is not None and div_yield > 0:
        if div_yield > 4:
            score += 12 * w["dividend"]
        elif div_yield > 2.5:
            score += 9 * w["dividend"]
        elif div_yield > 1:
            score += 6 * w["dividend"]
        else:
            score += 3 * w["dividend"]

    div_rate = _safe(quote.get("dividendRate"))
    if div_rate is not None and div_rate > 0:
        score += 8 * w["dividend"]

    # --- Momentum ---
    price = _safe(quote.get("regularMarketPrice"))
    sma50 = _safe(quote.get("fiftyDayAverage"))
    sma200 = _safe(quote.get("twoHundredDayAverage"))

    if price and sma50 and sma50 > 0:
        pct50 = (price - sma50) / sma50 * 100
        if pct50 > 5:
            score += 13 * w["momentum"]
        elif pct50 > 0:
            score += 10 * w["momentum"]
        elif pct50 > -5:
            score += 6 * w["momentum"]
        else:
            score += 2 * w["momentum"]

    if price and sma200 and sma200 > 0:
        pct200 = (price - sma200) / sma200 * 100
        if pct200 > 10:
            score += 12 * w["momentum"]
        elif pct200 > 0:
            score += 9 * w["momentum"]
        elif pct200 > -5:
            score += 5 * w["momentum"]
        else:
            score += 1 * w["momentum"]

    # --- Size ---
    mcap = _safe(quote.get("marketCap"))
    if mcap is not None:
        if mcap > 200e9:
            score += 20 * w["size"]
        elif mcap > 50e9:
            score += 16 * w["size"]
        elif mcap > 10e9:
            score += 12 * w["size"]
        elif mcap > 2e9:
            score += 8 * w["size"]
        else:
            score += 4 * w["size"]

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
        if fcf_yield > 100 or fcf_yield < -100:
            sb.details.append({"label": "FCF Yield", "value": "N/A (data mismatch)", "pts": 0, "max": 8})
            return sb
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
# 1b. Growth & Efficiency  (max 25 pts, optional)
# ---------------------------------------------------------------------------
def _score_growth_efficiency(info: dict) -> Optional[ScoreBreakdown]:
    sb = ScoreBreakdown(max_score=25)
    data_count = 0

    # Earnings Growth (max 7)
    eg = _safe(info.get("earningsGrowth"))
    if eg is not None:
        eg_pct = eg * 100
        data_count += 1
        if eg_pct > 20:
            pts = 7
        elif eg_pct > 10:
            pts = 5
        elif eg_pct > 0:
            pts = 3
        else:
            pts = 1
        sb.score += pts
        sb.details.append({"label": "Earnings Growth", "value": f"{eg_pct:+.1f}%", "pts": pts, "max": 7})
    else:
        sb.details.append({"label": "Earnings Growth", "value": "N/A", "pts": 0, "max": 7})

    # Return on Equity (max 6)
    roe = _safe(info.get("returnOnEquity"))
    if roe is not None:
        roe_pct = roe * 100
        data_count += 1
        if roe_pct > 20:
            pts = 6
        elif roe_pct > 12:
            pts = 5
        elif roe_pct > 5:
            pts = 3
        else:
            pts = 1
        sb.score += pts
        sb.details.append({"label": "Return on Equity", "value": f"{roe_pct:.1f}%", "pts": pts, "max": 6})
    else:
        sb.details.append({"label": "Return on Equity", "value": "N/A", "pts": 0, "max": 6})

    # Debt-to-Cash Ratio (max 5)
    debt = _safe(info.get("totalDebt"))
    cash = _safe(info.get("totalCash"))
    if debt is not None and cash is not None and cash > 0:
        ratio = debt / cash
        data_count += 1
        if ratio < 0.5:
            pts = 5
        elif ratio < 1:
            pts = 4
        elif ratio < 2:
            pts = 3
        elif ratio < 5:
            pts = 1
        else:
            pts = 0
        sb.score += pts
        sb.details.append({"label": "Debt/Cash Ratio", "value": f"{ratio:.2f}", "pts": pts, "max": 5})
    else:
        sb.details.append({"label": "Debt/Cash Ratio", "value": "N/A", "pts": 0, "max": 5})

    # Operating Margin Health (max 4)
    op_margin = _safe(info.get("operatingMargins"))
    net_margin = _safe(info.get("profitMargins"))
    if op_margin is not None:
        op_pct = op_margin * 100
        data_count += 1
        if op_pct > 25:
            pts = 4
        elif op_pct > 15:
            pts = 3
        elif op_pct > 5:
            pts = 2
        else:
            pts = 1
        sb.score += pts
        sb.details.append({"label": "Operating Margin", "value": f"{op_pct:.1f}%", "pts": pts, "max": 4})
    else:
        sb.details.append({"label": "Operating Margin", "value": "N/A", "pts": 0, "max": 4})

    # EV/EBITDA (max 3)
    ev_ebitda = _safe(info.get("enterpriseToEbitda"))
    if ev_ebitda is not None and ev_ebitda > 0:
        data_count += 1
        if ev_ebitda < 8:
            pts = 3
        elif ev_ebitda < 12:
            pts = 2
        elif ev_ebitda < 20:
            pts = 1
        else:
            pts = 0
        sb.score += pts
        sb.details.append({"label": "EV/EBITDA", "value": f"{ev_ebitda:.1f}", "pts": pts, "max": 3})
    else:
        sb.details.append({"label": "EV/EBITDA", "value": "N/A", "pts": 0, "max": 3})

    # Only activate section if at least 2 metrics have data
    if data_count < 2:
        return None

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
    if pb is not None and pb > 0.05:
        if pb < 1.5:
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
def _score_dividends(info: dict, symbol: str, val_data: Optional[dict] = None) -> ScoreBreakdown:
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

    # Prefer SecuritiesDB consecutive increase streak; fall back to Yahoo dividend history
    sdb_streak = None
    if val_data and val_data.get("dividends"):
        sdb_streak = val_data["dividends"].get("consecutive_annual_increases")

    if sdb_streak is not None and sdb_streak > 0:
        years_val = int(sdb_streak)
        if years_val >= 15:
            pts = 9
        elif years_val >= 10:
            pts = 7
        elif years_val >= 5:
            pts = 5
        elif years_val >= 2:
            pts = 3
        else:
            pts = 1
        sb.score += pts
        sb.details.append({"label": "Dividend History", "value": f"{years_val} yrs consecutive increases", "pts": pts, "max": 9})
    else:
        try:
            _throttle()
            divs = get_dividends(symbol)
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


def _fetch_valuation_data(symbol: str, info: dict = None, summary: dict = None) -> Optional[dict]:
    """Fetch DCF, quant health, and dividend data from SecuritiesDB.

    Falls back to Yahoo ratios for non-US stocks where SecuritiesDB has no data.
    """
    dcf = securitiesdb_api.get_dcf(symbol)
    quant = securitiesdb_api.get_quant_health(symbol)
    div_summary = securitiesdb_api.get_dividends(symbol)
    insider = securitiesdb_api.get_insider_activity(symbol)

    if not quant and info:
        quant = _build_yahoo_quant_fallback(info)
        logger.info(f"{symbol}: using Yahoo ratios fallback for quant data")

    if not dcf and info:
        dcf = _build_yahoo_dcf_fallback(info)
        if dcf:
            logger.info(f"{symbol}: using Yahoo DCF fallback")

    yahoo_inst = None
    if summary:
        yahoo_inst = extract_institutional(summary)
        if yahoo_inst:
            logger.info(f"{symbol}: extracted Yahoo institutional ownership data")

    if not dcf and not quant and not div_summary and not insider and not yahoo_inst:
        return None
    return {"dcf": dcf, "quant": quant, "dividends": div_summary, "insider": insider, "yahoo_institutional": yahoo_inst}


def _build_yahoo_quant_fallback(info: dict) -> Optional[dict]:
    """Build quant-health-like structure from Yahoo's financialData."""
    cr = _safe(info.get("currentRatio"))
    de_raw = _safe(info.get("debtToEquity"))
    de = de_raw / 100.0 if de_raw is not None else None
    npm = _safe(info.get("profitMargins"))
    roe = _safe(info.get("returnOnEquity"))
    gm = _safe(info.get("grossMargins"))
    om = _safe(info.get("operatingMargins"))
    beta = _safe(info.get("beta"))

    has_data = any(v is not None for v in [cr, de, npm, roe, gm, om, beta])
    if not has_data:
        return None

    return {
        "scores": {},
        "value_creation": {},
        "profitability": {
            "gross_margin": gm,
            "net_margin": npm,
        },
        "growth": {},
        "leverage": {
            "current_ratio": cr,
            "debt_to_equity": de,
        },
        "risk": {
            "volatility_annual": None,
            "sharpe_ratio_1y": None,
            "max_drawdown_3y": None,
        },
        "valuation": {},
    }


def _build_yahoo_dcf_fallback(info: dict) -> Optional[dict]:
    """Estimate a simple DCF fair value from Yahoo's freeCashflow + marketCap."""
    fcf = _safe(info.get("freeCashflow"))
    mcap = _safe(info.get("marketCap"))
    price = _safe(info.get("currentPrice")) or _safe(info.get("regularMarketPrice"))

    if not fcf or fcf <= 0 or not mcap or mcap <= 0 or not price or price <= 0:
        return None

    wacc = 0.10
    growth = 0.03
    terminal_value = fcf * (1 + growth) / (wacc - growth)

    shares = mcap / price
    if shares <= 0:
        return None
    fair_value = terminal_value / shares

    if fair_value <= 0:
        return None

    return {
        "fair_value": round(fair_value, 2),
        "upside_pct": round((fair_value - price) / price * 100, 2),
        "wacc": wacc,
        "terminal_growth_rate": growth,
    }


def _score_sentiment(fh_data: Optional[dict], val_data: Optional[dict] = None) -> Optional[ScoreBreakdown]:
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

    # --- Insider transactions (max 4) ---
    sdb_insider = val_data.get("insider") if val_data else None
    insider_scored = False

    if sdb_insider and sdb_insider.get("insider_transactions"):
        itx = sdb_insider["insider_transactions"]
        buy_val = itx.get("total_buy_value") or 0
        sell_val = itx.get("total_sell_value") or 0
        ratio = itx.get("net_buy_sell_ratio")
        recent = itx.get("recent") or []
        buys = sum(1 for t in recent if t.get("type", "").lower() in ("purchase", "buy"))
        sells = sum(1 for t in recent if t.get("type", "").lower() in ("sale", "sell"))

        if buy_val > sell_val or buys > sells:
            pts = 4
            signal = "Net buying"
        elif buy_val == sell_val and buys == sells:
            pts = 2
            signal = "Neutral"
        else:
            pts = 1
            signal = "Net selling"
        sb.score += pts
        count_str = f"{len(recent)} txns" if recent else "No recent"
        sb.details.append({
            "label": "Insider Activity",
            "value": f"{signal} ({count_str})",
            "pts": pts, "max": 4,
        })
        insider_scored = True

    if not insider_scored:
        insider_data = fh_data.get("insider")
        if insider_data and isinstance(insider_data, dict):
            txns = insider_data.get("data", [])
            if txns:
                net_shares = sum(t.get("change", 0) for t in txns[:20])
                if net_shares > 0:
                    pts = 4
                    signal = "Net buying"
                elif net_shares == 0:
                    pts = 2
                    signal = "Neutral"
                else:
                    pts = 1
                    signal = "Net selling"
                sb.score += pts
                sb.details.append({
                    "label": "Insider Activity",
                    "value": f"{signal} ({net_shares:+,.0f} shares)",
                    "pts": pts, "max": 4,
                })
            else:
                sb.details.append({"label": "Insider Activity", "value": "No recent", "pts": 2, "max": 4})
                sb.score += 2
        else:
            sb.details.append({"label": "Insider Activity", "value": "N/A", "pts": 0, "max": 4})

    # --- Institutional Flow / Smart Money (max 4) ---
    smart_money_scored = False

    if sdb_insider and sdb_insider.get("institutional_flow"):
        flows = sdb_insider["institutional_flow"]
        increased = sum(1 for f in flows if f.get("action") in ("Increased", "New"))
        decreased = sum(1 for f in flows if f.get("action") in ("Decreased", "Exited"))
        total_funds = len(flows)

        if total_funds > 0:
            bull_pct = increased / total_funds * 100
            if bull_pct >= 60:
                pts = 4
            elif bull_pct >= 40:
                pts = 3
            elif bull_pct >= 20:
                pts = 2
            else:
                pts = 1
            sb.score += pts
            sb.details.append({
                "label": "Smart Money (13F)",
                "value": f"{increased} buying, {decreased} selling ({total_funds} funds)",
                "pts": pts, "max": 4,
            })
            smart_money_scored = True

    if not smart_money_scored:
        yahoo_inst = val_data.get("yahoo_institutional") if val_data else None
        if yahoo_inst and yahoo_inst.get("total", 0) > 0:
            inc = yahoo_inst.get("increased", 0)
            dec = yahoo_inst.get("decreased", 0)
            total_h = yahoo_inst["total"]
            if total_h > 0:
                bull_pct = inc / total_h * 100
                if bull_pct >= 60:
                    pts = 4
                elif bull_pct >= 40:
                    pts = 3
                elif bull_pct >= 20:
                    pts = 2
                else:
                    pts = 1
            else:
                pts = 2
            sb.score += pts
            holders_str = ", ".join(
                h["name"] for h in (yahoo_inst.get("holders") or [])[:3] if h.get("name")
            ) or "institutional holders"
            sb.details.append({
                "label": "Smart Money",
                "value": f"{inc} increasing, {dec} decreasing ({total_h} holders: {holders_str})",
                "pts": pts, "max": 4,
            })
        else:
            sb.details.append({"label": "Smart Money", "value": "N/A", "pts": 0, "max": 4})

    if sb.score == 0:
        return None
    return sb


# ---------------------------------------------------------------------------
# 6. Fair Value  (max 25 pts) — FMP
# ---------------------------------------------------------------------------
def _score_fair_value(val_data: Optional[dict], current_price: float) -> Optional[ScoreBreakdown]:
    if val_data is None:
        return None

    sb = ScoreBreakdown(max_score=25)
    dcf = val_data.get("dcf")
    quant = val_data.get("quant")

    # --- DCF intrinsic value vs market price (max 8) ---
    if dcf and dcf.get("fair_value"):
        dcf_val = float(dcf["fair_value"])
        if current_price and current_price > 0 and 0.1 * current_price <= dcf_val <= 10 * current_price:
            margin = (dcf_val - current_price) / current_price * 100
            if margin > 30:
                pts = 8
            elif margin > 15:
                pts = 6
            elif margin > 0:
                pts = 5
            elif margin > -15:
                pts = 3
            elif margin > -30:
                pts = 2
            else:
                pts = 1
            sb.score += pts
            sb.details.append({
                "label": "DCF Fair Value",
                "value": f"${dcf_val:.2f} ({margin:+.1f}% vs price)",
                "pts": pts, "max": 8,
            })
        else:
            sb.details.append({"label": "DCF Fair Value", "value": "N/A", "pts": 0, "max": 8})
    else:
        sb.details.append({"label": "DCF Fair Value", "value": "N/A", "pts": 0, "max": 8})

    if quant:
        # --- Financial health: current ratio + debt/equity (max 6) ---
        leverage = quant.get("leverage") or {}
        cr = leverage.get("current_ratio")
        de = leverage.get("debt_to_equity")
        health_pts = 0

        if cr is not None:
            cr = float(cr)
            if cr >= 2.0:
                health_pts += 3
            elif cr >= 1.5:
                health_pts += 2
            elif cr >= 1.0:
                health_pts += 1

        if de is not None:
            de = float(de)
            if de < 0.5:
                health_pts += 3
            elif de < 1.0:
                health_pts += 2
            elif de < 2.0:
                health_pts += 1

        sb.score += health_pts
        cr_str = f"CR={cr:.2f}" if cr is not None else "CR=N/A"
        de_str = f"D/E={de:.2f}" if de is not None else "D/E=N/A"
        sb.details.append({
            "label": "Financial Health",
            "value": f"{cr_str}, {de_str}",
            "pts": health_pts, "max": 6,
        })

        # --- Net Profit Margin (max 5) ---
        prof = quant.get("profitability") or {}
        npm = prof.get("net_margin")
        if npm is not None:
            npm_pct = float(npm) * 100
            if npm_pct > 20:
                pts = 5
            elif npm_pct > 12:
                pts = 4
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
                "pts": pts, "max": 5,
            })
        else:
            sb.details.append({"label": "Net Profit Margin", "value": "N/A", "pts": 0, "max": 5})

        # --- ROIC vs WACC (max 6) ---
        vc = quant.get("value_creation") or {}
        roic = vc.get("roic")
        wacc = vc.get("wacc")
        spread = vc.get("roic_wacc_spread")
        eva = vc.get("economic_value_added", "")
        if spread is not None:
            spread_pct = float(spread) * 100
            if spread_pct > 20:
                pts = 6
            elif spread_pct > 10:
                pts = 5
            elif spread_pct > 0:
                pts = 4
            elif spread_pct > -5:
                pts = 2
            else:
                pts = 1
            sb.score += pts
            roic_str = f"{float(roic)*100:.1f}%" if roic is not None else "N/A"
            wacc_str = f"{float(wacc)*100:.1f}%" if wacc is not None else "N/A"
            sb.details.append({
                "label": "ROIC vs WACC",
                "value": f"{roic_str} vs {wacc_str} ({eva})",
                "pts": pts, "max": 6,
            })
        else:
            sb.details.append({"label": "ROIC vs WACC", "value": "N/A", "pts": 0, "max": 6})
    else:
        sb.details.append({"label": "Financial Health", "value": "N/A", "pts": 0, "max": 6})
        sb.details.append({"label": "Net Profit Margin", "value": "N/A", "pts": 0, "max": 5})
        sb.details.append({"label": "ROIC vs WACC", "value": "N/A", "pts": 0, "max": 6})

    if sb.score == 0:
        return None
    return sb


# ---------------------------------------------------------------------------
# Risk & Quality scoring (SecuritiesDB quant-health)
# ---------------------------------------------------------------------------
def _score_risk_quality(val_data: Optional[dict]) -> Optional[ScoreBreakdown]:
    if val_data is None:
        return None
    quant = val_data.get("quant")
    if not quant:
        return None

    sb = ScoreBreakdown(max_score=25)
    scores = quant.get("scores") or {}
    risk = quant.get("risk") or {}

    # --- Piotroski F-Score (max 8) ---
    piotroski = scores.get("piotroski_f")
    if piotroski is not None:
        piotroski = int(piotroski)
        if piotroski >= 7:
            pts = 8
        elif piotroski >= 5:
            pts = 5
        elif piotroski >= 3:
            pts = 3
        else:
            pts = 1
        sb.score += pts
        label = "Strong" if piotroski >= 7 else "Average" if piotroski >= 4 else "Weak"
        sb.details.append({
            "label": "Piotroski F-Score",
            "value": f"{piotroski}/9 ({label})",
            "pts": pts, "max": 8,
        })
    else:
        sb.details.append({"label": "Piotroski F-Score", "value": "N/A", "pts": 0, "max": 8})

    # --- Altman Z-Score (max 6) ---
    altman = scores.get("altman_z")
    zone = scores.get("altman_z_zone", "")
    if altman is not None:
        altman = float(altman)
        if altman > 2.99:
            pts = 6
        elif altman > 1.81:
            pts = 3
        else:
            pts = 1
        sb.score += pts
        zone_label = zone.capitalize() if zone else ("Safe" if altman > 2.99 else "Grey" if altman > 1.81 else "Distress")
        sb.details.append({
            "label": "Altman Z-Score",
            "value": f"{altman:.2f} ({zone_label})",
            "pts": pts, "max": 6,
        })
    else:
        sb.details.append({"label": "Altman Z-Score", "value": "N/A", "pts": 0, "max": 6})

    # --- Beneish M-Score (max 4) ---
    beneish = scores.get("beneish_m")
    beneish_flag = scores.get("beneish_flag")
    if beneish is not None:
        beneish = float(beneish)
        if beneish < -2.22:
            pts = 4
        elif beneish < -1.78:
            pts = 2
        else:
            pts = 0
        sb.score += pts
        flag_str = "Likely manipulator" if beneish_flag else "Unlikely manipulator"
        sb.details.append({
            "label": "Beneish M-Score",
            "value": f"{beneish:.2f} ({flag_str})",
            "pts": pts, "max": 4,
        })
    else:
        sb.details.append({"label": "Beneish M-Score", "value": "N/A", "pts": 0, "max": 4})

    # --- Sharpe Ratio 1Y (max 4) ---
    sharpe = risk.get("sharpe_ratio_1y")
    if sharpe is not None:
        sharpe = float(sharpe)
        if sharpe >= 1.5:
            pts = 4
        elif sharpe >= 1.0:
            pts = 3
        elif sharpe >= 0.5:
            pts = 2
        elif sharpe >= 0:
            pts = 1
        else:
            pts = 0
        sb.score += pts
        sb.details.append({
            "label": "Sharpe Ratio (1Y)",
            "value": f"{sharpe:.2f}",
            "pts": pts, "max": 4,
        })
    else:
        sb.details.append({"label": "Sharpe Ratio (1Y)", "value": "N/A", "pts": 0, "max": 4})

    # --- Max Drawdown 3Y (max 3) ---
    drawdown = risk.get("max_drawdown_3y")
    if drawdown is not None:
        dd_pct = abs(float(drawdown)) * 100
        if dd_pct < 15:
            pts = 3
        elif dd_pct < 30:
            pts = 2
        elif dd_pct < 50:
            pts = 1
        else:
            pts = 0
        sb.score += pts
        sb.details.append({
            "label": "Max Drawdown (3Y)",
            "value": f"-{dd_pct:.1f}%",
            "pts": pts, "max": 3,
        })
    else:
        sb.details.append({"label": "Max Drawdown (3Y)", "value": "N/A", "pts": 0, "max": 3})

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
    val_data: Optional[dict] = None,
) -> dict:
    """
    Multi-source 6-month price prediction.

    Signals (weighted dynamically based on availability):
      - Analyst consensus target  (Yahoo)         — base weight 40
      - Trend projection          (Yahoo)         — base weight 25
      - DCF intrinsic value       (SecuritiesDB)  — base weight 20
      - Earnings momentum adj.    (Finnhub)       — applied as a ±modifier
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

    # --- 3. DCF intrinsic value (SecuritiesDB) ---
    dcf_target = None
    if val_data:
        dcf = val_data.get("dcf")
        if dcf and dcf.get("fair_value"):
            raw_dcf = float(dcf["fair_value"])
            if raw_dcf > 0 and 0.1 * current_price <= raw_dcf <= 10 * current_price:
                dcf_target = raw_dcf
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
            logger.info(f"{symbol}: fetching quote summary (attempt {attempt})")
            summary = get_quote_summary(symbol)
            if not summary:
                return _empty_report(symbol, error=f"Ticker '{symbol}' not found.")

            info = extract_info(summary)
            name = info.get("shortName") or info.get("longName") or symbol
            if not name or name == symbol:
                price_data = summary.get("price", {})
                name = price_data.get("shortName") or price_data.get("longName") or symbol

            sector = info.get("sector", "N/A")
            industry = info.get("industry", "N/A")
            price = _safe(info.get("currentPrice")) or _safe(info.get("regularMarketPrice")) or 0
            currency = info.get("currency") or "USD"

            _throttle()
            logger.info(f"{symbol}: fetching chart data")
            hist = get_chart(symbol)

            fh_data = _fetch_finnhub(symbol)
            val_data = _fetch_valuation_data(symbol, info, summary)

            fund = _score_fundamentals(info)
            val = _score_valuation(info)
            div = _score_dividends(info, symbol, val_data)
            tech = _score_technicals(hist)

            sent = _score_sentiment(fh_data, val_data)
            fv = _score_fair_value(val_data, price)
            rq = _score_risk_quality(val_data)
            ge = _score_growth_efficiency(info)
            pred = _predict_price(info, hist, price, fh_data, val_data)

            report = StockReport(
                ticker=symbol, name=name, sector=sector, industry=industry,
                price=price, currency=currency,
                fundamentals=fund, valuation=val, dividends=div, technicals=tech,
                sentiment=sent, fair_value=fv, risk_quality=rq,
                growth_efficiency=ge,
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


def analyze_multiple(symbols: list[str], progress_cb=None) -> list[dict]:
    reports = []
    total = len(symbols)
    done = 0
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(analyze_stock, s): s for s in symbols}
        for fut in as_completed(futures):
            reports.append(fut.result())
            done += 1
            if progress_cb:
                progress_cb(done, total)
    reports.sort(key=lambda r: r.overall_pct, reverse=True)
    return [r.to_dict() for r in reports]


def suggest_stocks(top_n: int = 30, max_price: float = None, markets: list[str] = None,
                   strategy: str = None, filters: dict = None, progress_cb=None) -> list[dict]:
    """Two-phase scan: screener -> quick score -> deep analyze top candidates."""
    if not markets:
        markets = ["us"]

    def _progress(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    strat = STRATEGIES.get(strategy) if strategy else None
    screener_filters = dict(filters) if filters else {}
    if strat:
        for k, v in strat["screener_filters"].items():
            if k not in screener_filters:
                screener_filters[k] = v

    exchanges = []
    for m in markets:
        exchanges.extend(MARKETS.get(m, {}).get("exchanges", []))
    if not exchanges:
        exchanges = ["NMS", "NYQ"]

    strat_label = f" [{strat['label']}]" if strat else ""
    _progress(5, f"Screening {len(exchanges)} exchanges{strat_label}...")
    logger.info(f"Phase 1: Screening exchanges {exchanges} (max_price={max_price}, strategy={strategy}, filters={screener_filters})")
    try:
        quotes = screen_stocks(exchanges, max_price=max_price, size=_SCREENER_SIZE,
                               filters=screener_filters if screener_filters else None)
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
        if "-" in sym:
            parts = sym.split("-")
            if len(parts) == 2 and len(parts[1]) <= 2:
                continue
        if _SUFFIX_RE.search(sym):
            continue
        filtered.append(q)

    _progress(15, f"Filtered {len(filtered)} from {len(quotes)} — scoring...")
    logger.info(f"After filtering: {len(filtered)} of {len(quotes)}")

    score_weights = strat["score_weights"] if strat else None
    scored = []
    for q in filtered:
        sym = q.get("symbol")
        qs = _quick_score(q, weights=score_weights)
        scored.append((qs, sym, q))

    scored.sort(key=lambda x: x[0], reverse=True)
    candidates = scored[:_QUICK_TOP_N]

    logger.info(
        f"Phase 1 complete: {len(quotes)} screened -> "
        f"top {len(candidates)} candidates for deep analysis"
    )

    symbols = [sym for _, sym, _ in candidates]
    _progress(20, f"Deep-analyzing {len(symbols)} stocks...")
    logger.info(f"Phase 2: Deep-analyzing {len(symbols)} stocks")

    def _analysis_progress(done, total):
        pct = 20 + int(done / max(total, 1) * 75)
        _progress(pct, f"Analyzing {done}/{total} stocks...")

    all_results = analyze_multiple(symbols, progress_cb=_analysis_progress)

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


def gamble_stocks(top_n: int = 30, max_price: float = None, markets: list[str] = None,
                  filters: dict = None, progress_cb=None) -> list[dict]:
    """Find high-upside, riskier stocks — sorted by predicted gains, not safety."""
    if not markets:
        markets = ["us"]

    def _progress(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    exchanges = []
    for m in markets:
        exchanges.extend(MARKETS.get(m, {}).get("exchanges", []))
    if not exchanges:
        exchanges = ["NMS", "NYQ"]

    _progress(5, f"Screening {len(exchanges)} exchanges...")
    logger.info(f"Gamble mode: Screening exchanges {exchanges} (max_price={max_price}, filters={filters})")
    try:
        quotes = screen_stocks(exchanges, max_price=max_price, size=_SCREENER_SIZE,
                               filters=filters if filters else None)
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

    _progress(15, f"Ranking {len(filtered)} stocks by upside potential...")

    scored = []
    for q in filtered:
        sym = q.get("symbol")
        us = _upside_score(q)
        if us > 5:
            scored.append((us, sym, q))

    scored.sort(key=lambda x: x[0], reverse=True)
    candidates = scored[:_QUICK_TOP_N]

    logger.info(
        f"Gamble: {len(filtered)} filtered -> {len(scored)} with upside -> "
        f"top {len(candidates)} for deep analysis"
    )

    symbols = [sym for _, sym, _ in candidates]
    _progress(20, f"Deep-analyzing {len(symbols)} high-upside stocks...")
    logger.info(f"Gamble Phase 2: Deep-analyzing {len(symbols)} stocks")

    def _analysis_progress(done, total):
        pct = 20 + int(done / max(total, 1) * 75)
        _progress(pct, f"Analyzing {done}/{total} stocks...")

    all_results = analyze_multiple(symbols, progress_cb=_analysis_progress)

    good = [r for r in all_results if not r.get("error")]
    good.sort(
        key=lambda r: (r.get("prediction") or {}).get("upside_pct") or 0,
        reverse=True,
    )
    return good[:top_n]


# ---------------------------------------------------------------------------
# Scout mode: event-driven stock discovery
# ---------------------------------------------------------------------------
SCOUT_SIGNALS = [
    "earnings_beat",
    "insider_buying",
    "analyst_upgrade",
    "new_52w_low",
    "high_upside_gap",
    "dividend_increase",
]


def _check_earnings_beat(symbol: str) -> Optional[str]:
    """Check if stock beat earnings last quarter."""
    data = finnhub_api.get_earnings_surprises(symbol)
    if not data or not isinstance(data, list) or len(data) < 1:
        return None
    latest = data[0]
    surprise_pct = latest.get("surprisePercent")
    if surprise_pct is not None and surprise_pct > 0:
        return f"Beat earnings by {surprise_pct:.1f}%"
    return None


def _check_insider_buying(symbol: str) -> Optional[str]:
    """Check for net insider buying in recent transactions."""
    data = finnhub_api.get_insider_transactions(symbol)
    if not data or not isinstance(data, dict):
        return None
    transactions = data.get("data", [])
    if not transactions:
        return None
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    buys = 0
    sells = 0
    for tx in transactions[:20]:
        date = tx.get("transactionDate", "")
        if date < cutoff:
            continue
        change = tx.get("change", 0)
        if change > 0:
            buys += 1
        elif change < 0:
            sells += 1
    if buys > sells and buys >= 2:
        return f"{buys} insider buys vs {sells} sells (90d)"
    return None


def _check_analyst_upgrade(symbol: str) -> Optional[str]:
    """Check for recent analyst upgrades."""
    data = finnhub_api.get_recommendation_trend(symbol)
    if not data or not isinstance(data, list) or len(data) < 2:
        return None
    current = data[0]
    previous = data[1]
    curr_bull = (current.get("buy", 0) + current.get("strongBuy", 0))
    prev_bull = (previous.get("buy", 0) + previous.get("strongBuy", 0))
    if curr_bull > prev_bull:
        diff = curr_bull - prev_bull
        return f"+{diff} analyst upgrade(s) this month"
    return None


def _check_52w_low(quote: dict) -> Optional[str]:
    """Check if stock is near 52-week low."""
    price = _safe(quote.get("regularMarketPrice"))
    low52 = _safe(quote.get("fiftyTwoWeekLow"))
    high52 = _safe(quote.get("fiftyTwoWeekHigh"))
    if not price or not low52 or not high52 or high52 == low52:
        return None
    position = (price - low52) / (high52 - low52) * 100
    if position < 15:
        return f"Near 52-week low ({position:.0f}% of range)"
    return None


def _check_high_upside(quote: dict) -> Optional[str]:
    """Check for large gap between price and analyst target."""
    price = _safe(quote.get("regularMarketPrice"))
    target = _safe(quote.get("targetMeanPrice")) or _safe(quote.get("targetMedianPrice"))
    if not price or not target or price <= 0:
        return None
    upside = (target - price) / price * 100
    if upside > 30:
        return f"Analyst target {upside:.0f}% above current price"
    return None


def _check_dividend_increase(quote: dict) -> Optional[str]:
    """Check if trailing dividend yield is meaningfully higher than average."""
    div_yield = _safe(quote.get("dividendYield"))
    trailing_annual = _safe(quote.get("trailingAnnualDividendYield"))
    if div_yield and trailing_annual and div_yield > 0:
        if div_yield > trailing_annual * 1.1 and div_yield > 2:
            return f"Dividend yield {div_yield:.1f}% (above trailing avg)"
    elif div_yield and div_yield > 4:
        return f"High dividend yield: {div_yield:.1f}%"
    return None


def scout_stocks(top_n: int = 30, max_price: float = None, markets: list[str] = None,
                 signals: list[str] = None, filters: dict = None, progress_cb=None) -> list[dict]:
    """Event-driven stock discovery — find stocks with recent catalysts."""
    if not markets:
        markets = ["us"]
    if not signals:
        signals = SCOUT_SIGNALS

    def _progress(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    exchanges = []
    for m in markets:
        exchanges.extend(MARKETS.get(m, {}).get("exchanges", []))
    if not exchanges:
        exchanges = ["NMS", "NYQ"]

    _progress(5, f"Scouting {len(exchanges)} exchanges for catalysts...")
    logger.info(f"Scout mode: exchanges={exchanges}, signals={signals}, filters={filters}")

    try:
        quotes = screen_stocks(exchanges, max_price=max_price, size=_SCREENER_SIZE,
                               filters=filters if filters else None)
    except Exception as e:
        logger.error(f"Scout screener failed: {e}")
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

    _progress(10, f"Checking {len(filtered)} stocks for event signals...")

    # Phase 1: Quick screener-level signal checks (no API calls)
    candidates_with_signals = []
    for q in filtered:
        sym = q.get("symbol")
        triggered = []

        if "new_52w_low" in signals:
            sig = _check_52w_low(q)
            if sig:
                triggered.append(("new_52w_low", sig))

        if "high_upside_gap" in signals:
            sig = _check_high_upside(q)
            if sig:
                triggered.append(("high_upside_gap", sig))

        if "dividend_increase" in signals:
            sig = _check_dividend_increase(q)
            if sig:
                triggered.append(("dividend_increase", sig))

        if triggered:
            candidates_with_signals.append((sym, q, triggered))

    _progress(20, f"Found {len(candidates_with_signals)} screener-level signals...")

    # Phase 2: API-based signal checks (Finnhub) on top quick-scored stocks
    needs_api_check = any(s in signals for s in ["earnings_beat", "insider_buying", "analyst_upgrade"])

    if needs_api_check and finnhub_api.is_configured():
        scored_for_api = sorted(filtered, key=lambda q: _quick_score(q), reverse=True)[:80]
        api_check_count = min(len(scored_for_api), 40)
        _progress(25, f"Checking Finnhub signals for top {api_check_count} stocks...")

        for idx, q in enumerate(scored_for_api[:api_check_count]):
            sym = q.get("symbol")
            triggered = []

            if "earnings_beat" in signals:
                sig = _check_earnings_beat(sym)
                if sig:
                    triggered.append(("earnings_beat", sig))

            if "insider_buying" in signals:
                sig = _check_insider_buying(sym)
                if sig:
                    triggered.append(("insider_buying", sig))

            if "analyst_upgrade" in signals:
                sig = _check_analyst_upgrade(sym)
                if sig:
                    triggered.append(("analyst_upgrade", sig))

            if triggered:
                existing = next((c for c in candidates_with_signals if c[0] == sym), None)
                if existing:
                    existing[2].extend(triggered)
                else:
                    candidates_with_signals.append((sym, q, triggered))

            if idx % 5 == 0:
                pct = 25 + int(idx / max(api_check_count, 1) * 30)
                _progress(pct, f"Scanning signals {idx+1}/{api_check_count}...")

    if not candidates_with_signals:
        _progress(100, "No stocks matched the selected signals.")
        return []

    # Sort by number of triggered signals (more signals = stronger candidate)
    candidates_with_signals.sort(key=lambda x: len(x[2]), reverse=True)
    to_analyze = candidates_with_signals[:top_n]

    symbols = [sym for sym, _, _ in to_analyze]
    signal_map = {sym: sigs for sym, _, sigs in to_analyze}

    _progress(60, f"Deep-analyzing {len(symbols)} signal-triggered stocks...")
    logger.info(f"Scout: {len(candidates_with_signals)} with signals -> analyzing {len(symbols)}")

    def _analysis_progress(done, total):
        pct = 60 + int(done / max(total, 1) * 35)
        _progress(pct, f"Analyzing {done}/{total} stocks...")

    all_results = analyze_multiple(symbols, progress_cb=_analysis_progress)

    good = []
    for r in all_results:
        if r.get("error"):
            continue
        ticker = r["ticker"]
        if ticker in signal_map:
            r["scout_signals"] = [{"signal": s, "description": d} for s, d in signal_map[ticker]]
        good.append(r)

    good.sort(key=lambda r: (len(r.get("scout_signals", [])), r.get("overall_pct", 0)), reverse=True)
    return good[:top_n]


# ---------------------------------------------------------------------------
# Technical scan: chart-pattern detection
# ---------------------------------------------------------------------------
def technical_scan(top_n: int = 30, max_price: float = None, markets: list[str] = None,
                   setups: list[str] = None, filters: dict = None, progress_cb=None) -> list[dict]:
    """Scan for stocks exhibiting specific technical chart setups."""
    if not markets:
        markets = ["us"]
    if not setups:
        setups = ["golden_cross", "rsi_oversold_bounce", "breakout", "pullback_to_support"]

    def _progress(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    exchanges = []
    for m in markets:
        exchanges.extend(MARKETS.get(m, {}).get("exchanges", []))
    if not exchanges:
        exchanges = ["NMS", "NYQ"]

    _progress(5, "Screening for technical scan candidates...")
    try:
        quotes = screen_stocks(exchanges, max_price=max_price, size=_SCREENER_SIZE,
                               filters=filters if filters else None)
    except Exception as e:
        logger.error(f"Technical scan screener failed: {e}")
        return []

    if not quotes:
        return []

    # Pre-filter via quick score, take top 60 for chart analysis
    scored = [((_quick_score(q), q.get("symbol"), q)) for q in quotes if q.get("symbol")]
    scored.sort(key=lambda x: x[0], reverse=True)
    candidates = scored[:60]

    _progress(15, f"Fetching chart data for {len(candidates)} candidates...")
    results_with_setups = []

    for idx, (_, sym, q) in enumerate(candidates):
        if not sym:
            continue
        try:
            chart = get_chart(sym, range_str="1y", interval="1d")
            if chart is None or chart.empty or len(chart) < 50:
                continue

            closes = chart["Close"].values
            triggered = []

            # Golden Cross: SMA-50 crosses above SMA-200 in last 5 days
            if "golden_cross" in setups and len(closes) >= 200:
                sma50 = pd.Series(closes).rolling(50).mean().values
                sma200 = pd.Series(closes).rolling(200).mean().values
                for day in range(-5, 0):
                    if (not np.isnan(sma50[day]) and not np.isnan(sma200[day]) and
                        not np.isnan(sma50[day-1]) and not np.isnan(sma200[day-1])):
                        if sma50[day] > sma200[day] and sma50[day-1] <= sma200[day-1]:
                            triggered.append(("golden_cross", "Golden Cross detected in last 5 days"))
                            break

            # RSI Oversold Bounce: RSI was <30 within 10 days, now >35
            if "rsi_oversold_bounce" in setups and len(closes) >= 20:
                deltas = np.diff(closes)
                gains = np.where(deltas > 0, deltas, 0)
                losses = np.where(deltas < 0, -deltas, 0)
                avg_gain = pd.Series(gains).rolling(14).mean().values
                avg_loss = pd.Series(losses).rolling(14).mean().values
                rsi_vals = []
                for i in range(len(avg_gain)):
                    if avg_loss[i] == 0:
                        rsi_vals.append(100.0)
                    elif np.isnan(avg_gain[i]) or np.isnan(avg_loss[i]):
                        rsi_vals.append(50.0)
                    else:
                        rs = avg_gain[i] / avg_loss[i]
                        rsi_vals.append(100 - (100 / (1 + rs)))
                if len(rsi_vals) >= 10:
                    current_rsi = rsi_vals[-1]
                    was_oversold = any(r < 30 for r in rsi_vals[-10:])
                    if was_oversold and current_rsi > 35:
                        triggered.append(("rsi_oversold_bounce", f"RSI bounced from oversold (now {current_rsi:.0f})"))

            # Breakout: price above 20-day high
            if "breakout" in setups and len(closes) >= 25:
                recent_high = max(closes[-25:-1])
                if closes[-1] > recent_high:
                    triggered.append(("breakout", f"Breakout above 20-day high"))

            # Pullback to Support: within 2% of SMA-50 after being 5%+ above
            if "pullback_to_support" in setups and len(closes) >= 55:
                sma50_arr = pd.Series(closes).rolling(50).mean().values
                current_sma50 = sma50_arr[-1]
                if not np.isnan(current_sma50) and current_sma50 > 0:
                    dist_now = (closes[-1] - current_sma50) / current_sma50 * 100
                    was_extended = False
                    for i in range(-10, -1):
                        if not np.isnan(sma50_arr[i]) and sma50_arr[i] > 0:
                            d = (closes[i] - sma50_arr[i]) / sma50_arr[i] * 100
                            if d > 5:
                                was_extended = True
                                break
                    if was_extended and -2 <= dist_now <= 2:
                        triggered.append(("pullback_to_support", f"Pulled back to SMA-50 support ({dist_now:+.1f}%)"))

            if triggered:
                results_with_setups.append((sym, q, triggered))

        except Exception as e:
            logger.warning(f"Technical scan chart error for {sym}: {e}")
            continue

        if idx % 10 == 0:
            pct = 15 + int(idx / max(len(candidates), 1) * 50)
            _progress(pct, f"Scanning charts {idx+1}/{len(candidates)}...")

    if not results_with_setups:
        _progress(100, "No technical setups found.")
        return []

    results_with_setups.sort(key=lambda x: len(x[2]), reverse=True)
    to_analyze = results_with_setups[:top_n]

    symbols = [sym for sym, _, _ in to_analyze]
    setup_map = {sym: sigs for sym, _, sigs in to_analyze}

    _progress(70, f"Deep-analyzing {len(symbols)} stocks with technical setups...")

    def _analysis_progress(done, total):
        pct = 70 + int(done / max(total, 1) * 25)
        _progress(pct, f"Analyzing {done}/{total} stocks...")

    all_results = analyze_multiple(symbols, progress_cb=_analysis_progress)

    good = []
    for r in all_results:
        if r.get("error"):
            continue
        ticker = r["ticker"]
        if ticker in setup_map:
            r["scout_signals"] = [{"signal": s, "description": d} for s, d in setup_map[ticker]]
        good.append(r)

    good.sort(key=lambda r: r.get("overall_pct", 0), reverse=True)
    return good[:top_n]


# ---------------------------------------------------------------------------
# Find Similar: discover stocks with characteristics like a reference stock
# ---------------------------------------------------------------------------
def find_similar(ticker: str, top_n: int = 10, markets: list[str] = None,
                 progress_cb=None) -> list[dict]:
    """Find stocks similar to the given ticker based on its characteristics."""
    if not markets:
        markets = ["us"]

    def _progress(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    _progress(5, f"Analyzing {ticker} to build similarity profile...")
    summary = get_quote_summary(ticker)
    if not summary:
        return []
    info = extract_info(summary)

    sector = info.get("sector")
    mcap = _safe(info.get("marketCap"))
    pe = _safe(info.get("trailingPE"))
    div_yield = _safe(info.get("dividendYield"))

    sim_filters = {}

    if sector and sector != "N/A":
        sim_filters["sectors"] = [sector]

    if mcap and mcap > 0:
        sim_filters["min_market_cap"] = mcap * 0.3
        sim_filters["max_market_cap"] = mcap * 3.0

    if pe and pe > 0:
        sim_filters["min_pe"] = max(1, pe * 0.5)
        sim_filters["max_pe"] = pe * 2.0

    if div_yield and div_yield > 0:
        sim_filters["min_dividend_yield"] = max(0, (div_yield * 100) * 0.5)

    exchanges = []
    for m in markets:
        exchanges.extend(MARKETS.get(m, {}).get("exchanges", []))
    if not exchanges:
        exchanges = ["NMS", "NYQ"]

    _progress(15, f"Screening for stocks similar to {ticker}...")
    logger.info(f"Find similar: {ticker} -> filters={sim_filters}")

    try:
        quotes = screen_stocks(exchanges, size=_SCREENER_SIZE,
                               filters=sim_filters if sim_filters else None)
    except Exception as e:
        logger.error(f"Find similar screener failed: {e}")
        return []

    if not quotes:
        return []

    # Remove the reference ticker from results
    quotes = [q for q in quotes if q.get("symbol") != ticker]

    scored = [(_quick_score(q), q.get("symbol"), q) for q in quotes if q.get("symbol")]
    scored.sort(key=lambda x: x[0], reverse=True)
    candidates = scored[:top_n + 5]

    symbols = [sym for _, sym, _ in candidates]
    _progress(40, f"Deep-analyzing {len(symbols)} similar stocks...")

    def _analysis_progress(done, total):
        pct = 40 + int(done / max(total, 1) * 55)
        _progress(pct, f"Analyzing {done}/{total} stocks...")

    all_results = analyze_multiple(symbols, progress_cb=_analysis_progress)

    good = [r for r in all_results if not r.get("error") and r["ticker"] != ticker]
    good.sort(key=lambda r: r.get("overall_pct", 0), reverse=True)
    return good[:top_n]


def _empty_report(symbol, error="Unknown error"):
    empty = ScoreBreakdown()
    return StockReport(
        ticker=symbol, name=symbol, sector="N/A", industry="N/A",
        price=0, currency="USD",
        fundamentals=empty, valuation=empty, dividends=empty, technicals=empty,
        sentiment=None, fair_value=None, risk_quality=None,
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

    rq = None
    if d.get("risk_quality"):
        rq = _to_breakdown(d["risk_quality"])

    ge = None
    if d.get("growth_efficiency"):
        ge = _to_breakdown(d["growth_efficiency"])

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
        risk_quality=rq,
        growth_efficiency=ge,
        prediction=d.get("prediction"),
        error=d.get("error"),
    )


# ---------------------------------------------------------------------------
# Reddit Discovery
# ---------------------------------------------------------------------------
def reddit_stocks(top_n: int = 15, subreddits: list = None, markets: list = None,
                  progress_cb=None) -> list[dict]:
    """
    Discover trending stocks on Reddit (WSB and others).
    Scrapes mentions, validates tickers, and runs full analysis.
    """
    from reddit_api import scrape_wsb_tickers

    if progress_cb:
        progress_cb(5, "Scraping Reddit for ticker mentions...")

    reddit_data = scrape_wsb_tickers(subreddits=subreddits, limit=100)
    all_tickers = reddit_data.get("tickers", {})
    post_data = reddit_data.get("posts", {})

    if not all_tickers:
        logger.warning("Reddit scrape returned no tickers")
        return []

    # Take top candidates (more than we need, some might be invalid)
    candidates = list(all_tickers.keys())[:top_n * 3]

    # Validate tickers by checking if Yahoo has data for them
    valid_symbols = []
    for sym in candidates:
        if len(valid_symbols) >= top_n:
            break
        try:
            _throttle()
            summary = get_quote_summary(sym)
            if summary:
                price_data = summary.get("price", {})
                market_price = price_data.get("regularMarketPrice", {})
                if isinstance(market_price, dict):
                    market_price = market_price.get("raw", 0)
                if market_price and market_price > 0:
                    valid_symbols.append(sym)
        except Exception:
            continue

    if not valid_symbols:
        logger.warning("No valid Reddit tickers found after validation")
        return []

    logger.info(f"Reddit discovery: validated {len(valid_symbols)} tickers, running analysis")

    if progress_cb:
        progress_cb(30, f"Analyzing {len(valid_symbols)} Reddit-trending stocks...")

    def _analysis_progress(done, total):
        if progress_cb:
            pct = 30 + int(done / max(total, 1) * 65)
            progress_cb(pct, f"Analyzing {done}/{total} stocks...")

    results = analyze_multiple(valid_symbols, progress_cb=_analysis_progress)

    # Attach reddit signals to each result
    for r in results:
        ticker = r.ticker if hasattr(r, "ticker") else r.get("ticker", "")
        mentions = all_tickers.get(ticker, 0)
        posts = post_data.get(ticker, [])
        reddit_signals = {
            "mentions": mentions,
            "posts": posts,
            "subreddits": subreddits or ["wallstreetbets"],
        }
        if hasattr(r, "to_dict"):
            pass  # handled below
        else:
            r["reddit_signals"] = reddit_signals

    # Convert to dicts and attach signals
    final = []
    for r in results:
        if hasattr(r, "to_dict"):
            d = r.to_dict()
        else:
            d = r
        ticker = d.get("ticker", "")
        d["reddit_signals"] = {
            "mentions": all_tickers.get(ticker, 0),
            "posts": post_data.get(ticker, []),
            "subreddits": subreddits or ["wallstreetbets"],
        }
        final.append(d)

    # Sort by mention count (most discussed first)
    final.sort(key=lambda x: x.get("reddit_signals", {}).get("mentions", 0), reverse=True)
    return final
