import { useState, useEffect } from 'react';
import BeliefsChart from '../components/BeliefsChart';
import SubredditChart from '../components/SubredditChart';
import MultiSourceChart from '../components/MultiSourceChart';
import SourceSimilarityMap from '../components/SourceSimilarityMap';
import LoadingSpinner from '../components/LoadingSpinner';
import ErrorMessage from '../components/ErrorMessage';
import SectionHeader from '../components/ui/SectionHeader';
import {
  fetchBayesianBeliefs,
  fetchSourceHistory,
  fetchAllSourcesHistory,
  fetchSourceSimilarity,
} from '../api/client';

const Beliefs = () => {
  const [beliefs, setBeliefs] = useState(null);
  const [allSourcesHistory, setAllSourcesHistory] = useState(null);
  const [similarity, setSimilarity] = useState(null);
  const [selectedSource, setSelectedSource] = useState(null);
  const [selectedSourceHistory, setSelectedSourceHistory] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showInactive, setShowInactive] = useState(false);

  const loadData = async () => {
    setLoading(true);
    setError(null);

    try {
      const [beliefsData, historyData, similarityData] = await Promise.all([
        fetchBayesianBeliefs(),
        fetchAllSourcesHistory(30),
        fetchSourceSimilarity().catch(() => null),
      ]);

      setBeliefs(beliefsData);
      setAllSourcesHistory(historyData);
      setSimilarity(similarityData);
    } catch (err) {
      console.error('Failed to load beliefs data:', err);
      setError('Failed to load Bayesian beliefs. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleSourceClick = async (source) => {
    if (selectedSource === source) {
      setSelectedSource(null);
      setSelectedSourceHistory(null);
      return;
    }

    setSelectedSource(source);
    try {
      const history = await fetchSourceHistory(source, 30);
      setSelectedSourceHistory(history);
    } catch (err) {
      console.error('Failed to load source history:', err);
      setSelectedSourceHistory({ source, data: [] });
    }
  };

  if (loading) {
    return <LoadingSpinner message="Loading Bayesian beliefs..." />;
  }

  if (error) {
    return <ErrorMessage message={error} onRetry={loadData} />;
  }

  const formatDate = (dateStr) => {
    if (!dateStr) return 'N/A';
    return new Date(dateStr).toLocaleString();
  };

  return (
    <div className="space-y-6">
      <SectionHeader kicker="Bayesian source model" kickerTick title="Bayesian Model Beliefs" description="Our model learns which sources are predictive using Bayesian inference. Click on a source to see its sentiment history." />

      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="radar-card p-4">
          <div className="text-2xl font-bold text-slate-100">
            {beliefs?.beliefs?.length || 0}
          </div>
          <div className="text-sm text-slate-400">Total Sources</div>
        </div>
        <div className="radar-card p-4">
          <div className="radar-tabular text-2xl font-semibold text-green-300">
            {beliefs?.beliefs?.filter((b) => b.type_label === 'Momentum').length || 0}
          </div>
          <div className="text-sm text-slate-400">Momentum</div>
        </div>
        <div className="radar-card p-4">
          <div className="radar-tabular text-2xl font-semibold text-red-300">
            {beliefs?.beliefs?.filter((b) => b.type_label === 'Contrarian').length || 0}
          </div>
          <div className="text-sm text-slate-400">Contrarian</div>
        </div>
        <div className="radar-card p-4">
          <div className="text-2xl font-bold text-slate-300">
            {beliefs?.total_crawls?.toLocaleString() || 0}
          </div>
          <div className="text-sm text-slate-400">Total Samples</div>
        </div>
      </div>

      {/* Last Update */}
      <div className="text-sm text-slate-500">
        Last belief update: {formatDate(beliefs?.last_belief_update)}
      </div>

      {/* Multi-Source Comparison Chart */}
      {allSourcesHistory?.sources && (
        <MultiSourceChart sourcesData={allSourcesHistory.sources} />
      )}

      {/* Source Similarity Map */}
      {similarity && <SourceSimilarityMap similarity={similarity} />}

      {/* Selected Source Detail */}
      {selectedSource && selectedSourceHistory && (
        <SubredditChart
          source={selectedSource}
          data={selectedSourceHistory.data}
          onClose={() => {
            setSelectedSource(null);
            setSelectedSourceHistory(null);
          }}
        />
      )}

      {/* Beliefs Chart */}
      <BeliefsChart
        beliefs={beliefs?.beliefs || []}
        onSourceClick={handleSourceClick}
        showInactive={showInactive}
      />

      {/* Toggle for inactive sources */}
      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          id="showInactive"
          checked={showInactive}
          onChange={(e) => setShowInactive(e.target.checked)}
          className="radar-focus rounded border-slate-600 bg-slate-700 text-cyan-500"
        />
        <label htmlFor="showInactive" className="text-sm text-slate-400">
          Show inactive sources (no data)
        </label>
      </div>

      {/* Methodology */}
      <div className="radar-panel p-6">
        <h3 className="text-lg font-semibold text-slate-200 mb-4">
          How Bayesian Learning Works
        </h3>
        <div className="space-y-4 text-slate-400 text-sm">
          <div>
            <h4 className="text-slate-200 font-medium mb-1">Beta Distribution</h4>
            <p>
              Each source has a Beta(α, β) belief distribution. α represents
              successful predictions, β represents failures. The belief mean
              (α / (α + β)) shows our confidence in the source.
            </p>
          </div>
          <div>
            <h4 className="text-slate-200 font-medium mb-1">Accuracy Measurement</h4>
            <p>
              We compare each source&apos;s sentiment against price movements
              at a 4-hour lag. A source is &quot;correct&quot; if positive sentiment
              precedes price increases (and vice versa).
            </p>
          </div>
          <div>
            <h4 className="text-slate-200 font-medium mb-1">Contrarian Detection</h4>
            <p>
              Sources with accuracy below 45% are marked as contrarian. Their
              sentiment is inverted during inference because the crowd is
              consistently wrong.
            </p>
          </div>
          <div>
            <h4 className="text-slate-200 font-medium mb-1">Correlation</h4>
            <p>
              Pearson correlation between sentiment and 4-hour price change.
              Positive means sentiment aligns with price moves, negative means
              it&apos;s inversely related.
            </p>
          </div>
          <div>
            <h4 className="text-slate-200 font-medium mb-1">Source Similarity (GP Model)</h4>
            <p>
              Sources are compared using 7 features extracted from recent posts:
              sentiment mean/volatility, fear/euphoria signals, activity level,
              polarity ratio, and post volume. A Gaussian Process propagates
              belief updates across similar sources &mdash; when one source proves
              accurate, similar sources get their priors pulled upward.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Beliefs;
