# Pennies — Stock Suggestion Tool

A multi-factor stock analysis tool that scores stocks on **Fundamentals**, **Valuation**, **Dividends**, and **Technicals** and gives you a buy/hold/sell recommendation.

## Scoring Criteria (100 points total)

| Category (25 pts each) | What it checks |
|---|---|
| **Fundamentals** | Revenue growth (YoY), profit margins, free cash flow yield |
| **Valuation** | Trailing P/E, forward P/E, price-to-book ratio |
| **Dividends** | Current yield, payout ratio, years of dividend history |
| **Technicals** | SMA-50, SMA-200 trends, RSI-14, 52-week range position |

### Ratings

| Score | Rating |
|---|---|
| 75-100% | Strong Buy |
| 60-74% | Buy |
| 45-59% | Hold |
| 30-44% | Underperform |
| 0-29% | Sell |

## Setup

```bash
pip install -r requirements.txt
python app.py
```

Open **http://localhost:5000** in your browser.

## Usage

Enter one or more ticker symbols (e.g. `AAPL MSFT GOOG JNJ KO`) and click **Analyze**. Results are sorted by overall score with a detailed breakdown per category.

## Data Source

All financial data is pulled in real-time from Yahoo Finance via the `yfinance` library. No API key required.
