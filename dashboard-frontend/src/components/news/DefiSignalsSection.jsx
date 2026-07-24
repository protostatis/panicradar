import { EmptyState } from '../ui/StateViews';

const DefiSignalsSection = ({ signals }) => {
  if (!signals || signals.length === 0) {
    return (
      <section id="defi" className="scroll-mt-24">
        <EmptyState
          icon={'\u29BF'}
          title="No DeFi signals today"
          message="On-chain DeFi signals appear here when the daily scan surfaces them."
        />
      </section>
    );
  }

  return (
    <section id="defi" className="scroll-mt-24">
      <h2 className="mb-4 text-xl font-bold text-slate-100">DeFi Signals</h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {signals.map((signal, i) => (
          <div
            key={i}
            className="rounded-xl border border-purple-500/20 bg-purple-900/10 p-5 transition-colors hover:border-purple-500/40"
          >
            <h3 className="mb-2 text-sm font-semibold leading-snug text-purple-300">
              {signal.headline}
            </h3>
            <p className="mb-2 text-sm leading-relaxed text-slate-400">
              {signal.why_interesting}
            </p>
            <span className="font-mono text-xs text-slate-600">{signal.source}</span>
          </div>
        ))}
      </div>
    </section>
  );
};

export default DefiSignalsSection;
