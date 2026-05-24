import { useMemo } from 'react';
import { Link } from 'react-router-dom';

const MetricCard = ({ title, value, subtitle, type = 'default', href }) => {
  const colorClasses = useMemo(() => {
    switch (type) {
      case 'bullish':
        return 'border-green-400/50 text-green-300';
      case 'bearish':
        return 'border-red-400/50 text-red-300';
      case 'neutral':
        return 'border-yellow-400/50 text-yellow-300';
      case 'fear':
        return 'border-orange-400/50 text-orange-300';
      case 'greed':
        return 'border-emerald-400/50 text-emerald-300';
      case 'high':
        return 'border-red-400/50 text-red-300';
      case 'moderate':
        return 'border-yellow-400/50 text-yellow-300';
      case 'low':
        return 'border-green-400/50 text-green-300';
      default:
        return 'border-slate-600/50 text-slate-300';
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

  const cardClasses = `radar-card block border p-4 ${colorClasses} transition-all hover:-translate-y-0.5 cursor-pointer`;

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
      className={`radar-card border p-4 ${colorClasses} transition-all hover:-translate-y-0.5`}
    >
      {content}
    </div>
  );
};

export default MetricCard;
