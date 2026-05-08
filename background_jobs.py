"""Background job runner — decouples heavy analysis from HTTP requests."""

import threading
import logging
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from models import get_db

CACHE_TTL_HOURS = 6

logger = logging.getLogger(__name__)


def _update_job(job_id, **fields):
    fields["updated_at"] = datetime.now(timezone.utc)
    get_db().jobs.update_one({"_id": job_id}, {"$set": fields})


def start_job(kind, user_id, params):
    """Create a job doc and launch analysis in a background thread.

    Returns the job_id (str).
    """
    db = get_db()
    doc = {
        "user_id": user_id,
        "kind": kind,
        "params": params,
        "status": "running",
        "progress": 0,
        "message": "Starting...",
        "results": None,
        "error": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    result = db.jobs.insert_one(doc)
    job_id = result.inserted_id

    t = threading.Thread(target=_run_job, args=(job_id, kind, user_id, params), daemon=True)
    t.start()
    return str(job_id)


def get_job(job_id_str):
    """Return the job document (or None)."""
    try:
        return get_db().jobs.find_one({"_id": ObjectId(job_id_str)})
    except Exception:
        return None


def get_cached_results(kind, markets, max_price):
    """Return recent completed results for the same params (any user).

    Returns None if nothing fresh enough exists.
    """
    cutoff = datetime.utcnow() - timedelta(hours=CACHE_TTL_HOURS)
    query = {
        "kind": kind,
        "status": "done",
        "params.markets": sorted(markets),
        "created_at": {"$gte": cutoff},
    }
    if max_price is not None:
        query["params.max_price"] = max_price
    else:
        query["params.max_price"] = None
    doc = get_db().jobs.find_one(query, sort=[("created_at", -1)])
    return doc


def _run_job(job_id, kind, user_id, params):
    """Execute analysis in a background thread."""
    from analyzer import suggest_stocks, gamble_stocks

    top_n = params.get("top", 30)
    max_price = params.get("max_price")
    markets = params.get("markets") or ["us"]

    def progress_cb(pct, msg):
        _update_job(job_id, progress=min(pct, 99), message=msg)

    try:
        _update_job(job_id, progress=5, message="Screening exchanges...")

        if kind == "suggest":
            results = suggest_stocks(
                top_n, max_price=max_price, markets=markets,
                progress_cb=progress_cb,
            )
        elif kind == "gamble":
            results = gamble_stocks(
                top_n, max_price=max_price, markets=markets,
                progress_cb=progress_cb,
            )
        else:
            results = []

        _update_job(
            job_id,
            status="done",
            progress=100,
            message=f"Done — {len(results)} results",
            results=results,
        )

        _save_history(user_id, results, kind)

        logger.info(f"Job {job_id} completed: {len(results)} results")

    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}", exc_info=True)
        _update_job(job_id, status="failed", progress=0, message="", error=str(e))


def _save_history(user_id, results, source):
    """Save to history collection (same logic as app.py _save_history)."""
    import json
    valid = [r for r in results if not r.get("error")]
    if not valid:
        return
    tickers = ", ".join(r["ticker"] for r in valid[:20])
    top = max(valid, key=lambda r: r.get("overall_pct", 0))
    doc = {
        "user_id": user_id,
        "source": source,
        "tickers": tickers,
        "top_ticker": top["ticker"],
        "top_score": top.get("overall_pct"),
        "result_count": len(valid),
        "summary_json": json.dumps([
            {
                "ticker": r["ticker"],
                "score": r.get("overall_pct"),
                "rating": r.get("rating"),
                "price": r.get("price"),
                "currency": r.get("currency"),
                "fundamentals_pct": r.get("fundamentals", {}).get("pct") if isinstance(r.get("fundamentals"), dict) else None,
                "valuation_pct": r.get("valuation", {}).get("pct") if isinstance(r.get("valuation"), dict) else None,
                "dividends_pct": r.get("dividends", {}).get("pct") if isinstance(r.get("dividends"), dict) else None,
                "technicals_pct": r.get("technicals", {}).get("pct") if isinstance(r.get("technicals"), dict) else None,
            }
            for r in valid[:30]
        ]),
        "analyzed_at": datetime.now(timezone.utc),
    }
    get_db().history.insert_one(doc)
