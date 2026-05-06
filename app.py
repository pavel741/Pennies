"""Flask web app for Pennies — Stock Suggestion Tool."""

from flask import Flask, render_template, request, jsonify
from analyzer import analyze_multiple, suggest_stocks, gamble_stocks, MARKETS
from yahoo_api import get_quote_summary, extract_info

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/suggest", methods=["POST"])
def suggest():
    data = request.get_json(silent=True) or {}
    top_n = min(int(data.get("top", 30)), 30)
    max_price = data.get("max_price")
    if max_price is not None:
        max_price = float(max_price)
    markets = data.get("markets") or ["us"]
    results = suggest_stocks(top_n, max_price=max_price, markets=markets)
    return jsonify({"results": results, "markets": MARKETS})


@app.route("/gamble", methods=["POST"])
def gamble():
    data = request.get_json(silent=True) or {}
    top_n = min(int(data.get("top", 30)), 30)
    max_price = data.get("max_price")
    if max_price is not None:
        max_price = float(max_price)
    markets = data.get("markets") or ["us"]
    results = gamble_stocks(top_n, max_price=max_price, markets=markets)
    return jsonify({"results": results, "markets": MARKETS})


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json(silent=True) or {}
    raw = data.get("tickers", "")
    symbols = [s.strip().upper() for s in raw.replace(",", " ").split() if s.strip()]

    if not symbols:
        return jsonify({"error": "Please enter at least one ticker symbol."}), 400
    if len(symbols) > 20:
        return jsonify({"error": "Maximum 20 tickers at a time."}), 400

    results = analyze_multiple(symbols)
    return jsonify({"results": results})


@app.route("/dividends")
def dividends_page():
    return render_template("dividends.html")


@app.route("/dividend-calc", methods=["POST"])
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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=9000, threaded=True)
