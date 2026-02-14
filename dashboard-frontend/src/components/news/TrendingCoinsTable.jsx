import { useState } from 'react';

const CoinRow = ({ coin }) => {
  const isPositive = coin.price_change_24h.startsWith('+');
  const isNegative = coin.price_change_24h.startsWith('-');

  return (
    <tr className="border-t border-slate-700/50 hover:bg-slate-700/30 transition-colors">
      <td className="py-2.5 px-3 text-slate-500 text-xs font-mono">#{coin.rank}</td>
      <td className="py-2.5 px-3">
        <span className="text-slate-100 font-semibold text-sm">{coin.symbol}</span>
        <span className="text-slate-500 text-xs ml-2 hidden sm:inline">{coin.name}</span>
      </td>
      <td className={`py-2.5 px-3 text-right font-mono text-sm ${isPositive ? 'text-green-400' : isNegative ? 'text-red-400' : 'text-slate-400'}`}>
        {coin.price_change_24h}
      </td>
      <td className="py-2.5 px-3 text-right text-slate-400 text-xs font-mono hidden sm:table-cell">
        {coin.volume}
      </td>
      {coin.note && (
        <td className="py-2.5 px-3 text-slate-500 text-xs max-w-[200px] truncate hidden lg:table-cell">
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
        <th className="py-2 px-3 text-left w-16">Rank</th>
        <th className="py-2 px-3 text-left">Coin</th>
        <th className="py-2 px-3 text-right">24h</th>
        <th className="py-2 px-3 text-right hidden sm:table-cell">Volume</th>
        {hasNotes && <th className="py-2 px-3 text-left hidden lg:table-cell">Note</th>}
      </tr>
    </thead>
    <tbody>
      {coins.map((coin, i) => (
        <CoinRow key={i} coin={coin} />
      ))}
    </tbody>
  </table>
);

const TrendingCoinsTable = ({ coins, losers }) => {
  const [tab, setTab] = useState('trending');

  if (!coins?.length && !losers?.length) return null;

  const hasNotes = coins?.some(c => c.note);

  return (
    <section>
      <div className="flex items-center gap-1 mb-4">
        <button
          onClick={() => setTab('trending')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            tab === 'trending'
              ? 'bg-green-500/20 text-green-400 border border-green-500/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
          }`}
        >
          Trending ({coins?.length || 0})
        </button>
        <button
          onClick={() => setTab('losers')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            tab === 'losers'
              ? 'bg-red-500/20 text-red-400 border border-red-500/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
          }`}
        >
          Top Losers ({losers?.length || 0})
        </button>
      </div>

      <div className="bg-slate-800/50 rounded-xl border border-slate-700 overflow-hidden">
        {tab === 'trending' && coins?.length > 0 && (
          <Table coins={coins} hasNotes={hasNotes} />
        )}
        {tab === 'losers' && losers?.length > 0 && (
          <Table coins={losers} hasNotes={false} />
        )}
      </div>
    </section>
  );
};

export default TrendingCoinsTable;
