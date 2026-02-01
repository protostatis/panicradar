const BeliefCard = ({ belief, onClick }) => {
  const getTypeColor = (type) => {
    switch (type) {
      case 'Momentum':
        return 'bg-green-500';
      case 'Contrarian':
        return 'bg-orange-500';
      default:
        return 'bg-slate-500';
    }
  };

  const getAccuracyColor = (accuracy) => {
    if (accuracy === null) return 'text-slate-400';
    if (accuracy > 0.55) return 'text-green-400';
    if (accuracy < 0.45) return 'text-orange-400';
    return 'text-slate-300';
  };

  const formatSourceName = (source) => {
    return source
      .replace('reddit_', 'r/')
      .replace('4chan_', '/')
      .replace(/_/g, '');
  };

  // Beta distribution visualization (simplified)
  const beliefWidth = Math.min(100, Math.max(0, belief.belief_mean * 100));

  return (
    <div
      onClick={() => onClick?.(belief.source)}
      className={`bg-slate-800/50 rounded-lg border border-slate-700 p-4 hover:border-slate-500 transition-all ${
        onClick ? 'cursor-pointer hover:scale-[1.02]' : ''
      }`}
    >
      <div className="flex items-start justify-between mb-2">
        <div>
          <h4 className="text-slate-200 font-medium">
            {formatSourceName(belief.source)}
          </h4>
          <span
            className={`inline-block px-2 py-0.5 rounded text-xs font-medium text-white ${getTypeColor(
              belief.type_label
            )}`}
          >
            {belief.type_label}
          </span>
        </div>
        <div className="text-right">
          <div className={`text-lg font-bold ${getAccuracyColor(belief.accuracy)}`}>
            {belief.accuracy !== null
              ? `${(belief.accuracy * 100).toFixed(1)}%`
              : 'N/A'}
          </div>
          <div className="text-xs text-slate-500">accuracy</div>
        </div>
      </div>

      {/* Belief Distribution Bar */}
      <div className="mt-3">
        <div className="flex justify-between text-xs text-slate-500 mb-1">
          <span>Belief: {(belief.belief_mean * 100).toFixed(1)}%</span>
          <span>± {(belief.belief_std * 100).toFixed(1)}%</span>
        </div>
        <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-purple-500 to-blue-500 transition-all duration-500"
            style={{ width: `${beliefWidth}%` }}
          />
        </div>
      </div>

      {/* Stats */}
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <div>
          <span className="text-slate-500">α/β: </span>
          <span className="text-slate-300">
            {belief.alpha.toFixed(0)}/{belief.beta.toFixed(0)}
          </span>
        </div>
        <div>
          <span className="text-slate-500">Samples: </span>
          <span className="text-slate-300">{belief.total_crawls.toLocaleString()}</span>
        </div>
        {belief.correlation !== null && (
          <div className="col-span-2">
            <span className="text-slate-500">Correlation: </span>
            <span
              className={
                belief.correlation > 0 ? 'text-green-400' : 'text-red-400'
              }
            >
              {belief.correlation > 0 ? '+' : ''}
              {belief.correlation.toFixed(3)}
            </span>
          </div>
        )}
      </div>
    </div>
  );
};

export default BeliefCard;
