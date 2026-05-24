const TickerItem = ({ label, value, isPositive, isNegative }) => (
  <span className="inline-flex items-center gap-2 whitespace-nowrap rounded-full border border-slate-700/70 bg-slate-950/80 px-3 py-1.5">
    <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">{label}</span>
    <span className={
      isPositive ? 'text-green-400' :
      isNegative ? 'text-red-400' :
      'text-slate-200'
    }>
      {value}
    </span>
  </span>
);

const compactValue = (value) => {
  if (!value) return null;

  const text = String(value)
    .replace(/\s+area\b/i, '')
    .replace(/\s+on [A-Za-z].*$/i, '')
    .replace(/\s+on CoinGecko.*$/i, '')
    .replace(/\s+during the refresh.*$/i, '')
    .replace(/\s+in the .* article.*$/i, '')
    .replace(/\s+but .*$/i, '')
    .trim();

  return text.length > 42 ? `${text.slice(0, 39).trim()}...` : text;
};

const MarketTicker = ({ context }) => {
  if (!context) return null;

  const items = [
    context.btc_price && {
      label: 'BTC',
      value: compactValue(context.btc_price),
      isPositive: context.btc_price_direction === 'up',
      isNegative: context.btc_price_direction === 'down',
    },
    context.eth_price && { label: 'ETH', value: compactValue(context.eth_price) },
    context.sol_price && { label: 'SOL', value: compactValue(context.sol_price) },
    context.xrp_price && { label: 'XRP', value: compactValue(context.xrp_price) },
    context.hype_price && { label: 'HYPE', value: compactValue(context.hype_price) },
    context.total_market_cap && { label: 'MCAP', value: compactValue(context.total_market_cap) },
    context.market_cap && {
      label: 'MCAP',
      value: compactValue(`${context.market_cap} ${context.market_cap_change || ''}`),
      isPositive: context.market_cap_change?.startsWith('+'),
      isNegative: context.market_cap_change?.startsWith('-'),
    },
    context.volume_24h && { label: 'VOL 24H', value: compactValue(context.volume_24h) },
    context.btc_dominance && { label: 'BTC.D', value: compactValue(context.btc_dominance) },
    context.eth_dominance && { label: 'ETH.D', value: compactValue(context.eth_dominance) },
    context.liquidations_24h && { label: 'LIQ', value: compactValue(context.liquidations_24h), isNegative: true },
    context.total_tvl && { label: 'TVL', value: compactValue(context.total_tvl) },
    context.stablecoins_mcap && { label: 'STABLES', value: compactValue(context.stablecoins_mcap) },
  ].filter(Boolean);

  if (items.length === 0) return null;

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-2 shadow-lg shadow-slate-950/30">
      <div className="flex items-center gap-2 overflow-x-auto font-mono text-xs">
        <span className="sticky left-0 z-10 rounded-full border border-emerald-400/20 bg-slate-950 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-emerald-300 shadow-lg shadow-slate-950/80">
          Market Tape
        </span>
        {items.map((item, i) => (
          <TickerItem key={`${item.label}-${i}`} {...item} />
        ))}
      </div>
    </div>
  );
};

export default MarketTicker;
