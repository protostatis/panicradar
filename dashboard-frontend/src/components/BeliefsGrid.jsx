import BeliefCard from './BeliefCard';

const BeliefsGrid = ({ beliefs, onSourceClick, showInactive = false }) => {
  // Filter to only show sources with data (unless showInactive)
  const filteredBeliefs = showInactive
    ? beliefs
    : beliefs.filter((b) => b.total_crawls > 0);

  // Group by type
  const contrarian = filteredBeliefs.filter((b) => b.type_label === 'Contrarian');
  const momentum = filteredBeliefs.filter((b) => b.type_label === 'Momentum');
  const neutral = filteredBeliefs.filter((b) => b.type_label === 'Neutral');

  const renderSection = (title, items, description) => {
    if (items.length === 0) return null;

    return (
      <div className="mb-6">
        <h3 className="text-lg font-semibold text-slate-200 mb-1">{title}</h3>
        <p className="text-sm text-slate-400 mb-3">{description}</p>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {items.map((belief) => (
            <BeliefCard
              key={belief.source}
              belief={belief}
              onClick={onSourceClick}
            />
          ))}
        </div>
      </div>
    );
  };

  return (
    <div>
      {renderSection(
        'Momentum Sources',
        momentum,
        'Sentiment aligns with future price moves (accuracy > 52%)'
      )}
      {renderSection(
        'Contrarian Sources',
        contrarian,
        'Inverted signal - crowd tends to be wrong (accuracy < 45%)'
      )}
      {renderSection(
        'Neutral Sources',
        neutral,
        'Near 50% accuracy - limited predictive value'
      )}
    </div>
  );
};

export default BeliefsGrid;
