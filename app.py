"""Flask web app for Pennies — Stock Suggestion Tool."""

import os
import re
from dotenv import load_dotenv

load_dotenv()

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from analyzer import analyze_multiple, suggest_stocks, gamble_stocks, MARKETS
from yahoo_api import get_quote_summary, extract_info, get_chart
import finnhub_api
import fmp_api
import json
from datetime import datetime, timezone
from bson import ObjectId
from models import get_db, User

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "pennies-dev-secret-change-me")

login_manager = LoginManager(app)
login_manager.login_view = "login"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@login_manager.user_loader
def load_user(user_id):
    return User.find_by_id(user_id)


print("[Pennies] DB engine: MongoDB Atlas")


# --------------- Auth ---------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.find_by_email(email)

        if not user or not user.check_password(password):
            flash("Invalid email or password.", "error")
            return render_template("auth.html", tab="login", email=email)

        login_user(user, remember=True)
        return redirect(url_for("index"))

    return render_template("auth.html", tab="login")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""

        if not _EMAIL_RE.match(email):
            flash("Please enter a valid email address.", "error")
            return render_template("auth.html", tab="register", email=email)
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template("auth.html", tab="register", email=email)
        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("auth.html", tab="register", email=email)
        if User.find_by_email(email):
            flash("An account with this email already exists.", "error")
            return render_template("auth.html", tab="register", email=email)

        user = User.create(email, password)
        login_user(user, remember=True)
        return redirect(url_for("index"))

    return render_template("auth.html", tab="register")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# --------------- Pages ---------------

@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/dividends")
@login_required
def dividends_page():
    return render_template("dividends.html")


# --------------- Config API ---------------

@app.route("/api/config")
@login_required
def api_config():
    return jsonify({
        "finnhub": finnhub_api.is_configured(),
        "fmp": fmp_api.is_configured(),
    })


# --------------- Stock Analysis API ---------------

@app.route("/suggest", methods=["POST"])
@login_required
def suggest():
    data = request.get_json(silent=True) or {}
    top_n = min(int(data.get("top", 30)), 30)
    max_price = data.get("max_price")
    if max_price is not None:
        max_price = float(max_price)
    markets = data.get("markets") or ["us"]
    results = suggest_stocks(top_n, max_price=max_price, markets=markets)
    _save_history(results, "suggest")
    return jsonify({"results": results, "markets": MARKETS})


@app.route("/gamble", methods=["POST"])
@login_required
def gamble():
    data = request.get_json(silent=True) or {}
    top_n = min(int(data.get("top", 30)), 30)
    max_price = data.get("max_price")
    if max_price is not None:
        max_price = float(max_price)
    markets = data.get("markets") or ["us"]
    results = gamble_stocks(top_n, max_price=max_price, markets=markets)
    _save_history(results, "gamble")
    return jsonify({"results": results, "markets": MARKETS})


@app.route("/analyze", methods=["POST"])
@login_required
def analyze():
    data = request.get_json(silent=True) or {}
    raw = data.get("tickers", "")
    symbols = [s.strip().upper() for s in raw.replace(",", " ").split() if s.strip()]

    if not symbols:
        return jsonify({"error": "Please enter at least one ticker symbol."}), 400
    if len(symbols) > 20:
        return jsonify({"error": "Maximum 20 tickers at a time."}), 400

    results = analyze_multiple(symbols)
    _save_history(results, "analyze")
    return jsonify({"results": results})


def _save_history(results, source):
    if not current_user.is_authenticated:
        return
    valid = [r for r in results if not r.get("error")]
    if not valid:
        return
    tickers = ", ".join(r["ticker"] for r in valid[:20])
    top = max(valid, key=lambda r: r.get("overall_pct", 0))
    doc = {
        "user_id": current_user.id,
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


# --------------- Dividend Calculator ---------------

@app.route("/dividend-calc", methods=["POST"])
@login_required
def dividend_calc():
    data = request.get_json(silent=True) or {}
    ticker = (data.get("ticker") or "").strip().upper()
    invested = data.get("invested")

    if not ticker:
        return jsonify({"error": "Please enter a ticker symbol."}), 400
    if invested is None:
        return jsonify({"error": "Please enter your investment amount."}), 400

    invested = float(invested)
    if invested <= 0:
        return jsonify({"error": "Investment must be greater than 0."}), 400

    try:
        summary = get_quote_summary(ticker)
        if not summary:
            return jsonify({"error": f"Ticker '{ticker}' not found."}), 404

        info = extract_info(summary)
        detail = summary.get("summaryDetail", {})

        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if not price or price <= 0:
            return jsonify({"error": f"Could not get price for {ticker}."}), 400

        div_rate = None
        raw = detail.get("dividendRate", {})
        if isinstance(raw, dict):
            div_rate = raw.get("raw")
        else:
            div_rate = raw

        div_yield = info.get("dividendYield")
        payout_ratio = info.get("payoutRatio")
        ex_date_raw = detail.get("exDividendDate", {})
        ex_date = None
        if isinstance(ex_date_raw, dict) and ex_date_raw.get("fmt"):
            ex_date = ex_date_raw["fmt"]

        if not div_rate or div_rate <= 0:
            if div_yield and div_yield > 0:
                div_rate = price * div_yield
            else:
                return jsonify({
                    "ticker": ticker,
                    "name": info.get("shortName") or info.get("longName") or ticker,
                    "price": round(price, 2),
                    "currency": info.get("currency") or "USD",
                    "pays_dividend": False,
                    "error": f"{ticker} does not currently pay a dividend.",
                })

        shares = invested / price
        annual_dividend = shares * div_rate
        monthly_dividend = annual_dividend / 12
        yield_pct = (div_rate / price) * 100

        return jsonify({
            "ticker": ticker,
            "name": info.get("shortName") or info.get("longName") or ticker,
            "price": round(price, 2),
            "currency": info.get("currency") or "USD",
            "pays_dividend": True,
            "invested": round(invested, 2),
            "shares": round(shares, 4),
            "dividend_per_share": round(div_rate, 4),
            "dividend_yield": round(yield_pct, 2),
            "annual_dividend": round(annual_dividend, 2),
            "monthly_dividend": round(monthly_dividend, 2),
            "payout_ratio": round(payout_ratio * 100, 1) if payout_ratio else None,
            "ex_dividend_date": ex_date,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --------------- Watchlist ---------------

@app.route("/watchlist")
@login_required
def watchlist_page():
    return render_template("watchlist.html")


@app.route("/api/watchlist")
@login_required
def watchlist_get():
    db = get_db()
    items = list(db.watchlist.find({"user_id": current_user.id}).sort("added_at", -1))
    results = []
    for item in items:
        try:
            summary = get_quote_summary(item["ticker"])
            info = extract_info(summary) if summary else {}
            price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
            mcap = info.get("marketCap")
            target = info.get("targetMeanPrice")
            upside = round((target / price - 1) * 100, 1) if target and price else None
            results.append({
                "ticker": item["ticker"],
                "name": info.get("shortName") or info.get("longName") or item["ticker"],
                "price": round(price, 2),
                "currency": info.get("currency") or "USD",
                "change_pct": info.get("regularMarketChangePercent"),
                "sector": info.get("sector") or "N/A",
                "industry": info.get("industry") or "N/A",
                "dividend_yield": round(info["dividendYield"] * 100, 2) if info.get("dividendYield") else None,
                "trailing_pe": round(info["trailingPE"], 1) if info.get("trailingPE") else None,
                "forward_pe": round(info["forwardPE"], 1) if info.get("forwardPE") else None,
                "market_cap": mcap,
                "analyst_target": round(target, 2) if target else None,
                "analyst_count": info.get("numberOfAnalystOpinions"),
                "upside_pct": upside,
                "notes": item.get("notes", ""),
            })
        except Exception:
            results.append({
                "ticker": item["ticker"], "name": item["ticker"],
                "price": 0, "currency": "USD", "change_pct": None,
                "sector": "N/A", "industry": "N/A",
                "dividend_yield": None, "trailing_pe": None,
                "forward_pe": None, "market_cap": None,
                "analyst_target": None, "analyst_count": None,
                "upside_pct": None, "notes": item.get("notes", ""),
            })
    return jsonify({"items": results})


@app.route("/api/watchlist/add", methods=["POST"])
@login_required
def watchlist_add():
    data = request.get_json(silent=True) or {}
    ticker = (data.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"error": "Ticker required."}), 400
    db = get_db()
    if db.watchlist.find_one({"user_id": current_user.id, "ticker": ticker}):
        return jsonify({"status": "already_exists"})
    db.watchlist.insert_one({
        "user_id": current_user.id,
        "ticker": ticker,
        "notes": "",
        "added_at": datetime.now(timezone.utc),
    })
    return jsonify({"status": "added"})


@app.route("/api/watchlist/remove", methods=["POST"])
@login_required
def watchlist_remove():
    data = request.get_json(silent=True) or {}
    ticker = (data.get("ticker") or "").strip().upper()
    get_db().watchlist.delete_one({"user_id": current_user.id, "ticker": ticker})
    return jsonify({"status": "removed"})


@app.route("/api/watchlist/note", methods=["POST"])
@login_required
def watchlist_note():
    data = request.get_json(silent=True) or {}
    ticker = (data.get("ticker") or "").strip().upper()
    notes = (data.get("notes") or "").strip()
    result = get_db().watchlist.update_one(
        {"user_id": current_user.id, "ticker": ticker},
        {"$set": {"notes": notes}},
    )
    if result.matched_count == 0:
        return jsonify({"error": "Not in watchlist."}), 404
    return jsonify({"status": "saved"})


# --------------- Portfolio ---------------

@app.route("/portfolio")
@login_required
def portfolio_page():
    return render_template("portfolio.html")


@app.route("/api/portfolio")
@login_required
def portfolio_get():
    db = get_db()
    items = list(db.portfolio.find({"user_id": current_user.id}).sort("added_at", -1))
    results = []
    total_cost = 0
    total_value = 0
    total_day_pnl = 0
    total_annual_div = 0
    for item in items:
        info = {}
        try:
            summary = get_quote_summary(item["ticker"])
            info = extract_info(summary) if summary else {}
        except Exception:
            pass
        price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
        change_pct = info.get("regularMarketChangePercent")
        div_yield = info.get("dividendYield")
        shares = item["shares"]
        cost_basis = item["cost_basis"]
        market_value = shares * price
        cost_total = shares * cost_basis
        pnl = market_value - cost_total
        pnl_pct = (pnl / cost_total * 100) if cost_total else 0
        day_pnl = market_value * change_pct / (100 + change_pct) if change_pct else 0
        annual_div = market_value * div_yield if div_yield else 0
        total_cost += cost_total
        total_value += market_value
        total_day_pnl += day_pnl
        total_annual_div += annual_div
        results.append({
            "id": str(item["_id"]),
            "ticker": item["ticker"],
            "shares": round(shares, 4),
            "cost_basis": round(cost_basis, 2),
            "current_price": round(price, 2),
            "market_value": round(market_value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "change_pct": round(change_pct, 2) if change_pct is not None else None,
            "day_pnl": round(day_pnl, 2),
            "sector": info.get("sector") or "N/A",
            "industry": info.get("industry") or "N/A",
            "dividend_yield": round(div_yield * 100, 2) if div_yield else None,
            "annual_dividend": round(annual_div, 2),
        })
    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0

    best = max(results, key=lambda r: r["pnl_pct"]) if results else None
    worst = min(results, key=lambda r: r["pnl_pct"]) if results else None

    return jsonify({
        "items": results,
        "total_cost": round(total_cost, 2),
        "total_value": round(total_value, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "total_day_pnl": round(total_day_pnl, 2),
        "total_annual_dividend": round(total_annual_div, 2),
        "best": {"ticker": best["ticker"], "pnl_pct": best["pnl_pct"]} if best else None,
        "worst": {"ticker": worst["ticker"], "pnl_pct": worst["pnl_pct"]} if worst else None,
    })


@app.route("/api/portfolio/add", methods=["POST"])
@login_required
def portfolio_add():
    data = request.get_json(silent=True) or {}
    ticker = (data.get("ticker") or "").strip().upper()
    shares = data.get("shares")
    cost_basis = data.get("cost_basis")
    if not ticker:
        return jsonify({"error": "Ticker required."}), 400
    if not shares or float(shares) <= 0:
        return jsonify({"error": "Shares must be > 0."}), 400
    if not cost_basis or float(cost_basis) <= 0:
        return jsonify({"error": "Cost basis must be > 0."}), 400
    get_db().portfolio.insert_one({
        "user_id": current_user.id,
        "ticker": ticker,
        "shares": float(shares),
        "cost_basis": float(cost_basis),
        "added_at": datetime.now(timezone.utc),
    })
    return jsonify({"status": "added"})


@app.route("/api/portfolio/remove", methods=["POST"])
@login_required
def portfolio_remove():
    data = request.get_json(silent=True) or {}
    item_id = data.get("id")
    if not item_id:
        return jsonify({"error": "Item ID required."}), 400
    try:
        get_db().portfolio.delete_one({"_id": ObjectId(item_id), "user_id": current_user.id})
    except Exception:
        pass
    return jsonify({"status": "removed"})


@app.route("/api/portfolio/edit", methods=["POST"])
@login_required
def portfolio_edit():
    data = request.get_json(silent=True) or {}
    item_id = data.get("id")
    if not item_id:
        return jsonify({"error": "Item ID required."}), 400
    try:
        item = get_db().portfolio.find_one({"_id": ObjectId(item_id), "user_id": current_user.id})
    except Exception:
        return jsonify({"error": "Position not found."}), 404
    if not item:
        return jsonify({"error": "Position not found."}), 404
    updates = {}
    shares = data.get("shares")
    cost_basis = data.get("cost_basis")
    if shares is not None:
        if float(shares) <= 0:
            return jsonify({"error": "Shares must be > 0."}), 400
        updates["shares"] = float(shares)
    if cost_basis is not None:
        if float(cost_basis) <= 0:
            return jsonify({"error": "Cost basis must be > 0."}), 400
        updates["cost_basis"] = float(cost_basis)
    if updates:
        get_db().portfolio.update_one({"_id": ObjectId(item_id)}, {"$set": updates})
    return jsonify({"status": "updated"})


# --------------- History ---------------

@app.route("/history")
@login_required
def history_page():
    return render_template("history.html")


@app.route("/api/history")
@login_required
def history_get():
    page = request.args.get("page", 1, type=int)
    per_page = 15
    db = get_db()
    query = {"user_id": current_user.id}
    total = db.history.count_documents(query)
    pages = max(1, (total + per_page - 1) // per_page)
    skip = (page - 1) * per_page
    docs = list(db.history.find(query).sort("analyzed_at", -1).skip(skip).limit(per_page))
    items = []
    for h in docs:
        items.append({
            "id": str(h["_id"]),
            "source": h.get("source"),
            "tickers": h.get("tickers"),
            "top_ticker": h.get("top_ticker"),
            "top_score": h.get("top_score"),
            "result_count": h.get("result_count"),
            "summary": json.loads(h["summary_json"]) if h.get("summary_json") else [],
            "analyzed_at": h["analyzed_at"].strftime("%Y-%m-%d %H:%M") if h.get("analyzed_at") else None,
        })
    return jsonify({
        "items": items,
        "page": page,
        "pages": pages,
        "total": total,
    })


@app.route("/api/history/delete", methods=["POST"])
@login_required
def history_delete():
    data = request.get_json(silent=True) or {}
    item_id = data.get("id")
    if not item_id:
        return jsonify({"error": "ID required."}), 400
    try:
        get_db().history.delete_one({"_id": ObjectId(item_id), "user_id": current_user.id})
    except Exception:
        pass
    return jsonify({"status": "deleted"})


@app.route("/api/compare", methods=["POST"])
@login_required
def compare_stocks():
    from datetime import timedelta
    import pandas as pd

    data = request.get_json(silent=True) or {}
    tickers = data.get("tickers") or []
    as_of = data.get("as_of")
    if not tickers:
        return jsonify({"error": "Select at least 1 stock."}), 400
    if len(tickers) > 6:
        tickers = tickers[:6]

    results = analyze_multiple(tickers)

    historical_prices = {}
    if as_of:
        try:
            run_dt = datetime.strptime(as_of, "%Y-%m-%d %H:%M")
        except ValueError:
            run_dt = None
        if run_dt:
            for ticker in tickers:
                try:
                    df = get_chart(ticker, range_str="1y", interval="1d")
                    if df.empty:
                        continue
                    target = pd.Timestamp(run_dt, tz="UTC")
                    before = df[df.index <= target]
                    if not before.empty:
                        historical_prices[ticker] = round(float(before["Close"].iloc[-1]), 2)
                    elif not df.empty:
                        historical_prices[ticker] = round(float(df["Close"].iloc[0]), 2)
                except Exception:
                    pass

    return jsonify({"results": results, "historical_prices": historical_prices})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)
