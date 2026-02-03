import { useMemo, useState, useRef, useEffect } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
  ReferenceLine,
} from 'recharts';

const formatSourceName = (source) => {
  return source
    .replace('reddit_', 'r/')
    .replace('4chan_', '/')
    .replace(/_/g, '');
};

const CustomTooltip = ({ active, payload }) => {
  if (active && payload && payload.length) {
    const data = payload[0]?.payload;
    if (!data) return null;

    return (
      <div className="bg-slate-800 border border-slate-600 rounded-lg p-3 shadow-xl">
        <p className="text-slate-200 font-medium mb-2">{formatSourceName(data.source)}</p>
        <div className="space-y-1 text-sm">
          <p className="flex justify-between gap-4">
            <span className="text-slate-400">Accuracy</span>
            <span className={`font-medium ${
              data.accuracy > 0.55 ? 'text-green-400' :
              data.accuracy < 0.45 ? 'text-orange-400' : 'text-slate-300'
            }`}>
              {data.accuracy !== null ? `${(data.accuracy * 100).toFixed(1)}%` : 'N/A'}
            </span>
          </p>
          <p className="flex justify-between gap-4">
            <span className="text-slate-400">Type</span>
            <span className={`font-medium ${
              data.type_label === 'Momentum' ? 'text-green-400' :
              data.type_label === 'Contrarian' ? 'text-orange-400' : 'text-slate-400'
            }`}>
              {data.type_label}
            </span>
          </p>
          <p className="flex justify-between gap-4">
            <span className="text-slate-400">Samples</span>
            <span className="text-slate-300">{data.total_crawls?.toLocaleString()}</span>
          </p>
          <p className="flex justify-between gap-4">
            <span className="text-slate-400">Belief (α/β)</span>
            <span className="text-slate-300">{data.alpha?.toFixed(0)}/{data.beta?.toFixed(0)}</span>
          </p>
          {data.correlation !== null && (
            <p className="flex justify-between gap-4">
              <span className="text-slate-400">Correlation</span>
              <span className={data.correlation > 0 ? 'text-green-400' : 'text-red-400'}>
                {data.correlation > 0 ? '+' : ''}{data.correlation?.toFixed(3)}
              </span>
            </p>
          )}
        </div>
      </div>
    );
  }
  return null;
};

const BeliefsChart = ({ beliefs, onSourceClick, showInactive = false }) => {
  const [sortBy, setSortBy] = useState('accuracy'); // 'accuracy', 'samples', 'name'
  const [filterType, setFilterType] = useState('all'); // 'all', 'Momentum', 'Contrarian', 'Neutral'
  const containerRef = useRef(null);
  const [containerWidth, setContainerWidth] = useState(0);

  // Track container width
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

  // Process and sort data
  const chartData = useMemo(() => {
    let filtered = showInactive
      ? beliefs
      : beliefs.filter((b) => b.total_crawls > 0);

    // Filter by type
    if (filterType !== 'all') {
      filtered = filtered.filter((b) => b.type_label === filterType);
    }

    // Only include sources with accuracy data for the chart
    filtered = filtered.filter((b) => b.accuracy !== null);

    // Sort
    const sorted = [...filtered].sort((a, b) => {
      switch (sortBy) {
        case 'accuracy':
          return (b.accuracy || 0) - (a.accuracy || 0);
        case 'samples':
          return b.total_crawls - a.total_crawls;
        case 'name':
          return a.source.localeCompare(b.source);
        default:
          return 0;
      }
    });

    return sorted.map((b) => ({
      ...b,
      displayName: formatSourceName(b.source),
      accuracyPercent: (b.accuracy || 0) * 100,
    }));
  }, [beliefs, showInactive, sortBy, filterType]);

  // Get bar color based on type
  const getBarColor = (type) => {
    switch (type) {
      case 'Momentum':
        return '#22c55e'; // green
      case 'Contrarian':
        return '#f97316'; // orange
      default:
        return '#64748b'; // slate
    }
  };

  // Stats
  const stats = useMemo(() => {
    const momentum = beliefs.filter((b) => b.type_label === 'Momentum' && b.total_crawls > 0);
    const contrarian = beliefs.filter((b) => b.type_label === 'Contrarian' && b.total_crawls > 0);
    const neutral = beliefs.filter((b) => b.type_label === 'Neutral' && b.total_crawls > 0);

    return {
      momentum: momentum.length,
      contrarian: contrarian.length,
      neutral: neutral.length,
      avgMomentum: momentum.length > 0
        ? momentum.reduce((a, b) => a + (b.accuracy || 0), 0) / momentum.length
        : 0,
      avgContrarian: contrarian.length > 0
        ? contrarian.reduce((a, b) => a + (b.accuracy || 0), 0) / contrarian.length
        : 0,
    };
  }, [beliefs]);

  if (!beliefs || beliefs.length === 0) {
    return (
      <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6 h-64 flex items-center justify-center">
        <p className="text-slate-500">No beliefs data available</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6">
      <div className="flex flex-col lg:flex-row gap-6">
        {/* Chart */}
        <div className="flex-1">
          <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
            <h3 className="text-lg font-semibold text-slate-200">
              Source Accuracy
            </h3>
            <div className="flex items-center gap-3">
              {/* Filter by Type */}
              <select
                value={filterType}
                onChange={(e) => setFilterType(e.target.value)}
                className="bg-slate-700 border border-slate-600 text-slate-200 text-sm rounded-lg px-3 py-1.5 focus:ring-blue-500 focus:border-blue-500"
              >
                <option value="all">All Types</option>
                <option value="Momentum">Momentum</option>
                <option value="Contrarian">Contrarian</option>
                <option value="Neutral">Neutral</option>
              </select>

              {/* Sort By */}
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="bg-slate-700 border border-slate-600 text-slate-200 text-sm rounded-lg px-3 py-1.5 focus:ring-blue-500 focus:border-blue-500"
              >
                <option value="accuracy">Sort by Accuracy</option>
                <option value="samples">Sort by Samples</option>
                <option value="name">Sort by Name</option>
              </select>
            </div>
          </div>

          <div ref={containerRef} style={{ width: '100%', minWidth: 0 }}>
            {containerWidth > 0 && (
              <BarChart
                data={chartData}
                layout="vertical"
                width={containerWidth}
                height={Math.max(300, chartData.length * 28)}
                margin={{ top: 5, right: 30, left: 100, bottom: 5 }}
              >
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" horizontal={false} />
              <XAxis
                type="number"
                domain={[0, 100]}
                stroke="#64748b"
                tick={{ fill: '#64748b', fontSize: 11 }}
                tickFormatter={(v) => `${v}%`}
              />
              <YAxis
                type="category"
                dataKey="displayName"
                stroke="#64748b"
                tick={{ fill: '#94a3b8', fontSize: 11 }}
                width={90}
              />
              <Tooltip content={<CustomTooltip />} />

              {/* 50% reference line */}
              <ReferenceLine x={50} stroke="#64748b" strokeDasharray="3 3" />

              <Bar
                dataKey="accuracyPercent"
                radius={[0, 4, 4, 0]}
                onClick={(data) => onSourceClick?.(data.source)}
                cursor="pointer"
              >
                {chartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={getBarColor(entry.type_label)} />
                ))}
              </Bar>
              </BarChart>
            )}
          </div>

          {/* Legend */}
          <div className="flex items-center justify-center gap-6 mt-4 text-sm">
            <span className="flex items-center gap-2">
              <span className="w-4 h-3 bg-green-500 rounded"></span>
              <span className="text-slate-400">Momentum ({stats.momentum})</span>
            </span>
            <span className="flex items-center gap-2">
              <span className="w-4 h-3 bg-orange-500 rounded"></span>
              <span className="text-slate-400">Contrarian ({stats.contrarian})</span>
            </span>
            <span className="flex items-center gap-2">
              <span className="w-4 h-3 bg-slate-500 rounded"></span>
              <span className="text-slate-400">Neutral ({stats.neutral})</span>
            </span>
          </div>
        </div>

        {/* Stats Panel */}
        <div className="lg:w-52 space-y-3">
          <h4 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">
            Summary
          </h4>

          <div className="bg-slate-700/50 rounded-lg p-4">
            <div className="text-xs text-slate-500 mb-1">Sources Shown</div>
            <div className="text-2xl font-bold text-slate-200">
              {chartData.length}
            </div>
          </div>

          <div className="bg-slate-700/50 rounded-lg p-4">
            <div className="text-xs text-slate-500 mb-3">Avg Accuracy</div>
            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-slate-400 text-sm">Momentum</span>
                <span className="text-green-400 font-medium">
                  {(stats.avgMomentum * 100).toFixed(1)}%
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-400 text-sm">Contrarian</span>
                <span className="text-orange-400 font-medium">
                  {(stats.avgContrarian * 100).toFixed(1)}%
                </span>
              </div>
            </div>
          </div>

          <div className="bg-slate-700/50 rounded-lg p-4">
            <div className="text-xs text-slate-500 mb-2">Reference</div>
            <div className="text-sm text-slate-400">
              <p className="mb-1">50% line = random</p>
              <p className="text-green-400">&gt;52% = Momentum</p>
              <p className="text-orange-400">&lt;45% = Contrarian</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default BeliefsChart;
