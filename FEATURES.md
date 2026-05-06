# Pennies — Planned Features

## Done

- [x] **Login / Register** — Gate the app behind authentication. Users must create an account to access features.
- [x] **Watchlist** — Save and track stocks with live prices. Add/remove tickers, per-user SQLite storage.
- [x] **Portfolio Tracker** — Track holdings with live P&L. Add/remove positions, summary cards.
- [x] **Analysis History** — Auto-save every suggestion/analysis with paginated history view.
- [x] **Nav Bar** — Consistent navigation across all pages (Suggestions, Dividends, Watchlist, Portfolio, History, Logout).

---

## Ideas for Later

### 5. Email Verification
Add email verification to the registration flow using Resend API.
- User registers → verification email sent → must click link before logging in
- Requires `RESEND_API_KEY` environment variable

### 6. Price Alerts
Set alerts for when a stock hits a target price.
- User sets a target price (above or below) for a ticker
- Background job checks prices periodically
- Notification shown on next login (or via email if Resend is configured)

### 7. Comparison Mode
Compare two or more stocks side by side.
- Select 2-4 stocks from suggestions or manual entry
- Side-by-side breakdown: fundamentals, valuation, dividends, technicals
- Visual bar charts comparing scores

### 8. Sector Heatmap
Visual overview of market sectors.
- Grid of sectors colored by average score or daily performance
- Click a sector to see top stocks within it

### 9. Export Watchlist / Portfolio to CSV
Download your data.
- Export watchlist as CSV (ticker, name, price, date added)
- Export portfolio as CSV (ticker, shares, cost, current price, P&L)

### 10. Dark/Light Theme Toggle
User preference for theme.
- Toggle in nav bar
- Preference saved to user account
- Light theme CSS variables already partially exist in PDF export code
