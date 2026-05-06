# Pennies — Features & Roadmap

## Done

- [x] **Login / Register** — Gate the app behind authentication with hashed passwords.
- [x] **Stock Suggestions** — Screener-based suggestions scored on fundamentals, valuation, dividends, and technicals. Multi-market support (US, UK, EU, Nordics, Canada).
- [x] **Gamble Mode** — High-upside, higher-risk stock picks sorted by predicted gains.
- [x] **Ticker Lookup** — Manually analyze up to 20 tickers at once.
- [x] **Dividend Calculator** — Enter a ticker and investment amount, get annual/monthly dividend income.
- [x] **PDF Export** — Export suggestion results as a detailed multi-page PDF report.
- [x] **Watchlist** — Save and track stocks with live prices, sector, P/E, dividend yield, market cap, analyst targets, personal notes, inline analysis, add-to-portfolio, sort/filter, summary bar.
- [x] **Portfolio Tracker** — Track holdings with live P&L, daily change, dividend income, allocation donut chart, edit positions, inline analysis, sortable columns, best/worst performers.
- [x] **Analysis History** — Auto-save every suggestion/analysis. Track performance of past picks with live price deltas and score comparison. Delete old entries.
- [x] **Nav Bar** — Consistent navigation across all pages.
- [x] **Multi-Market Screener Batching** — Fixed Yahoo API 500 errors when querying many exchanges by batching requests.
- [x] **PostgreSQL + Render Deployment** — Production-ready with `render.yaml` blueprint, `DATABASE_URL` env var, `postgres://` prefix fix.

---

## Future Features

### Price Alerts
Set alerts for when a stock hits a target price.
- User sets a target price (above or below) for a ticker
- Background job checks prices periodically (APScheduler or Celery)
- Notification shown on next login or via email

### Email Verification
Add email verification to the registration flow.
- User registers -> verification email sent -> must click link before logging in
- Use Resend API or SMTP
- Requires `RESEND_API_KEY` or SMTP env vars

### Sector Heatmap
Visual overview of market sectors.
- Grid of sectors colored by average score or daily performance
- Click a sector to see top stocks within it

### Export Watchlist / Portfolio to CSV
Download your data.
- Export watchlist as CSV (ticker, name, price, sector, yield, date added)
- Export portfolio as CSV (ticker, shares, cost, current price, P&L, dividends)

### Dark / Light Theme Toggle
User preference for theme.
- Toggle in nav bar
- Preference saved to user account
- Light theme CSS variables already partially exist in PDF export code

### Social / Sharing
- Share a suggestion run as a public link (read-only)
- Share portfolio performance snapshot

### News Feed per Stock
- Show recent headlines for watchlist/portfolio tickers
- Could use Yahoo Finance news API or a free news API

---

## Optimizations

### API Caching Layer
- Cache `get_quote_summary` responses in Redis or in-memory with TTL (e.g. 5 min)
- Avoid re-fetching the same ticker data when watchlist and portfolio both need it
- Current `.cache/` JSON file caching only works for analyzer; extend to all API calls

### Async / Background Analysis
- Suggestion runs can take 30-60 seconds with many tickers
- Move heavy analysis to a background worker (Celery + Redis, or Render Background Workers)
- Return a job ID immediately, poll for results on the frontend
- Prevents request timeouts on Render (30s limit)

### Batch Portfolio / Watchlist Loading
- Currently fetches `get_quote_summary` sequentially per ticker
- Use `ThreadPoolExecutor` to fetch all tickers in parallel (already used in `analyze_multiple`)
- Would significantly speed up watchlist and portfolio page loads

### Database Indexing
- Add indexes on `user_id` for all tables (watchlist, portfolio, history)
- Add composite index on `(user_id, ticker)` for faster lookups

### Rate Limiting
- Add request rate limiting per user to prevent API abuse
- Use Flask-Limiter or a simple in-memory counter

### Frontend Bundle
- Consolidate repeated CSS (nav, variables, spinner) into a shared stylesheet
- Reduce page weight by extracting common JS into a shared file

### Gunicorn Tuning
- Configure workers based on Render instance CPU (`workers = 2 * cores + 1`)
- Add `--timeout 120` for long-running suggestion requests
- Add `--preload` to share memory across workers

### Error Handling
- Add global error handler for Yahoo API failures (session expired, rate limited)
- Show user-friendly messages instead of "Network error"
- Add retry logic with exponential backoff for transient failures

### Monitoring
- Add basic health check endpoint (`/health`) for Render uptime monitoring
- Log request durations for slow endpoint detection
- Track Yahoo API error rates
