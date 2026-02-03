import { useState, useEffect } from 'react';
import MetricCard from '../components/MetricCard';
import BullBearChart from '../components/BullBearChart';
import CoinPriceCard from '../components/CoinPriceCard';
import CrowdGauges from '../components/CrowdGauges';
import VolatilityOutlook from '../components/VolatilityOutlook';
import BeliefsSummary from '../components/BeliefsSummary';
import AffiliateBox from '../components/AffiliateBox';
import RecentPostsFeed from '../components/RecentPostsFeed';
import LoadingSpinner from '../components/LoadingSpinner';
import ErrorMessage from '../components/ErrorMessage';
import { ChartSyncProvider } from '../context/ChartSyncContext';
import {
  fetchDashboardSummary,
  fetchDashboardHistory,
  fetchAffiliates,
  fetchBayesianBeliefs,
  fetchAllSourcesHistory,
} from '../api/client';

const Dashboard = () => {
  const [summary, setSummary] = useState(null);
  const [history, setHistory] = useState(null);
  const [affiliates, setAffiliates] = useState(null);
  const [beliefs, setBeliefs] = useState(null);
  const [sourcesHistory, setSourcesHistory] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadData = async () => {
    setLoading(true);
    setError(null);

    try {
      const [summaryData, historyData, affiliateData, beliefsData, sourcesData] = await Promise.all([
        fetchDashboardSummary(),
        fetchDashboardHistory(30),
        fetchAffiliates(),
        fetchBayesianBeliefs(),
        fetchAllSourcesHistory(30),
      ]);

      setSummary(summaryData);
      setHistory(historyData);
      setAffiliates(affiliateData);
      setBeliefs(beliefsData);
      setSourcesHistory(sourcesData);
    } catch (err) {
      console.error('Failed to load dashboard data:', err);
      setError('Failed to load dashboard data. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    // Refresh data every 5 minutes
    const interval = setInterval(loadData, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  const getPanicIndexType = (value) => {
    if (value >= 0.3) return 'bearish';
    if (value >= 0.1) return 'moderate';
    return 'low';
  };

  const getFomoIndexType = (value) => {
    if (value >= 0.3) return 'bullish';
    if (value >= 0.1) return 'moderate';
    return 'low';
  };

  const getFearGreedCardType = (label) => {
    if (label.includes('Fear')) return 'fear';
    if (label.includes('Greed')) return 'greed';
    return 'neutral';
  };

  const getVolatilityCardType = (state) => {
    switch (state) {
      case 'High':
      case 'Extreme':
        return 'high';
      case 'Moderate':
        return 'moderate';
      case 'Low':
        return 'low';
      default:
        return 'default';
    }
  };

  if (loading) {
    return <LoadingSpinner message="Loading dashboard data..." />;
  }

  if (error) {
    return <ErrorMessage message={error} onRetry={loadData} />;
  }

  return (
    <ChartSyncProvider>
    <div className="space-y-6">
      {/* Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          title="Panic Index"
          value={`${((summary.fear_index || 0) * 100).toFixed(1)}%`}
          subtitle={summary.fear_index >= 0.3 ? 'High Panic' : summary.fear_index >= 0.1 ? 'Moderate' : 'Low'}
          type={getPanicIndexType(summary.fear_index || 0)}
        />
        <MetricCard
          title="FOMO Index"
          value={`${((summary.euphoria_index || 0) * 100).toFixed(1)}%`}
          subtitle={summary.euphoria_index >= 0.3 ? 'High FOMO' : summary.euphoria_index >= 0.1 ? 'Moderate' : 'Low'}
          type={getFomoIndexType(summary.euphoria_index || 0)}
        />
        <MetricCard
          title="Fear & Greed"
          value={summary.fear_greed_index ?? 'N/A'}
          subtitle={summary.fear_greed_label}
          type={getFearGreedCardType(summary.fear_greed_label)}
        />
        <MetricCard
          title="Volatility (24h)"
          value={
            summary.volatility_24h
              ? `${summary.volatility_24h.toFixed(1)}%`
              : 'N/A'
          }
          subtitle={summary.volatility_state}
          type={getVolatilityCardType(summary.volatility_state)}
        />
      </div>

      {/* Coin Price Card with Chart */}
      <CoinPriceCard />

      {/* Bull vs Bear Chart and Live Feed */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <BullBearChart
            data={history?.data || []}
            sourcesData={sourcesHistory?.sources || {}}
          />
        </div>
        <div className="lg:col-span-1">
          <RecentPostsFeed />
        </div>
      </div>

      {/* Bayesian Beliefs Summary */}
      {beliefs && (
        <BeliefsSummary
          beliefs={beliefs.beliefs}
          lastUpdate={beliefs.last_belief_update}
        />
      )}

      {/* Crowd Psychology and Volatility Outlook */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <CrowdGauges
          fearIndex={summary.fear_index}
          euphoriaIndex={summary.euphoria_index}
          activityLevel={summary.activity_level}
        />
        <VolatilityOutlook
          volatilityState={summary.volatility_state}
          sentimentState={summary.sentiment_state}
        />
      </div>

      {/* Affiliate Box */}
      {affiliates && (
        <AffiliateBox
          context={affiliates.context}
          recommendations={affiliates.recommendations}
        />
      )}
    </div>
    </ChartSyncProvider>
  );
};

export default Dashboard;
