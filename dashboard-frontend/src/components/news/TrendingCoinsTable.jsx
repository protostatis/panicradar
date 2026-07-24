import { useState } from 'react';
import SectionHeader from '../ui/SectionHeader';
import { EmptyState } from '../ui/StateViews';

const CoinRow = ({ coin }) => {
  const change = coin.price_change_24h || '';
  const isPositive = change.startsWith('+');
  const isNegative = change.startsWith('-');

  return (
    <tr className="border-t border-slate-700/50 transition-colors hover:bg-slate-700/30">
      <td className="px-3 py-2.5 font-mono text-xs text-slate-500">{coin.rank != null ? `#${coin.rank}` : '—'}</td>
      <td className="px-3 py-2.5">
        <span className="text-sm font-semibold text-slate-100">{coin.symbol}</span>
        <span className="ml-2 hidden text-xs text-slate-500 sm:inline">{coin.name}</span>
      </td>
      <td
        className={`px-3 py-2.5 text-right font-mono text-sm ${
          isPositive ? 'text-green-400' : isNegative ? 'text-red-400' : 'text-slate-400'
        }`}
      >
        {change || '—'}
      </td>
      <td className="hidden px-3 py-2.5 text-right font-mono text-xs text-slate-400 sm:table-cell">
        {coin.volume || '—'}
      </td>
      {coin.note && (
        <td className="hidden max-w-[200px] truncate px-3 py-2.5 text-xs text-slate-500 lg:table-cell">
          {coin.note}
        </td>
      )}
    </tr>
  );
};

const Table = ({ coins, hasNotes }) => (
  <table className="w-full">
    <thead>
      <tr className="text-xs uppercase tracking-wider text-slate-500">
        <th scope="col" className="w-16 px-3 py-2 text-left">Rank</th>
        <th scope="col" className="px-3 py-2 text-left">Coin</th>
        <th scope="col" className="px-3 py-2 text-right">24h</th>
        <th scope="col" className="hidden px-3 py-2 text-right sm:table-cell">Volume</th>
        {hasNotes && <th scope="col" className="hidden px-3 py-2 text-left lg:table-cell">Note</th>}
      </tr>
    </thead>
    <tbody>
      {coins.map((coin, i) => (
        <CoinRow key={i} coin={coin} />
      ))}
    </tbody>
  </table>
);

const TabButton = ({ active, onClick, children }) => (
  <button
    type="button"
    role="tab"
    aria-selected={active}
    onClick={onClick}
    className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
      active
        ? 'border border-green-500/30 bg-green-500/20 text-green-400'
        : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
    }`}
  >
    {children}
  </button>
);

const TrendingCoinsTable = ({ coins, losers }) => {
  const [tab, setTab] = useState('trending');

  const trending = coins || [];
  const losersList = losers || [];

  if (trending.length === 0 && losersList.length === 0) {
    return (
      <section>
        <EmptyState
          icon={'\u2248'}
          title="No mover data today"
          message="Trending coin and top-loser data refreshes with the daily scan."
        />
      </section>
    );
  }

  const hasNotes = trending.some((c) => c.note);
  const activeCoins = tab === 'trending' ? trending : losersList;

  return (
    <section id="movers" className="scroll-mt-32">
      <SectionHeader
        kicker="Flow"
        title="Movers"
        description="Trending tickers and the day's worst performers."
        actions={
          <div className="flex items-center gap-1" role="tablist" aria-label="Coin movers">
            <TabButton active={tab === 'trending'} onClick={() => setTab('trending')}>
              Trending ({trending.length})
            </TabButton>
            <TabButton active={tab === 'losers'} onClick={() => setTab('losers')}>
              Top Losers ({losersList.length})
            </TabButton>
          </div>
        }
      />

      <div className="mt-4 radar-panel overflow-hidden">
        {activeCoins.length > 0 ? (
          <Table coins={activeCoins} hasNotes={tab === 'trending' && hasNotes} />
        ) : (
          <div className="p-6">
            <EmptyState
              icon={'\u2014'}
              title={`No ${tab === 'trending' ? 'trending' : 'loser'} data`}
              message="Try the other tab."
            />
          </div>
        )}
      </div>
    </section>
  );
};

export default TrendingCoinsTable;
