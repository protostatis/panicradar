import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { fetchPanicScore, fetchDashboardSummary } from '../api/client';
import { trackEvent, GA_EVENTS } from '../utils/analytics';
import IntelligencePreview from '../components/news/IntelligencePreview';
import SectionHeader from '../components/ui/SectionHeader';
import Panel from '../components/ui/Panel';
import { levelToTone, tone } from '../components/ui/tones';

const TELEGRAM_URL = 'https://t.me/PanicRadarAlerts';

const PanicGauge = ({ score, label }) => {
  const s = typeof score === 'number' ? Math.min(100, Math.max(0, score)) : null;
  const t = tone(s === null ? 'neutral' : levelToTone(s));
  const pct = s ?? 0;
  const r = 84, cx = 100, cy = 100, startAngle = 135, sweep = 270;
  const endAngle = startAngle + (sweep * pct) / 100;
  const polar = (deg) => { const rad = (deg * Math.PI) / 180; return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)]; };
  const [sx, sy] = polar(startAngle);
  const [ex, ey] = polar(endAngle);
  const largeArc = endAngle - startAngle > 180 ? 1 : 0;

  return (
    <div className="radar-panel radar-panel--accent p-6 sm:p-8">
      <div className="mb-4 flex items-center justify-between">
        <span className="radar-kicker radar-kicker--tick">Live panic score</span>
        <span className="radar-live-dot" aria-hidden="true" />
      </div>
      <div className="flex flex-col items-center">
        <div className="relative">
          <svg viewBox="0 0 200 200" className="h-48 w-48" role="img" aria-label={`Panic score ${s ?? 'unknown'}, ${label || 'loading'}`}>
            <path d={`M ${sx} ${sy} A ${r} ${r} 0 1 1 ${polar(startAngle + sweep)[0]} ${polar(startAngle + sweep)[1]}`} fill="none" stroke="#1e293b" strokeWidth="10" strokeLinecap="round" />
            {s !== null && (
              <path d={`M ${sx} ${sy} A ${r} ${r} 0 ${largeArc} 1 ${ex} ${ey}`} fill="none" stroke="currentColor" className={t.text} strokeWidth="10" strokeLinecap="round" style={{ transition: 'all 700ms cubic-bezier(0.22,1,0.36,1)' }} />
            )}
            {[0, 25, 50, 75, 100].map((tick) => { const a = startAngle + (sweep * tick) / 100; const [x1, y1] = polar(a); return <circle key={tick} cx={x1} cy={y1} r="2" fill="#334155" />; })}
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <div className={`radar-tabular text-5xl font-semibold leading-none ${t.text}`}>{s ?? '—'}</div>
            <div className="mt-2 text-sm text-slate-400">{label || 'Loading…'}</div>
          </div>
        </div>
        <div className="mt-4 flex w-full justify-between text-[0.7rem] uppercase tracking-[0.14em] text-slate-500">
          <span>Calm</span><span>Moderate</span><span>Elevated</span><span>Panic</span>
        </div>
      </div>
    </div>
  );
};

const FeatureCard = ({ index, title, description }) => (
  <div className="radar-card p-6 transition-all hover:-translate-y-0.5 hover:border-cyan-400/30">
    <div className="radar-tabular mb-4 flex h-9 w-9 items-center justify-center rounded-lg border border-cyan-400/30 bg-cyan-400/10 text-sm font-semibold text-cyan-300">{index}</div>
    <h3 className="font-display text-lg font-semibold text-slate-100">{title}</h3>
    <p className="mt-2 text-sm leading-relaxed text-slate-400">{description}</p>
  </div>
);

const Landing = () => {
  const [panicScore, setPanicScore] = useState(null);
  const [summary, setSummary] = useState(null);
  useEffect(() => { const load = async () => { try { const [panic, sum] = await Promise.all([fetchPanicScore(), fetchDashboardSummary()]); setPanicScore(panic); setSummary(sum); } catch { /* landing works without live data */ } }; load(); }, []);

  return (
    <>
      <div className="space-y-24">
        <div className="radar-reveal">
          <IntelligencePreview />
          <section className="pt-10 sm:pt-16">
            <div className="grid items-center gap-10 lg:grid-cols-[1.1fr_0.9fr]">
              <div>
                <h1 className="font-display text-4xl font-semibold leading-[1.05] tracking-tight text-slate-50 sm:text-5xl lg:text-6xl">See the panic<br /><span className="text-cyan-400">before the crowd.</span></h1>
                <p className="mt-6 max-w-xl text-lg leading-relaxed text-slate-400">Real-time contrarian signals from 30+ crypto communities. Bayesian intelligence learns which sources to trust — so you know when extreme fear actually means opportunity.</p>
                <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                  <Link to="/dashboard" onClick={() => trackEvent(GA_EVENTS.CTA_CLICK, { label: 'hero_view_dashboard' })} className="radar-button-primary px-7 py-3 text-base">View Dashboard</Link>
                  <a href={TELEGRAM_URL} target="_blank" rel="noopener noreferrer" onClick={() => trackEvent(GA_EVENTS.TELEGRAM_CLICK, { label: 'hero_telegram' })} className="radar-button-ghost px-7 py-3 text-base">Free Telegram Alerts</a>
                </div>
                <p className="mt-4 text-sm text-slate-500">Free dashboard. Free alerts. No account required.</p>
              </div>
              <div className="mx-auto w-full max-w-sm"><PanicGauge score={panicScore?.panic_score} label={panicScore?.sentiment_label} /></div>
            </div>
          </section>
        </div>

        <section className="radar-reveal"><Panel pad="lg"><div className="grid grid-cols-2 gap-6 md:grid-cols-4">{[
          ['30+', 'Data Sources'], [summary?.fear_greed_index ?? '—', `Fear & Greed: ${summary?.fear_greed_label || '…'}`], [summary?.volatility_24h ? `${summary.volatility_24h.toFixed(1)}%` : '—', '24h Volatility'], ['24/7', 'Real-time Monitoring']
        ].map(([val, label]) => (<div key={label} className="text-center"><div className="radar-tabular text-3xl font-semibold text-slate-100">{val}</div><div className="mt-1 text-sm text-slate-400">{label}</div></div>))}</div></Panel></section>

        <section className="radar-reveal"><Panel accent pad="lg"><div className="max-w-3xl"><span className="radar-kicker radar-kicker--tick">Key research finding</span><h2 className="font-display mt-3 text-2xl font-semibold text-slate-100 sm:text-3xl">Price leads sentiment by ~15 hours.</h2><p className="mt-4 leading-relaxed text-slate-400">Our Granger analysis showed crypto crowds <strong className="text-slate-200">react to price moves</strong> — they don't predict them. That means extreme fear after a drop is usually overdone. PanicRadar detects these contrarian moments: when the crowd panics but the underlying volatility picture says otherwise.</p></div></Panel></section>

        <section className="radar-reveal space-y-8"><SectionHeader kicker="How it works" kickerTick title="Three layers of intelligence" description="Separating signal from noise — every source earns its weight." /><div className="grid gap-6 md:grid-cols-3">{[
          ['1', 'Crawl 30+ sources', 'Reddit, StockTwits, Twitter, news sites, and on-chain data. A FinBERT transformer analyzes sentiment at the segment level — separating real fear from noise.'],
          ['2', 'Bayesian learning', 'Thompson Sampling learns which sources actually predict what happens next. Every source earns its weight through observed performance — not assumptions.'],
          ['3', 'Contrarian signals', 'When extreme fear meets stable prices, that\'s a bullish divergence. When euphoria meets weakness, that\'s bearish. You get alerted before the move, not after.']
        ].map(([i, t, d]) => (<FeatureCard key={i} index={i} title={t} description={d} />))}</div></section>

        <section className="radar-reveal space-y-8"><SectionHeader kicker="Differentiators" kickerTick title="Not another Fear & Greed index" description="Most sentiment tools give you one number and call it a day. We go deeper." /><div className="grid gap-6 md:grid-cols-2">{[
          ['◆', 'Multi-dimensional scoring', 'Fear, euphoria, and activity tracked separately. A high fear index with low activity means something very different than high fear with high activity.'],
          ['◆', 'Source intelligence', 'Every source gets a Bayesian accuracy score based on its track record. Some communities earn their role as reliable contrarian indicators — the model learns which ones to trust and which to invert.'],
          ['◆', 'Volatility, not direction', 'We don\'t pretend to predict if BTC goes up or down. We predict when big moves are coming — so you can size positions and set stops accordingly.'],
          ['◆', 'Research-backed', 'Every claim is validated. Granger tests, backtested signal accuracy, and transparent methodology. No black boxes.']
        ].map(([i, t, d]) => (<FeatureCard key={t} index={i} title={t} description={d} />))}</div></section>

        <section className="radar-reveal"><Panel accent pad="lg"><h2 className="font-display text-center text-2xl font-semibold text-slate-100">Signal types we detect</h2><div className="mx-auto mt-6 grid max-w-3xl gap-4 sm:grid-cols-2">{[
          { toneKey: 'bull', title: 'Bullish divergence', text: 'Extreme fear + price stable or rising. The crowd is scared but price isn\'t falling.' },
          { toneKey: 'bear', title: 'Bearish divergence', text: 'Extreme greed + price stable or falling. The crowd is euphoric but price isn\'t rising.' },
          { toneKey: 'warn', title: 'Capitulation', text: 'Extreme negative sentiment spike. Fear index above 25% — historically marks bottoms.' },
          { toneKey: 'accent', title: 'Euphoria', text: 'Extreme positive spike. Euphoria index above 25% — historically marks tops.' }
        ].map((sig) => { const t = tone(sig.toneKey); return (<div key={sig.title} className={`rounded-xl border p-5 ${t.border} ${t.chipBg}`}><div className={`flex items-center gap-2 font-semibold ${t.text}`}><span aria-hidden="true" className="text-xs">{t.glyph}</span>{sig.title}</div><p className="mt-1 text-sm text-slate-400">{sig.text}</p></div>); })}</div></Panel></section>

        <section className="radar-reveal py-8 text-center"><h2 className="font-display text-3xl font-semibold text-slate-100">Stop trading on emotion.<br />Start trading on data.</h2><div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row"><Link to="/dashboard" onClick={() => trackEvent(GA_EVENTS.CTA_CLICK, { label: 'bottom_view_dashboard' })} className="radar-button-primary px-8 py-3 text-lg">View Dashboard</Link><a href={TELEGRAM_URL} target="_blank" rel="noopener noreferrer" onClick={() => trackEvent(GA_EVENTS.TELEGRAM_CLICK, { label: 'bottom_telegram' })} className="radar-button-ghost px-8 py-3 text-lg">Join Telegram</a></div></section>
      </div>
      <a href="/game/" onClick={() => trackEvent(GA_EVENTS.GAME_PROMO_CLICK)} className="game-promo" aria-label="Play BlockCoined — a free multiplayer match-3 strategy game"><span className="game-promo__icon" aria-hidden="true">{'\u{1FA99}'}</span><span>BlockCoined — Play now</span></a>
    </>
  );
};

export default Landing;
