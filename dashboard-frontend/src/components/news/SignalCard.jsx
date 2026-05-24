const SurpriseBadge = ({ level }) => {
  const config = {
    high: {
      bg: 'bg-red-900/30 border-red-500/40',
      text: 'text-red-400',
      dot: 'bg-red-500',
      ping: 'bg-red-400',
      label: 'HIGH',
    },
    medium: {
      bg: 'bg-amber-900/30 border-amber-500/40',
      text: 'text-amber-400',
      dot: 'bg-amber-500',
      ping: null,
      label: 'MED',
    },
    low: {
      bg: 'bg-blue-900/30 border-blue-500/40',
      text: 'text-blue-400',
      dot: 'bg-blue-500',
      ping: null,
      label: 'LOW',
    },
  };

  const c = config[level] || config.low;

  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-xs font-semibold ${c.bg} ${c.text}`}>
      <span className="relative flex h-2 w-2">
        {c.ping && (
          <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${c.ping} opacity-75`} />
        )}
        <span className={`relative inline-flex rounded-full h-2 w-2 ${c.dot}`} />
      </span>
      {c.label}
    </span>
  );
};

const SourceChain = ({ source }) => {
  const nodes = source.split(/\s*[→>]\s*/);
  return (
    <div className="flex items-center gap-1 flex-wrap">
      {nodes.map((node, i) => (
        <span key={i} className="inline-flex items-center">
          <span className="bg-slate-700/80 text-slate-300 text-xs px-2 py-0.5 rounded font-mono">
            {node.trim()}
          </span>
          {i < nodes.length - 1 && (
            <span className="text-slate-600 mx-0.5 text-xs">{'\u2192'}</span>
          )}
        </span>
      ))}
    </div>
  );
};

const EngagementMetrics = ({ engagement }) => {
  if (!engagement) return null;

  const metrics = Object.entries(engagement)
    .filter(([, v]) => typeof v === 'number')
    .slice(0, 4);

  if (metrics.length === 0) return null;

  return (
    <div className="flex items-center gap-3 text-xs text-slate-500">
      {metrics.map(([key, value]) => (
        <span key={key} className="inline-flex items-center gap-1">
          <span className="text-slate-600">{key.replace(/_/g, ' ')}:</span>
          <span className="text-slate-400 font-mono">{value.toLocaleString()}</span>
        </span>
      ))}
    </div>
  );
};

const SignalCard = ({ signal }) => {
  const borderColor = {
    high: 'border-l-red-500',
    medium: 'border-l-amber-500',
    low: 'border-l-blue-500',
  }[signal.surprise_score] || 'border-l-slate-600';

  return (
    <div className={`radar-card border-l-2 ${borderColor} p-6 transition-colors hover:border-emerald-400/30`}>
      {/* Header: badge + source */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <SurpriseBadge level={signal.surprise_score} />
        <SourceChain source={signal.source} />
      </div>

      {/* Headline */}
      <h3 className="text-lg font-semibold text-slate-100 mb-3 leading-snug">
        {signal.headline}
      </h3>

      {/* Contrarian analysis */}
      <p className="text-slate-400 text-sm leading-relaxed mb-3">
        {signal.why_interesting}
      </p>

      {/* Content hook quote */}
      {signal.content_hook && (
        <div className="bg-slate-950/50 border-l-2 border-green-500/50 pl-4 py-2 mb-3 rounded-r">
          <p className="text-slate-300 text-sm italic">
            {signal.content_hook}
          </p>
        </div>
      )}

      {/* Engagement */}
      <EngagementMetrics engagement={signal.engagement} />
    </div>
  );
};

export default SignalCard;
