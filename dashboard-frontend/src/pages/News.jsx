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

const TELEGRAM_URL = 'https://t.me/PanicRadarAlerts';
const NEWSLETTER_URL = 'https://panicradar.substack.com';

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

const BriefingHero = ({ data, updatedLabel }) => (
  <section className="radar-panel overflow-hidden p-6 sm:p-8 lg:p-10">
    <div className="absolute inset-0 bg-[radial-gradient(circle_at_15%_15%,rgba(16,185,129,0.18),transparent_34%),radial-gradient(circle_at_85%_20%,rgba(56,189,248,0.16),transparent_28%),linear-gradient(145deg,rgba(15,23,42,0),rgba(15,23,42,0.92))]" />
    <div className="absolute left-0 top-0 h-full w-px bg-gradient-to-b from-emerald-300/70 via-cyan-300/30 to-transparent" />

    <div className="relative grid gap-8 lg:grid-cols-[1.15fr_0.85fr] lg:items-end">
      <div>
        <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-cyan-400/30 bg-emerald-400/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-300 shadow-[0_0_14px_rgba(110,231,183,0.9)]" />
          Daily Intelligence Briefing
        </div>
        <h1 className="max-w-4xl text-4xl font-bold leading-[0.95] tracking-tight text-slate-50 sm:text-5xl lg:text-6xl">
          The crowd-risk tape for crypto markets.
        </h1>
        <p className="mt-5 max-w-2xl text-base leading-relaxed text-slate-300 sm:text-lg">
          PanicRadar scans market news, social chatter, source divergence, and on-chain context to surface the stories traders are likely to notice late.
        </p>

        <div className="mt-7 flex flex-col gap-3 sm:flex-row sm:flex-wrap">
          <Link
            to="/dashboard"
            onClick={() => trackEvent(GA_EVENTS.NEWS_CTA_CLICK, { label: 'news_hero_dashboard' })}
            className="radar-button-primary px-5 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-300 focus:ring-offset-2 focus:ring-offset-slate-950"
          >
            Open Live Dashboard
          </Link>
          <a
            href={TELEGRAM_URL}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => trackEvent(GA_EVENTS.NEWS_CTA_CLICK, { label: 'news_hero_telegram' })}
            className="radar-button-ghost px-5 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-300 focus:ring-offset-2 focus:ring-offset-slate-950"
          >
            Get Telegram Alerts
          </a>
          <a
            href={NEWSLETTER_URL}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => trackEvent(GA_EVENTS.NEWSLETTER_CLICK, { label: 'news_hero_newsletter' })}
            className="radar-button-ghost px-5 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-300 focus:ring-offset-2 focus:ring-offset-slate-950"
          >
            Weekly Email Briefing
          </a>
        </div>
      </div>

      <div className="rounded-3xl border border-slate-700/70 bg-slate-900/75 p-5 backdrop-blur">
        <div className="mb-4 flex items-center justify-between border-b border-slate-700/70 pb-3">
          <span className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
            Scan Telemetry
          </span>
          <span className="text-xs text-cyan-300">Updated {updatedLabel}</span>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <div className="text-2xl font-bold text-slate-50">{data.signals?.length || 0}</div>
            <div className="text-xs text-slate-500">signals</div>
          </div>
          <div>
            <div className="text-2xl font-bold text-slate-50">{data.sources_browsed}</div>
            <div className="text-xs text-slate-500">sources</div>
          </div>
          <div>
            <div className="text-2xl font-bold text-slate-50">{data.pages_visited}</div>
            <div className="text-xs text-slate-500">pages</div>
          </div>
        </div>
        <div className="mt-5 rounded-2xl border border-slate-800 bg-slate-950/80 p-4">
          <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">
            Market Read
          </div>
          <p className="line-clamp-5 text-sm leading-relaxed text-slate-400">
            {data.market_context?.dominant_sentiment || data.summary}
          </p>
        </div>
      </div>
    </div>
  </section>
);

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
      <MarketTicker context={data.market_context} />
      <BriefingHero data={data} updatedLabel={formatTimeAgo(data.generated_at)} />

      {/* Top 3 Hooks — Hero */}
      <HeroSignals hooks={data.top_3_hooks} />

      {/* Daily Summary */}
      <div className="radar-panel p-6">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300">
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
      <section className="radar-panel p-6 text-center sm:p-8">
        <h2 className="text-2xl font-bold text-slate-50">Turn the briefing into alerts.</h2>
        <p className="mx-auto mt-2 mb-5 max-w-xl text-sm leading-relaxed text-slate-400">
          The daily report shows what moved. Telegram alerts are for when crowd-risk changes while the market is still moving.
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
          <Link
            to="/dashboard"
            onClick={() => trackEvent(GA_EVENTS.NEWS_CTA_CLICK, { label: 'news_bottom_dashboard' })}
            className="radar-button-primary px-8 py-3"
          >
            View Live Dashboard
          </Link>
          <a
            href={TELEGRAM_URL}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => trackEvent(GA_EVENTS.NEWS_CTA_CLICK, { label: 'news_bottom_telegram' })}
            className="radar-button-ghost px-8 py-3"
          >
            Get Telegram Alerts
          </a>
        </div>
      </section>
    </div>
  );
};

export default News;
