import { useState, useEffect } from 'react';
import SourceTable from '../components/SourceTable';
import LoadingSpinner from '../components/LoadingSpinner';
import ErrorMessage from '../components/ErrorMessage';
import SectionHeader from '../components/ui/SectionHeader';
import { fetchSourceRankings } from '../api/client';

const Sources = () => {
  const [sources, setSources] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadData = async () => {
    setLoading(true);
    setError(null);

    try {
      const data = await fetchSourceRankings();
      setSources(data);
    } catch (err) {
      console.error('Failed to load source rankings:', err);
      setError('Failed to load source rankings. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  if (loading) {
    return <LoadingSpinner message="Loading source rankings..." />;
  }

  if (error) {
    return <ErrorMessage message={error} onRetry={loadData} />;
  }

  return (
    <div className="space-y-8">
      <SectionHeader kicker="Source intelligence" kickerTick title="Source Intelligence" description="Our Bayesian learning system ranks sources by their predictive accuracy. Sources are classified as momentum (sentiment aligns with future price) or contrarian (inverted signal)." />

      <SourceTable
        sources={sources?.sources || []}
        lastUpdated={sources?.last_updated}
      />

      <div className="radar-panel p-6">
        <h3 className="text-lg font-semibold text-slate-200 mb-4">
          How It Works
        </h3>
        <div className="space-y-4 text-slate-400">
          <div>
            <h4 className="text-slate-200 font-medium mb-1">Weight</h4>
            <p>
              The influence a source has on the aggregate sentiment score.
              Higher weights indicate more predictive power.
            </p>
          </div>
          <div>
            <h4 className="text-slate-200 font-medium mb-1">Accuracy</h4>
            <p>
              Percentage of times the source&apos;s sentiment correctly predicted
              price direction. Contrarian sources have accuracy below 50%
              (intentionally inverted).
            </p>
          </div>
          <div>
            <h4 className="text-slate-200 font-medium mb-1">Type</h4>
            <ul className="list-disc list-inside space-y-1">
              <li>
                <span className="text-green-300">{'\u25B2'} Momentum</span>: Sentiment
                aligns with future price moves
              </li>
              <li>
                <span className="text-red-300">{'\u25BC'} Contrarian</span>: Inverted
                signal (crowd is often wrong)
              </li>
              <li>
                <span className="text-slate-400">{'\u25AC'} Neutral</span>: Insufficient
                data or near 50% accuracy
              </li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Sources;
