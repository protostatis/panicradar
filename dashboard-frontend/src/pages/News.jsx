import { useState, useEffect, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { fetchTrendingSignals } from '../api/client';
import { trackEvent, GA_EVENTS } from '../utils/analytics';
import MarketTicker from '../components/news/MarketTicker';
import HeroSignals from '../components/news/HeroSignals';
import SignalsSection from '../components/news/SignalsSection';
import TrendingCoinsTable from '../components/news/TrendingCoinsTable';
import DefiSignalsSection from '../components/news/DefiSignalsSection';
import MarketContextPanel from '../components/news/MarketContextPanel';
import BriefingSectionNav from '../components/news/BriefingSectionNav';
import { LoadingState, ErrorState } from '../components/ui/StateViews';
import FreshnessChip from '../components/ui/FreshnessChip';
import Reveal from '../components/ui/Reveal';
import useSEO from '../hooks/useSEO';

const TELEGRAM_URL = 'https://t.me/PanicRadarAlerts';
const NEWSLETTER_URL = 'https://panicradar.substack.com';

const formatCalendarDate = (dateStr) => {
  if (!dateStr) return null;
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });
};

const BriefingHero = ({ data, calendarLabel }) => {
  const leadHook = data.top_3_hooks?.[0];
  const ctx = data.market_context || {};
  const btcDown = ctx.btc_price_direction === 'down';
  const btcUp = ctx.btc_price_direction === 'up';
  const highImpact = (data.signals || []).filter((s) => s.surprise_score === 'high').length;

  return (
    <section className="radar-panel overflow-hidden p-6 sm:p-8 lg:p-10">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_15%_15%,rgba(16,185,129,0.18),transparent_34%),radial-gradient(circle_at_85%_20%,rgba(56,189,248,0.16),transparent_28%),linear-gradient(145deg,rgba(15,23,42,0),rgba(15,23,42,0.92))]" />
      <div className="absolute left-0 top-0 h-full w-px bg-gradient-to-b from-emerald-300/70 via-cyan-300/30 to-transparent" />

      <div className="relative grid gap-8 lg:grid-cols-[1.15fr_0.85fr] lg:items-end">
        <div>
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-cyan-400/30 bg-emerald-400/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-300 shadow-[0_0_14px_rgba(110,231,183,0.9)]" />
            {calendarLabel ? `${calendarLabel} \u00b7 Briefing` : 'Daily Intelligence Briefing'}
          </div>

          {/* Today's lead signal — the juice, not a static tagline */}
          {leadHook && (
            <div className="mb-4">
              <div className="radar-kicker radar-kicker--tick mb-2.5">Today&apos;s Lead Signal</div>
              <h1 className="max-w-2xl text-xl font-bold leading-snug tracking-tight text-slate-50 sm:text-2xl lg:text-[1.7rem]">
                {leadHook}
              </h1>
            </div>
          )}

          {/* Summary — supporting context */}
          <p className="mt-4 max-w-2xl text-sm leading-relaxed text-slate-400 sm:text-base">
            {data.summary}
          </p>

          <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:flex-wrap">
            <Link
              to="/dashboard"
              onClick={() => trackEvent(GA_EVENTS.NEWS_CTA_CLICK, { label: 'news_hero_dashboard' })}
              className="radar-button-primary px-5 py-3 text-sm active:scale-[0.97] focus:outline-none focus:ring-2 focus:ring-emerald-300 focus:ring-offset-2 focus:ring-offset-slate-950"
            >
              Open Live Dashboard
            </Link>
            <a
              href={TELEGRAM_URL}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => trackEvent(GA_EVENTS.NEWS_CTA_CLICK, { label: 'news_hero_telegram' })}
              className="radar-button-ghost px-5 py-3 text-sm active:scale-[0.97] focus:outline-none focus:ring-2 focus:ring-emerald-300 focus:ring-offset-2 focus:ring-offset-slate-950"
            >
              Get Telegram Alerts
            </a>
          </div>
        </div>

        {/* Market snapshot — the interpretive read, not vanity metrics */}
        <div className="rounded-3xl border border-slate-700/70 bg-slate-900/75 p-5 backdrop-blur">
          <div className="mb-4 flex items-center justify-between border-b border-slate-700/70 pb-3">
            <span className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
              Market Read
            </span>
            <FreshnessChip updatedAt={data.generated_at} staleAfterMs={6 * 60 * 60 * 1000} />
          </div>

          {/* Anchor datum: BTC + direction */}
          {ctx.btc_price && (
            <div className="mb-3 flex items-baseline gap-2.5">
              <span className="text-2xl font-bold text-slate-50">{ctx.btc_price}</span>
              <span
                className={`text-sm font-semibold ${
                  btcUp ? 'text-green-400' : btcDown ? 'text-red-400' : 'text-slate-400'
                }`}
              >
                {btcUp ? '\u25B2' : btcDown ? '\u25BC' : ''} BTC
              </span>
            </div>
          )}

          {/* The contrarian narrative */}
          {ctx.dominant_sentiment && (
            <p className="line-clamp-4 text-sm leading-relaxed text-slate-400">
              {ctx.dominant_sentiment}
            </p>
          )}

          {/* Urgency + credibility strip */}
          <a
            href="#signals"
            className="mt-4 flex items-center justify-between border-t border-slate-700/70 pt-3 text-xs transition-colors hover:text-cyan-300"
          >
            <span className="text-slate-400">
              <span className="font-semibold text-slate-200">{data.signals?.length || 0}</span> signals
              {highImpact > 0 && (
                <>
                  {' \u00b7 '}
                  <span className="font-semibold text-red-400">{highImpact}</span> high-impact
                </>
              )}
            </span>
            <span className="text-slate-500 group-hover:text-cyan-300">
              {data.sources_browsed} sources scanned {'\u2193'}
            </span>
          </a>
        </div>
      </div>
    </section>
  );
};

const News = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useSEO({
    title: 'Intelligence Briefing | PanicRadar.ai',
    description: 'Daily crypto intelligence: trending signals, contrarian analysis, and market context from 30+ sources. See what the crowd missed.',
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
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
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Build the section nav from available data so empty sections don't dangle links.
  const navItems = useMemo(() => {
    if (!data) return [];
    const items = [];
    if (data.top_3_hooks?.length) items.push({ id: 'top-signals', label: 'Top signals' });
    if (data.signals?.length) items.push({ id: 'signals', label: 'Signals', count: data.signals.length });
    if (data.trending_coins?.length || data.top_losers?.length) items.push({ id: 'movers', label: 'Movers' });
    if (data.defi_signals?.length) items.push({ id: 'defi', label: 'DeFi', count: data.defi_signals.length });
    if (data.market_context) items.push({ id: 'context', label: 'Context' });
    return items;
  }, [data]);

  const calendarLabel = formatCalendarDate(data?.date);

  if (loading) return <LoadingState message="Loading intelligence briefing…" rows={4} />;
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!data) return null;

  return (
    <div className="space-y-6 sm:space-y-8">
      <Reveal>
        <MarketTicker context={data.market_context} />
      </Reveal>
      <Reveal delay={80}>
        <BriefingHero data={data} calendarLabel={calendarLabel} />
      </Reveal>

      {navItems.length > 1 && <BriefingSectionNav items={navItems} />}

      {/* Remaining top hooks — the #1 lead is already featured in the hero */}
      {data.top_3_hooks?.length > 1 && (
        <Reveal>
          <HeroSignals hooks={data.top_3_hooks.slice(1)} />
        </Reveal>
      )}

      {/* Signal cards — with filtering + search */}
      {data.signals?.length > 0 && <SignalsSection signals={data.signals} />}

      {/* Trending Coins + Top Losers */}
      <Reveal>
        <TrendingCoinsTable coins={data.trending_coins} losers={data.top_losers} />
      </Reveal>

      {/* DeFi Signals */}
      <Reveal>
        <DefiSignalsSection signals={data.defi_signals} />
      </Reveal>

      {/* Market Context (stats only — narrative lives in the hero) */}
      <Reveal>
        <MarketContextPanel context={data.market_context} />
      </Reveal>

      {/* CTA */}
      <Reveal>
        <section className="radar-panel p-6 text-center sm:p-8">
          <h2 className="text-2xl font-bold text-slate-50">Turn the briefing into alerts.</h2>
          <p className="mx-auto mt-2 mb-5 max-w-xl text-sm leading-relaxed text-slate-400">
            The daily report shows what moved. Telegram alerts are for when crowd-risk changes while the market is still moving.
          </p>
          <div className="flex flex-col items-center justify-center gap-4 sm:flex-row">
            <Link
              to="/dashboard"
              onClick={() => trackEvent(GA_EVENTS.NEWS_CTA_CLICK, { label: 'news_bottom_dashboard' })}
              className="radar-button-primary px-8 py-3 active:scale-[0.97]"
            >
              View Live Dashboard
            </Link>
            <a
              href={TELEGRAM_URL}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => trackEvent(GA_EVENTS.NEWS_CTA_CLICK, { label: 'news_bottom_telegram' })}
              className="radar-button-ghost px-8 py-3 active:scale-[0.97]"
            >
              Get Telegram Alerts
            </a>
            <a
              href={NEWSLETTER_URL}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => trackEvent(GA_EVENTS.NEWSLETTER_CLICK, { label: 'news_bottom_newsletter' })}
              className="radar-button-ghost px-8 py-3 active:scale-[0.97]"
            >
              Weekly Email
            </a>
          </div>
        </section>
      </Reveal>
    </div>
  );
};

export default News;
