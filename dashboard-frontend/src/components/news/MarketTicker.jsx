const TickerItem = ({ label, value, isPositive, isNegative }) => (
  <span className="inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-full border border-slate-700/70 bg-slate-950/80 px-3 py-1.5">
    <span className="text-[0.65rem] font-semibold uppercase tracking-[0.18em] text-slate-500">{label}</span>
    <span
      className={
        isPositive ? 'text-green-400' : isNegative ? 'text-red-400' : 'text-slate-200'
      }
    >
      {value}
    </span>
  </span>
);

const MarketTicker = ({ context }) => {
  if (!context) return null;

  const items = [
    context.btc_price && {
      label: 'BTC',
      value: context.btc_price,
      isPositive: context.btc_price_direction === 'up',
      isNegative: context.btc_price_direction === 'down',
    },
    context.eth_price && { label: 'ETH', value: context.eth_price },
    context.sol_price && { label: 'SOL', value: context.sol_price },
    context.xrp_price && { label: 'XRP', value: context.xrp_price },
    context.hype_price && { label: 'HYPE', value: context.hype_price },
    context.total_market_cap && { label: 'MCAP', value: context.total_market_cap },
    context.market_cap && {
      label: 'MCAP',
      value: context.market_cap,
      isPositive: context.market_cap_change?.startsWith('+'),
      isNegative: context.market_cap_change?.startsWith('-'),
    },
    context.volume_24h && { label: 'VOL 24H', value: context.volume_24h },
    context.btc_dominance && { label: 'BTC.D', value: context.btc_dominance },
    context.eth_dominance && { label: 'ETH.D', value: context.eth_dominance },
    context.liquidations_24h && {
      label: 'LIQ',
      value: context.liquidations_24h,
      isNegative: true,
    },
    context.total_tvl && { label: 'TVL', value: context.total_tvl },
    context.stablecoins_mcap && { label: 'STABLES', value: context.stablecoins_mcap },
  ].filter(Boolean);

  if (items.length === 0) return null;

  return (
    <div className="relative rounded-2xl border border-slate-800 bg-slate-950/80 p-2 shadow-lg shadow-slate-950/30">
      {/* Scroll affordance: right-edge fade so users know there's more */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute right-0 top-0 z-10 h-full w-10 bg-gradient-to-l from-slate-950 via-slate-950/60 to-transparent"
      />
      <div
        className="flex items-center gap-2 overflow-x-auto font-mono text-xs [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        role="marquee"
        aria-label="Live market prices"
      >
        <span className="sticky left-0 z-10 shrink-0 rounded-full border border-emerald-400/20 bg-slate-950 px-3 py-1.5 text-[0.65rem] font-semibold uppercase tracking-[0.18em] text-cyan-300 shadow-lg shadow-slate-950/80">
          Market Tape
        </span>
        {items.map((item, i) => (
          <TickerItem key={`${item.label}-${i}`} {...item} />
        ))}
        <span aria-hidden="true" className="shrink-0 px-1 text-slate-700">
          {'\u00B7'}
        </span>
      </div>
    </div>
  );
};

export default MarketTicker;
