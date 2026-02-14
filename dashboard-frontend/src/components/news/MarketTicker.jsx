const TickerItem = ({ label, value, isPositive, isNegative }) => (
  <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
    <span className="text-slate-500">{label}</span>
    <span className={
      isPositive ? 'text-green-400' :
      isNegative ? 'text-red-400' :
      'text-slate-300'
    }>
      {value}
    </span>
  </span>
);

const Separator = () => (
  <span className="text-slate-700 mx-3">|</span>
);

const MarketTicker = ({ context }) => {
  if (!context) return null;

  const items = [
    context.btc_price && {
      label: 'BTC',
      value: `${context.btc_price} ${context.btc_price_direction === 'up' ? '\u25B2' : '\u25BC'}`,
      isPositive: context.btc_price_direction === 'up',
      isNegative: context.btc_price_direction === 'down',
    },
    context.market_cap && {
      label: 'MCAP',
      value: `${context.market_cap} ${context.market_cap_change || ''}`,
      isPositive: context.market_cap_change?.startsWith('+'),
      isNegative: context.market_cap_change?.startsWith('-'),
    },
    context.volume_24h && { label: 'VOL 24H', value: context.volume_24h },
    context.btc_dominance && { label: 'BTC.D', value: context.btc_dominance },
    context.eth_dominance && { label: 'ETH.D', value: context.eth_dominance },
    context.liquidations_24h && { label: 'LIQ', value: context.liquidations_24h, isNegative: true },
    context.total_tvl && { label: 'TVL', value: context.total_tvl },
    context.stablecoins_mcap && { label: 'STABLES', value: context.stablecoins_mcap },
  ].filter(Boolean);

  return (
    <div className="bg-slate-950 border border-slate-800 rounded-lg overflow-hidden">
      <div className="relative">
        <div className="flex items-center overflow-hidden">
          <div className="animate-ticker flex items-center font-mono text-xs py-2.5 px-4">
            {/* Duplicate items for seamless loop */}
            {[...items, ...items].map((item, i) => (
              <span key={i} className="inline-flex items-center">
                <TickerItem {...item} />
                <Separator />
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

export default MarketTicker;
