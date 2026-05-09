"""
Reddit scraper for stock ticker mentions.
Fetches posts from r/wallstreetbets (and other subreddits) using public JSON endpoints.
No API key required.
"""

import re
import time
import logging
import requests
from typing import Optional
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

_CACHE: dict = {}
_CACHE_TTL = 60 * 30  # 30 minutes
_RATE_DELAY = 2.0  # Be polite to Reddit

# Common English words / abbreviations that are also valid tickers — filter these out
_TICKER_BLOCKLIST = {
    "I", "A", "AM", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "IF", "IN",
    "IS", "IT", "ME", "MY", "NO", "OF", "OK", "ON", "OR", "SO", "TO", "UP",
    "US", "WE", "AI",
    "ALL", "ARE", "BIG", "CAN", "CEO", "DD", "DIP", "EPS", "ETF", "FOR",
    "FUD", "GDP", "HAS", "HIS", "HOW", "IPO", "ITS", "LOW", "MAY", "NEW",
    "NOT", "NOW", "OLD", "ONE", "OUR", "OUT", "OWN", "PER", "PUT", "RUN",
    "SAY", "SEC", "SET", "SHE", "THE", "TOP", "TWO", "USE", "WAS", "WAY",
    "WHO", "WHY", "WIN", "WON", "YET", "YOU",
    "ALSO", "AWAY", "BACK", "BEEN", "BEST", "BODY", "BOTH", "BULL", "BURN",
    "CALL", "CASH", "COME", "CORE", "COST", "DAMP", "DATA", "DAYS", "DEAD",
    "DEAL", "DEEP", "DOME", "DONE", "DOWN", "DROP", "DUMP", "EACH", "EARN",
    "EDIT", "ELSE", "EVEN", "EVER", "FAST", "FELL", "FIND", "FLAT", "FLIP",
    "FORM", "FREE", "FROM", "FULL", "FUND", "GAIN", "GAME", "GAVE", "GETS",
    "GIVE", "GOES", "GOLD", "GONE", "GOOD", "GRAB", "GROW", "HALF", "HANG",
    "HARD", "HATE", "HAVE", "HEAR", "HELP", "HERE", "HIGH", "HOLD", "HOME",
    "HOPE", "HUGE", "IDEA", "INTO", "JUST", "KEEP", "KNEW", "KNOW", "LAST",
    "LATE", "LEAD", "LEFT", "LESS", "LIFE", "LIKE", "LINE", "LINK", "LIST",
    "LIVE", "LONG", "LOOK", "LORD", "LOSE", "LOSS", "LOST", "LOTS", "LOVE",
    "LUCK", "MADE", "MAIN", "MAKE", "MANY", "MARK", "MIND", "MINE", "MISS",
    "MODE", "MORE", "MOST", "MOVE", "MUCH", "MUST", "NAME", "NEAR", "NEED",
    "NEXT", "NICE", "NONE", "NOTE", "ONLY", "OPEN", "OVER", "PAID", "PART",
    "PAST", "PATH", "PEAK", "PICK", "PLAN", "PLAY", "PLUS", "POOR", "POST",
    "PULL", "PUMP", "PURE", "PUSH", "PUTS", "RATE", "READ", "REAL", "REST",
    "RICH", "RIDE", "RISE", "RISK", "ROAD", "ROLL", "SAFE", "SAID", "SALE",
    "SAME", "SAVE", "SEEN", "SELL", "SEND", "SHOW", "SHUT", "SIDE", "SIGN",
    "SITS", "SIZE", "SLOW", "SOLD", "SOME", "SOON", "SPOT", "STAY", "STEP",
    "STOP", "SUCH", "SURE", "TAKE", "TALK", "TANK", "TELL", "TERM", "TEST",
    "THAN", "THAT", "THEM", "THEN", "THEY", "THIS", "TILL", "TIME", "TIPS",
    "TOLD", "TOOK", "TRIM", "TRUE", "TURN", "TYPE", "UNIT", "UPON", "USED",
    "VERY", "VOTE", "WAIT", "WALK", "WALL", "WANT", "WEEK", "WELL", "WENT",
    "WERE", "WHAT", "WHEN", "WILL", "WISH", "WITH", "WORD", "WORK", "YEAR",
    "YOUR", "ZERO", "YOLO", "HODL", "MOON", "BEAR", "BAGS", "BANG", "BOOM",
    "ROPE", "TLDR", "FOMO", "LMAO", "IMHO",
}

_DOLLAR_TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b")
_CAPS_WORD_RE = re.compile(r"\b([A-Z]{2,5})\b")


def _fetch_subreddit_posts(subreddit: str, sort: str = "hot", limit: int = 100) -> list[dict]:
    """Fetch posts from a subreddit using public JSON endpoint."""
    url = f"https://www.reddit.com/r/{subreddit}/{sort}.json"
    params = {"limit": min(limit, 100), "raw_json": 1}
    headers = {"User-Agent": "Pennies/1.0 (Stock Research Tool)"}

    try:
        time.sleep(_RATE_DELAY)
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code == 429:
            logger.warning(f"Reddit rate-limited on r/{subreddit}/{sort}, waiting 5s")
            time.sleep(5)
            resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        posts = data.get("data", {}).get("children", [])
        return [p.get("data", {}) for p in posts]
    except Exception as e:
        logger.warning(f"Reddit fetch failed for r/{subreddit}/{sort}: {e}")
        return []


def _extract_tickers_from_text(text: str) -> list[str]:
    """Extract potential stock tickers from text."""
    tickers = []

    # Explicit $TICKER mentions (highest confidence)
    dollar_matches = _DOLLAR_TICKER_RE.findall(text)
    tickers.extend(dollar_matches)

    # ALL-CAPS words (2-5 chars) that could be tickers
    caps_matches = _CAPS_WORD_RE.findall(text)
    for word in caps_matches:
        if word not in _TICKER_BLOCKLIST and len(word) >= 2:
            tickers.append(word)

    return tickers


def scrape_wsb_tickers(
    subreddits: list[str] = None,
    limit: int = 100,
) -> dict:
    """
    Scrape Reddit for stock ticker mentions.

    Returns dict with:
        tickers: dict[str, int] - ticker -> mention count (sorted by frequency)
        posts: dict[str, list] - ticker -> list of post titles mentioning it
        meta: dict - subreddits scraped, post count, timestamp
    """
    if subreddits is None:
        subreddits = ["wallstreetbets"]

    # Check cache
    cache_key = f"reddit:{','.join(sorted(subreddits))}:{limit}"
    if cache_key in _CACHE:
        cached_time, cached_data = _CACHE[cache_key]
        if time.time() - cached_time < _CACHE_TTL:
            logger.info(f"Reddit cache hit for {cache_key}")
            return cached_data

    ticker_counts: dict[str, int] = {}
    ticker_posts: dict[str, list] = {}
    total_posts = 0

    for sub in subreddits:
        for sort in ["hot", "rising"]:
            posts = _fetch_subreddit_posts(sub, sort=sort, limit=limit)
            total_posts += len(posts)

            for post in posts:
                title = post.get("title", "")
                selftext = post.get("selftext", "")
                full_text = f"{title} {selftext}"
                upvotes = post.get("ups", 0)

                tickers_found = _extract_tickers_from_text(full_text)
                seen_in_post = set()

                for ticker in tickers_found:
                    if ticker in seen_in_post:
                        continue
                    seen_in_post.add(ticker)

                    # Weight by upvotes (popular posts count more)
                    weight = 1 + (min(upvotes, 10000) // 100)
                    ticker_counts[ticker] = ticker_counts.get(ticker, 0) + weight

                    if ticker not in ticker_posts:
                        ticker_posts[ticker] = []
                    if len(ticker_posts[ticker]) < 3:
                        ticker_posts[ticker].append({
                            "title": title[:120],
                            "upvotes": upvotes,
                            "subreddit": sub,
                        })

    # Sort by mention count
    sorted_tickers = dict(sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True))

    result = {
        "tickers": sorted_tickers,
        "posts": ticker_posts,
        "meta": {
            "subreddits": subreddits,
            "total_posts_scanned": total_posts,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }

    _CACHE[cache_key] = (time.time(), result)
    logger.info(f"Reddit scrape complete: {total_posts} posts, {len(sorted_tickers)} unique tickers")
    return result
