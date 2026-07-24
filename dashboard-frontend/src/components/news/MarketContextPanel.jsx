import SectionHeader from '../ui/SectionHeader';
import { EmptyState } from '../ui/StateViews';

const StatItem = ({ label, value }) => {
  if (!value) return null;
  return (
    <div className="radar-card p-3">
      <div className="mb-1 text-xs uppercase tracking-wider text-slate-500">{label}</div>
      <div className="font-mono text-sm text-slate-200">{value}</div>
    </div>
  );
};

const MarketContextPanel = ({ context }) => {
  if (!context) return null;

  const stats = [
    { label: 'BTC Price', value: context.btc_price },
    { label: 'Market Cap', value: context.market_cap },
    { label: '24h Volume', value: context.volume_24h },
    { label: 'BTC Dominance', value: context.btc_dominance },
    { label: 'ETH Dominance', value: context.eth_dominance },
    { label: 'Liquidations', value: context.liquidations_24h },
    { label: 'Total TVL', value: context.total_tvl },
    { label: 'Stablecoins', value: context.stablecoins_mcap },
    { label: 'ETF Flows', value: context.etf_flows },
    { label: 'Macro', value: context.government_shutdown },
  ].filter((s) => s.value);

  if (stats.length === 0) {
    return (
      <section id="context" className="scroll-mt-32">
        <SectionHeader kicker="Backdrop" title="Market Context" />
        <div className="mt-4">
          <EmptyState
            icon={'\u2248'}
            title="No market stats available"
            message="Quantitative context refreshes with the daily scan."
          />
        </div>
      </section>
    );
  }

  return (
    <section id="context" className="scroll-mt-32">
      <SectionHeader
        kicker="Backdrop"
        title="Market Context"
        description="The quantitative backdrop behind today's narrative."
      />
      <div className="mt-4 radar-panel p-6">
        {/* Stats grid (narrative lives in the hero, not duplicated here) */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {stats.map((s) => (
            <StatItem key={s.label} label={s.label} value={s.value} />
          ))}
        </div>

        {/* Top stablecoins breakdown */}
        {context.top_stablecoins && (
          <div className="mt-4 border-t border-slate-700/50 pt-4">
            <div className="mb-1 text-xs uppercase tracking-wider text-slate-500">
              Top Stablecoins
            </div>
            <div className="font-mono text-xs text-slate-400">{context.top_stablecoins}</div>
          </div>
        )}
      </div>
    </section>
  );
};

export default MarketContextPanel;
