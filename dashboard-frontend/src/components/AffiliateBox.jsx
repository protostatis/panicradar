const AffiliateBox = ({ context, recommendations }) => {
  const getContextTitle = () => {
    switch (context) {
      case 'high_volatility':
        return '💡 High Volatility? Consider:';
      default:
        return '💡 Useful Tools:';
    }
  };

  const getCategoryIcon = (category) => {
    switch (category) {
      case 'exchange':
        return '📈';
      case 'wallet':
        return '🔐';
      case 'tools':
        return '📊';
      case 'tax':
        return '📋';
      default:
        return '🔗';
    }
  };

  if (!recommendations || recommendations.length === 0) {
    return null;
  }

  return (
    <div className="radar-panel p-6">
      <h3 className="text-lg font-semibold text-slate-200 mb-4">
        {getContextTitle()}
      </h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {recommendations.map((affiliate, index) => (
          <a
            key={index}
            href={affiliate.url}
            target="_blank"
            rel="noopener noreferrer"
            className="radar-card flex items-start gap-3 p-3 transition-colors hover:border-cyan-400/40"
          >
            <span className="text-xl">{getCategoryIcon(affiliate.category)}</span>
            <div>
              <div className="text-slate-200 font-medium">{affiliate.name}</div>
              <div className="text-slate-400 text-sm">{affiliate.description}</div>
            </div>
          </a>
        ))}
      </div>
      <p className="text-xs text-slate-500 mt-4">
        Partner links. We may earn a commission at no extra cost to you.
      </p>
    </div>
  );
};

export default AffiliateBox;
