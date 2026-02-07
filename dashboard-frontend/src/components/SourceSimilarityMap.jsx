import { useMemo, useState, useRef, useEffect } from 'react';

const formatSourceName = (source) => {
  return source
    .replace('reddit_', 'r/')
    .replace('4chan_', '/')
    .replace(/_/g, '');
};

// Interpolate between two colors based on t (0-1)
const interpolateColor = (t) => {
  // Purple (similar) -> Slate (different)
  // Similar (high): #a855f7 (purple-500)
  // Medium:         #475569 (slate-600)
  // Different (low): #1e293b (slate-800)
  if (t > 0.5) {
    // Interpolate purple -> slate-600
    const s = (t - 0.5) * 2; // 0..1
    const r = Math.round(71 + s * (168 - 71));
    const g = Math.round(85 + s * (85 - 85));
    const b = Math.round(105 + s * (247 - 105));
    return `rgb(${r}, ${g}, ${b})`;
  } else {
    // Interpolate slate-800 -> slate-600
    const s = t * 2; // 0..1
    const r = Math.round(30 + s * (71 - 30));
    const g = Math.round(41 + s * (85 - 41));
    const b = Math.round(59 + s * (105 - 59));
    return `rgb(${r}, ${g}, ${b})`;
  }
};

const HeatmapTooltip = ({ data, x, y }) => {
  if (!data) return null;

  return (
    <div
      className="fixed bg-slate-800 border border-slate-600 rounded-lg p-3 shadow-xl z-50 pointer-events-none"
      style={{ left: x + 12, top: y - 10 }}
    >
      <p className="text-slate-200 font-medium text-sm mb-1">
        {formatSourceName(data.x)} &harr; {formatSourceName(data.y)}
      </p>
      <div className="space-y-0.5 text-xs">
        <p className="flex justify-between gap-4">
          <span className="text-slate-400">Similarity</span>
          <span className={`font-medium ${
            data.similarity > 0.7 ? 'text-purple-400' :
            data.similarity > 0.4 ? 'text-slate-300' : 'text-slate-500'
          }`}>
            {(data.similarity * 100).toFixed(0)}%
          </span>
        </p>
        <p className="flex justify-between gap-4">
          <span className="text-slate-400">Distance</span>
          <span className="text-slate-300">{data.distance.toFixed(2)}</span>
        </p>
      </div>
    </div>
  );
};

const Heatmap = ({ sources, heatmap }) => {
  const containerRef = useRef(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const [tooltip, setTooltip] = useState(null);

  useEffect(() => {
    const updateWidth = () => {
      if (containerRef.current) {
        setContainerWidth(containerRef.current.offsetWidth);
      }
    };
    updateWidth();
    window.addEventListener('resize', updateWidth);
    return () => window.removeEventListener('resize', updateWidth);
  }, []);

  // Build lookup
  const heatmapLookup = useMemo(() => {
    const lookup = {};
    for (const cell of heatmap) {
      lookup[`${cell.x}|${cell.y}`] = cell;
    }
    return lookup;
  }, [heatmap]);

  const n = sources.length;
  const labelWidth = 110;
  const availableWidth = containerWidth - labelWidth - 20;
  const cellSize = n > 0 ? Math.min(36, Math.max(20, availableWidth / n)) : 30;
  const totalWidth = labelWidth + cellSize * n + 20;
  const totalHeight = 24 + cellSize * n + 10;

  if (!containerWidth) {
    return <div ref={containerRef} style={{ width: '100%', minHeight: 200 }} />;
  }

  return (
    <div ref={containerRef} style={{ width: '100%', overflowX: 'auto' }}>
      <svg width={totalWidth} height={totalHeight}>
        {/* Column labels */}
        {sources.map((source, j) => (
          <text
            key={`col-${j}`}
            x={labelWidth + j * cellSize + cellSize / 2}
            y={16}
            textAnchor="middle"
            fill="#94a3b8"
            fontSize={10}
            fontFamily="monospace"
          >
            {formatSourceName(source).slice(0, 5)}
          </text>
        ))}

        {/* Rows */}
        {sources.map((rowSource, i) => (
          <g key={`row-${i}`}>
            {/* Row label */}
            <text
              x={labelWidth - 6}
              y={24 + i * cellSize + cellSize / 2 + 4}
              textAnchor="end"
              fill="#94a3b8"
              fontSize={10}
              fontFamily="monospace"
            >
              {formatSourceName(rowSource)}
            </text>

            {/* Cells */}
            {sources.map((colSource, j) => {
              const cell = heatmapLookup[`${rowSource}|${colSource}`];
              const similarity = cell?.similarity ?? (i === j ? 1 : 0);

              return (
                <rect
                  key={`cell-${i}-${j}`}
                  x={labelWidth + j * cellSize}
                  y={24 + i * cellSize}
                  width={cellSize - 1}
                  height={cellSize - 1}
                  rx={2}
                  fill={i === j ? '#6d28d9' : interpolateColor(similarity)}
                  opacity={i === j ? 0.6 : 1}
                  onMouseEnter={(e) => {
                    if (cell && i !== j) {
                      setTooltip({ data: cell, x: e.clientX, y: e.clientY });
                    }
                  }}
                  onMouseMove={(e) => {
                    if (tooltip) {
                      setTooltip((prev) => prev ? { ...prev, x: e.clientX, y: e.clientY } : null);
                    }
                  }}
                  onMouseLeave={() => setTooltip(null)}
                  style={{ cursor: i !== j ? 'pointer' : 'default' }}
                />
              );
            })}
          </g>
        ))}
      </svg>

      {tooltip && <HeatmapTooltip {...tooltip} />}
    </div>
  );
};

const SourceSimilarityMap = ({ similarity }) => {
  const [view, setView] = useState('heatmap'); // 'heatmap' | 'neighbors' | 'features'

  if (!similarity || !similarity.sources || similarity.sources.length === 0) {
    return (
      <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6 h-40 flex items-center justify-center">
        <p className="text-slate-500">Not enough source data for similarity analysis</p>
      </div>
    );
  }

  const { sources, pairs, neighbors, features, heatmap, feature_names } = similarity;

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <div>
          <h3 className="text-lg font-semibold text-slate-200">
            Source Similarity (GP Features)
          </h3>
          <p className="text-sm text-slate-500 mt-1">
            How similarly sources behave based on 7D sentiment features
          </p>
        </div>
        <div className="flex items-center gap-1 bg-slate-700/50 rounded-lg p-1">
          {[
            { key: 'heatmap', label: 'Heatmap' },
            { key: 'neighbors', label: 'Neighbors' },
            { key: 'features', label: 'Features' },
          ].map((tab) => (
            <button
              key={tab.key}
              onClick={() => setView(tab.key)}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                view === tab.key
                  ? 'bg-purple-600 text-white'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Heatmap View */}
      {view === 'heatmap' && (
        <div>
          <Heatmap sources={sources} heatmap={heatmap} />

          {/* Color legend */}
          <div className="flex items-center justify-center gap-4 mt-4 text-xs text-slate-400">
            <div className="flex items-center gap-2">
              <div className="flex h-3 rounded overflow-hidden">
                {[0, 0.25, 0.5, 0.75, 1.0].map((t) => (
                  <div
                    key={t}
                    className="w-5 h-3"
                    style={{ backgroundColor: interpolateColor(t) }}
                  />
                ))}
              </div>
            </div>
            <span>Different</span>
            <span>&rarr;</span>
            <span>Similar</span>
          </div>

          {/* Top similar pairs */}
          <div className="mt-5">
            <h4 className="text-sm font-medium text-slate-300 mb-2">
              Most Similar Pairs
            </h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {pairs.slice(0, 6).map((pair, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between bg-slate-700/30 rounded-lg px-3 py-2"
                >
                  <div className="flex items-center gap-2 text-sm">
                    <span className="text-purple-400 font-mono text-xs font-medium w-5">
                      #{i + 1}
                    </span>
                    <span className="text-slate-200">
                      {formatSourceName(pair.source1)}
                    </span>
                    <span className="text-slate-500">&harr;</span>
                    <span className="text-slate-200">
                      {formatSourceName(pair.source2)}
                    </span>
                  </div>
                  <span className="text-slate-400 text-xs font-mono">
                    d={pair.distance.toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Neighbors View */}
      {view === 'neighbors' && (
        <div className="space-y-2">
          {neighbors.map((item) => (
            <div
              key={item.source}
              className="bg-slate-700/30 rounded-lg px-4 py-3"
            >
              <div className="flex items-start justify-between">
                <div>
                  <span className="text-slate-100 font-medium text-sm">
                    {formatSourceName(item.source)}
                  </span>
                  <div className="flex items-center gap-4 mt-1 text-xs">
                    <span className="text-slate-400">
                      Closest:{' '}
                      <span className="text-purple-400 font-medium">
                        {formatSourceName(item.nearest)}
                      </span>
                      <span className="text-slate-500 ml-1">
                        (d={item.nearest_distance?.toFixed(2)})
                      </span>
                    </span>
                    {item.second && (
                      <span className="text-slate-400">
                        2nd:{' '}
                        <span className="text-slate-300">
                          {formatSourceName(item.second)}
                        </span>
                        <span className="text-slate-500 ml-1">
                          (d={item.second_distance?.toFixed(2)})
                        </span>
                      </span>
                    )}
                  </div>
                </div>
                {/* Distance bar */}
                <div className="flex items-center gap-1 ml-4">
                  <div className="w-16 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-purple-500 rounded-full"
                      style={{
                        width: `${Math.max(5, 100 - (item.nearest_distance || 0) * 15)}%`,
                      }}
                    />
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Features View */}
      {view === 'features' && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-700">
                <th className="text-left text-slate-400 font-medium py-2 px-2 sticky left-0 bg-slate-800/90">
                  Source
                </th>
                {feature_names.map((fname) => (
                  <th key={fname} className="text-right text-slate-400 font-medium py-2 px-2 whitespace-nowrap">
                    {fname.replace('mean_', '').replace('_', ' ')}
                  </th>
                ))}
                <th className="text-right text-slate-400 font-medium py-2 px-2">posts</th>
              </tr>
            </thead>
            <tbody>
              {features.map((row) => (
                <tr key={row.source} className="border-b border-slate-700/50 hover:bg-slate-700/30">
                  <td className="py-2 px-2 text-slate-200 font-mono sticky left-0 bg-slate-800/90">
                    {formatSourceName(row.source)}
                  </td>
                  {feature_names.map((fname) => {
                    const val = row[fname];
                    const abs = Math.abs(val);
                    const color = val > 1
                      ? 'text-purple-400'
                      : val > 0.5
                        ? 'text-blue-400'
                        : val < -1
                          ? 'text-orange-400'
                          : val < -0.5
                            ? 'text-amber-400'
                            : 'text-slate-400';
                    return (
                      <td key={fname} className={`py-2 px-2 text-right font-mono ${color}`}>
                        {val > 0 ? '+' : ''}{val.toFixed(2)}
                      </td>
                    );
                  })}
                  <td className="py-2 px-2 text-right text-slate-500">
                    {row.post_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-slate-500 mt-2">
            Values are z-scored (mean=0, std=1). Colors: <span className="text-purple-400">strong positive</span>, <span className="text-orange-400">strong negative</span>.
          </p>
        </div>
      )}
    </div>
  );
};

export default SourceSimilarityMap;
