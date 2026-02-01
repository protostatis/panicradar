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
  const date = new Date(dateStr);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-slate-800 border border-slate-600 rounded-lg p-3 shadow-xl">
        <p className="text-slate-400 text-sm mb-2">{formatDate(label)}</p>
        {payload.map((entry, index) => (
          <p key={index} className="text-sm" style={{ color: entry.color }}>
            Sentiment: {entry.value?.toFixed(3)}
          </p>
        ))}
        {payload[0]?.payload?.sample_size && (
          <p className="text-slate-500 text-xs mt-1">
            Samples: {payload[0].payload.sample_size}
          </p>
        )}
      </div>
    );
  }
  return null;
};

const SubredditChart = ({ source, data, onClose }) => {
  const formatSourceName = (s) => {
    return s
      .replace('reddit_', 'r/')
      .replace('4chan_', '/')
      .replace(/_/g, '');
  };

  if (!data || data.length === 0) {
    return (
      <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6">
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold text-slate-200">
            {formatSourceName(source)}
          </h3>
          {onClose && (
            <button
              onClick={onClose}
              className="text-slate-400 hover:text-slate-200 transition-colors"
            >
              ✕
            </button>
          )}
        </div>
        <p className="text-slate-500">No sentiment data available for this source</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-6">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold text-slate-200">
          {formatSourceName(source)} Sentiment
        </h3>
        {onClose && (
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-200 transition-colors px-2 py-1 hover:bg-slate-700 rounded"
          >
            ✕
          </button>
        )}
      </div>
      <ResponsiveContainer width="100%" height={250}>
        <LineChart data={data} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
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
          <ReferenceLine y={0} stroke="#475569" strokeDasharray="3 3" />
          <Line
            type="monotone"
            dataKey="sentiment_score"
            stroke="#8b5cf6"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

export default SubredditChart;
