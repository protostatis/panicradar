import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { fetchPanicScore, fetchDashboardSummary } from '../api/client';

const TELEGRAM_URL = 'https://t.me/PanicRadarAlerts';
const NEWSLETTER_URL = 'https://panicradar.substack.com';

const PanicGauge = ({ score, label }) => {
  const getColor = (s) => {
    if (s >= 60) return { bar: 'bg-red-500', text: 'text-red-400', glow: 'shadow-red-500/20' };
    if (s >= 40) return { bar: 'bg-orange-500', text: 'text-orange-400', glow: 'shadow-orange-500/20' };
    if (s >= 20) return { bar: 'bg-yellow-500', text: 'text-yellow-400', glow: 'shadow-yellow-500/20' };
    return { bar: 'bg-green-500', text: 'text-green-400', glow: 'shadow-green-500/20' };
  };

  const colors = getColor(score);
  const pct = Math.min(100, Math.max(0, score));

  return (
    <div className={`bg-slate-800/80 rounded-2xl border border-slate-700 p-8 shadow-lg ${colors.glow}`}>
      <div className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3">
        Live Panic Score
      </div>
      <div className={`text-6xl font-bold mb-2 ${colors.text}`}>
        {score ?? '--'}
      </div>
      <div className="text-sm text-slate-400 mb-4">{label || 'Loading...'}</div>
      <div className="h-3 bg-slate-700 rounded-full overflow-hidden">
        <div
          className={`h-full ${colors.bar} rounded-full transition-all duration-1000`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex justify-between text-xs text-slate-500 mt-1">
        <span>Calm</span>
        <span>Moderate</span>
        <span>Elevated</span>
        <span>Panic</span>
      </div>
    </div>
  );
};

const FeatureCard = ({ icon, title, description }) => (
  <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6 hover:border-slate-600 transition-colors">
    <div className="text-2xl mb-3">{icon}</div>
    <h3 className="text-lg font-semibold text-slate-100 mb-2">{title}</h3>
    <p className="text-slate-400 text-sm leading-relaxed">{description}</p>
  </div>
);

const StatCard = ({ value, label }) => (
  <div className="text-center">
    <div className="text-3xl font-bold text-slate-100">{value}</div>
    <div className="text-sm text-slate-400 mt-1">{label}</div>
  </div>
);

const Landing = () => {
  const [panicScore, setPanicScore] = useState(null);
  const [summary, setSummary] = useState(null);

  useEffect(() => {
    const load = async () => {
      try {
        const [panic, sum] = await Promise.all([
          fetchPanicScore(),
          fetchDashboardSummary(),
        ]);
        setPanicScore(panic);
        setSummary(sum);
      } catch {
        // Silently fail — landing page still works without live data
      }
    };
    load();
  }, []);

  return (
    <div className="space-y-20">
      {/* Hero */}
      <section className="text-center pt-8 sm:pt-16">
        <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold text-slate-100 mb-6 leading-tight">
          See the panic<br />
          <span className="text-green-400">before the crowd.</span>
        </h1>
        <p className="text-lg sm:text-xl text-slate-400 max-w-2xl mx-auto mb-10 leading-relaxed">
          Real-time contrarian signals from 30+ crypto communities.
          Bayesian intelligence learns which sources to trust —
          so you know when extreme fear means opportunity.
        </p>

        {/* Live Score */}
        <div className="max-w-sm mx-auto mb-10">
          <PanicGauge
            score={panicScore?.panic_score}
            label={panicScore?.sentiment_label}
          />
        </div>

        {/* CTAs */}
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
          <Link
            to="/dashboard"
            className="px-8 py-3 bg-green-500 hover:bg-green-400 text-slate-900 font-semibold rounded-lg transition-colors text-lg"
          >
            View Dashboard
          </Link>
          <a
            href={TELEGRAM_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="px-8 py-3 bg-slate-800 hover:bg-slate-700 text-slate-100 font-semibold rounded-lg border border-slate-600 transition-colors text-lg"
          >
            Free Telegram Alerts
          </a>
        </div>
      </section>

      {/* Stats Bar */}
      <section className="bg-slate-800/30 rounded-2xl border border-slate-700/50 p-8">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          <StatCard value="30+" label="Data Sources" />
          <StatCard
            value={summary?.fear_greed_index ?? '--'}
            label={`Fear & Greed: ${summary?.fear_greed_label || '...'}`}
          />
          <StatCard
            value={summary?.volatility_24h ? `${summary.volatility_24h.toFixed(1)}%` : '--'}
            label="24h Volatility"
          />
          <StatCard value="24/7" label="Real-time Monitoring" />
        </div>
      </section>

      {/* Key Insight Callout */}
      <section className="bg-gradient-to-r from-purple-900/30 to-slate-800/30 rounded-2xl border border-purple-500/20 p-8 sm:p-10">
        <div className="max-w-3xl mx-auto">
          <div className="text-sm font-semibold text-purple-400 uppercase tracking-wider mb-3">
            Key Research Finding
          </div>
          <h2 className="text-2xl sm:text-3xl font-bold text-slate-100 mb-4">
            Price leads sentiment by ~15 hours.
          </h2>
          <p className="text-slate-400 leading-relaxed">
            Our Granger causality analysis proved that crypto crowds
            <strong className="text-slate-200"> react to price moves</strong> — they
            don't predict them. This means extreme fear after a drop is usually
            overdone. PanicRadar detects these contrarian moments: when the crowd
            panics but the data says otherwise.
          </p>
        </div>
      </section>

      {/* How It Works */}
      <section>
        <div className="text-center mb-12">
          <h2 className="text-3xl font-bold text-slate-100 mb-4">
            How PanicRadar Works
          </h2>
          <p className="text-slate-400 max-w-xl mx-auto">
            Three layers of intelligence working together to separate signal from noise.
          </p>
        </div>
        <div className="grid md:grid-cols-3 gap-6">
          <FeatureCard
            icon="1"
            title="Crawl 30+ Sources"
            description="Reddit, 4chan /biz/, StockTwits, Twitter, news sites, and on-chain data. FinBERT transformer analyzes sentiment at the segment level — separating real fear from noise."
          />
          <FeatureCard
            icon="2"
            title="Bayesian Learning"
            description="Thompson Sampling learns which sources actually predict what happens next. Contrarian sources (like 4chan) get their signals inverted. Every source earns its weight."
          />
          <FeatureCard
            icon="3"
            title="Contrarian Signals"
            description="When extreme fear meets stable prices, that's a bullish divergence. When euphoria meets weakness, that's bearish. You get alerted before the move, not after."
          />
        </div>
      </section>

      {/* Differentiators */}
      <section>
        <div className="text-center mb-12">
          <h2 className="text-3xl font-bold text-slate-100 mb-4">
            Not Another Fear & Greed Index
          </h2>
          <p className="text-slate-400 max-w-xl mx-auto">
            Most sentiment tools give you one number and call it a day. We go deeper.
          </p>
        </div>
        <div className="grid md:grid-cols-2 gap-6">
          <FeatureCard
            icon="🎯"
            title="Multi-Dimensional Scoring"
            description="Fear, euphoria, and activity tracked separately. A high fear index with low activity means something very different than high fear with high activity."
          />
          <FeatureCard
            icon="🧠"
            title="Source Intelligence"
            description="Every source gets a Bayesian accuracy score. 4chan /biz/ runs at 38% accuracy — making it one of our best contrarian indicators when inverted."
          />
          <FeatureCard
            icon="📊"
            title="Volatility, Not Direction"
            description="We don't pretend to predict if BTC goes up or down. We predict when big moves are coming — so you can size positions and set stops accordingly."
          />
          <FeatureCard
            icon="🔬"
            title="Research-Backed"
            description="Every claim is validated. Granger causality tests, backtested signal accuracy, and transparent methodology. No black boxes."
          />
        </div>
      </section>

      {/* Signal Types */}
      <section className="bg-slate-800/30 rounded-2xl border border-slate-700/50 p-8 sm:p-10">
        <h2 className="text-2xl font-bold text-slate-100 mb-6 text-center">
          Signal Types We Detect
        </h2>
        <div className="grid sm:grid-cols-2 gap-4 max-w-3xl mx-auto">
          <div className="bg-green-900/20 border border-green-500/30 rounded-xl p-5">
            <div className="text-green-400 font-semibold mb-1">Bullish Divergence</div>
            <p className="text-slate-400 text-sm">Extreme fear + price stable or rising. The crowd is scared but price isn't falling.</p>
          </div>
          <div className="bg-red-900/20 border border-red-500/30 rounded-xl p-5">
            <div className="text-red-400 font-semibold mb-1">Bearish Divergence</div>
            <p className="text-slate-400 text-sm">Extreme greed + price stable or falling. The crowd is euphoric but price isn't rising.</p>
          </div>
          <div className="bg-orange-900/20 border border-orange-500/30 rounded-xl p-5">
            <div className="text-orange-400 font-semibold mb-1">Capitulation</div>
            <p className="text-slate-400 text-sm">Extreme negative sentiment spike. Fear index above 25% — historically marks bottoms.</p>
          </div>
          <div className="bg-purple-900/20 border border-purple-500/30 rounded-xl p-5">
            <div className="text-purple-400 font-semibold mb-1">Euphoria</div>
            <p className="text-slate-400 text-sm">Extreme positive spike. Euphoria index above 25% — historically marks tops.</p>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="text-center py-8">
        <h2 className="text-3xl font-bold text-slate-100 mb-4">
          Stop trading on emotion.<br />Start trading on data.
        </h2>
        <p className="text-slate-400 max-w-lg mx-auto mb-8">
          Free dashboard. Free Telegram alerts. No account required.
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-8">
          <Link
            to="/dashboard"
            className="px-8 py-3 bg-green-500 hover:bg-green-400 text-slate-900 font-semibold rounded-lg transition-colors text-lg"
          >
            View Dashboard
          </Link>
          <a
            href={TELEGRAM_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="px-8 py-3 bg-slate-800 hover:bg-slate-700 text-slate-100 font-semibold rounded-lg border border-slate-600 transition-colors text-lg"
          >
            Join Telegram
          </a>
        </div>

        {/* Newsletter Signup */}
        <div className="max-w-md mx-auto bg-slate-800/50 rounded-xl border border-slate-700 p-6">
          <div className="text-sm font-semibold text-slate-200 mb-2">Weekly Sentiment Briefing</div>
          <p className="text-slate-400 text-sm mb-4">
            Data-driven analysis every Sunday. What the crowd got wrong this week.
          </p>
          <a
            href={NEWSLETTER_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block px-6 py-2 bg-purple-600 hover:bg-purple-500 text-white font-medium rounded-lg transition-colors"
          >
            Subscribe on Substack
          </a>
        </div>
      </section>
    </div>
  );
};

export default Landing;
