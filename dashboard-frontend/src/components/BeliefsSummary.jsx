import { Link } from 'react-router-dom';

const BeliefsSummary = ({ beliefs, lastUpdate }) => {
  if (!beliefs || beliefs.length === 0) {
    return null;
  }

  // Get top performers by accuracy (with enough samples)
  const activeBeliefs = beliefs.filter((b) => b.total_crawls >= 20);
  const momentum = activeBeliefs
    .filter((b) => b.type_label === 'Momentum')
    .sort((a, b) => (b.accuracy || 0) - (a.accuracy || 0))
    .slice(0, 3);
  const contrarian = activeBeliefs
    .filter((b) => b.type_label === 'Contrarian')
    .sort((a, b) => (a.accuracy || 1) - (b.accuracy || 1))
    .slice(0, 3);

  const formatSourceName = (source) => {
    return source
      .replace('reddit_', 'r/')
      .replace('4chan_', '/')
      .replace(/_/g, '');
  };

  const SourcePill = ({ belief, type }) => {
    const bgColor = type === 'momentum' ? 'bg-green-900/40' : 'bg-orange-900/40';
    const borderColor = type === 'momentum' ? 'border-green-600/50' : 'border-orange-600/50';
    const textColor = type === 'momentum' ? 'text-green-400' : 'text-orange-400';

    return (
      <div
        className={`${bgColor} ${borderColor} border rounded-lg px-3 py-2 flex items-center justify-between gap-2`}
      >
        <span className="text-slate-200 text-sm font-medium truncate">
          {formatSourceName(belief.source)}
        </span>
        <span className={`${textColor} text-sm font-bold`}>
          {belief.accuracy !== null ? `${(belief.accuracy * 100).toFixed(0)}%` : 'N/A'}
        </span>
      </div>
    );
  };

  return (
    <div className="radar-panel p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-slate-200">
          Bayesian Model Beliefs
        </h3>
        <Link
          to="/beliefs"
          className="text-sm text-emerald-300 hover:text-emerald-200 transition-colors"
        >
          View All →
        </Link>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Momentum Sources */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="w-2 h-2 rounded-full bg-green-500"></span>
            <span className="text-sm text-slate-400">Top Momentum Sources</span>
          </div>
          <div className="space-y-2">
            {momentum.length > 0 ? (
              momentum.map((b) => (
                <SourcePill key={b.source} belief={b} type="momentum" />
              ))
            ) : (
              <p className="text-slate-500 text-sm">No momentum sources yet</p>
            )}
          </div>
        </div>

        {/* Contrarian Sources */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="w-2 h-2 rounded-full bg-orange-500"></span>
            <span className="text-sm text-slate-400">Top Contrarian Sources</span>
          </div>
          <div className="space-y-2">
            {contrarian.length > 0 ? (
              contrarian.map((b) => (
                <SourcePill key={b.source} belief={b} type="contrarian" />
              ))
            ) : (
              <p className="text-slate-500 text-sm">No contrarian sources yet</p>
            )}
          </div>
        </div>
      </div>

      {/* Stats Row */}
      <div className="mt-4 pt-4 border-t border-slate-700/70 flex flex-wrap gap-4 text-xs text-slate-500">
        <span>
          <span className="text-slate-400">{activeBeliefs.length}</span> active sources
        </span>
        <span>
          <span className="text-green-400">
            {beliefs.filter((b) => b.type_label === 'Momentum').length}
          </span>{' '}
          momentum
        </span>
        <span>
          <span className="text-orange-400">
            {beliefs.filter((b) => b.type_label === 'Contrarian').length}
          </span>{' '}
          contrarian
        </span>
        {lastUpdate && (
          <span className="ml-auto">
            Updated: {new Date(lastUpdate).toLocaleDateString()}
          </span>
        )}
      </div>
    </div>
  );
};

export default BeliefsSummary;
