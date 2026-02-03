import { useMemo, useState, useRef, useCallback } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
} from 'recharts';
import { useChartSync } from '../context/ChartSyncContext';

const formatDate = (dateStr) => {
  // Parse as local date to avoid timezone shift
  const [year, month, day] = dateStr.split('-').map(Number);
  const date = new Date(year, month - 1, day);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    const bull = payload.find((p) => p.dataKey === 'bull')?.value || 0;
    const bear = payload.find((p) => p.dataKey === 'bear')?.value || 0;

    return (
      <div className="bg-slate-800 border border-slate-600 rounded-lg p-3 shadow-xl">
        <p className="text-slate-400 text-sm mb-2">{formatDate(label)}</p>
        <div className="space-y-1 text-sm">
          <p className="text-green-400 flex justify-between gap-4">
            <span>Bull (Euphoria)</span>
            <span className="font-medium">{bull.toFixed(2)}%</span>
          </p>
          <p className="text-red-400 flex justify-between gap-4">
            <span>Bear (Fear)</span>
            <span className="font-medium">{bear.toFixed(2)}%</span>
          </p>
        </div>
      </div>
    );
  }
  return null;
};

const BullBearChart = ({ data, sourcesData = {} }) => {
  const [selectedSource, setSelectedSource] = useState('all');
  const [containerWidth, setContainerWidth] = useState(0);
  const { activeDate, handleMouseMove, handleMouseLeave } = useChartSync();
  const resizeObserverRef = useRef(null);

  // Callback ref to set up ResizeObserver when element mounts
  const containerRef = useCallback((node) => {
    if (resizeObserverRef.current) {
      resizeObserverRef.current.disconnect();
    }

    if (node) {
      resizeObserverRef.current = new ResizeObserver((entries) => {
        for (const entry of entries) {
          setContainerWidth(entry.contentRect.width);
        }
      });
      resizeObserverRef.current.observe(node);
    }
  }, []);

  // Get available sources from sourcesData
  const availableSources = useMemo(() => {
    return Object.keys(sourcesData).sort();
  }, [sourcesData]);

  // Process data for grouped bar chart (both bars going up)
  const chartData = useMemo(() => {
    let sourceData;

    if (selectedSource === 'all' || !sourcesData[selectedSource]) {
      sourceData = data;
    } else {
      sourceData = sourcesData[selectedSource];
    }

    if (!sourceData) return [];

    return sourceData.map((d) => ({
      ...d,
      // Both values positive for side-by-side comparison
      bull: (d.euphoria_index || 0) * 100,
      bear: (d.fear_index || 0) * 100,
    }));
  }, [data, sourcesData, selectedSource]);

  // Calculate stats
  const stats = useMemo(() => {
    if (!chartData || chartData.length === 0) return null;

    const bulls = chartData.map((d) => d.bull);
    const bears = chartData.map((d) => d.bear);

    const avgBull = bulls.reduce((a, b) => a + b, 0) / bulls.length;
    const avgBear = bears.reduce((a, b) => a + b, 0) / bears.length;

    const maxBull = Math.max(...bulls);
    const maxBear = Math.max(...bears);

    const currentBull = bulls[bulls.length - 1] || 0;
    const currentBear = bears[bears.length - 1] || 0;
    const ratio = currentBear > 0 ? currentBull / currentBear : currentBull > 0 ? Infinity : 1;

    // Determine overall sentiment
    let sentiment = 'Balanced';
    if (ratio > 1.5) sentiment = 'Bullish';
    else if (ratio < 0.67) sentiment = 'Bearish';

    return {
      avgBull,
      avgBear,
      maxBull,
      maxBear,
      currentBull,
      currentBear,
      ratio,
      sentiment,
      totalDays: chartData.length,
    };
  }, [chartData]);

  if (!data || data.length === 0) {
    return (
      <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6 h-64 flex items-center justify-center">
        <p className="text-slate-500">No bull/bear data available</p>
      </div>
    );
  }

  // Find max value for Y-axis domain
  const maxVal = Math.max(
    ...chartData.map((d) => Math.max(d.bull, d.bear))
  );
  const domain = Math.ceil(maxVal * 1.2 * 10) / 10 || 1;

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6">
      <div className="flex flex-col lg:flex-row gap-6">
        {/* Chart */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
            <h3 className="text-lg font-semibold text-slate-200">
              Bull vs Bear (30 days)
            </h3>
            <div className="flex items-center gap-3">
              {/* Source Selector */}
              {availableSources.length > 0 && (
                <select
                  value={selectedSource}
                  onChange={(e) => setSelectedSource(e.target.value)}
                  className="bg-slate-700 border border-slate-600 text-slate-200 text-sm rounded-lg px-3 py-1.5 focus:ring-blue-500 focus:border-blue-500"
                >
                  <option value="all">All Sources</option>
                  {availableSources.map((source) => (
                    <option key={source} value={source}>
                      {source}
                    </option>
                  ))}
                </select>
              )}
              {stats && (
                <span
                  className={`px-3 py-1 rounded-full text-sm font-medium ${
                    stats.sentiment === 'Bullish'
                      ? 'bg-green-900/50 text-green-400'
                      : stats.sentiment === 'Bearish'
                      ? 'bg-red-900/50 text-red-400'
                      : 'bg-slate-700 text-slate-300'
                  }`}
                >
                  {stats.sentiment}
                </span>
              )}
            </div>
          </div>

          <div ref={containerRef} style={{ width: '100%', height: 280, minWidth: 0 }}>
            {containerWidth > 0 && (
              <BarChart
                data={chartData}
                width={containerWidth}
                height={280}
                margin={{ top: 20, right: 20, left: 0, bottom: 0 }}
                onMouseMove={handleMouseMove}
                onMouseLeave={handleMouseLeave}
              >
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
              {activeDate && chartData.some((d) => d.date === activeDate) && (
                <ReferenceLine x={activeDate} stroke="#8b5cf6" strokeWidth={1} strokeDasharray="3 3" />
              )}
              <XAxis
                dataKey="date"
                tickFormatter={formatDate}
                stroke="#64748b"
                tick={{ fill: '#64748b', fontSize: 10 }}
                tickLine={false}
                axisLine={{ stroke: '#475569' }}
              />
              <YAxis
                domain={[0, domain]}
                stroke="#64748b"
                tick={{ fill: '#64748b', fontSize: 10 }}
                tickFormatter={(v) => `${v.toFixed(1)}%`}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip content={<CustomTooltip />} />
              <Legend
                wrapperStyle={{ paddingTop: '10px' }}
                formatter={(value) => (
                  <span className="text-slate-400 text-sm">
                    {value === 'bull' ? 'Bull (Euphoria)' : 'Bear (Fear)'}
                  </span>
                )}
              />

              {/* Bull bars (green) */}
              <Bar
                dataKey="bull"
                fill="#22c55e"
                radius={[4, 4, 0, 0]}
                maxBarSize={16}
              />

              {/* Bear bars (red) */}
              <Bar
                dataKey="bear"
                fill="#ef4444"
                radius={[4, 4, 0, 0]}
                maxBarSize={16}
              />
            </BarChart>
            )}
          </div>
        </div>

        {/* Stats Panel */}
        {stats && (
          <div className="lg:w-52 space-y-3">
            <h4 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">
              Current Reading
            </h4>

            {/* Bull/Bear Ratio */}
            <div className="bg-slate-700/50 rounded-lg p-4">
              <div className="text-xs text-slate-500 mb-1">Bull/Bear Ratio</div>
              <div className="flex items-baseline gap-2">
                <span
                  className={`text-3xl font-bold ${
                    stats.ratio > 1.2
                      ? 'text-green-400'
                      : stats.ratio < 0.8
                      ? 'text-red-400'
                      : 'text-slate-200'
                  }`}
                >
                  {stats.ratio === Infinity ? '∞' : stats.ratio.toFixed(2)}
                </span>
              </div>
            </div>

            {/* Today's Values */}
            <div className="bg-slate-700/50 rounded-lg p-4">
              <div className="text-xs text-slate-500 mb-3">Today</div>
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <span className="text-slate-400 text-sm">Bull</span>
                  <span className="text-green-400 font-medium">
                    {stats.currentBull.toFixed(2)}%
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-400 text-sm">Bear</span>
                  <span className="text-red-400 font-medium">
                    {stats.currentBear.toFixed(2)}%
                  </span>
                </div>
              </div>
            </div>

            {/* 30d Stats */}
            <div className="bg-slate-700/50 rounded-lg p-4">
              <div className="text-xs text-slate-500 mb-3">30-Day Stats</div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-500">Avg Bull</span>
                  <span className="text-slate-300">{stats.avgBull.toFixed(2)}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Avg Bear</span>
                  <span className="text-slate-300">{stats.avgBear.toFixed(2)}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Max Bull</span>
                  <span className="text-green-400">{stats.maxBull.toFixed(2)}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Max Bear</span>
                  <span className="text-red-400">{stats.maxBear.toFixed(2)}%</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default BullBearChart;
