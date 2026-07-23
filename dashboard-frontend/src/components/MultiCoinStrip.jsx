import { useState, useEffect } from 'react';
import { fetchCoinsList, fetchCoinPrice, fetchCoinHistory } from '../api/client';
import Delta from './ui/Delta';

const MAX_COINS = 10;
const SPARK_DAYS = 14;
const FALLBACK_COINS = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'ADA'];

const formatPrice = (price) => {
  if (!price) return '—';
  if (price < 1) return `$${price.toFixed(4)}`;
  if (price < 100) return `$${price.toFixed(2)}`;
  return `$${price.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
};

/** Lightweight inline-SVG sparkline (no recharts overhead per tile). */
const Sparkline = ({ points, positive }) => {
  if (!points || points.length < 2) {
    return <div className="h-9" aria-hidden="true" />;
  }
  const w = 120;
  const h = 36;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const step = w / (points.length - 1);
  const coords = points.map((p, i) => {
    const x = i * step;
    const y = h - ((p - min) / range) * (h - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const stroke = positive ? '#22c55e' : '#ef4444';
  const fill = positive ? 'rgba(45,212,191,0.14)' : 'rgba(251,113,133,0.14)';
  const area = `0,${h} ${coords.join(' ')} ${w},${h}`;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-9 w-full" preserveAspectRatio="none" aria-hidden="true">
      <polygon points={area} fill={fill} />
      <polyline
        points={coords.join(' ')}
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
};

const CoinTile = ({ coin }) => (
  <div className="radar-card flex min-w-0 flex-col gap-2 p-3">
    <div className="flex items-baseline justify-between gap-2">
      <span className="font-display text-sm font-semibold tracking-wide text-slate-100">
        {coin.symbol}
      </span>
      {coin.price != null && typeof coin.change24h === 'number' ? (
        <Delta value={coin.change24h} suffix="%" className="text-xs" />
      ) : (
        <span className="text-xs text-slate-500">{coin.price != null ? '\u2014' : '\u2014'}</span>
      )}
    </div>
    <div className="radar-tabular text-base font-semibold text-slate-50">
      {coin.price != null ? formatPrice(coin.price) : '—'}
    </div>
    {coin.spark?.length > 1 ? (
      <Sparkline points={coin.spark} positive={(coin.change30d ?? 0) >= 0} />
    ) : (
      <div className="h-9 flex items-center text-xs text-slate-600" aria-hidden="true">
        no data yet
      </div>
    )}
  </div>
);

const MultiCoinStrip = () => {
  const [coins, setCoins] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const list = await fetchCoinsList();
        let symbols = (list?.coins?.length ? list.coins : []).slice(0, MAX_COINS);

        // Ensure at least 6 coin slots — pad with fallback if API returns fewer
        if (symbols.length < 6) {
          const seen = new Set(symbols);
          for (const c of FALLBACK_COINS) {
            if (!seen.has(c)) {
              symbols.push(c);
              seen.add(c);
            }
            if (symbols.length >= 6) break;
          }
        }

        const results = await Promise.all(
          symbols.map(async (symbol) => {
            try {
              const [price, history] = await Promise.all([
                fetchCoinPrice(symbol),
                fetchCoinHistory(symbol, SPARK_DAYS),
              ]);
              return {
                symbol,
                price: price?.price,
                change24h: price?.change_24h,
                change30d: price?.change_30d,
                spark: history?.data?.map((d) => d.price).filter(Number.isFinite) || [],
              };
            } catch {
              return { symbol, spark: [] };
            }
          }),
        );

        if (!cancelled) {
          setCoins(results);
          setLoading(false);
        }
      } catch {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {Array.from({ length: MAX_COINS }).map((_, i) => (
          <div key={i} className="radar-card h-[104px] animate-pulse p-3" />
        ))}
      </div>
    );
  }

  if (coins.length === 0) return null;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {coins.map((coin) => (
        <CoinTile key={coin.symbol} coin={coin} />
      ))}
    </div>
  );
};

export default MultiCoinStrip;
