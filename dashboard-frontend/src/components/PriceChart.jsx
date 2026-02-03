import { useMemo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

const formatDate = (dateStr) => {
  // Parse as local date to avoid timezone shift
  const [year, month, day] = dateStr.split('-').map(Number);
  const date = new Date(year, month - 1, day);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};

const formatPrice = (price) => {
  if (!price) return 'N/A';
  return `$${price.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
};

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    const price = payload[0]?.value;
    return (
      <div className="bg-slate-800 border border-slate-600 rounded-lg p-2 shadow-xl">
        <p className="text-slate-400 text-xs mb-1">{formatDate(label)}</p>
        <p className="text-slate-100 font-medium">{formatPrice(price)}</p>
      </div>
    );
  }
  return null;
};

const PriceChart = ({ data }) => {
  // Extract price data from history
  const chartData = useMemo(() => {
    if (!data) return [];
    return data
      .filter((d) => d.btc_price != null)
      .map((d) => ({
        date: d.date,
        price: d.btc_price,
      }));
  }, [data]);

  // Calculate price change for gradient color
  const priceChange = useMemo(() => {
    if (chartData.length < 2) return 0;
    const first = chartData[0].price;
    const last = chartData[chartData.length - 1].price;
    return ((last - first) / first) * 100;
  }, [chartData]);

  const isPositive = priceChange >= 0;
  const gradientColor = isPositive ? '#22c55e' : '#ef4444';

  if (!chartData || chartData.length === 0) {
    return (
      <div className="h-24 flex items-center justify-center">
        <p className="text-slate-500 text-sm">No price data</p>
      </div>
    );
  }

  // Calculate domain with some padding
  const prices = chartData.map((d) => d.price);
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const padding = (maxPrice - minPrice) * 0.1;

  return (
    <div className="h-24">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={chartData}
          margin={{ top: 5, right: 5, left: 5, bottom: 0 }}
        >
          <defs>
            <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={gradientColor} stopOpacity={0.3} />
              <stop offset="95%" stopColor={gradientColor} stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="date" hide />
          <YAxis domain={[minPrice - padding, maxPrice + padding]} hide />
          <Tooltip content={<CustomTooltip />} />
          <Area
            type="monotone"
            dataKey="price"
            stroke={gradientColor}
            strokeWidth={2}
            fill="url(#priceGradient)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
};

export default PriceChart;
