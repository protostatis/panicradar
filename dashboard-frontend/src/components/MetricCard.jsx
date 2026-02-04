import { useMemo } from 'react';
import { Link } from 'react-router-dom';

const MetricCard = ({ title, value, subtitle, type = 'default', href }) => {
  const colorClasses = useMemo(() => {
    switch (type) {
      case 'bullish':
        return 'bg-green-900/30 border-green-500/50 text-green-400';
      case 'bearish':
        return 'bg-red-900/30 border-red-500/50 text-red-400';
      case 'neutral':
        return 'bg-yellow-900/30 border-yellow-500/50 text-yellow-400';
      case 'fear':
        return 'bg-orange-900/30 border-orange-500/50 text-orange-400';
      case 'greed':
        return 'bg-emerald-900/30 border-emerald-500/50 text-emerald-400';
      case 'high':
        return 'bg-red-900/30 border-red-500/50 text-red-400';
      case 'moderate':
        return 'bg-yellow-900/30 border-yellow-500/50 text-yellow-400';
      case 'low':
        return 'bg-green-900/30 border-green-500/50 text-green-400';
      default:
        return 'bg-slate-800/50 border-slate-600/50 text-slate-300';
    }
  }, [type]);

  const content = (
    <>
      <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">
        {title}
      </h3>
      <div className="text-3xl font-bold mb-1">{value}</div>
      {subtitle && (
        <div className="text-sm text-slate-400">{subtitle}</div>
      )}
    </>
  );

  const cardClasses = `block rounded-xl border p-4 ${colorClasses} transition-all hover:scale-[1.02] cursor-pointer`;

  if (href) {
    // Internal link (starts with /)
    if (href.startsWith('/')) {
      return (
        <Link to={href} className={cardClasses}>
          {content}
        </Link>
      );
    }
    // External link
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className={cardClasses}
      >
        {content}
      </a>
    );
  }

  return (
    <div
      className={`rounded-xl border p-4 ${colorClasses} transition-all hover:scale-[1.02]`}
    >
      {content}
    </div>
  );
};

export default MetricCard;
