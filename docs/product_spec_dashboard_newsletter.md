# Product Spec: Dashboard + Newsletter

## The Flywheel

```
Newsletter (free) → builds audience → drives to Dashboard
     ↓                                      ↓
Trust & credibility              Free tier → Paid conversion
     ↓                                      ↓
Shareable content ←──────────── Data for newsletter content
```

---

## Product 1: Newsletter

### Name Ideas
- "Volatility Radar" - Weekly crypto sentiment briefing
- "The Sentiment Edge" - Data-driven crypto insights
- "Crypto Pulse" - What the crowd is feeling
- "Signal & Noise" - Cutting through crypto sentiment

### Format (Weekly, Sunday evening)

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE SENTIMENT EDGE - Week of Feb 3, 2026
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 THIS WEEK'S READINGS

Sentiment Score:  ██████████░░░░░░░░░░  47 (Neutral)
Volatility Risk:  ████████████████░░░░  HIGH
Market Regime:    Sideways (consolidation)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔮 VOLATILITY OUTLOOK

Extreme sentiment readings this week suggest elevated
volatility over the next 5 days. Historically, similar
conditions preceded 4%+ daily moves 73% of the time.

→ Consider: Reducing position sizes, widening stops

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📈 WHAT THE CROWD IS SAYING

Activity Level:   ████░░░░░░  23% (quiet)
Fear Index:       ██░░░░░░░░   8% (low)
Euphoria Index:   ███░░░░░░░  14% (moderate)

Top themes this week:
• ETF inflows dominating discussion
• Layer 2 narrative gaining momentum
• Macro concerns (Fed, rates) elevated

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 SOURCE INTELLIGENCE

Most accurate sources this week:
1. r/BitcoinMarkets (58% accuracy)
2. r/ethtrader (54% accuracy)
3. StockTwits BTC (52% accuracy)

Divergence alert: Reddit bullish, StockTwits bearish
→ When sources disagree, expect choppy price action

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 View full dashboard: [link]
🔔 Get real-time alerts: [upgrade link]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Platform Options

| Platform | Pros | Cons | Cost |
|----------|------|------|------|
| **Substack** | Built-in discovery, easy paid tier | 10% fee on paid | Free |
| **Beehiiv** | Better analytics, no fee | Less discovery | $0-49/mo |
| **ConvertKit** | Full control, integrations | More setup | $29+/mo |
| **Ghost** | Self-hosted, no fees | Technical setup | $9-25/mo |

**Recommendation:** Start with Substack (free, built-in audience), migrate later if needed.

### Monetization

| Tier | Price | Content |
|------|-------|---------|
| Free | $0 | Weekly summary, basic metrics |
| Paid | $10/mo | Full analysis, source intelligence, early access |

---

## Product 2: Dashboard

### Name
Same brand as newsletter: "The Sentiment Edge" or "Volatility Radar"

### Pages

#### 1. Home / Overview
```
┌─────────────────────────────────────────────────────────┐
│  CRYPTO SENTIMENT DASHBOARD                    [Login]  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │ SENTIMENT   │  │ VOLATILITY  │  │   REGIME    │     │
│  │             │  │   RISK      │  │             │     │
│  │     47      │  │    HIGH     │  │  SIDEWAYS   │     │
│  │   Neutral   │  │   ████████  │  │             │     │
│  └─────────────┘  └─────────────┘  └─────────────┘     │
│                                                         │
│  ┌───────────────────────────────────────────────────┐ │
│  │  SENTIMENT OVER TIME                    [30 days] │ │
│  │  ▁▂▃▄▅▆▇█▇▆▅▄▃▂▁▂▃▄▅▆▇▆▅▄▃▂▁▂▃▄▅▆▇█▇▆▅▄▃▂▁     │ │
│  └───────────────────────────────────────────────────┘ │
│                                                         │
│  ┌──────────────────────┐  ┌──────────────────────┐   │
│  │  MULTI-DIMENSIONAL   │  │  PRICE vs SENTIMENT  │   │
│  │  Activity:  ███░░ 23%│  │  [chart overlay]     │   │
│  │  Fear:      █░░░░  8%│  │                      │   │
│  │  Euphoria:  ██░░░ 14%│  │                      │   │
│  └──────────────────────┘  └──────────────────────┘   │
│                                                         │
│  [Sign up for weekly newsletter] [Upgrade for alerts]  │
└─────────────────────────────────────────────────────────┘
```

#### 2. Volatility Forecast (Key differentiator)
```
┌─────────────────────────────────────────────────────────┐
│  5-DAY VOLATILITY FORECAST                              │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Current sentiment extremeness: 34 (elevated)           │
│                                                         │
│  Expected volatility: HIGH                              │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Historical accuracy: When sentiment this       │   │
│  │  extreme, 5-day volatility was 74% higher       │   │
│  │  than average (p < 0.0001, n=407)               │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  Suggested actions:                                     │
│  • Reduce position sizes by 25-50%                     │
│  • Widen stop losses to avoid whipsaws                 │
│  • Consider hedging with options                       │
│                                                         │
│  [🔔 Get volatility alerts - Upgrade to Pro]           │
└─────────────────────────────────────────────────────────┘
```

#### 3. Source Intelligence (Pro feature)
```
┌─────────────────────────────────────────────────────────┐
│  SOURCE ACCURACY RANKINGS                    [PRO]      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Source                  Accuracy   Type      Weight    │
│  ─────────────────────────────────────────────────────  │
│  r/BitcoinMarkets        57.0%     Momentum   0.12     │
│  r/ethtrader             53.8%     Momentum   0.09     │
│  r/cryptocurrency        51.8%     Momentum   0.08     │
│  StockTwits              51.1%     Momentum   0.07     │
│  ...                                                    │
│  ─────────────────────────────────────────────────────  │
│  r/cryptomarkets         42.9%     CONTRARIAN 0.11     │
│  4chan /biz/             38.6%     CONTRARIAN 0.09     │
│                                                         │
│  ⚠️ Divergence Alert: Reddit vs StockTwits disagree    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

#### 4. Historical Data (Pro feature)
```
┌─────────────────────────────────────────────────────────┐
│  HISTORICAL ANALYSIS                         [PRO]      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Date Range: [Jan 2018 ▼] to [Feb 2026 ▼]  [Apply]     │
│                                                         │
│  [Interactive chart with sentiment + price overlay]     │
│                                                         │
│  Download: [CSV] [JSON] [API Access]                   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Tech Stack Options

| Option | Pros | Cons | Effort |
|--------|------|------|--------|
| **Next.js + Vercel** | Fast, modern, easy deploy | JS ecosystem | Medium |
| **Streamlit** | Python native, quick MVP | Less customizable | Low |
| **Dash (Plotly)** | Python, good charts | Heavier | Medium |
| **Static + API** | Simple, fast | Less interactive | Low |

**Recommendation:** Start with Streamlit for MVP (we're already Python), migrate to Next.js for production.

### Pricing Tiers

| Tier | Price | Features |
|------|-------|----------|
| **Free** | $0 | Current readings, basic chart, newsletter signup |
| **Pro** | $19/mo | Historical data, source intelligence, alerts, API |
| **Team** | $49/mo | Multiple users, export, priority support |

---

## Combined Launch Plan

### Phase 1: Foundation (Week 1-2)
- [ ] Set up Substack newsletter
- [ ] Build basic Streamlit dashboard
- [ ] Create first newsletter issue
- [ ] Connect dashboard to existing data pipeline

### Phase 2: Launch (Week 3-4)
- [ ] Soft launch newsletter to crypto Twitter
- [ ] Share dashboard link in newsletter
- [ ] Post on r/cryptocurrency, r/bitcoinmarkets
- [ ] Collect feedback, iterate

### Phase 3: Monetization (Week 5-8)
- [ ] Add Pro features to dashboard
- [ ] Enable paid tier on newsletter
- [ ] Set up Stripe for dashboard payments
- [ ] Create upgrade flows

### Phase 4: Growth (Month 2-3)
- [ ] SEO optimization
- [ ] Guest posts on crypto blogs
- [ ] Twitter content strategy
- [ ] Referral program

---

## Content Calendar (First Month)

| Week | Newsletter Topic | Dashboard Update |
|------|------------------|------------------|
| 1 | "Introducing: Data-driven sentiment" | MVP launch |
| 2 | "What volatility forecasting tells us" | Add vol forecast page |
| 3 | "Source intelligence: Who to trust" | Add source rankings |
| 4 | "Monthly review: What worked" | Historical charts |

---

## Success Metrics

### Month 1
- Newsletter subscribers: 500
- Dashboard visitors: 1,000
- Email capture rate: 20%

### Month 3
- Newsletter subscribers: 2,000
- Dashboard visitors: 5,000
- Paid conversions: 50 ($500-1000/mo revenue)

### Month 6
- Newsletter subscribers: 5,000
- Paid subscribers: 200 ($2,000-4,000/mo revenue)

---

## Open Questions

1. **Brand name:** What resonates? "Sentiment Edge", "Volatility Radar", other?
2. **Design style:** Minimal/clean or data-dense/quant?
3. **Free vs paid split:** What's free, what's behind paywall?
4. **Tech choice:** Streamlit MVP or go straight to proper frontend?
5. **Launch audience:** Where do we find first 100 users?
