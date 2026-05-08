# Pennies Stock Analysis Card Guide

This guide explains every metric on the Pennies stock analysis card, how each score is calculated, and what it means for your trading decisions.

Throughout this guide, we use a real example from the screenshot to illustrate each metric.

---

## How the Overall Score Works

Pennies scores every stock across up to **7 sections**, each worth a maximum of **25 points**:

| Section | Max Points | Always Present? |
|---------|-----------|-----------------|
| Fundamentals | 25 | Yes |
| Valuation | 25 | Yes |
| Dividends | 25 | Yes |
| Technicals | 25 | Yes |
| Sentiment & Signals | 25 | Only if Finnhub data is available |
| Fair Value | 25 | Only if DCF/quant data exists |
| Risk & Quality | 25 | Only if SecuritiesDB quant data exists |

The overall score is calculated as:

```
Overall % = (sum of all section scores) / (sum of all active section max scores) x 100
```

If a section has no data (for example, Sentiment for a stock with no analyst coverage), that section is excluded from both the numerator and denominator. This means a stock with 4 active sections scoring 80/100 gets the same 80% rating as a stock with 7 active sections scoring 140/175.

### Rating Labels

| Overall % | Rating | What It Means |
|-----------|--------|---------------|
| 75% + | **Strong Buy** | Excellent across most metrics. High conviction. |
| 60 - 74% | **Buy** | Solid fundamentals with some minor weaknesses. |
| 45 - 59% | **Hold** | Mixed signals. Worth watching, not urgent to buy or sell. |
| 30 - 44% | **Underperform** | More red flags than strengths. Consider alternatives. |
| Below 30% | **Sell** | Significant issues across multiple dimensions. |

---

## 6M Outlook Strip

The colored strip at the top of each card shows the 6-month price prediction, built from four independent signals blended together with dynamic weighting.

### 6M Estimate

**What it is:** A weighted average of the analyst target, trend projection, and DCF fair value, adjusted by earnings momentum.

**How it's calculated:** Each available signal gets a base weight:
- Analyst consensus target: weight **40**
- Trend projection: weight **25**
- DCF intrinsic value: weight **20**

If a signal is unavailable, its weight is redistributed proportionally to the others. The earnings momentum modifier is then applied as a percentage adjustment to the blended estimate.

**Example:** $24.60 (+20.9%) means the model estimates the stock price will rise roughly 21% over the next 6 months.

**Trading tip:** This is a directional guide, not a guarantee. Use it alongside the section scores to gauge conviction.

### Analyst Target

**What it is:** The median 12-month price target from Wall Street analysts who cover the stock.

**Why it matters:** Analyst targets reflect professional research, models, and industry access. The range (low to high) shows how much analysts disagree -- a wide range means higher uncertainty.

**Example:** $20.90 (14 analysts, range $13.00 - $29.00). The $16 spread between low and high suggests moderate disagreement among analysts.

**Trading tip:** When the current price is well below the low target, the stock is potentially deeply undervalued. When it's above the high target, be cautious.

### Trend Projection

**What it is:** A linear regression line fitted to the last ~126 trading days (roughly 6 months) of closing prices, extrapolated forward another 126 days.

**Why it matters:** It shows the mathematical momentum of the stock -- if the current trajectory continues unchanged, where would the price land? It ignores fundamentals and just follows the trend.

**Example:** $33.43 means the recent uptrend, if extended, would put the price at $33.43 in 6 months.

**Trading tip:** A trend projection significantly above or below the analyst target can signal that momentum and fundamentals are diverging -- a potential turning point.

### DCF Fair Value

**What it is:** The intrinsic value of the stock based on Discounted Cash Flow analysis. DCF models project a company's future cash flows and discount them back to present value using a weighted average cost of capital (WACC).

**Why it matters:** This is the "what the company is actually worth" number based on its financials, independent of market sentiment. If the stock trades well below DCF value, it may be undervalued. If above, it may be overpriced.

**Example:** $19.43 (-4.5%) means DCF analysis values the stock 4.5% below the current market price, suggesting it's slightly overvalued by this measure alone.

**Trading tip:** DCF works best for stable, cash-generating businesses. For high-growth companies with volatile cash flows, take it with a grain of salt.

### Earnings Momentum

**What it is:** A modifier based on whether the company has consistently beaten or missed earnings estimates in recent quarters.

**How it's calculated:**
- 4/4 quarters beat: **+3%** adjustment
- 3/4 quarters beat: **+1.5%**
- 2/4 quarters: **0%** (neutral)
- 1/4 quarters beat: **-1.5%**
- 0/4 quarters beat: **-3%**

The modifier is capped at the average surprise magnitude (max 5%) to prevent overshooting.

**Example:** +1.5% means the company has been beating estimates moderately, nudging the 6M estimate slightly upward.

**Trading tip:** Consistent earnings beats often lead to upward estimate revisions, which tend to push the stock price higher.

---

## Fundamentals (Max 25 Points)

This section answers: **"Is this a good business?"**

### Revenue Growth (Year over Year) -- Max 8 Points

**What it is:** The percentage change in the company's total revenue compared to the same period last year.

**Why it matters:** A company that grows revenue consistently is expanding its market, winning customers, or raising prices. Shrinking revenue is a warning sign that the business may be losing relevance.

| Growth Rate | Points | Meaning |
|-------------|--------|---------|
| Above 20% | 8/8 | Exceptional growth |
| 10 - 20% | 6/8 | Strong growth |
| 0 - 10% | 4/8 | Moderate growth |
| -5% to 0% | 2/8 | Slight decline, watch closely |
| Below -5% | 0/8 | Significant decline |

**Example:** +5.0% scores 4/8 -- moderate growth. The company is expanding, but not aggressively.

**Trading tip:** Growth stocks should score 6+. For value/dividend stocks, 4 points is perfectly acceptable as long as revenue isn't declining.

### Profit Margin -- Max 9 Points

**What it is:** Net income divided by total revenue, expressed as a percentage. It shows how much of every dollar in revenue the company keeps as profit after all expenses.

**Why it matters:** High margins indicate pricing power, efficiency, or a competitive moat. Low margins mean the company is vulnerable to cost increases or price wars. This is weighted most heavily (9 pts) because profitability is the foundation of shareholder returns.

| Profit Margin | Points | Meaning |
|---------------|--------|---------|
| Above 20% | 9/9 | Excellent -- strong competitive position |
| 10 - 20% | 7/9 | Healthy |
| 5 - 10% | 5/9 | Adequate |
| 0 - 5% | 3/9 | Thin margins, vulnerable |
| Negative | 1/9 | Losing money |

**Example:** 22.1% scores 9/9 -- this company has excellent profitability, keeping over a fifth of revenue as profit.

**Trading tip:** Compare margins within the same industry. A 5% margin is excellent for a grocery chain but poor for a software company.

### FCF Yield -- Max 8 Points

**What it is:** Free Cash Flow divided by Market Capitalization, expressed as a percentage. Free cash flow is the cash left over after the company pays for operations and capital expenditures -- it's real, spendable money.

**Why it matters:** Earnings can be manipulated through accounting, but cash flow is much harder to fake. A high FCF yield means the company generates significant cash relative to its price. This cash can fund dividends, buybacks, debt repayment, or growth.

| FCF Yield | Points | Meaning |
|-----------|--------|---------|
| Above 8% | 8/8 | Outstanding cash generation |
| 5 - 8% | 6/8 | Strong |
| 2 - 5% | 4/8 | Reasonable |
| 0 - 2% | 2/8 | Modest |
| Negative | 0/8 | Burning cash |

**Example:** 64.8% scores 8/8 -- an extremely high FCF yield, meaning the company generates enormous cash relative to its market value. This is often seen in energy, finance, or deeply undervalued companies.

**Trading tip:** FCF yield above 8% combined with a stable or growing dividend is a classic value investing signal.

---

## Valuation (Max 25 Points)

This section answers: **"Am I paying a fair price?"**

### Trailing P/E -- Max 9 Points

**What it is:** The current stock price divided by earnings per share over the last 12 months. A P/E of 10 means you're paying $10 for every $1 of earnings.

**Why it matters:** Lower P/E generally means cheaper valuation, but context matters. A low P/E could mean the market expects earnings to decline. A high P/E could mean the market expects rapid growth.

| Trailing P/E | Points | Meaning |
|--------------|--------|---------|
| Below 15 | 9/9 | Deeply discounted |
| 15 - 20 | 7/9 | Fairly valued |
| 20 - 30 | 5/9 | Growth premium |
| 30 - 50 | 3/9 | Expensive |
| Above 50 | 1/9 | Very expensive |
| Negative | 0/9 | Company is losing money |

**Example:** 6.7 scores 9/9 -- extremely cheap. The market is valuing this stock at just 6.7 times its earnings.

**Trading tip:** A P/E below 10 combined with positive earnings growth often signals an undervalued stock. But check why it's cheap -- sometimes low P/E means the market sees trouble ahead.

### Forward P/E -- Max 8 Points

**What it is:** The current stock price divided by the estimated earnings per share for the next 12 months (analyst projections).

**Why it matters:** Forward P/E tells you what you're paying for *future* earnings. If forward P/E is lower than trailing P/E, analysts expect earnings to grow. If higher, they expect a decline.

| Forward P/E | Points | Meaning |
|-------------|--------|---------|
| Below 12 | 8/8 | Very attractive |
| 12 - 18 | 6/8 | Fair value |
| 18 - 25 | 4/8 | Growth priced in |
| 25 - 40 | 2/8 | Expensive |
| Above 40 | 1/8 | Speculative |

**Example:** 5.3 scores 8/8 -- analysts expect earnings to grow (since 5.3 < 6.7), and the stock is priced very cheaply relative to expected earnings.

**Trading tip:** When forward P/E is significantly lower than trailing P/E, it's a bullish signal -- the market hasn't fully priced in the expected earnings growth yet.

### Price / Book -- Max 8 Points

**What it is:** The stock price divided by book value per share (total assets minus total liabilities, divided by shares outstanding).

**Why it matters:** A P/B below 1 means the stock trades below the company's net asset value -- you could theoretically buy the company, sell its assets, pay off debts, and still profit. This is a classic value metric favored by Benjamin Graham and Warren Buffett.

| Price/Book | Points | Meaning |
|------------|--------|---------|
| Below 1.5 | 8/8 | Deep value territory |
| 1.5 - 3.0 | 6/8 | Reasonable |
| 3.0 - 5.0 | 4/8 | Growth premium |
| 5.0 - 10.0 | 2/8 | Expensive |
| Above 10.0 | 1/8 | Very expensive |

**Example:** 1.57 scores 6/8 -- just above deep value territory. The market is paying 1.57x the company's net asset value.

**Trading tip:** P/B is most useful for asset-heavy industries (banks, real estate, energy). For tech companies with few physical assets but valuable intellectual property, P/B is less meaningful.

---

## Dividends (Max 25 Points)

This section answers: **"Will this stock pay me while I wait?"**

### Dividend Yield -- Max 8 Points

**What it is:** The annual dividend payment divided by the current stock price, expressed as a percentage. A 4% yield means you receive $4 per year for every $100 invested.

**Why it matters:** Dividend yield is your "salary" for holding the stock. Higher yields mean more passive income. But extremely high yields (above 8-10%) can be a warning sign that the market expects a dividend cut.

| Dividend Yield | Points | Meaning |
|----------------|--------|---------|
| Above 4% | 8/8 | High income |
| 2.5 - 4% | 6/8 | Solid income |
| 1 - 2.5% | 4/8 | Moderate income |
| 0 - 1% | 2/8 | Token dividend |
| None | 0/8 | No dividend |

**Example:** 7.01% scores 8/8 -- a very high yield. Combined with the strong payout ratio, this suggests a genuine income stock rather than a yield trap.

**Trading tip:** Always check the payout ratio alongside yield. A 7% yield with a 90% payout ratio is riskier than a 4% yield with a 40% payout ratio.

### Payout Ratio -- Max 8 Points

**What it is:** The percentage of earnings paid out as dividends. A 50% payout means the company distributes half its earnings and retains the other half.

**Why it matters:** A sustainable dividend needs a reasonable payout ratio. Too low (under 20%) and the company could be paying more. Too high (over 80%) and there's little room for error -- a bad quarter could force a dividend cut.

| Payout Ratio | Points | Meaning |
|--------------|--------|---------|
| 0 - 40% | 8/8 | Very safe, room to grow |
| 40 - 60% | 6/8 | Healthy balance |
| 60 - 80% | 4/8 | Elevated, watch for stress |
| 80 - 100% | 2/8 | Risky, little margin |
| Above 100% | 0/8 | Unsustainable, paying more than it earns |

**Example:** 56% scores 6/8 -- a healthy payout. The company retains 44% of earnings for reinvestment while returning a generous amount to shareholders.

**Trading tip:** The ideal income stock has a payout between 30-60% with a history of increasing dividends. This combination signals a commitment to shareholders with financial headroom.

### Dividend History -- Max 9 Points

**What it is:** The number of consecutive years the company has paid (or increased) dividends. When SecuritiesDB data is available, this tracks **consecutive annual increases** specifically. Otherwise, it counts years with any dividend payment.

**Why it matters:** A long streak of dividend payments signals management discipline and financial stability. Companies with 25+ years of increases are called "Dividend Aristocrats" and are among the most reliable income investments in the market.

| Years | Points | Meaning |
|-------|--------|---------|
| 15+ years | 9/9 | Aristocrat-level reliability |
| 10 - 14 years | 7/9 | Well-established dividend |
| 5 - 9 years | 5/9 | Building a track record |
| 2 - 4 years | 3/9 | Recently started or restarted |
| 1 year | 1/9 | Unproven |

**Example:** 23 years scores 9/9 -- this company has been increasing dividends for over two decades, nearly qualifying as a Dividend Aristocrat. Very high confidence the dividend will continue.

**Trading tip:** During recessions, companies with 15+ years of dividend history are far more likely to maintain or increase payments. Shorter histories often get cut first.

---

## Technicals (Max 25 Points)

This section answers: **"What is the price momentum telling us?"**

### Price vs SMA-50 -- Max 7 Points

**What it is:** The percentage distance between the current price and the 50-day Simple Moving Average. The SMA-50 smooths out short-term noise and represents the stock's average price over the last ~2.5 months.

**Why it matters:** When the price is above SMA-50, the short-term trend is bullish. When below, bears are in control. The degree to which the price is above or below indicates the strength of the trend.

| Condition | Points | Meaning |
|-----------|--------|---------|
| Above by more than 5% | 7/7 | Strong short-term uptrend |
| Above by 0-5% | 5/7 | Mild uptrend |
| Below by 0-5% | 3/7 | Mild pullback, possibly a dip-buy |
| Below by more than 5% | 1/7 | Short-term downtrend |

**Example:** +1.9% (above) scores 5/7 -- the stock is slightly above its 50-day average, indicating a mild but positive short-term trend.

**Trading tip:** A stock crossing above its SMA-50 after being below it is a common buy signal. Crossing below after being above is a sell signal.

### Price vs SMA-200 -- Max 7 Points

**What it is:** Same concept as SMA-50 but over 200 trading days (~10 months). The SMA-200 is the gold standard for long-term trend analysis.

**Why it matters:** Being above the SMA-200 is the single most important technical signal for long-term investors. It separates bull markets from bear markets. Institutional investors often won't buy stocks trading below their 200-day average.

| Condition | Points | Meaning |
|-----------|--------|---------|
| Above by more than 10% | 7/7 | Strong long-term uptrend |
| Above by 0-10% | 5/7 | Healthy uptrend |
| Below by 0-5% | 3/7 | Testing the trend |
| Below by more than 5% | 1/7 | Long-term downtrend |

**Example:** +39.4% (above) scores 7/7 -- the stock is trading significantly above its 200-day average, indicating a powerful long-term uptrend.

**Trading tip:** The "Golden Cross" (SMA-50 crosses above SMA-200) is one of the most watched bullish signals in trading. The "Death Cross" (opposite) is bearish.

### RSI (14) -- Max 6 Points

**What it is:** The Relative Strength Index, calculated over 14 periods. It oscillates between 0 and 100, measuring the speed and magnitude of recent price changes.

**Why it matters:** RSI identifies overbought and oversold conditions. A stock that has risen too far too fast (RSI > 70) often pulls back. One that has fallen too far (RSI < 30) often bounces. The "Goldilocks zone" (40-60) suggests balanced, sustainable price action.

| RSI Value | Points | Meaning |
|-----------|--------|---------|
| 40 - 60 | 6/6 | Balanced, ideal entry zone |
| 30-40 or 60-70 | 4/6 | Slightly extended, still OK |
| Below 30 | 3/6 | Oversold (potential bounce, but also risk) |
| Above 70 | 1/6 | Overbought, likely to pull back |

**Example:** 48.8 scores 6/6 -- right in the middle of the ideal zone. The stock isn't overbought or oversold, which is healthy for a new position.

**Trading tip:** RSI below 30 combined with strong fundamentals is a classic "buy the dip" signal. RSI above 70 for a stock you own might be a good time to take partial profits.

### 52-Week Range Position -- Max 5 Points

**What it is:** Where the current price sits between its 52-week low and 52-week high, expressed as a percentage (0% = at the low, 100% = at the high).

**Why it matters:** This provides context for the current price. A stock near its 52-week high has strong momentum but less upside. A stock near its 52-week low might be a bargain or a falling knife.

| Range Position | Points | Meaning |
|----------------|--------|---------|
| 30 - 70% | 5/5 | Middle of range, balanced |
| 20-30% or 70-85% | 3/5 | Approaching extremes |
| Below 20% or above 85% | 1/5 | At extremes, caution warranted |

**Example:** 85% scores 3/5 -- the stock is near the top of its 52-week range. Strong momentum, but limited near-term upside before hitting the yearly high.

**Trading tip:** Value investors look for stocks in the 20-40% range with improving fundamentals. Momentum traders prefer the 60-80% range with accelerating earnings.

---

## Sentiment & Signals (Max 25 Points)

This section answers: **"What are the professionals and insiders doing?"**

This section only appears when Finnhub data is available. It captures soft signals that quantitative metrics miss -- what analysts think, whether management is buying or selling, and where institutional money is flowing.

### Analyst Consensus -- Max 8 Points

**What it is:** The percentage of Wall Street analysts rating the stock as Buy or Strong Buy, out of all analysts covering it.

**Why it matters:** While individual analysts can be wrong, the consensus of many analysts provides a useful signal. Strong consensus (70%+ bullish) means most professionals see upside. Weak consensus means opinions are divided.

| Bullish % | Points | Meaning |
|-----------|--------|---------|
| 70%+ | 8/8 | Strong consensus -- most analysts are bullish |
| 50 - 70% | 6/8 | Majority bullish |
| 30 - 50% | 4/8 | Mixed opinions |
| Below 30% | 2/8 | Mostly bearish |

**Example:** 84% bullish (19 analysts) scores 8/8 -- overwhelming analyst support with strong coverage depth.

**Trading tip:** High analyst consensus combined with a stock price below the median target is a strong setup. But be wary of "crowded trades" where everyone is already bullish.

### Earnings Surprises -- Max 9 Points

**What it is:** How many of the last 4 quarterly earnings reports beat analyst estimates, plus the average magnitude of the surprise.

**Why it matters:** Consistent earnings beats indicate that a company is executing better than expectations. This tends to lead to upward estimate revisions, which drive stock prices higher. It's one of the strongest predictors of near-term stock performance.

| Beats | Points | Meaning |
|-------|--------|---------|
| 4/4 | 9/9 | Perfect streak -- momentum is strong |
| 3/4 | 7/9 | Consistently beating |
| 2/4 | 5/9 | Mixed results |
| 1/4 | 3/9 | Mostly missing |
| 0/4 | 1/9 | Consistently disappointing |

**Example:** 3/4 beats (avg +6.7%) scores 7/9 -- the company has beaten estimates in 3 of the last 4 quarters by an average of 6.7%. Solid execution.

**Trading tip:** A company that beats 4/4 quarters with increasing surprise percentages is often about to see major upward revisions from analysts. This is the "PEAD" (Post-Earnings Announcement Drift) effect.

### Insider Activity -- Max 4 Points

**What it is:** Whether company insiders (executives, directors, large shareholders) have been net buyers or net sellers of the stock recently. When SecuritiesDB data is available, it uses insider transaction records with buy/sell values. Otherwise, it falls back to Finnhub insider transaction data.

**Why it matters:** Insiders know their company better than anyone. While insiders sell for many reasons (taxes, diversification, personal needs), they only buy for one reason: they think the stock is going up. Net insider buying is one of the strongest bullish signals in the market.

| Activity | Points | Meaning |
|----------|--------|---------|
| Net buying | 4/4 | Insiders are confident |
| Neutral / no recent | 2/4 | No strong signal |
| Net selling | 1/4 | Insiders are cautious |

**Example:** Neutral (No recent) scores 2/4 -- no significant insider transactions recently. This is common and not concerning on its own.

**Trading tip:** When you see heavy insider buying combined with a stock near its 52-week low, pay attention. Insiders often buy most aggressively before a turnaround.

### Smart Money -- Max 4 Points

**What it is:** Whether large institutional holders (mutual funds, pension funds, hedge funds) have been increasing or decreasing their positions. Data comes from SEC 13F filings (via SecuritiesDB for US stocks) or Yahoo institutional ownership data (for global stocks).

**Why it matters:** When major institutions like Vanguard, BlackRock, or top hedge funds increase their positions, it validates the investment thesis. When they decrease, it could signal they see trouble ahead.

| Buying vs Selling | Points | Meaning |
|-------------------|--------|---------|
| 60%+ increasing | 4/4 | Strong institutional support |
| 40 - 60% increasing | 3/4 | Balanced flow |
| 20 - 40% increasing | 2/4 | More selling than buying |
| Below 20% increasing | 1/4 | Institutions exiting |

**Example:** 6 increasing, 4 decreasing (10 holders) scores 4/4 -- 60% of top institutional holders are adding to their positions. Names like GQG Partners and Capital International Investors are among those buying.

**Trading tip:** Institutional holders are slow-moving but well-resourced. When they increase positions, it's often based on deep research. Follow their direction, but know that their data is reported with a delay (13F filings are quarterly).

---

## Fair Value (Max 25 Points)

This section answers: **"Is the stock priced above or below what it's actually worth?"**

This section combines discounted cash flow analysis with financial health metrics to determine whether you're getting a good deal.

### DCF Fair Value vs Price -- Max 8 Points

**What it is:** The margin of safety between the DCF intrinsic value and the current market price. A positive margin means the stock trades below fair value (undervalued). A negative margin means it trades above (overvalued).

**Why it matters:** DCF is the gold standard of fundamental valuation. If a stock has a 30%+ margin of safety (DCF value well above market price), you have a significant buffer against errors in the model or unexpected bad news.

| Margin (DCF above price) | Points | Meaning |
|---------------------------|--------|---------|
| Above +30% | 8/8 | Deeply undervalued |
| +15% to +30% | 6/8 | Meaningfully undervalued |
| 0% to +15% | 5/8 | Slightly undervalued |
| -15% to 0% | 3/8 | Slightly overvalued |
| -30% to -15% | 2/8 | Overvalued |
| Below -30% | 1/8 | Significantly overvalued |

**Example:** $19.43 (-4.5% vs price) scores 3/8 -- the DCF model says the stock is worth slightly less than its current price. Not a bargain by DCF standards, but only marginally overvalued.

**Trading tip:** A DCF margin of safety above 15% combined with a Piotroski F-Score above 7 is a classic "quality value" setup that historically outperforms the market.

### Financial Health -- Max 6 Points

**What it is:** Two metrics combined: **Current Ratio** (current assets / current liabilities) and **Debt-to-Equity** (total debt / shareholder equity).

**Why it matters:** A company can have great revenue and profits but still go bankrupt if it can't pay its short-term bills (low current ratio) or is crushed by debt (high D/E). Financial health is the foundation everything else rests on.

**Current Ratio scoring (up to 3 pts):**
| CR Value | Points | Meaning |
|----------|--------|---------|
| 2.0+ | 3 | Very strong liquidity |
| 1.5 - 2.0 | 2 | Healthy |
| 1.0 - 1.5 | 1 | Adequate but tight |
| Below 1.0 | 0 | May struggle to pay short-term debts |

**Debt-to-Equity scoring (up to 3 pts):**
| D/E Value | Points | Meaning |
|-----------|--------|---------|
| Below 0.5 | 3 | Conservative debt levels |
| 0.5 - 1.0 | 2 | Moderate leverage |
| 1.0 - 2.0 | 1 | Elevated debt |
| Above 2.0 | 0 | High leverage |

**Example:** CR=0.71, D/E=1.93 scores 1/6 -- a weak financial health score. Current ratio below 1.0 means short-term liabilities exceed short-term assets, and D/E near 2 indicates heavy debt. This is common in banking and finance where leverage is the business model.

**Trading tip:** Always interpret financial health in industry context. Banks and utilities naturally have high D/E and low current ratios. Tech companies with a D/E above 1.5 are more concerning.

### Net Profit Margin -- Max 5 Points

**What it is:** The same profit margin as in Fundamentals, but here sourced from the quantitative health dataset to cross-validate.

**Why it matters:** In the Fair Value context, margin quality matters because high margins support the DCF model's assumptions. A company with thin margins is more vulnerable to economic downturns, making its DCF value less reliable.

| Net Margin | Points | Meaning |
|------------|--------|---------|
| Above 20% | 5/5 | High-quality earnings |
| 12 - 20% | 4/5 | Solid |
| 5 - 12% | 3/5 | Adequate |
| 0 - 5% | 2/5 | Thin |
| Negative | 1/5 | Losing money |

**Example:** 22.0% scores 5/5 -- excellent profit margins that support the reliability of the DCF valuation.

### ROIC vs WACC -- Max 6 Points

**What it is:** **Return on Invested Capital** (how much profit the company generates per dollar of capital invested) versus **Weighted Average Cost of Capital** (the blended cost of the company's debt and equity financing).

**Why it matters:** This is arguably the most important metric in corporate finance. If ROIC > WACC, the company is **creating** shareholder value -- every dollar reinvested generates more than it costs. If ROIC < WACC, the company is **destroying** value -- shareholders would be better off if the company returned the money.

| ROIC-WACC Spread | Points | Meaning |
|------------------|--------|---------|
| Above +20% | 6/6 | Exceptional value creation |
| +10% to +20% | 5/6 | Strong value creation |
| 0% to +10% | 4/6 | Positive, creating value |
| -5% to 0% | 2/6 | Marginal, barely covering costs |
| Below -5% | 1/6 | Destroying shareholder value |

**Example:** 13.1% vs 7.4% (creating) scores 4/6 -- a spread of +5.7%, meaning the company earns 5.7 percentage points more than its cost of capital. Value is being created for shareholders.

**Trading tip:** Consistent ROIC > WACC is the hallmark of a competitive moat. Companies like this can compound wealth over decades. A widening spread over time is even more bullish.

---

## Risk & Quality (Max 25 Points)

This section answers: **"How safe is this investment?"**

These metrics come from academic research and use standardized financial models to assess accounting quality, bankruptcy risk, and risk-adjusted returns.

### Piotroski F-Score -- Max 8 Points

**What it is:** A 9-point scoring system (created by Professor Joseph Piotroski at Stanford) that evaluates a company's financial strength across profitability (4 points), leverage/liquidity (3 points), and operating efficiency (2 points).

**Why it matters:** Companies scoring 7-9 have strong fundamentals and historically outperform the market. Those scoring 0-3 have weak fundamentals and are more likely to decline. This is one of the most academically validated stock-picking tools.

| F-Score | Points | Label | Meaning |
|---------|--------|-------|---------|
| 7 - 9 | 8/8 | Strong | High-quality fundamentals |
| 5 - 6 | 5/8 | Average | Mixed picture |
| 3 - 4 | 3/8 | Weak | Deteriorating fundamentals |
| 0 - 2 | 1/8 | Very Weak | Serious financial issues |

**Example:** 7/9 (Strong) scores 8/8 -- this company passes 7 of 9 financial strength tests, indicating robust fundamentals.

**Trading tip:** Piotroski F-Score is especially powerful when combined with low P/B ratios. Buying cheap stocks (low P/B) with high F-Scores (7+) has historically generated significant excess returns -- this is the original Piotroski strategy.

### Altman Z-Score -- Max 6 Points

**What it is:** A formula developed by Professor Edward Altman at NYU that predicts the probability of a company going bankrupt within 2 years. It combines five financial ratios related to working capital, retained earnings, EBIT, market cap, and revenue.

**Why it matters:** This is an early warning system. A Z-Score below 1.81 puts a company in the "distress zone" where bankruptcy risk is real. Above 2.99 is the "safe zone." The grey area in between warrants closer monitoring.

| Z-Score | Points | Zone | Meaning |
|---------|--------|------|---------|
| Above 2.99 | 6/6 | Safe | Very low bankruptcy risk |
| 1.81 - 2.99 | 3/6 | Grey | Elevated risk, monitor closely |
| Below 1.81 | 1/6 | Distress | Significant bankruptcy risk |

**Example:** 1.36 (Distress) scores 1/6 -- this is a red flag. However, the Altman Z-Score was designed for manufacturing companies and is notoriously unreliable for financial firms and utilities, which naturally have high leverage and low working capital. Always consider the industry.

**Trading tip:** An Altman Z-Score in the distress zone for a non-financial company is a serious warning. For banks and insurers, focus more on the Piotroski F-Score and regulatory capital ratios instead.

### Beneish M-Score -- Max 4 Points

**What it is:** A statistical model (developed by Professor Messod Beneish at Indiana University) that detects whether a company is likely manipulating its earnings through aggressive accounting practices.

**Why it matters:** Earnings manipulation eventually unravels, leading to restatements and stock price crashes. A score below -2.22 suggests the company is unlikely to be manipulating earnings. Above -2.22 raises suspicion.

| M-Score | Points | Meaning |
|---------|--------|---------|
| Below -2.22 | 4/4 | Unlikely manipulator -- clean books |
| -2.22 to -1.78 | 2/4 | Grey area, some red flags |
| Above -1.78 | 0/4 | Possible manipulator -- caution |

**Example:** -2.59 (Unlikely manipulator) scores 4/4 -- the company's financials pass the manipulation test. The numbers appear genuine.

**Trading tip:** A Beneish M-Score above -1.78 combined with rapid revenue growth but declining cash flow is a classic pattern that preceded accounting scandals like Enron and WorldCom.

### Sharpe Ratio (1Y) -- Max 4 Points

**What it is:** The stock's excess return (above the risk-free rate) divided by the standard deviation of returns over the past year. It measures how much return you received per unit of risk taken.

**Why it matters:** Two stocks might both return 20%, but if one had smooth, steady gains and the other had wild swings, the smooth one is the better risk-adjusted investment. A higher Sharpe ratio means better risk-adjusted performance.

| Sharpe Ratio | Points | Meaning |
|--------------|--------|---------|
| 1.5+ | 4/4 | Excellent risk-adjusted returns |
| 1.0 - 1.5 | 3/4 | Good |
| 0.5 - 1.0 | 2/4 | Adequate |
| 0 - 0.5 | 1/4 | Poor risk/reward |
| Negative | 0/4 | Returns worse than risk-free rate |

**Example:** N/A scores 0/4 -- data was not available for this stock (this can happen for certain international stocks or those without sufficient history).

**Trading tip:** A Sharpe ratio above 1.0 for a full year is genuinely impressive and suggests the stock has a real edge, not just luck.

### Max Drawdown (3Y) -- Max 3 Points

**What it is:** The largest peak-to-trough decline in the stock price over the last 3 years, expressed as a percentage. If a stock went from $100 to $50 before recovering, the max drawdown is -50%.

**Why it matters:** Max drawdown tells you the worst-case scenario you would have experienced as a holder. Even if a stock has great long-term returns, a -60% drawdown can cause panic selling and permanent capital loss for investors who can't stomach the volatility.

| Max Drawdown | Points | Meaning |
|--------------|--------|---------|
| Less than -15% | 3/3 | Very stable, low volatility |
| -15% to -30% | 2/3 | Normal volatility |
| -30% to -50% | 1/3 | Significant drawdown risk |
| Worse than -50% | 0/3 | Extreme volatility |

**Example:** N/A scores 0/3 -- data unavailable for this stock.

**Trading tip:** If your risk tolerance is low, prioritize stocks with max drawdowns under 30%. Pair this with position sizing: never allocate more than you can afford to see temporarily drop by the max drawdown amount.

---

## Putting It All Together: Reading the Card

### The Quick Scan (10 seconds)

1. **Overall rating and percentage** -- is this a Buy, Hold, or Sell?
2. **6M Estimate** -- what's the predicted upside?
3. **Colored progress bars** -- which sections are strong (long green bars) and which are weak (short yellow/red bars)?

### The Deep Read (2 minutes)

Look at the score breakdown by section:

- **Strong Fundamentals + Strong Valuation + Weak Technicals** = A good company at a fair price that's currently out of favor. Classic value opportunity -- the market may catch up.
- **Strong Technicals + Weak Fundamentals** = Momentum without substance. Potentially a speculative bubble. Be cautious.
- **Strong Dividends + Strong Risk & Quality + Weak Fair Value** = A quality income stock that might be slightly overpriced. Good for long-term holding, but consider waiting for a dip.
- **Strong everything + Low Fair Value DCF** = The market hasn't caught up to the fundamentals yet. This is the holy grail.
- **High yield + Low Piotroski + High Altman Z risk** = Classic "yield trap." The high dividend looks attractive but the company may be forced to cut it.

### Suggest Mode vs Gamble Mode

**Suggest** ranks stocks by overall score percentage -- it favors balanced, high-quality stocks that score well across all sections. Best for: building a core portfolio.

**Gamble** ranks stocks by predicted upside percentage -- it favors stocks with the highest gap between current price and projected price. These are often riskier, more volatile, and more dependent on a turnaround thesis. Best for: speculative positions with a small portion of your portfolio.

### The Example Stock

Looking at the screenshot:

| Section | Score | Assessment |
|---------|-------|------------|
| Fundamentals | 21/25 (84%) | Excellent -- profitable, growing, cash-generating |
| Valuation | 23/25 (92%) | Deeply undervalued by traditional metrics |
| Dividends | 23/25 (92%) | Outstanding dividend stock with long history |
| Technicals | 21/25 (84%) | Strong uptrend, healthy RSI |
| Sentiment | 21/25 (84%) | Analysts and institutions are bullish |
| Fair Value | 13/25 (52%) | Mixed -- DCF says slightly overvalued, but margins and ROIC are strong |
| Risk & Quality | 13/25 (52%) | Piotroski strong, but Altman Z in distress (likely a financial stock) |

**Verdict:** This is a high-income value stock with strong momentum and analyst support. The main risks are financial health (leverage) and the distress-zone Z-Score, which are likely structural characteristics of its industry (banking/energy) rather than genuine bankruptcy risk. The 7% dividend yield with 23 years of history and a 56% payout ratio makes this an attractive income holding.

The 6M estimate of +20.9% is optimistic and driven primarily by the trend projection ($33.43) pulling the average up. The more conservative analyst target ($20.90) and DCF ($19.43) suggest limited near-term upside from current levels. A realistic expectation might be in the middle: 5-15% price appreciation plus the 7% dividend yield, for a total return of 12-22%.
