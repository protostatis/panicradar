import { useState, useEffect, useMemo, useRef } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
} from 'recharts';
import { fetchCoinsList, fetchCoinPrice, fetchCoinHistory } from '../api/client';
import { useChartSync } from '../context/ChartSyncContext';

const formatDate = (dateStr) => {
  // Parse as local date to avoid timezone shift
  const [year, month, day] = dateStr.split('-').map(Number);
  const date = new Date(year, month - 1, day);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};

const formatPrice = (price) => {
  if (!price) return 'N/A';
  if (price < 1) return `$${price.toFixed(4)}`;
  if (price < 100) return `$${price.toFixed(2)}`;
  return `$${price.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
};

const formatChange = (change) => {
  if (change === null || change === undefined) return '-';
  const sign = change >= 0 ? '+' : '';
  return `${sign}${change.toFixed(1)}%`;
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

const CoinPriceCard = () => {
  const [coins, setCoins] = useState(['BTC', 'ETH', 'SOL']);
  const [selectedCoin, setSelectedCoin] = useState('BTC');
  const [coinPrice, setCoinPrice] = useState(null);
  const [coinHistory, setCoinHistory] = useState(null);
  const [loading, setLoading] = useState(false);
  const containerRef = useRef(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const { activeDate, handleMouseMove, handleMouseLeave } = useChartSync();

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

  // Fetch available coins on mount
  useEffect(() => {
    const loadCoins = async () => {
      try {
        const data = await fetchCoinsList();
        if (data.coins && data.coins.length > 0) {
          setCoins(data.coins);
        }
      } catch (err) {
        console.error('Failed to load coins list:', err);
      }
    };
    loadCoins();
  }, []);

  // Fetch coin price and history when selected coin changes
  useEffect(() => {
    const loadCoinData = async () => {
      setLoading(true);
      try {
        const [priceData, historyData] = await Promise.all([
          fetchCoinPrice(selectedCoin),
          fetchCoinHistory(selectedCoin, 30),
        ]);
        setCoinPrice(priceData);
        setCoinHistory(historyData);
      } catch (err) {
        console.error('Failed to load coin data:', err);
        setCoinPrice(null);
        setCoinHistory(null);
      } finally {
        setLoading(false);
      }
    };
    loadCoinData();
  }, [selectedCoin]);

  // Extract price data for chart
  const chartData = useMemo(() => {
    if (!coinHistory?.data) return [];
    return coinHistory.data.map((d) => ({
      date: d.date,
      price: d.price,
    }));
  }, [coinHistory]);

  // Calculate price change for gradient color
  const priceChange = coinPrice?.change_30d ?? 0;
  const isPositive = priceChange >= 0;
  const gradientColor = isPositive ? '#22c55e' : '#ef4444';

  // Calculate domain with padding
  const { minPrice, maxPrice, padding } = useMemo(() => {
    if (chartData.length === 0) return { minPrice: 0, maxPrice: 100, padding: 10 };
    const prices = chartData.map((d) => d.price);
    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const pad = (max - min) * 0.1;
    return { minPrice: min, maxPrice: max, padding: pad };
  }, [chartData]);

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-4">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-2">
        <div className="flex items-center gap-3">
          {/* Coin Selector */}
          <select
            value={selectedCoin}
            onChange={(e) => setSelectedCoin(e.target.value)}
            className="bg-slate-700 border border-slate-600 text-slate-200 text-sm rounded-lg px-3 py-1.5 focus:ring-blue-500 focus:border-blue-500"
          >
            {coins.map((coin) => (
              <option key={coin} value={coin}>
                {coin}
              </option>
            ))}
          </select>
          <div>
            <div className="text-2xl font-bold text-slate-100">
              {loading ? '...' : formatPrice(coinPrice?.price)}
            </div>
          </div>
        </div>
        <div className="flex gap-4">
          <div className="text-center">
            <span className="text-slate-400 text-xs block">24h</span>
            <div
              className={`text-sm font-semibold ${
                (coinPrice?.change_24h || 0) >= 0 ? 'text-green-400' : 'text-red-400'
              }`}
            >
              {formatChange(coinPrice?.change_24h)}
            </div>
          </div>
          <div className="text-center">
            <span className="text-slate-400 text-xs block">7d</span>
            <div
              className={`text-sm font-semibold ${
                (coinPrice?.change_7d || 0) >= 0 ? 'text-green-400' : 'text-red-400'
              }`}
            >
              {formatChange(coinPrice?.change_7d)}
            </div>
          </div>
          <div className="text-center">
            <span className="text-slate-400 text-xs block">30d</span>
            <div
              className={`text-sm font-semibold ${
                (coinPrice?.change_30d || 0) >= 0 ? 'text-green-400' : 'text-red-400'
              }`}
            >
              {formatChange(coinPrice?.change_30d)}
            </div>
          </div>
        </div>
      </div>

      {/* Price Chart */}
      {loading ? (
        <div className="h-24 flex items-center justify-center">
          <p className="text-slate-500 text-sm">Loading...</p>
        </div>
      ) : chartData.length > 0 ? (
        <div ref={containerRef} style={{ width: '100%', height: 96, minWidth: 0 }}>
          {containerWidth > 0 && (
            <AreaChart
              data={chartData}
              width={containerWidth}
              height={96}
              margin={{ top: 5, right: 5, left: 5, bottom: 0 }}
              onMouseMove={handleMouseMove}
              onMouseLeave={handleMouseLeave}
            >
              <defs>
                <linearGradient id={`priceGradient-${selectedCoin}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={gradientColor} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={gradientColor} stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="date" hide />
              <YAxis domain={[minPrice - padding, maxPrice + padding]} hide />
              <Tooltip content={<CustomTooltip />} />
              {activeDate && chartData.some((d) => d.date === activeDate) && (
                <ReferenceLine x={activeDate} stroke="#8b5cf6" strokeWidth={1} strokeDasharray="3 3" />
              )}
              <Area
                type="monotone"
                dataKey="price"
                stroke={gradientColor}
                strokeWidth={2}
                fill={`url(#priceGradient-${selectedCoin})`}
              />
            </AreaChart>
          )}
        </div>
      ) : (
        <div className="h-24 flex items-center justify-center">
          <p className="text-slate-500 text-sm">No price data available</p>
        </div>
      )}
    </div>
  );
};

export default CoinPriceCard;
