const SourceTable = ({ sources, lastUpdated }) => {
  const getTypeColor = (type) => {
    switch (type) {
      case 'Momentum':
        return 'text-green-400 bg-green-900/30';
      case 'Contrarian':
        return 'text-orange-400 bg-orange-900/30';
      default:
        return 'text-slate-400 bg-slate-700/50';
    }
  };

  if (!sources || sources.length === 0) {
    return (
      <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-200 mb-4">
          Source Rankings
        </h3>
        <p className="text-slate-500">No source data available</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold text-slate-200">Source Rankings</h3>
        {lastUpdated && (
          <span className="text-xs text-slate-500">
            Updated: {new Date(lastUpdated).toLocaleDateString()}
          </span>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700">
              <th className="text-left py-2 px-3 text-slate-400 font-medium">
                Source
              </th>
              <th className="text-right py-2 px-3 text-slate-400 font-medium">
                Weight
              </th>
              <th className="text-right py-2 px-3 text-slate-400 font-medium">
                Accuracy
              </th>
              <th className="text-center py-2 px-3 text-slate-400 font-medium">
                Type
              </th>
              <th className="text-right py-2 px-3 text-slate-400 font-medium">
                Samples
              </th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source, index) => (
              <tr
                key={source.source}
                className={`border-b border-slate-700/50 ${
                  index % 2 === 0 ? 'bg-slate-800/30' : ''
                }`}
              >
                <td className="py-2 px-3 text-slate-300">{source.source}</td>
                <td className="py-2 px-3 text-right text-slate-300">
                  {source.weight.toFixed(4)}
                </td>
                <td className="py-2 px-3 text-right text-slate-300">
                  {source.accuracy
                    ? `${(source.accuracy * 100).toFixed(1)}%`
                    : 'N/A'}
                </td>
                <td className="py-2 px-3 text-center">
                  <span
                    className={`px-2 py-1 rounded text-xs font-medium ${getTypeColor(
                      source.type_label
                    )}`}
                  >
                    {source.type_label}
                  </span>
                </td>
                <td className="py-2 px-3 text-right text-slate-400">
                  {source.sample_size.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default SourceTable;
