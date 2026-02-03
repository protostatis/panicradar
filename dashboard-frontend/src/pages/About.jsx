const About = () => {
  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-bold text-slate-100 mb-2">
          About Panic Radar
        </h1>
        <p className="text-slate-400">
          A real-time crypto sentiment analysis dashboard that predicts
          volatility, not price direction.
        </p>
      </div>

      <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6 space-y-6">
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

        <section>
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
  );
};

export default About;
