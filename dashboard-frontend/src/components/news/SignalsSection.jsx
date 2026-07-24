import { useMemo, useState } from 'react';
import SignalCard from './SignalCard';
import { EmptyState } from '../ui/StateViews';

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'high', label: 'High impact' },
  { key: 'medium', label: 'Watch' },
  { key: 'low', label: 'Context' },
];

const countByLevel = (signals) => {
  const counts = { all: signals.length, high: 0, medium: 0, low: 0 };
  signals.forEach((s) => {
    if (counts[s.surprise_score] != null) counts[s.surprise_score] += 1;
  });
  return counts;
};

const SignalsSection = ({ signals }) => {
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');

  const counts = useMemo(() => countByLevel(signals), [signals]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return signals.filter((signal) => {
      if (filter !== 'all' && signal.surprise_score !== filter) return false;
      if (!q) return true;
      return (
        signal.headline?.toLowerCase().includes(q) ||
        signal.why_interesting?.toLowerCase().includes(q) ||
        signal.source?.toLowerCase().includes(q)
      );
    });
  }, [signals, filter, query]);

  return (
    <section id="signals" className="scroll-mt-24">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <h2 className="text-xl font-bold text-slate-100">
          Signals{' '}
          <span className="font-mono text-base font-normal text-slate-500">
            ({visible.length}
            {visible.length !== signals.length ? ` of ${signals.length}` : ''})
          </span>
        </h2>

        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          {/* Search */}
          <div className="relative">
            <span aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-xs text-slate-500">
              {'\u2315'}
            </span>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter signals…"
              aria-label="Filter signals by text"
              className="w-full rounded-lg border border-slate-700 bg-slate-950/80 py-1.5 pl-8 pr-3 text-sm text-slate-200 placeholder:text-slate-600 focus:border-cyan-400/50 focus:outline-none focus:ring-1 focus:ring-cyan-400/40 sm:w-56"
            />
          </div>
        </div>
      </div>

      {/* Priority filters */}
      <div className="mb-4 flex flex-wrap items-center gap-1" role="group" aria-label="Filter by impact level">
        {FILTERS.map(({ key, label }) => {
          const active = filter === key;
          const disabled = key !== 'all' && counts[key] === 0;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setFilter(key)}
              disabled={disabled}
              aria-pressed={active}
              className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                active
                  ? 'border border-cyan-400/40 bg-cyan-400/15 text-cyan-300'
                  : 'border border-slate-700/60 text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              } ${disabled ? 'cursor-not-allowed opacity-40 hover:bg-transparent' : ''}`}
            >
              {label}
              <span className="ml-1.5 text-[0.65rem] text-slate-500">{counts[key] ?? 0}</span>
            </button>
          );
        })}
      </div>

      {visible.length > 0 ? (
        <div className="space-y-4">
          {visible.map((signal, i) => (
            <SignalCard key={i} signal={signal} />
          ))}
        </div>
      ) : (
        <EmptyState
          icon={'\u2315'}
          title="No matching signals"
          message={query ? `Nothing matches "${query}".` : 'No signals at this impact level today.'}
        />
      )}
    </section>
  );
};

export default SignalsSection;
