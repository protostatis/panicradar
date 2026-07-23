import { useEffect, lazy, Suspense } from 'react';
import { useParams, Link } from 'react-router-dom';
import useSEO from '../hooks/useSEO';

// Custom component-based blog posts (for rich visualizations)
const customPosts = {
  'gp-beta-correlated-sampling': lazy(() => import('../components/blog/GPBetaBlogPost')),
};

const posts = {
  'measuring-ourselves': {
    title: 'The Day We Realized Our Sentiment Engine Was Measuring Itself',
    date: '2026-07-23',
    category: 'Research',
    description:
      'After 29,000 crawls and 7 months of live data, we audited our AI sentiment pipeline. Most sources converged to coin-flip accuracy. Our fear index was mostly regex. Our Thompson Sampling was optimizing something we never intended. Here\'s what we found.',
    keywords: 'crypto sentiment AI audit, Thompson Sampling, Reddit sentiment accuracy, Bayesian source weighting critique, contrarian signal false positives, sentiment model calibration',
    content: `
*This analysis draws from our live production database — Reddit-only, 29 subreddits, 29,128 stored-content events. Non-Reddit sources like 4chan and Stocktwits are tracked in our beliefs but have not been actively crawled in the current pipeline.*

## The Excitement Phase

Seven months ago we launched PanicRadar with a compelling thesis: crawl crypto communities, score their sentiment with embedding models, and use Bayesian Thompson Sampling to learn which sources actually predict price moves. Invert the ones that are reliably wrong. Alert traders when crowd psychology diverges from price action.

We built a Gaussian Process model to share knowledge between correlated sources. We ran lead-lag analysis on sentiment vs. price. We shipped real-time signal detection. Gaussian Process posteriors! Probit moment matching! L-BFGS-B hyperparameter optimization! The codebase was clean and the dashboard looked great.

Then we audited the data — and it told a different story than the one we'd been telling ourselves.

---

## What Didn't Work

### 1. Source accuracy converged to coin-flip territory

After 29,128 stored-content events across 29 communities, here's what source accuracy looks like ("accuracy" = fraction of posts where sentiment direction matched BTC's 4-hour price direction):

| Source | Accuracy | Samples | Weight |
|--------|----------|---------|--------|
| r/altcoin | 68.6% | 172 | 0.1025 |
| r/dogecoin | 54.8% | 1,364 | 0.0376 |
| r/ethtrader | 53.0% | 1,532 | 0.0273 |
| r/btc | 51.6% | 2,490 | 0.0190 |
| r/coinbase | 51.8% | 1,784 | 0.0203 |
| r/bitcoin | 51.0% | 6,429 | 0.0157 |
| r/cryptocurrency | 51.0% | 4,943 | 0.0155 |
| r/defi | 49.4% | 1,789 | 0.0133 |
| r/ethereum | 50.0% | 1,056 | 0.0100 |

**The most-crawled sources cluster at 50%.** r/bitcoin (6,429 samples) and r/cryptocurrency (4,943 samples) — 39% of all stored content — are barely distinguishable from random. This isn't Bayesian shrinkage. It's regression to the mean.

r/bitcoinbeginners told the starker story: 58.5% accuracy in February with 142 samples, **50.2%** today with 1,085. The early signal was noise.

The exception is r/altcoin at 68.6%, but with only 172 temporally-clustered samples, a naive 95% binomial interval is 61%–75%. Is that a real edge, or did we get lucky checking 41 sources and celebrating the hottest streak? We haven't run out-of-time validation to know.

### 2. The 31-day bearish streak is probably our model, not the crowd

Every day from June 23 through July 23 shows negative average sentiment. BTC sits at \\$64K–\\$66K. Persistent, grinding fear — or a measurement artifact?

Our scorer uses \`all-MiniLM-L6-v2\` embeddings with handcrafted anchors. Bullish scoring uses a single centroid. Bearish scoring blends a centroid with the five nearest bearish anchors — structurally amplifying negative signals. Title gets 20% weight, body/comments 80%. Only threads with 4+ comments are scored, selecting for contentious discussions.

A human-label audit of 154 posts confirmed the tilt: **Pearson r = 0.44**, categorical agreement **51.3%**, mean bias **-0.029** (systematically bearish). Real signal, but far from precise.

Then there's source composition. The most negative communities are r/coinbase (-0.303), r/cryptoscams (-0.294), r/binance (-0.261). These are support channels — people complaining about frozen accounts and scam tokens. Their "sentiment" reflects customer experience, not market outlook.

**We can't distinguish "the market is fearful" from "people hate their exchange's customer support"** without source-level decomposition and a calibrated baseline.

### 3. Our "fear index" is a literal-phrase detector

We advertise multi-dimensional sentiment — fear_index, euphoria_index, activity_level — as sophisticated AI outputs. Here's what they actually are: the pipeline matches each post segment against literal phrases like "panic sell," "to the moon," or "scam alert." First-match classification, first 20 segments only. No match? Both indices are zero.

The result: **4.15% of posts trigger any fear, 4.27% trigger any euphoria.** 91.8% register as having neither. Not because crypto Reddit is emotionless — because our detector misses sarcasm, implicit anxiety, irony, and any slang we didn't add to the list.

These indices are useful high-precision event detectors. When they fire, something real is happening. But they're not psychological measurements — they're "literal-panic-phrase detector" and "literal-moon-phrase detector."

### 4. Thompson Sampling was optimizing novelty, not accuracy

We built a principled Bayesian bandit: Beta(α, β) posteriors, Thompson Sampling, mathematically well-understood tradeoffs. Except the live outcome evaluator caches the BTC price once and never refreshes it. \`price_before ≈ price_after\` — every move looks like ~0%.

A 0% move scores 0.5 accuracy. With our utility formula \`0.7 × accuracy + 0.3 × novelty\` and a 0.5 utility threshold, novelty alone determines success. **The bandit learned to value interesting content over predictive content.** This plausibly explains why high-volume communities like r/bitcoin dominate despite being coin-flips.

A separate 30-minute job computes accurate source scores from database prices — but the running bandit never reloads them. The dashboard accuracy table and the live bandit's internal beliefs can diverge. Dead sources remain eligible after cooldown expires. The gap between documented behavior and production behavior is larger than we want to admit.

### 5. Our contrarian labels are overconfident

We label sources below 45% accuracy as "contrarian" and invert their signals:

| Source | Accuracy | Samples | Naive 95% CI |
|--------|----------|---------|--------------|
| r/crypto_general | 38.6% | 104 | 30%–48% |
| r/cryptocurrencymemes | 40.7% | 76 | 30%–52% |
| r/cryptomoonshots | 43.2% | 151 | 36%–51% |
| r/cryptobanter | 44.0% | 107 | 35%–53% |

Every naive confidence interval includes 50%. Real intervals should be wider (temporal clustering, multiple-comparison across 41 sources). **We can't reject the hypothesis that these sources are random.** And the 4chan /biz/ belief (1,669 crawls, 44.5% accuracy) is a ghost — migrated from an earlier system, with zero raw posts in our current database.

---

## What Did Work

Not everything broke. Three things survived the audit:

- **Data collection infrastructure.** 26,000+ posts across 29 communities with per-segment scoring, price data, and confounders. The pipeline runs reliably. That alone is nontrivial.

- **Source-level interpretability.** Knowing r/coinbase sentiment (-0.303) reflects customer complaints while r/dogecoin (-0.026) reflects meme-culture optimism is genuinely useful. Anchor-phrase scoring means we can inspect *why* any post scored the way it did — which made this audit possible.

- **Falsifiability as a feature.** We formed explicit hypotheses ("large communities contain predictive signal"), tested them against data, and published the results when they contradicted our expectations. That's the scientific method — and it's rare in crypto tools.

---

## What We'd Do Differently

If we were starting over:

**1. Baselines before models.** Every source should be compared against naive baselines — always-bullish, always-bearish, timestamp-matched majority. If a sophisticated bandit can't beat "assume the last 4 hours continue," the math doesn't matter.

**2. End-to-end production audits.** We found the price cache bug by reading code, not monitoring outputs. A weekly trace from crawl → score → evaluate → update → sample would have caught the novelty-vs-accuracy disconnect in days, not months.

**3. Confidence intervals, not point estimates.** Sources should earn "contrarian" status only when the posterior probability that accuracy < 50% is high, effective sample size is sufficient, and out-of-time validation confirms persistence. A fixed 45% threshold with 76 samples doesn't cut it.

---

## The Bottom Line

We set out to build an AI that learns which crypto communities predict the market. After seven months and 29,000 stored-content events, we learned something unexpected: **most of the signal we thought we were measuring was our own measurement apparatus reflecting back at us.**

Our bandit was optimizing novelty. Our fear index was a regex. Our bearish streak was model calibration. Our exciting early accuracies were small-sample noise. Our "30+ sources" was 29 Reddit communities plus ghost entries.

This isn't failure — it's the normal, necessary process of building real ML systems on messy social data. It's also a process most projects don't talk about publicly. We think they should.

The next version of PanicRadar will have baselines before models, confidence intervals before labels, and end-to-end audits before blog posts. When we find the next thing we got wrong, we'll publish that too.

---

*All data from our live production database as of July 23, 2026. System continues to run. We welcome scrutiny of methodology, code, and conclusions.*
    `,
  },
  'gp-beta-correlated-sampling': {
    title: 'Teaching Our Crawler That r/Bitcoin and r/CryptoCurrency Are Related',
    date: '2026-02-07',
    category: 'Research',
    description:
      'How we built a Gaussian Process model that shares knowledge between correlated Reddit sources, enabling correlated Thompson Sampling for smarter crawl decisions.',
    keywords: 'Gaussian Process, Thompson Sampling, Bayesian inference, correlated bandit, crypto sentiment, source similarity, GP-Beta hybrid',
    custom: true,
    content: `Rendered by custom component.
## The Problem: Every Source Is an Island

PanicRadar crawls 25+ Reddit communities to measure crypto sentiment. Each source has a **Beta distribution** that tracks how informative it is — how often its sentiment correctly predicted price direction.

When we observe that r/bitcoin gave us a good signal, we update its Beta parameters. Great. But r/cryptocurrency, which covers similar topics with overlapping users, learns *nothing* from that observation. It has to discover its own accuracy from scratch.

With 25 correlated sources, this is wasteful. A human would naturally think: "if r/bitcoin is accurate, r/cryptocurrency probably is too." We wanted our system to reason the same way.

## The Idea: A Joint Distribution Over Sources

Instead of treating each source independently, we model them *jointly*. The key insight is that sources which look similar — similar sentiment patterns, similar volatility, similar fear levels — should share statistical strength.

We use a **Gaussian Process (GP)** to model the latent correlation structure between sources. The GP acts as a "bridge" that connects similar sources, so evidence about one source flows to its neighbors.

Here's the high-level architecture:

- **Beta distributions** continue handling individual updates (fast, exact, battle-tested)
- **Gaussian Process** models the correlation structure via a kernel on source features
- **Thompson Sampling** draws from the GP's joint posterior to get correlated probability samples

We call it the **GP-Beta hybrid**.

## Step 1: Describing Each Source With Features

To know which sources are "similar," we need to describe them numerically. We extract a **7-dimensional feature vector** from each source's recent sentiment data (last 7 days):

| Feature | What It Measures |
|---------|-----------------|
| Mean sentiment score | Central tendency — is this source generally bullish or bearish? |
| Sentiment volatility | Standard deviation — does this source swing wildly or stay steady? |
| Mean fear index | How much panic/loss content appears |
| Mean euphoria index | How much moon/FOMO content appears |
| Mean activity level | Prevalence of scam warnings and market chatter |
| Polarity ratio | Proportion of positive vs negative posts |
| Log post volume | How active the community is (log-scaled) |

All features are **z-scored** (subtract mean, divide by standard deviation) so no single dimension dominates. After this, each source is a point in 7D space, and we can measure distances between them.

For example, r/bitcoinbeginners and r/coinbase end up very close (distance 1.10) — both have moderate sentiment, low volatility, and similar activity levels. Meanwhile r/cryptocurrencymemes is far from r/cryptotax (distance 5.24) — completely different communities.

## Step 2: The Kernel — Measuring Source Similarity

The GP uses a **kernel function** to quantify how similar two sources are. We use a composite kernel with three components:

**RBF (Radial Basis Function):** The main similarity measure. Two sources with similar feature vectors get a high kernel value. The formula is:

\`k_rbf(x_i, x_j) = sigma_f^2 * exp(-||x_i - x_j||^2 / (2 * l^2))\`

Where \`||x_i - x_j||\` is the Euclidean distance between feature vectors, \`l\` is the length scale (how far "similar" extends), and \`sigma_f^2\` is the signal variance (overall magnitude).

**Categorical bonus:** Sources of the same type (e.g., both Reddit subs, or both forums) get an extra similarity bump:

\`k_cat(x_i, x_j) = sigma_cat^2 * delta(type_i, type_j)\`

Where \`delta\` is 1 if the types match, 0 otherwise.

**Noise term:** Each source has some irreducible observation noise:

\`k_noise(x_i, x_j) = sigma_n^2 * I(i = j)\`

This only applies on the diagonal (a source compared to itself).

The full kernel is their sum:

\`k(x_i, x_j) = k_rbf + k_cat + k_noise\`

This gives us a **kernel matrix** K where entry (i, j) tells us how correlated sources i and j should be. The matrix is always positive semi-definite (a mathematical requirement for valid covariance matrices).

**Four hyperparameters** control the kernel: length scale \`l\`, signal variance \`sigma_f^2\`, category variance \`sigma_cat^2\`, and noise variance \`sigma_n^2\`. We optimize these automatically (more on that later).

## Step 3: Moment Matching — Connecting Beta to GP

Here's the tricky part. Each source has a **Beta(alpha, beta)** distribution (discrete binary observations), but the GP works in **Gaussian** (continuous normal) space. We need a bridge.

We use the **probit link function** — the inverse of the standard normal CDF, written as \`Phi^{-1}\`. This maps probabilities in [0, 1] to the entire real line, which is where Gaussians live.

For each source with Beta parameters alpha and beta:

**Convert the Beta mean to Gaussian space:**

\`mu_obs = Phi^{-1}(alpha / (alpha + beta))\`

For example, a source with 60% accuracy (alpha=60, beta=40) maps to \`Phi^{-1}(0.6) = 0.253\` in probit space.

**Convert the Beta variance to Gaussian variance** using the delta method:

\`sigma^2_obs = 1 / (phi(mu)^2 * (alpha + beta + 1))\`

Where \`phi\` (lowercase) is the standard normal PDF. Sources with more observations (larger alpha + beta) have smaller variance — we're more certain about them.

This is called **moment matching**: we match the first two moments (mean and variance) of the Beta distribution to a Gaussian in probit space.

## Step 4: The GP Posterior — Where the Magic Happens

Now we have:
- A kernel matrix **K** encoding source similarity (from step 2)
- Gaussian observations \`mu_obs\` with variances \`sigma^2_obs\` for each source (from step 3)

The GP posterior combines these using Bayes' rule. Let \`Lambda = diag(1/sigma^2_obs_1, ..., 1/sigma^2_obs_n)\` be the diagonal precision matrix (inverse variances).

**Posterior covariance:**

\`Sigma_post = (K^{-1} + Lambda)^{-1}\`

**Posterior mean:**

\`mu_post = Sigma_post * Lambda * mu_obs\`

This is the key equation. Look at what it does:

- \`K^{-1}\` is the prior precision — how much the kernel structure constrains things
- \`Lambda\` is the observation precision — how much we trust each source's data
- The posterior balances these two forces

When a source has lots of observations (large alpha + beta), its \`Lambda\` entry is large, so the posterior stays close to its observed value. But when a source has few observations, the kernel pulls it toward similar sources. **Knowledge flows from data-rich sources to data-poor ones.**

For example: if r/bitcoin has 500 observations and r/bitcoinbeginners has 50, and they have similar features, the GP posterior for r/bitcoinbeginners will be pulled toward r/bitcoin's accuracy estimate. The beginner sub borrows statistical strength from the larger community.

## Step 5: Correlated Thompson Sampling

Standard Thompson Sampling draws *independently* from each source's Beta distribution:

\`theta_i ~ Beta(alpha_i, beta_i)\` for each source independently.

This ignores correlations entirely. Our GP-Beta hybrid draws *jointly*:

**Draw a sample from the GP posterior:**

\`z ~ N(mu_post, Sigma_post)\`

This is a single draw from a multivariate normal — all sources are sampled simultaneously, with correlations encoded in \`Sigma_post\`.

**Map back to probabilities:**

\`theta_i = Phi(z_i)\`

The probit function \`Phi\` maps each sample back to [0, 1].

The result: **correlated probability samples**. When z_i is high for r/bitcoin, z_j tends to be high for r/cryptocurrency too (because \`Sigma_post\` has positive off-diagonal entries for similar sources). This means the bandit naturally groups similar sources together in its exploration.

## Step 6: Hyperparameter Optimization

The four kernel hyperparameters (length scale, signal variance, category variance, noise variance) control how much information flows between sources. We optimize them by maximizing the **marginal log-likelihood**:

\`log p(y | X, theta) = -0.5 * [y^T * (K + Lambda^{-1})^{-1} * y + log|K + Lambda^{-1}| + n * log(2*pi)]\`

Where \`y = mu_obs\` and \`X\` are the source features. This balances model fit against complexity — it prefers the simplest kernel that explains the observed data well.

We use **L-BFGS-B** (a quasi-Newton optimizer) with bounded constraints to prevent degenerate solutions. With only 30 sources and 4 parameters, this takes milliseconds.

The optimization runs every 50 belief evaluations, so the kernel adapts as the system collects more data.

## The Three-Tier Fallback

Not every source can participate in the GP. We use a tiered system:

1. **GP-eligible** (10+ crawls AND features available): correlated Thompson Sampling via the GP posterior
2. **Cold-start** (fewer than 10 crawls or no features): independent Beta sampling, the classic approach
3. **System fallback** (fewer than 5 GP-eligible sources or numerical issues): the entire system falls back to independent Thompson Sampling

This means the GP is purely additive — it can only help, never hurt. If anything goes wrong, we gracefully degrade to the battle-tested independent approach.

## What We Observed

After fitting the GP to our live data (13 active sources), some interesting patterns emerged:

**Most similar pairs:**
- r/bitcoinbeginners and r/coinbase (distance: 1.10) — both serve newcomers
- r/bitcoin and r/cryptocurrency (distance: 1.56) — the two main hubs
- r/cryptocurrencymemes and r/cryptomarkets (distance: 1.88) — both low-activity

**Least similar:**
- r/cryptotax and r/cryptocurrencymemes (distance: 5.24) — tax advice vs memes
- r/cryptotax and r/dogecoin (distance: 4.81) — completely different cultures

These groupings match intuition, which gives us confidence the feature vectors capture meaningful source characteristics.

## Why Not a Simpler Approach?

**Why not just cluster sources and share data within clusters?**

Clustering forces hard boundaries — a source is either in the cluster or not. The GP gives soft, continuous similarity. r/ethereum might be 70% similar to r/bitcoin and 30% similar to r/defi, and the GP handles this naturally.

**Why not a pure GP classification model?**

A pure GP classifier over all 7000+ historical observations would need to store and invert enormous matrices. The Beta sufficient statistics compress all history into just two numbers per source (alpha, beta). The hybrid gets the best of both: Beta for efficient per-source learning, GP for cross-source correlation.

**Why not just use a correlation matrix?**

A sample correlation matrix from raw accuracy data would be noisy and unstable with only 30 sources. The GP kernel imposes smoothness via the RBF function, giving us a principled correlation structure even with limited data. Plus, the kernel can extrapolate to new sources based on their features.

## Summary

The GP-Beta hybrid lets our crawler share knowledge between similar sources:

1. **Feature vectors** (7D) describe each source's sentiment behavior
2. **Composite kernel** measures similarity in feature space
3. **Moment matching** bridges Beta and Gaussian distributions via the probit link
4. **GP posterior** fuses the kernel prior with observed data
5. **Correlated Thompson Sampling** draws joint probability samples
6. **Hyperparameter optimization** tunes the kernel automatically

The result: when one source proves accurate, similar sources benefit. The crawler learns faster, explores more efficiently, and makes better decisions about where to crawl next.

You can see the source similarity visualization on our [Beliefs dashboard](/beliefs) — including the heatmap showing which sources behave most alike.

---

*All the math in this post is implemented in our open-source codebase. See [gp_model.py](https://github.com/protostatis/panicradar) for the GP implementation and [feature_extraction.py](https://github.com/protostatis/panicradar) for the feature pipeline.*
    `,
  },
  'looking-for-partners': {
    title: 'Looking for Affiliate Partners',
    date: '2026-02-04',
    category: 'Announcement',
    description:
      'PanicRadar.ai is seeking affiliate partners to help grow our crypto sentiment intelligence platform. Learn about our partnership program.',
    keywords: 'crypto affiliate, sentiment analysis partnership, crypto tools affiliate program',
    content: `
## Join the PanicRadar.ai Partner Program

We're building something different in the crypto space - a sentiment intelligence platform that actually tells you when the crowd might be wrong. And we're looking for partners to help spread the word.

### What is PanicRadar.ai?

PanicRadar.ai tracks real-time sentiment across Reddit, StockTwits, 4chan, and other crypto communities. But here's the twist: we don't just measure sentiment - we measure *when to bet against it*.

Our system uses Bayesian learning to identify "contrarian sources" - communities that consistently get it wrong. When everyone on r/CryptoCurrencyMemes is scared, that might actually be a buy signal.

### Why Partner With Us?

**Competitive Commissions**
- Earn recurring commissions on every paying subscriber you refer
- Tiered rates that increase with volume

**Growing Market**
- Crypto sentiment tools are in high demand
- Our unique contrarian approach stands out

**Quality Product**
- Real-time data from 30+ sources
- Machine learning-powered signal detection
- Transparent methodology (we publish our research)

### Who We're Looking For

- **Crypto content creators** - YouTubers, podcasters, newsletter writers
- **Trading communities** - Discord servers, Telegram groups, forums
- **Financial bloggers** - Personal finance and investing writers
- **Influencers** - Anyone with an engaged crypto audience

### How It Works

1. Apply to our partner program
2. Get your unique referral link
3. Share with your audience
4. Earn commissions on conversions

### Ready to Partner?

We're excited to work with creators and communities who share our vision of smarter crypto analysis.

**[Contact us at protostatis.dev@gmail.com](mailto:protostatis.dev@gmail.com?subject=Affiliate%20Partnership%20Inquiry%20-%20PanicRadar.ai&body=Hi%20PanicRadar.ai%20Team%2C%0A%0AI'm%20interested%20in%20becoming%20an%20affiliate%20partner.%0A%0ACompany%2FName%3A%20%0AWebsite%3A%20%0AHow%20I%20plan%20to%20promote%3A%20%0A%0AThanks!)**

Include your name, website/channel, and how you plan to promote PanicRadar.ai. We'll get back to you within 48 hours.

---

*PanicRadar.ai - See through the noise. Trade the signal.*
    `,
  },
  'causal-analysis-findings': {
    title: 'What We Learned: Does Reddit Sentiment Actually Move Crypto Prices?',
    date: '2026-02-04',
    category: 'Research',
    description:
      'Granger causality analysis reveals price leads crypto sentiment by ~15 hours. We explain what this means for traders and how PanicRadar uses contrarian signals.',
    keywords: 'crypto sentiment analysis, Granger causality crypto, Reddit sentiment Bitcoin, contrarian crypto signals, price leads sentiment',
    content: `
## The Big Question

Here at PanicRadar.ai, we started with a simple hypothesis: *if we can measure what the crypto crowd is feeling, we can predict where prices are going*.

Turns out, it's not that simple. But what we discovered was actually more useful.

## What We Did

We collected a month of data (January 2026):
- **1,432 sentiment scores** from Reddit posts across r/Bitcoin, r/CryptoCurrency, r/Ethereum, and 20+ other crypto communities
- **2,214 hourly price points** for Bitcoin
- **724 confounder snapshots** - things like VIX (market fear), volatility, and trends

Then we ran proper causal analysis. Not just "sentiment goes up, price goes up" correlation - we wanted to know if sentiment actually *causes* price movements.

## The First Surprise: Our Sentiment Scoring Was Broken

Before we could analyze anything, we found a big problem. Our VADER-based sentiment analyzer was getting things spectacularly wrong:

| What the post said | What we scored | What it actually was |
|-------------------|----------------|---------------------|
| "crypto tax software is expensive and unable to deal with..." | **+0.94** (very positive) | Negative (complaint) |
| "WARNING: Protect Your Crypto from Scammers" | **+0.73** (positive) | Negative (warning) |
| "This proposal seeks approval for the DAO..." | **+0.99** (extremely positive) | Neutral (governance) |

Classic sentiment tools score words like "approval", "protect", and "fund" as positive - but in crypto context, they often appear in complaints and warnings.

**Fix**: We built a crypto-specific lexicon with 80+ custom terms and pattern detection for phrases like "too expensive", "unable to", and "WARNING:". Accuracy jumped from ~25% to 88%.

## The Second Surprise: Fear & Greed Index is a Collider

We almost made a huge mistake. We were going to use the Fear & Greed Index (that 0-100 score you see everywhere) as a "confounder" in our analysis - something we needed to control for.

But when we tested it properly:

- **Does F&G predict sentiment?** p = 0.06 - No, not really
- **Does past price predict F&G?** p = 0.008 - Yes!
- **Correlation between F&G and price trend:** r = 0.85 - They're basically the same thing

The Fear & Greed Index doesn't *cause* sentiment or price - it's *caused by* price. It's what statisticians call a "collider". If we had controlled for it, we would have introduced bias into our results.

This matters because a lot of crypto analysis tools treat F&G as a predictor. It's not - it's a thermometer that tells you where you've been, not where you're going.

## The Main Finding: Sentiment Doesn't Cause Price (But...)

After fixing our sentiment scoring and removing F&G, here's what we found:

| Analysis Type | Sentiment Effect | p-value | Significant? |
|--------------|------------------|---------|--------------|
| Simple correlation | +0.059 | 0.14 | No |
| With 3-hour lag | +0.092 | 0.02 | Yes |
| After adjusting for confounders | +0.070 | 0.35 | No |

The weak signal at 3 hours disappears when we account for things like VIX and volatility. These factors affect both sentiment and price, creating a spurious correlation.

**In plain English**: Reddit sentiment doesn't reliably predict crypto prices. The times it seems to work are probably just both reacting to the same underlying news.

## The Plot Twist: Price Leads Sentiment

Here's where it gets interesting. When we looked at the timing relationship:

**Peak correlation: Price leads sentiment by 15 hours**

In other words, price moves *first*, and then Reddit reacts. People post because of what happened, not before it happens.

This makes sense when you think about it. A big price drop happens, people go to Reddit to panic, sentiment turns negative. The posts don't cause the drop; they react to it.

## How We Used This

Instead of throwing away our sentiment data, we pivoted. If sentiment is a *lagging* indicator that often overreacts, we can use it as a **contrarian signal**.

We built a Bayesian learning system that tracks each source's "accuracy" - how often bullish sentiment actually precedes price increases. Sources below 45% accuracy get flagged as "contrarian" and their sentiment is *inverted* in our calculations.

Current stats:
- **32 sources** with learned weights
- **15 contrarian sources** (we flip their signals)
- **Accuracy range**: 30% to 60%

When r/CryptoCurrencyMemes is extremely scared and price isn't actually falling? That's often a buy signal. We call it "bullish divergence."

## What This Means For You

1. **Don't trust simple sentiment scores.** Crypto text is weird - warnings can look positive to basic sentiment tools.

2. **Fear & Greed is a thermometer, not a crystal ball.** It tells you how people feel, not where price is going.

3. **Contrarian signals work.** Extreme sentiment (especially extreme fear) often marks turning points.

4. **The crowd is a lagging indicator.** By the time Reddit is panicking, the drop may already be priced in.

## Limitations

We're being honest about what we don't know:
- This is one month of data (January 2026, a fearful market)
- We can't observe "whale intent" - big players who might be manipulating both sentiment and price
- Hourly aggregation might miss faster dynamics
- Results could differ in bull vs bear markets

We're continuing to collect data and will update our analysis as we learn more.

---

## Technical Details

For the data scientists in the audience:

- **Method**: Backdoor adjustment with observable confounders (VIX, volatility, trend)
- **Sentiment**: Enhanced VADER with crypto lexicon + pattern detection
- **Sample**: 464 aligned hourly observations
- **DAG**: Explicit causal graph with identified confounders and colliders

Full technical documentation available in our [GitHub repo](https://github.com/protostatis/panicradar).

---

*This analysis directly shapes how PanicRadar.ai generates signals. We don't just aggregate sentiment - we learn which sources to trust, which to invert, and when the crowd is probably wrong.*
    `,
  },
};

const BlogPost = () => {
  const { slug } = useParams();
  const post = posts[slug];

  useSEO({
    title: post ? post.title : 'Post Not Found',
    description: post?.description || '',
    url: post ? `https://panicradar.ai/blog/${slug}` : undefined,
    type: 'article',
  });

  // Inject JSON-LD structured data for search engines
  useEffect(() => {
    if (!post) return;

    const jsonLd = {
      '@context': 'https://schema.org',
      '@type': 'Article',
      headline: post.title,
      description: post.description,
      datePublished: post.date,
      dateModified: post.date,
      author: {
        '@type': 'Organization',
        name: 'PanicRadar',
        url: 'https://panicradar.ai',
      },
      publisher: {
        '@type': 'Organization',
        name: 'PanicRadar',
        url: 'https://panicradar.ai',
      },
      mainEntityOfPage: {
        '@type': 'WebPage',
        '@id': `https://panicradar.ai/blog/${slug}`,
      },
      keywords: post.keywords,
    };

    const script = document.createElement('script');
    script.type = 'application/ld+json';
    script.textContent = JSON.stringify(jsonLd);
    script.id = 'blog-post-jsonld';
    document.head.appendChild(script);

    return () => {
      const existing = document.getElementById('blog-post-jsonld');
      if (existing) existing.remove();
    };
  }, [slug, post]);

  if (!post) {
    return (
      <div className="text-center py-12">
        <h1 className="text-2xl font-bold text-slate-100 mb-4">Post Not Found</h1>
        <Link to="/blog" className="text-purple-400 hover:text-purple-300">
          &larr; Back to Blog
        </Link>
      </div>
    );
  }

  // Estimate reading time from word count
  const wordCount = post.content.trim().split(/\s+/).length;
  const readingTime = Math.max(1, Math.round(wordCount / 230));

  return (
    <div className="max-w-3xl mx-auto">
      <Link to="/blog" className="text-purple-400 hover:text-purple-300 text-sm mb-6 inline-block">
        &larr; Back to Blog
      </Link>

      <article className="bg-slate-800/50 rounded-xl p-8 border border-slate-700">
        <div className="flex items-center gap-3 mb-4">
          <span className="px-2 py-1 text-xs font-medium bg-purple-500/20 text-purple-300 rounded">
            {post.category}
          </span>
          <time dateTime={post.date} className="text-sm text-slate-500">
            {post.date}
          </time>
          <span className="text-sm text-slate-500">{readingTime} min read</span>
        </div>

        <h1 className="text-3xl font-bold text-slate-100 mb-8">
          {post.title}
        </h1>

        {post.custom && customPosts[slug] ? (
          <Suspense fallback={<div className="text-slate-500">Loading...</div>}>
            {(() => { const CustomPost = customPosts[slug]; return <CustomPost />; })()}
          </Suspense>
        ) : (
          <div className="prose prose-invert prose-slate max-w-none
            prose-headings:text-slate-100 prose-headings:font-semibold
            prose-h2:text-2xl prose-h2:mt-8 prose-h2:mb-4
            prose-h3:text-xl prose-h3:mt-6 prose-h3:mb-3
            prose-p:text-slate-300 prose-p:leading-relaxed prose-p:mb-4
            prose-a:text-purple-400 prose-a:no-underline hover:prose-a:text-purple-300
            prose-strong:text-slate-200 prose-strong:font-semibold
            prose-ul:text-slate-300 prose-li:mb-2
            prose-table:border-collapse prose-table:w-full
            prose-th:bg-slate-700/50 prose-th:text-slate-200 prose-th:p-3 prose-th:text-left prose-th:border prose-th:border-slate-600
            prose-td:p-3 prose-td:border prose-td:border-slate-600 prose-td:text-slate-300
            prose-code:text-purple-300 prose-code:bg-slate-700/50 prose-code:px-1 prose-code:rounded
            prose-hr:border-slate-700 prose-hr:my-8
            prose-blockquote:border-l-purple-500 prose-blockquote:text-slate-400"
          >
            <div dangerouslySetInnerHTML={{ __html: renderMarkdown(post.content) }} />
          </div>
        )}

        {/* CTA section */}
        <div className="mt-10 pt-8 border-t border-slate-700">
          <div className="bg-slate-900/50 rounded-xl p-6 text-center">
            <p className="text-slate-200 font-semibold mb-2">
              See the panic before the crowd.
            </p>
            <p className="text-slate-400 text-sm mb-4">
              Free dashboard with live sentiment data from 30+ crypto
              communities.
            </p>
            <div className="flex items-center justify-center gap-3">
              <Link
                to="/dashboard"
                className="px-5 py-2 bg-green-500 hover:bg-green-400 text-slate-900 font-medium rounded-lg transition-colors text-sm"
              >
                View Dashboard
              </Link>
              <Link
                to="/blog"
                className="px-5 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 font-medium rounded-lg transition-colors text-sm"
              >
                More Articles
              </Link>
            </div>
          </div>
        </div>
      </article>
    </div>
  );
};

// Simple markdown renderer (tables, headings, bold, links, lists, code, hr)
function renderMarkdown(text) {
  let html = text
    // Escape HTML
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    // Tables
    .replace(/^\|(.+)\|\s*$/gm, (match, content) => {
      const cells = content.split('|').map(c => c.trim());
      if (cells.every(c => /^-+$/.test(c))) {
        return '<!-- table separator -->';
      }
      return `<tr>${cells.map(c => `<td>${c}</td>`).join('')}</tr>`;
    })
    // Wrap consecutive table rows
    .replace(/((?:<tr>.*<\/tr>\n?)+)/g, '<table>$1</table>')
    .replace(/<!-- table separator -->\n?/g, '')
    // First row of each table to th
    .replace(/<table><tr>(.*?)<\/tr>/g, (match, cells) => {
      const ths = cells.replace(/<td>/g, '<th>').replace(/<\/td>/g, '</th>');
      return `<table><thead><tr>${ths}</tr></thead><tbody>`;
    })
    .replace(/<\/table>/g, '</tbody></table>')
    // Horizontal rules
    .replace(/^---+$/gm, '<hr />')
    // Headers
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    // Bold
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Links
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>')
    // Inline code
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // Unordered lists
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>')
    // Numbered lists
    .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
    // Paragraphs (lines not already wrapped)
    .replace(/^(?!<[hupolta]|<li|<hr|<\/|$)(.+)$/gm, '<p>$1</p>')
    // Clean up empty paragraphs
    .replace(/<p>\s*<\/p>/g, '')
    // Fix nested issues
    .replace(/<\/ul>\n<ul>/g, '');

  return html;
}

export default BlogPost;
