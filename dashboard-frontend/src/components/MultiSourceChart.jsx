import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';

const COLORS = [
  '#8b5cf6', // purple
  '#f59e0b', // amber
  '#10b981', // emerald
  '#ef4444', // red
  '#3b82f6', // blue
  '#ec4899', // pink
  '#14b8a6', // teal
  '#f97316', // orange
];

const formatDate = (dateStr) => {
  const date = new Date(dateStr);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};

const formatSourceName = (source) => {
  return source
    .replace('reddit_', 'r/')
    .replace('4chan_', '/')
    .replace(/_/g, '');
};

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-slate-800 border border-slate-600 rounded-lg p-3 shadow-xl max-h-64 overflow-y-auto">
        <p className="text-slate-400 text-sm mb-2">{formatDate(label)}</p>
        {payload
          .sort((a, b) => (b.value || 0) - (a.value || 0))
          .map((entry, index) => (
            <p key={index} className="text-xs" style={{ color: entry.color }}>
              {formatSourceName(entry.dataKey)}: {entry.value?.toFixed(3)}
            </p>
          ))}
      </div>
    );
  }
  return null;
};

const MultiSourceChart = ({ sourcesData, selectedSources }) => {
  if (!sourcesData || Object.keys(sourcesData).length === 0) {
    return (
      <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6 h-80 flex items-center justify-center">
        <p className="text-slate-500">No source data available</p>
      </div>
    );
  }

  // Get all unique dates across all sources
  const allDates = new Set();
  Object.values(sourcesData).forEach((sourceData) => {
    sourceData.forEach((point) => allDates.add(point.date));
  });

  // Create merged data with all sources as columns
  const sortedDates = Array.from(allDates).sort();
  const mergedData = sortedDates.map((date) => {
    const point = { date };
    Object.entries(sourcesData).forEach(([source, data]) => {
      const found = data.find((d) => d.date === date);
      if (found) {
        point[source] = found.sentiment_score;
      }
    });
    return point;
  });

  // Filter to selected sources or top 5 by data points
  const sourcesToShow =
    selectedSources && selectedSources.length > 0
      ? selectedSources
      : Object.entries(sourcesData)
          .sort((a, b) => b[1].length - a[1].length)
          .slice(0, 5)
          .map(([source]) => source);

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6">
      <h3 className="text-lg font-semibold text-slate-200 mb-4">
        Source Sentiment Comparison
      </h3>
      <ResponsiveContainer width="100%" height={350}>
        <LineChart data={mergedData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis
            dataKey="date"
            tickFormatter={formatDate}
            stroke="#64748b"
            tick={{ fill: '#64748b', fontSize: 11 }}
          />
          <YAxis
            domain={[-1, 1]}
            stroke="#64748b"
            tick={{ fill: '#64748b', fontSize: 11 }}
            tickFormatter={(v) => v.toFixed(1)}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend
            wrapperStyle={{ color: '#94a3b8', fontSize: '12px' }}
            formatter={(value) => formatSourceName(value)}
          />
          <ReferenceLine y={0} stroke="#475569" strokeDasharray="3 3" />
          {sourcesToShow.map((source, index) => (
            <Line
              key={source}
              type="monotone"
              dataKey={source}
              name={source}
              stroke={COLORS[index % COLORS.length]}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

export default MultiSourceChart;
