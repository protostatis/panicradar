const About = () => {
  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <div className="radar-panel p-6 sm:p-8">
        <div className="radar-kicker mb-3">Methodology</div>
        <h1 className="max-w-3xl text-3xl font-bold text-slate-100 mb-2 sm:text-4xl">
          About PanicRadar.ai
        </h1>
        <p className="max-w-3xl text-slate-400">
          A real-time crypto sentiment analysis dashboard that predicts
          volatility, not price direction.
        </p>
      </div>

      <div className="radar-panel p-6 sm:p-8">
        <div className="grid gap-8 lg:grid-cols-[1fr_1fr]">
        <section>
          <h2 className="text-lg font-semibold text-slate-200 mb-3">
            Our Approach
          </h2>
          <p className="text-slate-400 mb-4">
            Traditional sentiment analysis tries to predict price direction
            (up or down). Our research shows that crowd sentiment is better at
            predicting <strong className="text-slate-200">volatility</strong>{' '}
            — how much prices will move, not which direction.
          </p>
          <p className="text-slate-400">
            When sentiment reaches extremes (very bullish or very bearish),
            volatility typically increases. This insight helps traders prepare
            for significant price moves without trying to predict direction.
          </p>
        </section>

        <section id="panic-score" className="scroll-mt-20">
          <h2 className="text-lg font-semibold text-slate-200 mb-3">
            Panic Score
          </h2>
          <p className="text-slate-400 mb-4">
            Our proprietary Panic Score (0-100) measures real-time fear levels
            by combining Reddit community sentiment with market-wide fear signals.
            It uses FinBERT-based sentiment analysis on posts from the last 24 hours,
            compared against a 7-day rolling baseline to detect genuine sentiment shifts.
          </p>
          <div className="radar-card p-4 mb-4">
            <h3 className="text-sm font-semibold text-slate-300 mb-2">
              How It&apos;s Calculated
            </h3>
            <ul className="list-disc list-inside text-slate-400 space-y-2 text-sm">
              <li>
                <strong className="text-slate-300">Bearish Ratio (0-25 pts)</strong>:
                Percentage of Reddit posts with negative sentiment (&lt; -0.1)
              </li>
              <li>
                <strong className="text-slate-300">Relative Sentiment Shift (0-25 pts)</strong>:
                How much more negative today&apos;s sentiment is compared to the 7-day rolling average
              </li>
              <li>
                <strong className="text-slate-300">Negative Intensity (0-20 pts)</strong>:
                How strongly negative the bearish posts are (avg negative score)
              </li>
              <li>
                <strong className="text-slate-300">Market Fear Context (0-25 pts)</strong>:
                Inverted crypto Fear &amp; Greed Index &mdash; amplifies score during market-wide fear
              </li>
              <li>
                <strong className="text-slate-300">Fear Signals (0-5 pts)</strong>:
                Bonus for explicit panic language (capitulation, loss mentions)
              </li>
            </ul>
            <p className="text-slate-500 text-xs mt-3">
              Data sources: Reddit posts via FinBERT sentiment analysis + crypto Fear &amp; Greed Index
            </p>
          </div>
          <div className="grid grid-cols-4 gap-2 text-center text-sm">
            <div className="radar-card p-2 border-green-400/30">
              <div className="text-green-300 font-semibold">{'\u25B2'} 0-20</div>
              <div className="text-slate-500 text-xs">Calm</div>
            </div>
            <div className="radar-card p-2 border-slate-400/30">
              <div className="text-slate-300 font-semibold">{'\u25AC'} 20-40</div>
              <div className="text-slate-500 text-xs">Moderate</div>
            </div>
            <div className="radar-card p-2 border-amber-400/30">
              <div className="text-amber-300 font-semibold">{'\u25C6'} 40-60</div>
              <div className="text-slate-500 text-xs">Elevated</div>
            </div>
            <div className="radar-card p-2 border-orange-400/30">
              <div className="text-orange-300 font-semibold">{'\u25CF'} 60-100</div>
              <div className="text-slate-500 text-xs">High Panic</div>
            </div>
          </div>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-slate-200 mb-3">
            Multi-Dimensional Signals
          </h2>
          <p className="text-slate-400 mb-4">
            Beyond simple positive/negative sentiment, we analyze posts at the
            segment level to extract:
          </p>
          <ul className="list-disc list-inside text-slate-400 space-y-2">
            <li>
              <strong className="text-slate-200">Fear Index</strong>: Loss
              mentions, panic language, capitulation signals
            </li>
            <li>
              <strong className="text-slate-200">Euphoria Index</strong>: Moon
              talk, FOMO indicators, excessive optimism
            </li>
            <li>
              <strong className="text-slate-200">Activity Level</strong>: Scam
              warnings, promotional content, market activity
            </li>
          </ul>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-slate-200 mb-3">
            Bayesian Source Weighting
          </h2>
          <p className="text-slate-400 mb-4">
            Not all sources are equal. Our system learns which sources have
            predictive value using Bayesian inference:
          </p>
          <ul className="list-disc list-inside text-slate-400 space-y-2">
            <li>
              <strong className="text-slate-200">Momentum sources</strong>:
              Their sentiment aligns with future price moves
            </li>
            <li>
              <strong className="text-slate-200">Contrarian sources</strong>:
              When they&apos;re bullish, prices often fall (and vice versa)
            </li>
            <li>
              <strong className="text-slate-200">Neutral sources</strong>:
              Little predictive value, weighted minimally
            </li>
          </ul>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-slate-200 mb-3">
            Data Sources
          </h2>
          <p className="text-slate-400 mb-4">We aggregate data from:</p>
          <ul className="list-disc list-inside text-slate-400 space-y-1">
            <li>20+ cryptocurrency subreddits</li>
            <li>Crypto Twitter/X</li>
            <li>Fear &amp; Greed Index</li>
            <li>Price data (CoinGecko)</li>
            <li>On-chain metrics</li>
          </ul>
        </section>

        <section className="lg:col-span-2 border-t border-slate-700/70 pt-6">
          <h2 className="text-lg font-semibold text-slate-200 mb-3">
            Disclaimer
          </h2>
          <p className="text-slate-400 text-sm">
            This dashboard is for informational purposes only and does not
            constitute financial advice. Cryptocurrency investments carry
            significant risk. Always do your own research and never invest more
            than you can afford to lose.
          </p>
        </section>
        </div>
      </div>
    </div>
  );
};

export default About;
