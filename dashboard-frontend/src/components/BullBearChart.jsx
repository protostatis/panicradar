import { useMemo, useState, useEffect, useRef, useCallback } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  Cell,
} from 'recharts';
import { fetchDailySentiment } from '../api/client';
import { useChartSync } from '../context/ChartSyncContext';

// Gradient definitions for the bars
const GradientDefs = () => (
  <defs>
    <linearGradient id="bullGradient" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stopColor="#22c55e" stopOpacity={0.8} />
      <stop offset="100%" stopColor="#4ade80" stopOpacity={1} />
    </linearGradient>
    <linearGradient id="bearGradient" x1="1" y1="0" x2="0" y2="0">
      <stop offset="0%" stopColor="#ef4444" stopOpacity={0.8} />
      <stop offset="100%" stopColor="#f87171" stopOpacity={1} />
    </linearGradient>
    <filter id="glow">
      <feGaussianBlur stdDeviation="2" result="coloredBlur"/>
      <feMerge>
        <feMergeNode in="coloredBlur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
  </defs>
);

const formatDate = (dateStr) => {
  const [year, month, day] = dateStr.split('-').map(Number);
  const date = new Date(year, month - 1, day);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    const data = payload[0]?.payload;
    if (!data) return null;

    return (
      <div className="bg-slate-800 border border-slate-600 rounded-lg p-3 shadow-xl">
        <p className="text-slate-400 text-sm mb-2">{formatDate(label)}</p>
        <div className="space-y-1 text-sm">
          <p className="text-green-400 flex justify-between gap-4">
            <span>Bullish</span>
            <span className="font-medium">{data.bull_count} posts</span>
          </p>
          <p className="text-red-400 flex justify-between gap-4">
            <span>Bearish</span>
            <span className="font-medium">{data.bear_count} posts</span>
          </p>
          <p className="text-slate-500 flex justify-between gap-4">
            <span>Total</span>
            <span className="font-medium">{data.total_count} posts</span>
          </p>
        </div>
      </div>
    );
  }
  return null;
};

const BullBearChart = () => {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const resizeObserverRef = useRef(null);
  const { activeDate, handleMouseMove, handleMouseLeave } = useChartSync();

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

  useEffect(() => {
    const loadData = async () => {
      try {
        setLoading(true);
        const result = await fetchDailySentiment(30);
        setData(result.data || []);
        setError(null);
      } catch (err) {
        console.error('Failed to load sentiment data:', err);
        setError('Failed to load data');
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, []);

  // Transform data for diverging bar chart
  // Bull goes positive (right), Bear goes negative (left)
  // Reverse so latest date is on top
  const chartData = useMemo(() => {
    return [...data].reverse().map((d) => ({
      ...d,
      bull: d.bull_count,
      bear: -d.bear_count, // Negative for left side
    }));
  }, [data]);

  // Calculate stats
  const stats = useMemo(() => {
    if (!data || data.length === 0) return null;

    const totalBull = data.reduce((sum, d) => sum + d.bull_count, 0);
    const totalBear = data.reduce((sum, d) => sum + d.bear_count, 0);
    const totalPosts = data.reduce((sum, d) => sum + d.total_count, 0);

    // Rolling 24h: use last 2 days to approximate (in case today is partial)
    const recentData = data.slice(-2);
    const recent24hBull = recentData.reduce((sum, d) => sum + d.bull_count, 0);
    const recent24hBear = recentData.reduce((sum, d) => sum + d.bear_count, 0);
    const recent24hTotal = recentData.reduce((sum, d) => sum + d.total_count, 0);

    const ratio = totalBear > 0 ? totalBull / totalBear : totalBull > 0 ? Infinity : 1;
    const recent24hRatio = recent24hBear > 0 ? recent24hBull / recent24hBear : recent24hBull > 0 ? Infinity : 1;

    let sentiment = 'Balanced';
    if (recent24hRatio > 1.3) sentiment = 'Bullish';
    else if (recent24hRatio < 0.77) sentiment = 'Bearish';

    return {
      totalBull,
      totalBear,
      totalPosts,
      recent24hBull,
      recent24hBear,
      recent24hTotal,
      recent24hRatio,
      ratio,
      sentiment,
      days: data.length,
    };
  }, [data]);

  if (loading) {
    return (
      <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6 h-80 flex items-center justify-center">
        <div className="animate-pulse text-slate-500">Loading sentiment data...</div>
      </div>
    );
  }

  if (error || !data || data.length === 0) {
    return (
      <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6 h-80 flex items-center justify-center">
        <p className="text-slate-500">{error || 'No sentiment data available'}</p>
      </div>
    );
  }

  // Find max value for symmetric Y-axis domain
  const maxVal = Math.max(
    ...chartData.map((d) => Math.max(Math.abs(d.bull), Math.abs(d.bear)))
  );
  const domain = [-Math.ceil(maxVal * 1.1), Math.ceil(maxVal * 1.1)];

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6">
      <div className="flex flex-col lg:flex-row gap-6">
        {/* Chart */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
            <h3 className="text-lg font-semibold text-slate-200">
              Bull vs Bear (30 days)
            </h3>
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

          <div ref={containerRef} style={{ width: '100%', height: 400, minWidth: 0 }}>
            {containerWidth > 0 && (
              <BarChart
                data={chartData}
                width={containerWidth}
                height={400}
                layout="vertical"
                margin={{ top: 10, right: 30, left: 60, bottom: 10 }}
                barGap={2}
                onMouseMove={handleMouseMove}
                onMouseLeave={handleMouseLeave}
              >
                <GradientDefs />
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
                <XAxis
                  type="number"
                  domain={domain}
                  stroke="#475569"
                  tick={{ fill: '#94a3b8', fontSize: 10 }}
                  tickLine={false}
                  axisLine={{ stroke: '#334155' }}
                  tickFormatter={(v) => Math.abs(v)}
                />
                <YAxis
                  type="category"
                  dataKey="date"
                  stroke="#475569"
                  tick={{ fill: '#94a3b8', fontSize: 9 }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={formatDate}
                  width={50}
                />
                <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(148, 163, 184, 0.15)' }} />
                <ReferenceLine x={0} stroke="#64748b" strokeWidth={1} strokeDasharray="3 3" />
                {/* Cross-chart highlight */}
                {activeDate && chartData.some((d) => d.date === activeDate) && (
                  <ReferenceLine y={activeDate} stroke="#8b5cf6" strokeWidth={2} strokeDasharray="3 3" />
                )}

                {/* Bear bars with gradient - rounds on far left end */}
                <Bar dataKey="bear" barSize={10} radius={[0, 4, 4, 0]}>
                  {chartData.map((entry, index) => (
                    <Cell key={`bear-${index}`} fill="url(#bearGradient)" />
                  ))}
                </Bar>

                {/* Bull bars with gradient - rounds on far right end */}
                <Bar dataKey="bull" barSize={10} radius={[0, 4, 4, 0]}>
                  {chartData.map((entry, index) => (
                    <Cell key={`bull-${index}`} fill="url(#bullGradient)" />
                  ))}
                </Bar>
              </BarChart>
            )}
          </div>

          {/* Legend */}
          <div className="flex justify-center gap-8 mt-3 text-sm">
            <div className="flex items-center gap-2">
              <div className="w-4 h-2 rounded-full bg-gradient-to-r from-red-500 to-red-400"></div>
              <span className="text-slate-400">Bear</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-2 rounded-full bg-gradient-to-r from-green-500 to-green-400"></div>
              <span className="text-slate-400">Bull</span>
            </div>
          </div>
        </div>

        {/* Stats Panel */}
        {stats && (
          <div className="lg:w-48 space-y-3">
            <h4 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">
              Summary
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

            {/* Rolling 24h Counts */}
            <div className="bg-slate-700/50 rounded-lg p-4">
              <div className="text-xs text-slate-500 mb-3">Last 24h</div>
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <span className="text-slate-400 text-sm">Bull</span>
                  <span className="text-green-400 font-medium">
                    {stats.recent24hBull}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-400 text-sm">Bear</span>
                  <span className="text-red-400 font-medium">
                    {stats.recent24hBear}
                  </span>
                </div>
                <div className="flex justify-between items-center pt-1 border-t border-slate-600">
                  <span className="text-slate-500 text-sm">Ratio</span>
                  <span className={`font-medium ${
                    stats.recent24hRatio > 1.2 ? 'text-green-400' :
                    stats.recent24hRatio < 0.8 ? 'text-red-400' : 'text-slate-300'
                  }`}>
                    {stats.recent24hRatio === Infinity ? '∞' : stats.recent24hRatio.toFixed(2)}
                  </span>
                </div>
              </div>
            </div>

            {/* 30d Totals */}
            <div className="bg-slate-700/50 rounded-lg p-4">
              <div className="text-xs text-slate-500 mb-3">30-Day Totals</div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-500">Bull Posts</span>
                  <span className="text-green-400">{stats.totalBull}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Bear Posts</span>
                  <span className="text-red-400">{stats.totalBear}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Total</span>
                  <span className="text-slate-300">{stats.totalPosts}</span>
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
