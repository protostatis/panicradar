const BeliefCard = ({ belief, onClick }) => {
  const getTypeStyle = (type) => {
    switch (type) {
      case 'Momentum':
        return { cls: 'bg-green-400/10 border-green-400/30 text-green-300', glyph: '\u25B2' };
      case 'Contrarian':
        return { cls: 'bg-red-400/10 border-red-400/30 text-red-300', glyph: '\u25BC' };
      default:
        return { cls: 'bg-slate-600/30 border-slate-500/40 text-slate-300', glyph: '\u25AC' };
    }
  };

  const getAccuracyColor = (accuracy) => {
    if (accuracy === null) return 'text-slate-400';
    if (accuracy > 0.55) return 'text-green-300';
    if (accuracy < 0.45) return 'text-red-300';
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
  const typeStyle = getTypeStyle(belief.type_label);

  return (
    <div
      onClick={() => onClick?.(belief.source)}
      className={`radar-card p-4 hover:border-slate-500 transition-all ${
        onClick ? 'cursor-pointer hover:scale-[1.02]' : ''
      }`}
    >
      <div className="flex items-start justify-between mb-2">
        <div>
          <h4 className="text-slate-200 font-medium">
            {formatSourceName(belief.source)}
          </h4>
          <span className={`radar-tabular mt-1 inline-flex items-center gap-1 px-2 py-0.5 rounded border text-xs font-medium ${typeStyle.cls}`}><span aria-hidden="true" className="text-[0.6rem]">{typeStyle.glyph}</span>{belief.type_label}</span>
        </div>
        <div className="text-right">
          <div className={`radar-tabular text-lg font-bold ${getAccuracyColor(belief.accuracy)}`}>
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
            className="h-full bg-gradient-to-r from-cyan-500 to-cyan-400 transition-all duration-500"
            style={{ width: `${beliefWidth}%` }}
          />
        </div>
      </div>

      {/* Stats */}
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <div>
          <span className="text-slate-500">α/β: </span>
          <span className="radar-tabular text-slate-300">
            {belief.alpha.toFixed(0)}/{belief.beta.toFixed(0)}
          </span>
        </div>
        <div>
          <span className="text-slate-500">Samples: </span>
          <span className="radar-tabular text-slate-300">{belief.total_crawls.toLocaleString()}</span>
        </div>
        {belief.correlation !== null && (
          <div className="col-span-2">
            <span className="text-slate-500">Correlation: </span>
            <span
              className={`radar-tabular ${
                belief.correlation > 0 ? 'text-green-300' : 'text-red-300'
              }`}
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
