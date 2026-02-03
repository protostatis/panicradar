import { useState, useMemo } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';

const formatDate = (dateStr) => {
  // Parse as local date to avoid timezone shift
  const [year, month, day] = dateStr.split('-').map(Number);
  const date = new Date(year, month - 1, day);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};

const formatSourceName = (source) => {
  if (source === 'aggregate') return 'All Sources (Avg)';
  return source
    .replace('reddit_', 'r/')
    .replace('4chan_', '/')
    .replace(/_/g, '');
};

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    const sentiment = payload[0]?.value;
    const sampleSize = payload[0]?.payload?.sample_size;

    let sentimentLabel = 'Neutral';
    let labelColor = 'text-slate-300';
    if (sentiment > 0.3) {
      sentimentLabel = 'Bullish';
      labelColor = 'text-green-400';
    } else if (sentiment < -0.3) {
      sentimentLabel = 'Bearish';
      labelColor = 'text-red-400';
    }

    return (
      <div className="bg-slate-800 border border-slate-600 rounded-lg p-3 shadow-xl">
        <p className="text-slate-400 text-sm mb-2">{formatDate(label)}</p>
        <p className={`text-sm font-medium ${labelColor}`}>
          {sentimentLabel}: {sentiment?.toFixed(3)}
        </p>
        {sampleSize && (
          <p className="text-slate-500 text-xs mt-1">
            {sampleSize} samples
          </p>
        )}
      </div>
    );
  }
  return null;
};

const SentimentChart = ({ data, sourcesData }) => {
  const [selectedSource, setSelectedSource] = useState('aggregate');

  // Get available sources sorted by data points
  const availableSources = useMemo(() => {
    if (!sourcesData) return [];
    return Object.entries(sourcesData)
      .map(([source, data]) => ({ source, count: data.length }))
      .filter((s) => s.count >= 5)
      .sort((a, b) => b.count - a.count)
      .slice(0, 15)
      .map((s) => s.source);
  }, [sourcesData]);

  // Get chart data based on selection
  const chartData = useMemo(() => {
    if (selectedSource === 'aggregate') {
      return data || [];
    }
    return sourcesData?.[selectedSource] || [];
  }, [selectedSource, data, sourcesData]);

  // Calculate insights and Y-axis domain
  const { insights, yDomain } = useMemo(() => {
    if (!chartData || chartData.length === 0) {
      return { insights: null, yDomain: [-1, 1] };
    }

    const scores = chartData.map((d) => d.sentiment_score).filter((s) => s != null);
    if (scores.length === 0) {
      return { insights: null, yDomain: [-1, 1] };
    }

    const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
    const max = Math.max(...scores);
    const min = Math.min(...scores);
    const current = scores[scores.length - 1];
    const previous = scores.length > 1 ? scores[scores.length - 2] : current;
    const trend = current - previous;

    // Count extreme days
    const extremeBullish = scores.filter((s) => s > 0.3).length;
    const extremeBearish = scores.filter((s) => s < -0.3).length;

    // Calculate volatility (std dev)
    const variance = scores.reduce((sum, s) => sum + Math.pow(s - avg, 2), 0) / scores.length;
    const volatility = Math.sqrt(variance);

    // Calculate dynamic Y domain with padding
    const range = max - min;
    const padding = Math.max(0.1, range * 0.2);
    const yMin = Math.max(-1, min - padding);
    const yMax = Math.min(1, max + padding);

    return {
      insights: {
        avg,
        max,
        min,
        current,
        trend,
        extremeBullish,
        extremeBearish,
        totalDays: scores.length,
        volatility,
        range,
      },
      yDomain: [Math.floor(yMin * 10) / 10, Math.ceil(yMax * 10) / 10],
    };
  }, [chartData]);

  if (!data || data.length === 0) {
    return (
      <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6 h-80 flex items-center justify-center">
        <p className="text-slate-500">No data available</p>
      </div>
    );
  }

  // Determine line color based on current sentiment
  const lineColor = insights?.current > 0 ? '#22c55e' : insights?.current < 0 ? '#ef4444' : '#8b5cf6';

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6">
      <div className="flex flex-col lg:flex-row gap-6">
        {/* Chart */}
        <div className="flex-1">
          <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
            <h3 className="text-lg font-semibold text-slate-200">
              Sentiment Score
            </h3>
            {/* Source Selector */}
            {availableSources.length > 0 && (
              <select
                value={selectedSource}
                onChange={(e) => setSelectedSource(e.target.value)}
                className="bg-slate-700 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-purple-500"
              >
                <option value="aggregate">All Sources (Avg)</option>
                <optgroup label="Individual Sources">
                  {availableSources.map((source) => (
                    <option key={source} value={source}>
                      {formatSourceName(source)}
                    </option>
                  ))}
                </optgroup>
              </select>
            )}
          </div>

          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={chartData} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />

              <XAxis
                dataKey="date"
                tickFormatter={formatDate}
                stroke="#64748b"
                tick={{ fill: '#64748b', fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: '#334155' }}
              />
              <YAxis
                domain={yDomain}
                stroke="#64748b"
                tick={{ fill: '#64748b', fontSize: 11 }}
                tickFormatter={(v) => v.toFixed(1)}
                tickLine={false}
                axisLine={{ stroke: '#334155' }}
              />
              <Tooltip content={<CustomTooltip />} />

              {/* Neutral line at zero */}
              <ReferenceLine y={0} stroke="#475569" strokeWidth={1} strokeDasharray="4 4" />

              {/* Single sentiment line */}
              <Line
                type="monotone"
                dataKey="sentiment_score"
                stroke={lineColor}
                strokeWidth={2.5}
                dot={false}
                activeDot={{ r: 5, fill: lineColor }}
              />
            </LineChart>
          </ResponsiveContainer>

          {/* Legend */}
          <div className="flex items-center justify-center gap-6 mt-2 text-xs text-slate-500">
            <span>Bullish (&gt;0) = Green</span>
            <span>Bearish (&lt;0) = Red</span>
            <span>Dashed line = Neutral (0)</span>
          </div>
        </div>

        {/* Insights Panel */}
        {insights && (
          <div className="lg:w-56 space-y-3">
            <h4 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">
              {formatSourceName(selectedSource)}
            </h4>

            {/* Current Reading */}
            <div className="bg-slate-700/50 rounded-lg p-3">
              <div className="text-xs text-slate-500 mb-1">Current</div>
              <div className="flex items-center gap-2">
                <span
                  className={`text-2xl font-bold ${
                    insights.current > 0.1
                      ? 'text-green-400'
                      : insights.current < -0.1
                      ? 'text-red-400'
                      : 'text-slate-200'
                  }`}
                >
                  {insights.current > 0 ? '+' : ''}{insights.current.toFixed(2)}
                </span>
                <span
                  className={`text-sm ${
                    insights.trend > 0 ? 'text-green-400' : 'text-red-400'
                  }`}
                >
                  {insights.trend > 0 ? '↑' : '↓'} {Math.abs(insights.trend).toFixed(2)}
                </span>
              </div>
            </div>

            {/* Range */}
            <div className="bg-slate-700/50 rounded-lg p-3">
              <div className="text-xs text-slate-500 mb-2">30-Day Range</div>
              <div className="flex justify-between text-sm">
                <span className="text-red-400">{insights.min.toFixed(2)}</span>
                <span className="text-slate-400">avg: {insights.avg.toFixed(2)}</span>
                <span className="text-green-400">{insights.max > 0 ? '+' : ''}{insights.max.toFixed(2)}</span>
              </div>
              {/* Visual range bar */}
              <div className="mt-2 h-2 bg-gradient-to-r from-red-500 via-slate-500 to-green-500 rounded-full relative">
                <div
                  className="absolute w-2 h-2 bg-white rounded-full border-2 border-slate-800"
                  style={{
                    left: `${Math.max(0, Math.min(100, ((insights.current - insights.min) / (insights.max - insights.min || 1)) * 100))}%`,
                    transform: 'translateX(-50%)',
                  }}
                />
              </div>
            </div>

            {/* Stats */}
            <div className="bg-slate-700/50 rounded-lg p-3">
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <div className="text-xs text-slate-500">Bullish days</div>
                  <span className="text-green-400 font-medium">{insights.extremeBullish}</span>
                  <span className="text-slate-500 text-xs"> / {insights.totalDays}</span>
                </div>
                <div>
                  <div className="text-xs text-slate-500">Bearish days</div>
                  <span className="text-red-400 font-medium">{insights.extremeBearish}</span>
                  <span className="text-slate-500 text-xs"> / {insights.totalDays}</span>
                </div>
              </div>
            </div>

            {/* Volatility */}
            <div className="bg-slate-700/50 rounded-lg p-3">
              <div className="text-xs text-slate-500 mb-1">Sentiment Swing</div>
              <div className="text-lg font-medium text-slate-200">
                {(insights.range).toFixed(2)}
                <span className="text-xs text-slate-500 ml-2">
                  ({insights.volatility > 0.3 ? 'High volatility' : insights.volatility > 0.15 ? 'Moderate' : 'Stable'})
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default SentimentChart;
