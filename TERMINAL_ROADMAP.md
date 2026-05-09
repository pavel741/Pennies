# Pennies Terminal — Future Vision

The long-term goal is to transform Pennies from a stock suggestion tool into a **Bloomberg Terminal-style equity research workstation** — command-driven, multi-panel, and live.

---

## Phase 1: Terminal Shell (Enhance Current UI)

### Command Bar
A persistent input at the top of the page that accepts typed commands. This is the soul of a terminal interface.

| Command | Action |
|---------|--------|
| `AAPL` | Instant equity dashboard for Apple |
| `SCAN VALUE US` | Run value strategy on US market |
| `SCOUT` | Event-driven signal discovery |
| `COMPARE AAPL MSFT GOOG` | Side-by-side comparison table |
| `CHART AAPL 6M` | Fullscreen interactive chart |
| `ALERT AAPL < 180` | Set a price alert |
| `SECTOR TECH` | Technology sector overview |
| `MOVERS` | Today's top gainers and losers |
| `NEWS AAPL` | Latest headlines |
| `HELP` | List all commands |

- Autocomplete ticker symbols as user types
- Command history (up/down arrow)
- Fuzzy matching for company names ("apple" resolves to AAPL)

### Interactive Charting
Replace static price display with a proper charting library.

- Use **Lightweight Charts** (TradingView open-source) for candlestick/line charts
- Overlay technical indicators: SMA-50, SMA-200, Bollinger Bands
- RSI sub-chart below main chart
- Volume bars
- Highlight detected technical setups (golden cross, breakouts) directly on chart
- Time range selector: 1D, 5D, 1M, 3M, 6M, 1Y, 5Y
- Drawing tools: trendlines, horizontal support/resistance

### Persistent Watchlist Sidebar
- Always-visible sidebar showing watchlist tickers with live prices
- Clicking a ticker updates the main panel (chart + fundamentals)
- Color-coded daily change (green/red)
- Mini sparkline per ticker

### Keyboard Shortcuts
- `/` to focus command bar
- `W` to toggle watchlist sidebar
- `1-7` to switch between panels
- `Esc` to close overlays
- `N` / `P` to navigate between results

---

## Phase 2: Multi-Panel Workspace

### Panel Grid System
Transform from page-based navigation to a single-screen workspace with resizable panels.

- Layouts: 2-panel (chart + data), 4-panel (chart + fundamentals + watchlist + news), 6-panel (full workstation)
- Panels are "linked" — selecting a ticker in one panel updates all linked panels
- Drag to resize panels
- Save custom layouts per user

### Comparative Analysis
Select 2-5 stocks and compare them head-to-head.

- Radar chart overlaying scores (fundamentals, valuation, dividends, technicals, etc.)
- Metric comparison table with "winner" highlighted per row
- Relative price performance chart (all stocks rebased to 100 at start date)
- Exportable as PDF

### Market Overview Dashboard
A home panel showing broad market context.

- Major indices: S&P 500, NASDAQ, FTSE 100, DAX, Nikkei
- Sector performance treemap/heatmap (colored by daily change)
- Top 5 gainers / Top 5 losers (from your markets)
- Upcoming earnings calendar (next 7 days)
- VIX / fear gauge indicator
- Market breadth (% of stocks above SMA-200)

### Live Price Updates (WebSocket)
Replace HTTP polling with real-time push.

- Use **Finnhub WebSocket** (free tier: real-time US stock trades, ~50 symbols)
- Watchlist and portfolio prices tick live during market hours
- Background job progress pushed via Flask-SocketIO (no more polling `/api/job/`)
- Price alerts fire within seconds of condition being met
- Visual flash animation when price updates

### News Feed
Per-stock and market-wide news integration.

- Finnhub company news API (free: 60 req/min)
- Headlines shown in a dedicated panel with timestamp + source
- Sentiment indicator per headline (bullish/bearish/neutral)
- Filter by: ticker, sector, or "all markets"
- Click headline to expand summary or open source article

---

## Phase 3: Full Terminal Experience

### Single-Page App Rewrite
Migrate from Flask/Jinja templates to a proper SPA framework.

- **Svelte** or **React** frontend with component-based architecture
- Flask becomes a pure API server (JSON only)
- Client-side routing (no page reloads)
- Offline-capable with service worker caching
- Mobile-responsive panel collapse

### Alert Engine
Automated monitoring with notifications.

| Alert Type | Trigger |
|------------|---------|
| Price target | Stock crosses above/below a set price |
| RSI extreme | RSI enters overbought (>70) or oversold (<30) |
| Golden cross / Death cross | SMA-50 crosses SMA-200 |
| Earnings surprise | Company beats/misses estimates |
| Insider buying | Cluster of insider purchases detected |
| Analyst upgrade | New buy/strong buy rating |
| Dividend change | Dividend increased or cut |
| Drawdown | Stock falls X% from recent high |

- Background scheduler checks conditions every 5 minutes during market hours
- Notifications via: in-app badge, email (Resend API), browser push notifications
- Alert history log with timestamps

### Saved Screener Queries
Let users save custom screener configurations and re-run them.

- Name and save a set of filters + strategy
- "My Screens" panel with one-click execution
- Optional: auto-run on schedule (daily before market open)
- Compare results across runs (what's new this week?)

### Backtesting Engine
Test how a strategy would have performed historically.

- Select a strategy (e.g., "Value, US, max P/E 15")
- Pick a time range (e.g., "2020-2024")
- Simulate buying top-scored stocks monthly, holding for 6 months
- Show: total return, annualized return, max drawdown, Sharpe ratio
- Compare vs S&P 500 benchmark
- This requires historical screener data (can be approximated with historical prices + current fundamentals)

### Equity Research Notes
Personal research journal per stock.

- Markdown-formatted notes attached to any ticker
- Investment thesis template (why buy, target price, risks, catalysts)
- Track thesis evolution over time
- Link notes to watchlist/portfolio entries

### Multi-User / Team Features
For small investment clubs or study groups.

- Shared watchlists
- Shared screener results
- Discussion threads per stock
- Vote on buy/sell conviction

---

## Data Sources & API Strategy

### Currently Integrated
| Source | Data | Limit |
|--------|------|-------|
| Yahoo Finance | Quotes, fundamentals, charts, screener | Unlimited (unofficial) |
| Finnhub | Analyst recs, earnings, insider tx | 60 req/min (free) |
| SecuritiesDB | DCF, Piotroski, Altman Z, Beneish M | Rate-limited (free, US only) |

### To Integrate
| Source | Data | Limit | Priority |
|--------|------|-------|----------|
| Finnhub WebSocket | Real-time US stock prices | ~50 symbols | High |
| Finnhub News | Company & market news | 60 req/min | High |
| Alpha Vantage | News sentiment, earnings calendar | 25 req/day (free) | Medium |
| FRED (Federal Reserve) | Economic indicators, rates, GDP | Unlimited (free) | Medium |
| SEC EDGAR | 13F filings, insider forms | Unlimited (free) | Medium |
| OpenFIGI | Ticker-to-ISIN mapping | 100 req/min | Low |
| CoinGecko | Crypto prices (if expanding) | 30 req/min (free) | Low |

### Paid Upgrades (if monetized)
| Source | Unlocks | Cost |
|--------|---------|------|
| Polygon.io | True real-time + options data | $30/mo |
| IEX Cloud | More reliable fundamentals | $20/mo |
| Finnhub Premium | Unlimited requests + more data | $50/mo |
| TradingView widget | Embedded pro charts | Free (with branding) |

---

## Technical Architecture (Terminal Version)

```
┌─────────────────────────────────────────────────────────────┐
│                     FRONTEND (SPA)                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │
│  │ Command  │ │  Chart   │ │  Data    │ │  News    │      │
│  │   Bar    │ │  Panel   │ │  Panel   │ │  Panel   │      │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘      │
│              WebSocket + REST API Layer                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────┐
│                     BACKEND (Flask)                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │
│  │  REST    │ │ WebSocket│ │  Alert   │ │ Scheduler│      │
│  │  API     │ │  Server  │ │  Engine  │ │  (cron)  │      │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘      │
│              Analysis Engine + Data Layer                    │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────┐
│                   DATA SOURCES                               │
│  Yahoo Finance │ Finnhub │ SecuritiesDB │ FRED │ EDGAR      │
└─────────────────────────────────────────────────────────────┘
```

---

## Design Principles

1. **Information density** — Show maximum useful data per pixel. No wasted whitespace.
2. **Command-first** — Every action achievable by typing. Mouse is optional.
3. **Speed** — Cached data loads instantly. Fresh data fetches in background.
4. **Context preservation** — Switching views never loses state. Back button works.
5. **Progressive disclosure** — Summary first, drill down on demand.
6. **Terminal aesthetic** — Dark background, monospace for numbers, accent colors for signals.
