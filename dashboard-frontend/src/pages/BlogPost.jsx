import { useParams, Link } from 'react-router-dom';

const posts = {
  'looking-for-partners': {
    title: 'Looking for Affiliate Partners',
    date: '2026-02-04',
    category: 'Announcement',
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

This makes sense when you think about it. A big price drop happens → people go to Reddit to panic → sentiment turns negative. The posts don't cause the drop; they react to it.

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

Full technical documentation available in our [GitHub repo](https://github.com).

---

*This analysis directly shapes how PanicRadar.ai generates signals. We don't just aggregate sentiment - we learn which sources to trust, which to invert, and when the crowd is probably wrong.*
    `,
  },
};

const BlogPost = () => {
  const { slug } = useParams();
  const post = posts[slug];

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
          <span className="text-sm text-slate-500">{post.date}</span>
        </div>

        <h1 className="text-3xl font-bold text-slate-100 mb-8">
          {post.title}
        </h1>

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
    // Paragraphs (lines not already wrapped)
    .replace(/^(?!<[hupolta]|<li|<hr|<\/|$)(.+)$/gm, '<p>$1</p>')
    // Clean up empty paragraphs
    .replace(/<p>\s*<\/p>/g, '')
    // Fix nested issues
    .replace(/<\/ul>\n<ul>/g, '');

  return html;
}

export default BlogPost;
