const StatItem = ({ label, value }) => {
  if (!value) return null;
  return (
    <div className="bg-slate-800/60 rounded-lg p-3">
      <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">{label}</div>
      <div className="text-sm text-slate-200 font-mono">{value}</div>
    </div>
  );
};

const MarketContextPanel = ({ context }) => {
  if (!context) return null;

  return (
    <section>
      <h2 className="text-xl font-bold text-slate-100 mb-4">
        Market Context
      </h2>
      <div className="bg-slate-800/30 rounded-2xl border border-slate-700/50 p-6">
        {/* Dominant sentiment narrative */}
        {context.dominant_sentiment && (
          <div className="mb-5">
            <div className="text-xs font-semibold uppercase tracking-wider text-green-400 mb-2">
              Dominant Narrative
            </div>
            <p className="text-slate-300 text-sm leading-relaxed">
              {context.dominant_sentiment}
            </p>
          </div>
        )}

        {/* Stats grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          <StatItem label="BTC Price" value={context.btc_price} />
          <StatItem label="Market Cap" value={context.market_cap} />
          <StatItem label="24h Volume" value={context.volume_24h} />
          <StatItem label="BTC Dominance" value={context.btc_dominance} />
          <StatItem label="ETH Dominance" value={context.eth_dominance} />
          <StatItem label="Liquidations" value={context.liquidations_24h} />
          <StatItem label="Total TVL" value={context.total_tvl} />
          <StatItem label="Stablecoins" value={context.stablecoins_mcap} />
          {context.etf_flows && <StatItem label="ETF Flows" value={context.etf_flows} />}
          {context.government_shutdown && <StatItem label="Macro" value={context.government_shutdown} />}
        </div>

        {/* Top stablecoins breakdown */}
        {context.top_stablecoins && (
          <div className="mt-4 pt-4 border-t border-slate-700/50">
            <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">Top Stablecoins</div>
            <div className="text-xs text-slate-400 font-mono">{context.top_stablecoins}</div>
          </div>
        )}
      </div>
    </section>
  );
};

export default MarketContextPanel;
