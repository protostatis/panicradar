import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { fetchTrendingSignals } from '../api/client';
import { trackEvent, GA_EVENTS } from '../utils/analytics';
import MarketTicker from '../components/news/MarketTicker';
import HeroSignals from '../components/news/HeroSignals';
import SignalCard from '../components/news/SignalCard';
import TrendingCoinsTable from '../components/news/TrendingCoinsTable';
import DefiSignalsSection from '../components/news/DefiSignalsSection';
import MarketContextPanel from '../components/news/MarketContextPanel';
import LoadingSpinner from '../components/LoadingSpinner';
import ErrorMessage from '../components/ErrorMessage';
import useSEO from '../hooks/useSEO';

const formatTimeAgo = (dateStr) => {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);

  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${Math.floor(diffMs / 86400000)}d ago`;
};

const News = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useSEO({
    title: 'Intelligence Briefing | PanicRadar.ai',
    description: 'Daily crypto intelligence: trending signals, contrarian analysis, and market context from 30+ sources. See what the crowd missed.',
  });

  useEffect(() => {
    const load = async () => {
      try {
        const result = await fetchTrendingSignals();
        setData(result);
        trackEvent(GA_EVENTS.NEWS_VIEW);
      } catch (err) {
        if (err.response?.status === 404) {
          setError('No intelligence data available yet. Check back after 7:45 AM CT.');
        } else {
          setError('Failed to load trending signals.');
        }
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  if (loading) return <LoadingSpinner message="Loading intelligence briefing..." />;
  if (error) return <ErrorMessage message={error} />;
  if (!data) return null;

  return (
    <div className="space-y-8">
      {/* Market Ticker */}
      <MarketTicker context={data.market_context} />

      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <h1 className="text-3xl font-bold text-slate-100">
            Intelligence Briefing
          </h1>
          <p className="text-slate-500 text-sm mt-1">
            {data.date} &middot; {data.sources_browsed} sources &middot; {data.pages_visited} pages analyzed
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
          </span>
          <span className="text-xs text-slate-500">Updated {formatTimeAgo(data.generated_at)}</span>
        </div>
      </div>

      {/* Top 3 Hooks — Hero */}
      <HeroSignals hooks={data.top_3_hooks} />

      {/* Daily Summary */}
      <div className="bg-slate-800/30 rounded-xl border border-slate-700/50 p-6">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-green-400 mb-3">
          Daily Summary
        </h2>
        <p className="text-slate-300 text-sm leading-relaxed">
          {data.summary}
        </p>
      </div>

      {/* Signal Cards */}
      <section>
        <h2 className="text-xl font-bold text-slate-100 mb-4">
          Signals ({data.signals.length})
        </h2>
        <div className="space-y-4">
          {data.signals.map((signal, i) => (
            <SignalCard key={i} signal={signal} />
          ))}
        </div>
      </section>

      {/* Trending Coins + Top Losers */}
      <TrendingCoinsTable
        coins={data.trending_coins}
        losers={data.top_losers}
      />

      {/* DeFi Signals */}
      <DefiSignalsSection signals={data.defi_signals} />

      {/* Market Context */}
      <MarketContextPanel context={data.market_context} />

      {/* CTA */}
      <section className="text-center py-6">
        <p className="text-slate-400 mb-4">
          See the panic before the crowd. Real-time contrarian signals.
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
          <Link
            to="/dashboard"
            onClick={() => trackEvent(GA_EVENTS.NEWS_CTA_CLICK, { label: 'news_view_dashboard' })}
            className="px-8 py-3 bg-green-500 hover:bg-green-400 text-slate-900 font-semibold rounded-lg transition-colors"
          >
            View Live Dashboard
          </Link>
          <a
            href="https://t.me/PanicRadarAlerts"
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => trackEvent(GA_EVENTS.NEWS_CTA_CLICK, { label: 'news_telegram' })}
            className="px-8 py-3 bg-slate-800 hover:bg-slate-700 text-slate-100 font-semibold rounded-lg border border-slate-600 transition-colors"
          >
            Get Telegram Alerts
          </a>
        </div>
      </section>
    </div>
  );
};

export default News;
