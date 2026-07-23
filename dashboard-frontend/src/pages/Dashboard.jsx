import { useState, useEffect, useMemo } from 'react';
import MetricCard from '../components/MetricCard';
import BullBearChart from '../components/BullBearChart';
import CoinPriceCard from '../components/CoinPriceCard';
import MultiCoinStrip from '../components/MultiCoinStrip';
import CrowdGauges from '../components/CrowdGauges';
import VolatilityOutlook from '../components/VolatilityOutlook';
import BeliefsSummary from '../components/BeliefsSummary';
import AffiliateBox from '../components/AffiliateBox';
import RecentPostsFeed from '../components/RecentPostsFeed';
import LoadingSpinner from '../components/LoadingSpinner';
import ErrorMessage from '../components/ErrorMessage';
import { ChartSyncProvider } from '../context/ChartSyncContext';
import SectionHeader from '../components/ui/SectionHeader';
import FreshnessChip from '../components/ui/FreshnessChip';
import ContrarianLens, { lensFromBelief } from '../components/ui/ContrarianLens';
import {
  fetchDashboardSummary, fetchAffiliates, fetchBayesianBeliefs, fetchPanicScore,
} from '../api/client';

const getFearGreedCardType = (label) => { if (!label) return 'default'; if (label.includes('Fear')) return 'fear'; if (label.includes('Greed')) return 'greed'; return 'neutral'; };
const getVolatilityCardType = (state) => { switch (state) { case 'High': case 'Extreme': return 'high'; case 'Moderate': return 'moderate'; case 'Low': return 'low'; default: return 'default'; } };
const formatSourceName = (source) => source.replace('reddit_', 'r/').replace('4chan_', '/').replace(/_/g, '');

const Dashboard = () => {
  const [summary, setSummary] = useState(null);
  const [affiliates, setAffiliates] = useState(null);
  const [beliefs, setBeliefs] = useState(null);
  const [panicScore, setPanicScore] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadData = async () => {
    setLoading(true); setError(null);
    try {
      const [summaryData, affiliateData, beliefsData, panicData] = await Promise.all([fetchDashboardSummary(), fetchAffiliates(), fetchBayesianBeliefs(), fetchPanicScore()]);
      setSummary(summaryData); setAffiliates(affiliateData); setBeliefs(beliefsData); setPanicScore(panicData); setLastUpdated(new Date());
    } catch (err) { console.error('Failed to load dashboard data:', err); setError('Failed to load dashboard data. Please try again.'); }
    finally { setLoading(false); }
  };

  useEffect(() => { loadData(); const interval = setInterval(loadData, 5 * 60 * 1000); return () => clearInterval(interval); }, []);

  const contrarianExample = useMemo(() => {
    const active = beliefs?.beliefs?.filter((b) => b.total_crawls >= 20) || [];
    const contrarian = active.filter((b) => b.type_label === 'Contrarian').sort((a, b) => (a.accuracy ?? 1) - (b.accuracy ?? 1));
    return contrarian[0] || null;
  }, [beliefs]);

  if (loading) return <LoadingSpinner message="Loading dashboard data…" />;
  if (error) return <ErrorMessage message={error} onRetry={loadData} />;

  return (
    <ChartSyncProvider>
      <div className="space-y-10">
        <header className="radar-reveal"><SectionHeader kicker="Live crowd-risk console" kickerTick title="PanicRadar Dashboard" description="Source-weighted crowd psychology and volatility context from 30+ crypto communities. The model predicts volatility, not direction." actions={<FreshnessChip updatedAt={lastUpdated} />} /></header>

        {/* DYNAMICS — chart-first to capture attention */}
        <section className="radar-reveal space-y-4" style={{ animationDelay: '60ms' }}>
          <SectionHeader as="h3" kicker="Dynamics" kickerTick title="Crowd vs price, synchronized" description="Sentiment and price on a shared timeline. Hover either chart to cross-reference dates — our research found price leads sentiment by ~15h. Watch for divergence, not prediction." />
          <BullBearChart />
          <CoinPriceCard />
          <MultiCoinStrip />
        </section>

        {/* NOW */}
        <section className="radar-reveal space-y-4" style={{ animationDelay: '120ms' }}>
          <SectionHeader as="h3" kicker="Now" kickerTick title="Current state" />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <MetricCard title="Panic Score" value={panicScore?.panic_score ?? 'N/A'} subtitle={panicScore?.sentiment_label || 'Loading…'} score={panicScore?.panic_score || 0} href="/about#panic-score" />
            <MetricCard title="Fear & Greed" value={summary.fear_greed_index ?? 'N/A'} subtitle={summary.fear_greed_label} type={getFearGreedCardType(summary.fear_greed_label)} href="https://alternative.me/crypto/fear-and-greed-index/" />
            <MetricCard title="Volatility (24h)" value={summary.volatility_24h ? `${summary.volatility_24h.toFixed(1)}%` : 'N/A'} subtitle={summary.volatility_state} type={getVolatilityCardType(summary.volatility_state)} href="https://www.coinglass.com/volatility" />
          </div>
          <RecentPostsFeed />
        </section>

        {/* DRIVERS */}
        {contrarianExample && (
          <section className="radar-reveal space-y-4" style={{ animationDelay: '180ms' }}>
            <SectionHeader as="h3" kicker="Drivers" kickerTick title="How the model reads the crowd" description="The Bayesian layer learns which sources predict volatility — and inverts the ones that are reliably wrong. Here's the strongest contrarian source right now." />
            <ContrarianLens source={formatSourceName(contrarianExample.source)} stages={lensFromBelief(contrarianExample, contrarianExample.correlation >= 0 ? 'Bullish lean' : 'Bearish lean')} horizon="4h lag vs price" footnote={`Trained on ${contrarianExample.total_crawls?.toLocaleString() || 0} samples · ρ ${contrarianExample.correlation?.toFixed(2) ?? '—'}`} />
          </section>
        )}

        {/* EVIDENCE */}
        <section className="radar-reveal space-y-4" style={{ animationDelay: '240ms' }}>
          <SectionHeader as="h3" kicker="Evidence" kickerTick title="Why these signals are trustworthy" description="Source accuracy, crowd-psychology dimensions, and the volatility outlook that ties them together." />
          {beliefs && <BeliefsSummary beliefs={beliefs.beliefs} lastUpdate={beliefs.last_belief_update} />}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <CrowdGauges fearIndex={summary.fear_index} euphoriaIndex={summary.euphoria_index} activityLevel={summary.activity_level} explicitFearPhraseRate={summary.explicit_fear_phrase_rate} explicitEuphoriaPhraseRate={summary.explicit_euphoria_phrase_rate} warningScamPhraseRate={summary.warning_scam_phrase_rate} />
            <VolatilityOutlook volatilityState={summary.volatility_state} sentimentState={summary.sentiment_state} />
          </div>
        </section>

        {/* RESOURCES */}
        {affiliates && (
          <section className="radar-reveal space-y-3" style={{ animationDelay: '300ms' }}>
            <div className="flex items-center gap-2"><span className="radar-kicker">Resources</span><span className="text-xs text-slate-600">— partner links, clearly separated</span></div>
            <AffiliateBox context={affiliates.context} recommendations={affiliates.recommendations} />
          </section>
        )}
      </div>
    </ChartSyncProvider>
  );
};

export default Dashboard;
